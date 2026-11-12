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
    hass.states.async_set("sensor.fordpass_wf0rpbef9tsk88764_soc", soc)
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


async def test_simulation_counts_costs(hass: HomeAssistant) -> None:
    entry = await _setup(hass)
    coordinator = entry.runtime_data
    await coordinator.async_set("fixed_import", 0.30)
    hass.states.async_set("sensor.meterkast_p1_meter_hw_energie_import", "1001.0")
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
    hass.states.async_set("sensor.fordpass_wf0rpbef9tsk88764_soc", "85")
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
    hass.states.async_set("sensor.fordpass_wf0rpbef9tsk88764_soc", "85")
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
    hass.states.async_set("sensor.fordpass_wf0rpbef9tsk88764_soc", "70")
    hass.states.async_set("sensor.fordpass_wf0rpbef9tsk88764_elvehcharging", "COMPLETED")
    await entry.runtime_data.async_set("active", True)
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get("sensor.laadplanner_plan").state == "geen"
    assert float(hass.states.get("sensor.laadplanner_resterende_vraag").state) == 0
    assert [c.data["entity_id"] for c in off] == ["switch.iq_ev_charger_1219"]


async def test_car_charging_status_keeps_planning(hass: HomeAssistant) -> None:
    entry = await _setup(hass)
    hass.states.async_set("sensor.fordpass_wf0rpbef9tsk88764_elvehcharging", "IN_PROGRESS")
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get("sensor.laadplanner_plan").state in ("kwartieren", "zon_aanvullen")
