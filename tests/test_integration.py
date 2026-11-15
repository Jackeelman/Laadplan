"""Integration test in a real HA core (pytest-homeassistant-custom-component)."""

from datetime import timedelta

import pytest

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util

from pytest_homeassistant_custom_component.common import async_mock_service

from custom_components.laadplanner.const import DEFAULTS


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


def _states(hass: HomeAssistant, soc: str = "40") -> None:
    now = dt_util.now().replace(minute=0, second=0, microsecond=0)
    raw = [{"start": (now + timedelta(minutes=15 * i)).isoformat(),
            "end": (now + timedelta(minutes=15 * (i + 1))).isoformat(),
            "value": 0.12 if i % 7 == 0 else 0.30} for i in range(96)]
    hass.states.async_set("sensor.fordpass_jouw_vin_soc", soc)
    hass.states.async_set("binary_sensor.iq_ev_charger_1219_ingeplugd", "on")
    hass.states.async_set("sensor.nordpool_kwh_nl_eur_3_10_021", "0.3",
                          {"raw_today": raw, "raw_tomorrow": []})
    hass.states.async_set("sensor.energy_production_today_remaining_2", "2")
    hass.states.async_set("sensor.energy_production_tomorrow_2", "8")
    hass.states.async_set("sensor.meterkast_p1_meter_hw_energie_import", "1000.0")
    hass.states.async_set("sensor.meterkast_p1_meter_hw_energie_export", "500.0")
    hass.states.async_set("select.iq_ev_charger_1219_laadmodus", "Handmatig",
                          {"options": ["Handmatig", "Gepland", "Groen"]})
    hass.states.async_set("switch.iq_ev_charger_1219", "off")
    hass.states.async_set("sensor.iq_ev_charger_1219_vermogen", "0",
                          {"unit_of_measurement": "W"})


async def _setup(hass: HomeAssistant):
    _states(hass)
    result = await hass.config_entries.flow.async_init(
        "laadplanner", context={"source": config_entries.SOURCE_USER})
    assert result["type"] == "form"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], dict(DEFAULTS))
    assert result["type"] == "create_entry"
    await hass.async_block_till_done()
    return hass.config_entries.async_entries("laadplanner")[0]


async def test_setup_creates_entities_in_shadow_mode(hass: HomeAssistant) -> None:
    await _setup(hass)
    ids = {s.entity_id for s in hass.states.async_all() if "laadplanner" in s.entity_id}
    for expected in ("sensor.laadplanner_plan", "sensor.laadplanner_resterende_vraag",
                     "select.laadplanner_strategie", "switch.laadplanner_sturing_actief",
                     "time.laadplanner_deadline", "time.laadplanner_laden_vanaf", "number.laadplanner_doel_soc"):
        assert expected in ids, ids
    plan = hass.states.get("sensor.laadplanner_plan")
    assert plan.state in ("kwartieren", "zon_aanvullen")
    assert plan.attributes["kwartieren"]
    assert float(hass.states.get("sensor.laadplanner_resterende_vraag").state) > 30
    assert hass.states.get("switch.laadplanner_sturing_actief").state == "off"


async def test_shadow_mode_never_touches_charger(hass: HomeAssistant) -> None:
    entry = await _setup(hass)
    calls = async_mock_service(hass, "switch", "turn_on")
    calls += async_mock_service(hass, "switch", "turn_off")
    await coordinator_set(entry, "strategy", "direct")
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert calls == []


async def test_active_direct_switches_charger_on(hass: HomeAssistant) -> None:
    entry = await _setup(hass)
    calls = async_mock_service(hass, "switch", "turn_on")
    coordinator = entry.runtime_data
    await coordinator.async_set("strategy", "direct")
    await coordinator.async_set("active", True)
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert [c.data["entity_id"] for c in calls] == ["switch.iq_ev_charger_1219"]


async def test_simulation_counts_costs(hass: HomeAssistant, freezer) -> None:
    entry = await _setup(hass)
    coordinator = entry.runtime_data
    await coordinator.async_set("fixed_import", 0.30)
    hass.states.async_set("sensor.meterkast_p1_meter_hw_energie_import", "1001.0")
    freezer.tick(timedelta(minutes=15))
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    fixed = float(hass.states.get("sensor.laadplanner_kosten_vast_vandaag").state)
    dyn = hass.states.get("sensor.laadplanner_kosten_dynamisch_vandaag").state
    assert abs(fixed - 0.30) < 1e-6
    assert float(dyn) in (0.12, 0.30)


async def coordinator_set(entry, key, value):
    await entry.runtime_data.async_set(key, value)


async def test_current_is_never_changed(hass: HomeAssistant) -> None:
    entry = await _setup(hass)
    calls = async_mock_service(hass, "number", "set_value")
    async_mock_service(hass, "switch", "turn_on")
    await entry.runtime_data.async_set("strategy", "direct")
    await entry.runtime_data.async_set("active", True)
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert calls == []


async def test_unplugged_active_shows_preview_and_never_steers(hass: HomeAssistant) -> None:
    entry = await _setup(hass)
    hass.states.async_set("binary_sensor.iq_ev_charger_1219_ingeplugd", "off")
    on = async_mock_service(hass, "switch", "turn_on")
    off = async_mock_service(hass, "switch", "turn_off")
    sel = async_mock_service(hass, "select", "select_option")
    await entry.runtime_data.async_set("active", True)
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    plan = hass.states.get("sensor.laadplanner_plan")
    assert plan.state == "voorlopig"
    assert plan.attributes["kwartieren"]
    assert on == [] and off == [] and sel == []


async def test_target_reached_stops_manual_charge(hass: HomeAssistant) -> None:
    entry = await _setup(hass)
    off = async_mock_service(hass, "switch", "turn_off")
    hass.states.async_set("switch.iq_ev_charger_1219", "on")
    hass.states.async_set("sensor.fordpass_jouw_vin_soc", "85")
    await entry.runtime_data.async_set("active", True)
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get("sensor.laadplanner_plan").state == "geen"
    assert [c.data["entity_id"] for c in off] == ["switch.iq_ev_charger_1219"]


async def test_target_reached_leaves_green_mode_alone(hass: HomeAssistant) -> None:
    entry = await _setup(hass)
    off = async_mock_service(hass, "switch", "turn_off")
    hass.states.async_set("select.iq_ev_charger_1219_laadmodus", "Groen",
                          {"options": ["Handmatig", "Gepland", "Groen"]})
    hass.states.async_set("switch.iq_ev_charger_1219", "on")
    hass.states.async_set("sensor.fordpass_jouw_vin_soc", "85")
    await entry.runtime_data.async_set("active", True)
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert off == []


async def test_failing_charger_keeps_plan_available(hass: HomeAssistant) -> None:
    entry = await _setup(hass)

    async def broken(call):
        raise HomeAssistantError("laadpaal offline")

    hass.services.async_register("switch", "turn_on", broken)
    await entry.runtime_data.async_set("strategy", "direct")
    await entry.runtime_data.async_set("active", True)
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert entry.runtime_data.last_update_success
    assert hass.states.get("sensor.laadplanner_plan").state == "direct"


async def test_simulation_is_saved_while_running(hass: HomeAssistant) -> None:
    entry = await _setup(hass)
    coordinator = entry.runtime_data
    store = coordinator._store  # noqa: SLF001
    calls = []
    original = store.async_delay_save
    store.async_delay_save = lambda func, delay=0: calls.append(delay) or original(func, delay)
    for value in ("1001.0", "1002.0", "1003.0"):
        hass.states.async_set("sensor.meterkast_p1_meter_hw_energie_import", value)
        await coordinator.async_refresh()
    # scheduled once, not pushed back on every update
    assert len(calls) <= 1


async def test_optional_power_entity_can_be_cleared(hass: HomeAssistant) -> None:
    entry = await _setup(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    data = {k: v for k, v in DEFAULTS.items() if k != "charger_power_entity"}
    result = await hass.config_entries.options.async_configure(result["flow_id"], data)
    assert result["type"] == "create_entry"
    await hass.async_block_till_done()
    entry = hass.config_entries.async_entries("laadplanner")[0]
    assert not entry.runtime_data.conf("charger_power_entity")


async def test_car_own_limit_stops_planning(hass: HomeAssistant) -> None:
    entry = await _setup(hass)
    off = async_mock_service(hass, "switch", "turn_off")
    hass.states.async_set("switch.iq_ev_charger_1219", "on")
    hass.states.async_set("sensor.fordpass_jouw_vin_soc", "70")
    hass.states.async_set("sensor.fordpass_jouw_vin_elvehcharging", "COMPLETED")
    # FordPass refreshed after the car was plugged in
    hass.states.async_set("sensor.fordpass_jouw_vin_lastrefresh",
                          (dt_util.utcnow() + timedelta(seconds=1)).isoformat())
    await entry.runtime_data.async_set("active", True)
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get("sensor.laadplanner_plan").state == "geen"
    assert float(hass.states.get("sensor.laadplanner_resterende_vraag").state) == 0
    assert [c.data["entity_id"] for c in off] == ["switch.iq_ev_charger_1219"]


async def test_car_charging_status_keeps_planning(hass: HomeAssistant) -> None:
    entry = await _setup(hass)
    hass.states.async_set("sensor.fordpass_jouw_vin_elvehcharging", "IN_PROGRESS")
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get("sensor.laadplanner_plan").state in ("kwartieren", "zon_aanvullen")


async def test_cost_sensors_update_once_per_quarter(hass: HomeAssistant, freezer) -> None:
    freezer.move_to("2026-11-12 18:01:00+01:00")
    entry = await _setup(hass)
    coordinator = entry.runtime_data
    await coordinator.async_set("fixed_import", 0.30)
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    before = hass.states.get("sensor.laadplanner_kosten_vast_vandaag").state
    hass.states.async_set("sensor.meterkast_p1_meter_hw_energie_import", "1001.0")
    freezer.tick(timedelta(minutes=1))
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    # counted, but not shown yet: no extra database row this minute
    assert abs(coordinator.sim["fixed_day"] - 0.30) < 1e-6
    assert hass.states.get("sensor.laadplanner_kosten_vast_vandaag").state == before
    freezer.move_to("2026-11-12 18:15:00+01:00")
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert float(hass.states.get("sensor.laadplanner_kosten_vast_vandaag").state) == 0.30


async def test_steering_failure_warns_once(hass: HomeAssistant, caplog) -> None:
    entry = await _setup(hass)

    async def broken(call):
        raise HomeAssistantError("laadpaal offline")

    hass.services.async_register("switch", "turn_on", broken)
    coordinator = entry.runtime_data
    await coordinator.async_set("strategy", "direct")
    await coordinator.async_set("active", True)
    caplog.clear()
    for _ in range(3):
        coordinator._last_switch = None  # noqa: SLF001
        await coordinator.async_refresh()
    warnings = [r for r in caplog.records
                if r.levelname == "WARNING" and "sturen mislukt" in r.getMessage()]
    assert len(warnings) == 1


async def test_stale_completed_from_last_session_is_ignored(hass: HomeAssistant) -> None:
    # Yesterday's "COMPLETED", FordPass not refreshed since plugging in at 50%
    entry = await _setup(hass)
    hass.states.async_set("sensor.fordpass_jouw_vin_elvehcharging", "COMPLETED")
    hass.states.async_set("sensor.fordpass_jouw_vin_lastrefresh",
                          (dt_util.utcnow() - timedelta(hours=5)).isoformat())
    hass.states.async_set("binary_sensor.iq_ev_charger_1219_ingeplugd", "off")
    hass.states.async_set("binary_sensor.iq_ev_charger_1219_ingeplugd", "on")
    hass.states.async_set("sensor.fordpass_jouw_vin_soc", "50")
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get("sensor.laadplanner_plan").state in ("kwartieren", "zon_aanvullen")
    assert float(hass.states.get("sensor.laadplanner_resterende_vraag").state) > 0


async def test_completed_without_refresh_time_is_ignored(hass: HomeAssistant) -> None:
    entry = await _setup(hass)
    hass.states.async_set("sensor.fordpass_jouw_vin_elvehcharging", "COMPLETED")
    hass.states.async_set("sensor.fordpass_jouw_vin_lastrefresh", "unavailable")
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get("sensor.laadplanner_plan").state != "geen"


def _current(hass: HomeAssistant, amps: str, phases: str = "Three Phase") -> None:
    hass.states.async_set("number.auto_iq_ev_charger_1219_standaard_laadniveau", amps,
                          {"unit_of_measurement": "A"})
    hass.states.async_set("sensor.iq_ev_charger_1219_elektrische_fase", phases)


async def test_plan_uses_set_current(hass: HomeAssistant, freezer) -> None:
    _current(hass, "16.0")
    freezer.tick(timedelta(minutes=5))
    entry = await _setup(hass)
    plan = hass.states.get("sensor.laadplanner_plan")
    # 16 A x 230 V x 3 = 11.04 kW, of which the car takes 90% until learned
    assert plan.attributes["laadvermogen_kw"] == 9.9
    assert plan.attributes["laadstroom_a"] == 16.0
    assert plan.attributes["fasen"] == 3

    _current(hass, "6.0")
    freezer.tick(timedelta(minutes=3))
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    plan6 = hass.states.get("sensor.laadplanner_plan")
    assert plan6.attributes["laadvermogen_kw"] == 3.7  # 6 x 230 x 3 x 0.9
    assert plan6.attributes["kwartieren_nodig"] > plan.attributes["kwartieren_nodig"]


async def test_brief_current_change_is_ignored(hass: HomeAssistant, freezer) -> None:
    _current(hass, "16.0")
    freezer.tick(timedelta(minutes=5))
    entry = await _setup(hass)
    _current(hass, "6.0")  # a few seconds at 6 A, as seen in practice
    freezer.tick(timedelta(seconds=10))
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get("sensor.laadplanner_plan").attributes["laadstroom_a"] == 16.0


async def test_single_phase(hass: HomeAssistant, freezer) -> None:
    _current(hass, "16.0", "Single Phase")
    freezer.tick(timedelta(minutes=5))
    await _setup(hass)
    plan = hass.states.get("sensor.laadplanner_plan")
    assert plan.attributes["fasen"] == 1
    assert plan.attributes["laadvermogen_kw"] == 3.3  # 16 x 230 x 0.9


async def test_learns_share_the_car_takes(hass: HomeAssistant, freezer) -> None:
    _current(hass, "16.0")
    freezer.tick(timedelta(minutes=10))
    entry = await _setup(hass)
    coordinator = entry.runtime_data
    freezer.tick(timedelta(minutes=1))
    hass.states.async_set("sensor.iq_ev_charger_1219_vermogen", "9936",
                          {"unit_of_measurement": "W"})
    await coordinator.async_refresh()
    assert abs(coordinator.charge_factor - 9.936 / 11.04) < 1e-6
    # at another current the same share is used
    _current(hass, "10.0")
    freezer.tick(timedelta(minutes=3))
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    expected = round(10 * 230 * 3 / 1000 * 9.936 / 11.04, 1)
    assert hass.states.get("sensor.laadplanner_plan").attributes["laadvermogen_kw"] == expected


async def test_fordpass_defaults_follow_configured_soc(hass: HomeAssistant) -> None:
    entry = await _setup(hass)
    hass.config_entries.async_update_entry(
        entry, data={**entry.data, "soc_entity": "sensor.fordpass_abc123_soc"})
    await hass.async_block_till_done()
    entry = hass.config_entries.async_entries("laadplanner")[0]
    data = {k: v for k, v in entry.data.items()
            if k not in ("car_charge_status_entity", "car_last_refresh_entity")}
    hass.config_entries.async_update_entry(entry, data=data)
    coordinator = entry.runtime_data
    assert coordinator.conf("car_charge_status_entity") == "sensor.fordpass_abc123_elvehcharging"
    assert coordinator.conf("car_last_refresh_entity") == "sensor.fordpass_abc123_lastrefresh"


async def _active(hass, entry, strategy="direct"):
    coordinator = entry.runtime_data
    await coordinator.async_set("strategy", strategy)
    await coordinator.async_set("active", True)
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    return coordinator


async def test_start_not_repeated_while_cloud_lags(hass: HomeAssistant, freezer) -> None:
    """The Enphase switch stays 'off' for minutes after a start (seen 15-11)."""
    entry = await _setup(hass)
    on = async_mock_service(hass, "switch", "turn_on")
    coordinator = await _active(hass, entry)
    assert len(on) == 1
    for _ in range(3):  # 3 x 1 min: switch still reported off
        freezer.tick(timedelta(minutes=1))
        await coordinator.async_refresh()
        await hass.async_block_till_done()
    assert len(on) == 1
    freezer.tick(timedelta(minutes=3))  # > 5 min and still nothing: try again
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert len(on) == 2


async def test_stop_sent_although_switch_still_reports_off(hass: HomeAssistant, freezer) -> None:
    """Right after a start the reported switch is still 'off': stop anyway."""
    entry = await _setup(hass)
    async_mock_service(hass, "switch", "turn_on")
    off = async_mock_service(hass, "switch", "turn_off")
    coordinator = await _active(hass, entry)
    freezer.tick(timedelta(seconds=30))  # well within the 120 s flap guard
    await coordinator.async_set("strategy", "kwartieren")
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get("sensor.laadplanner_plan").attributes["nu_laden"] is False
    assert len(off) == 1


async def test_stop_repeated_while_car_still_charges(hass: HomeAssistant, freezer) -> None:
    entry = await _setup(hass)
    off = async_mock_service(hass, "switch", "turn_off")
    hass.states.async_set("switch.iq_ev_charger_1219", "on")
    coordinator = await _active(hass, entry, "kwartieren")
    assert hass.states.get("sensor.laadplanner_plan").attributes["nu_laden"] is False
    assert len(off) == 1
    hass.states.async_set("switch.iq_ev_charger_1219", "off")  # cloud says off ...
    freezer.tick(timedelta(minutes=1))
    hass.states.async_set("sensor.fordpass_jouw_vin_elvehcharging", "IN_PROGRESS")  # ... car disagrees
    hass.states.async_set("sensor.fordpass_jouw_vin_lastrefresh",  # with data from after the stop
                          dt_util.utcnow().isoformat())
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert len(off) == 1  # not every minute
    for _ in range(20):
        freezer.tick(timedelta(minutes=2, seconds=1))
        await coordinator.async_refresh()
        await hass.async_block_till_done()
    assert len(off) == 5  # capped
    # once nothing shows charging any more, nothing is sent
    hass.states.async_set("sensor.fordpass_jouw_vin_elvehcharging", "NOT_READY")
    freezer.tick(timedelta(minutes=10))
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert len(off) == 5


async def test_quiet_charger_gets_no_stop(hass: HomeAssistant) -> None:
    entry = await _setup(hass)
    off = async_mock_service(hass, "switch", "turn_off")
    await _active(hass, entry, "kwartieren")
    assert off == []


async def test_no_learning_in_green_mode(hass: HomeAssistant, freezer) -> None:
    _current(hass, "16.0")
    freezer.tick(timedelta(minutes=10))
    entry = await _setup(hass)
    hass.states.async_set("select.iq_ev_charger_1219_laadmodus", "Groen",
                          {"options": ["Handmatig", "Gepland", "Groen"]})
    freezer.tick(timedelta(minutes=1))
    hass.states.async_set("sensor.iq_ev_charger_1219_vermogen", "3600",
                          {"unit_of_measurement": "W"})
    await entry.runtime_data.async_refresh()
    assert entry.runtime_data.charge_factor is None


async def test_stale_car_charging_status_sends_no_extra_stops(hass: HomeAssistant, freezer) -> None:
    """An old 'in progress' from before the stop must not use up the retries."""
    entry = await _setup(hass)
    hass.states.async_set("sensor.fordpass_jouw_vin_elvehcharging", "IN_PROGRESS")
    hass.states.async_set("sensor.fordpass_jouw_vin_lastrefresh",
                          (dt_util.utcnow() - timedelta(hours=3)).isoformat())
    off = async_mock_service(hass, "switch", "turn_off")
    hass.states.async_set("switch.iq_ev_charger_1219", "on")
    coordinator = await _active(hass, entry, "kwartieren")
    assert len(off) == 1
    hass.states.async_set("switch.iq_ev_charger_1219", "off")
    for _ in range(10):
        freezer.tick(timedelta(minutes=2, seconds=1))
        await coordinator.async_refresh()
        await hass.async_block_till_done()
    assert len(off) == 1


async def test_warns_once_when_charger_keeps_charging(hass: HomeAssistant, freezer, caplog) -> None:
    entry = await _setup(hass)
    off = async_mock_service(hass, "switch", "turn_off")
    hass.states.async_set("switch.iq_ev_charger_1219", "on")  # stays on: charger ignores us
    coordinator = await _active(hass, entry, "kwartieren")
    caplog.clear()
    for _ in range(12):
        freezer.tick(timedelta(minutes=2, seconds=1))
        await coordinator.async_refresh()
        await hass.async_block_till_done()
    assert len(off) == 5
    warnings = [r for r in caplog.records
                if r.levelname == "WARNING" and "nog te laden" in r.getMessage()]
    assert len(warnings) == 1


async def test_stop_resent_when_cloud_catches_up(hass: HomeAssistant, freezer) -> None:
    """15-11 19:56: 'off' sent while the cloud still said 'off' was ignored.
    As soon as the cloud reports the charger on, stop again at once."""
    entry = await _setup(hass)
    async_mock_service(hass, "switch", "turn_on")
    off = async_mock_service(hass, "switch", "turn_off")
    coordinator = await _active(hass, entry)          # start, cloud says off
    freezer.tick(timedelta(minutes=2))
    await coordinator.async_set("strategy", "kwartieren")
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert len(off) == 1                               # sent too early
    freezer.tick(timedelta(seconds=30))                # within the resend wait
    hass.states.async_set("switch.iq_ev_charger_1219", "on")  # cloud catches up
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert len(off) == 2                               # immediately again


async def test_live_stream_requested_after_command(hass: HomeAssistant) -> None:
    from homeassistant.helpers import entity_registry as er
    reg = er.async_get(hass)
    made = reg.async_get_or_create("switch", "enphase_ev", "iq1219",
                                   suggested_object_id="iq_ev_charger_1219")
    assert made.entity_id == "switch.iq_ev_charger_1219"
    entry = await _setup(hass)
    async_mock_service(hass, "switch", "turn_on")
    live = async_mock_service(hass, "enphase_ev", "start_live_stream")
    await _active(hass, entry)
    await hass.async_block_till_done()
    assert [c.data["entity_id"] for c in live] == ["switch.iq_ev_charger_1219"]
