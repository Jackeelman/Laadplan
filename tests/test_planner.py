"""Tests for the pure planner logic."""

from datetime import datetime, time, timedelta
import importlib.util
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

_PATH = Path(__file__).parents[1] / "custom_components" / "laadplanner" / "planner.py"
_spec = importlib.util.spec_from_file_location("planner", _PATH)
p = importlib.util.module_from_spec(_spec)
sys.modules["planner"] = p
_spec.loader.exec_module(p)

TZ = ZoneInfo("Europe/Amsterdam")


def base(**kw):
    now = kw.pop("now", datetime(2026, 11, 12, 18, 7, tzinfo=TZ))
    args = dict(
        now=now,
        soc_pct=40.0,
        target_pct=80.0,
        capacity_kwh=77.0,
        efficiency=0.9,
        charge_power_kw=11.0,
        deadline=p.next_deadline(now, time(7, 0)),
        plugged_in=True,
        strategy=p.STRATEGY_AUTO,
        contract=p.CONTRACT_FIXED,
    )
    args.update(kw)
    return p.PlanInput(**args)


def test_needed_energy_includes_losses():
    inp = base()
    assert abs(p.needed_energy_kwh(inp) - 0.4 * 77 / 0.9) < 1e-6


def test_quarters_round_up():
    assert p.quarters_for(34.2, 11.0) == 13
    assert p.quarters_for(0, 11.0) == 0
    assert p.quarters_for(2.75, 11.0) == 1


def test_not_plugged_in_gives_preview():
    plan = p.make_plan(base(plugged_in=False))
    assert plan.mode == p.MODE_PREVIEW
    assert len(plan.slots) == plan.quarters_needed == 13
    assert plan.reason.startswith("Voorlopig")
    # a preview is never steered
    assert not plan.charge_now(datetime(2026, 11, 12, 22, 5, tzinfo=TZ))


def test_not_plugged_in_and_full_is_idle():
    plan = p.make_plan(base(plugged_in=False, soc_pct=85))
    assert plan.mode == p.MODE_IDLE and plan.slots == []


def test_preview_of_direct_is_never_steered():
    plan = p.make_plan(base(plugged_in=False, strategy=p.STRATEGY_DIRECT))
    assert plan.mode == p.MODE_PREVIEW
    assert not plan.charge_now(datetime(2026, 11, 12, 18, 7, tzinfo=TZ))


def test_full_is_idle():
    plan = p.make_plan(base(soc_pct=80))
    assert plan.mode == p.MODE_IDLE


def test_fixed_contract_picks_night_quarters_in_order():
    plan = p.make_plan(base())
    assert plan.mode == p.MODE_QUARTERS
    assert plan.feasible
    assert len(plan.slots) == plan.quarters_needed == 13
    assert plan.slots[0] == datetime(2026, 11, 12, 22, 0, tzinfo=TZ)
    assert all(p.is_night(s, time(22), time(7)) for s in plan.slots)
    assert plan.slots == sorted(plan.slots)


def test_dynamic_contract_picks_cheapest():
    now = datetime(2026, 11, 12, 18, 0, tzinfo=TZ)
    prices = []
    start = now
    for i in range(13 * 4):
        price = 0.30
        if i in (20, 21, 30):  # three cheap quarters
            price = 0.10
        prices.append(p.PriceSlot(start + i * p.QUARTER, start + (i + 1) * p.QUARTER, price))
    plan = p.make_plan(base(now=now, contract=p.CONTRACT_DYNAMIC, prices=prices,
                            soc_pct=72))
    assert plan.quarters_needed == 3
    assert set(plan.slots) == {now + 20 * p.QUARTER, now + 21 * p.QUARTER,
                               now + 30 * p.QUARTER}


def test_dynamic_unknown_prices_fall_back_to_night():
    now = datetime(2026, 11, 12, 18, 0, tzinfo=TZ)
    prices = [p.PriceSlot(now + i * p.QUARTER, now + (i + 1) * p.QUARTER, 0.2)
              for i in range(8)]  # only until 20:00
    plan = p.make_plan(base(now=now, contract=p.CONTRACT_DYNAMIC, prices=prices))
    assert plan.feasible
    assert "zonder bekende prijs" in plan.reason


def test_enough_sun_goes_green():
    plan = p.make_plan(base(solar_before_deadline_kwh=80, solar_surplus_factor=0.5))
    assert plan.mode == p.MODE_SOLAR and plan.slots == []


def test_partial_sun_tops_up():
    plan = p.make_plan(base(solar_before_deadline_kwh=30, solar_surplus_factor=0.5))
    assert plan.mode == p.MODE_SOLAR_TOPUP
    rest = plan.needed_kwh - 15
    assert len(plan.slots) == p.quarters_for(rest, 11.0)


def test_direct():
    plan = p.make_plan(base(strategy=p.STRATEGY_DIRECT))
    assert plan.mode == p.MODE_DIRECT
    assert plan.charge_now(datetime(2026, 11, 12, 18, 7, tzinfo=TZ))


def test_not_feasible_when_too_little_time():
    now = datetime(2026, 11, 13, 6, 10, tzinfo=TZ)
    plan = p.make_plan(base(now=now, soc_pct=10))
    assert not plan.feasible
    assert "niet haalbaar" in plan.reason


def test_charge_now_and_next_start():
    plan = p.make_plan(base())
    assert not plan.charge_now(datetime(2026, 11, 12, 21, 50, tzinfo=TZ))
    assert plan.charge_now(datetime(2026, 11, 12, 22, 5, tzinfo=TZ))
    assert plan.next_start(datetime(2026, 11, 12, 18, 7, tzinfo=TZ)) == datetime(
        2026, 11, 12, 22, 0, tzinfo=TZ)


def test_unknown_soc_uses_fallback():
    plan = p.make_plan(base(soc_pct=None, fallback_kwh=11))
    assert plan.needed_kwh == 11
    assert plan.quarters_needed == 4


def test_hourly_prices_are_spread_over_quarters():
    now = datetime(2026, 11, 12, 18, 0, tzinfo=TZ)
    lookup = p._price_lookup([p.PriceSlot(now, now + timedelta(hours=1), 0.25)])
    assert len(lookup) == 4


def test_solar_share_overnight_deadline():
    now = datetime(2026, 11, 12, 12, 30, tzinfo=TZ)
    dl = p.next_deadline(now, time(7, 0))
    assert p.solar_share_before(dl, now, 5.0, 20.0) == 5.0
    dl_noon = p.next_deadline(now, time(12, 30)) # tomorrow 12:30
    share = p.solar_share_before(dl_noon, now, 5.0, 18.0)
    assert abs(share - (5.0 + 18.0 * 270 / 540)) < 1e-6


def test_quarter_costs():
    t = p.Tariffs(fixed_import=0.30, fixed_export=0.05,
                  dyn_import_markup=0.15, dyn_export_markup=0.02)
    fixed, dyn = p.quarter_costs(1.0, 0.5, 0.10, t)
    assert abs(fixed - (0.30 - 0.025)) < 1e-9
    assert abs(dyn - (0.25 - 0.04)) < 1e-9
    fixed, dyn = p.quarter_costs(1.0, 0.0, None, t)
    assert dyn is None
