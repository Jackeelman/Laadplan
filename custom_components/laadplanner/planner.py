"""Pure planning logic for Laadplanner (no Home Assistant imports).

Kept free of HA so it can be unit-tested on its own.

The charger's current cannot be changed while the car is charging, so the
planner never touches the current. It only decides *when* to charge
(which quarters) or to hand control to the charger's own green mode.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, time, timedelta
import math

QUARTER = timedelta(minutes=15)

STRATEGY_AUTO = "automatisch"
STRATEGY_SOLAR = "zon"
STRATEGY_QUARTERS = "kwartieren"
STRATEGY_DIRECT = "direct"
STRATEGIES = [STRATEGY_AUTO, STRATEGY_SOLAR, STRATEGY_QUARTERS, STRATEGY_DIRECT]

CONTRACT_FIXED = "vast"
CONTRACT_DYNAMIC = "dynamisch"
CONTRACTS = [CONTRACT_FIXED, CONTRACT_DYNAMIC]

MODE_IDLE = "geen"            # nothing to do (full, not plugged in, ...)
MODE_SOLAR = "zon"            # charger in green mode, follows surplus itself
MODE_SOLAR_TOPUP = "zon_aanvullen"  # green by day, top up in chosen quarters
MODE_QUARTERS = "kwartieren"  # charge only in chosen quarters
MODE_DIRECT = "direct"        # charge now until target
MODE_PREVIEW = "voorlopig"    # car not plugged in: plan shown, never steered


@dataclass
class PriceSlot:
    """One price interval (normally 15 minutes)."""

    start: datetime
    end: datetime
    price: float


@dataclass
class PlanInput:
    """Everything the planner needs, already read from Home Assistant."""

    now: datetime
    soc_pct: float | None
    target_pct: float
    capacity_kwh: float
    efficiency: float           # 0..1, energy into battery / energy from grid
    charge_power_kw: float      # what the charger really delivers
    deadline: datetime          # next moment the car must be ready
    plugged_in: bool
    strategy: str
    contract: str
    prices: list[PriceSlot] = field(default_factory=list)
    solar_before_deadline_kwh: float = 0.0
    solar_surplus_factor: float = 0.5   # share of PV that is real surplus
    night_start: time = time(22, 0)
    night_end: time = time(7, 0)
    fallback_kwh: float = 10.0  # used when the SoC is unknown
    car_done: bool = False      # the car itself reports charging completed


@dataclass
class Plan:
    """Result of one planning run."""

    mode: str
    needed_kwh: float
    quarters_needed: int
    slots: list[datetime]
    reason: str
    feasible: bool = True
    expected_surplus_kwh: float = 0.0

    def charge_now(self, now: datetime) -> bool:
        """True if the charger should be on at ``now`` (quarter modes)."""
        if self.mode == MODE_DIRECT:
            return self.needed_kwh > 0
        if self.mode not in (MODE_QUARTERS, MODE_SOLAR_TOPUP):
            return False
        current = floor_quarter(now)
        return current in self.slots

    def next_start(self, now: datetime) -> datetime | None:
        """First planned quarter that has not ended yet."""
        current = floor_quarter(now)
        upcoming = [s for s in self.slots if s >= current]
        return min(upcoming) if upcoming else None


def floor_quarter(moment: datetime) -> datetime:
    """Round down to the start of the quarter."""
    return moment.replace(
        minute=moment.minute - moment.minute % 15, second=0, microsecond=0
    )


def next_deadline(now: datetime, deadline_time: time) -> datetime:
    """Next occurrence of ``deadline_time`` after ``now`` (same tz)."""
    candidate = now.replace(
        hour=deadline_time.hour,
        minute=deadline_time.minute,
        second=0,
        microsecond=0,
    )
    if candidate <= now:
        candidate += timedelta(days=1)
    return candidate


def needed_energy_kwh(inp: PlanInput) -> float:
    """Grid energy needed to reach the target, including charging losses."""
    if inp.soc_pct is None:
        return max(0.0, inp.fallback_kwh)
    missing_pct = max(0.0, inp.target_pct - inp.soc_pct)
    battery_kwh = missing_pct / 100.0 * inp.capacity_kwh
    eff = inp.efficiency if inp.efficiency > 0 else 1.0
    return battery_kwh / eff


def quarters_for(energy_kwh: float, power_kw: float) -> int:
    """Number of quarters needed to deliver ``energy_kwh`` at ``power_kw``."""
    if energy_kwh <= 0:
        return 0
    per_quarter = max(power_kw, 0.1) * 0.25
    return math.ceil(energy_kwh / per_quarter - 1e-9)


def is_night(moment: datetime, night_start: time, night_end: time) -> bool:
    """True if ``moment`` falls in the night window (may cross midnight)."""
    t = moment.time()
    if night_start <= night_end:
        return night_start <= t < night_end
    return t >= night_start or t < night_end


def candidate_quarters(now: datetime, deadline: datetime) -> list[datetime]:
    """All quarters that start now or later and end by the deadline."""
    # Step in UTC so a DST change does not add or drop an hour of quarters.
    slots: list[datetime] = []
    cursor = floor_quarter(now).astimezone(UTC)
    while cursor + QUARTER <= deadline:
        slots.append(cursor.astimezone(now.tzinfo))
        cursor += QUARTER
    return slots


def _price_lookup(prices: list[PriceSlot]) -> dict[datetime, float]:
    """Map each quarter start to its price (hourly prices are spread out)."""
    lookup: dict[datetime, float] = {}
    for slot in prices:
        cursor = floor_quarter(slot.start).astimezone(UTC)
        while cursor < slot.end:
            lookup[cursor.astimezone(slot.start.tzinfo)] = slot.price
            cursor += QUARTER
    return lookup


def pick_quarters(
    inp: PlanInput, count: int, candidates: list[datetime]
) -> tuple[list[datetime], str]:
    """Choose ``count`` quarters from ``candidates``.

    Fixed contract: price does not matter, so take night quarters first,
    in time order (finish early = margin), then the quarters closest to
    the night window.

    Dynamic contract: cheapest known quarters first; on equal price the
    night wins, then the earlier quarter. Quarters without a known price
    (tomorrow not published yet) are only used when needed, night first.
    """
    if count <= 0 or not candidates:
        return [], ""

    def night(s: datetime) -> bool:
        return is_night(s, inp.night_start, inp.night_end)

    if inp.contract == CONTRACT_DYNAMIC and inp.prices:
        lookup = _price_lookup(inp.prices)
        priced = [s for s in candidates if s in lookup]
        unpriced = [s for s in candidates if s not in lookup]
        priced.sort(key=lambda s: (round(lookup[s], 5), not night(s), s))
        unpriced.sort(key=lambda s: (not night(s), s))
        chosen = (priced + unpriced)[:count]
        how = "goedkoopste kwartieren"
        if any(s in unpriced for s in chosen):
            how += " (deels zonder bekende prijs, nacht gekozen)"
    else:
        # Night quarters in time order; if the night is too short, take the
        # evening quarters closest to the night (latest first).
        nights = sorted(s for s in candidates if night(s))
        others = sorted((s for s in candidates if not night(s)), reverse=True)
        chosen = (nights + others)[:count]
        how = (f"nachtkwartieren vanaf {inp.night_start.strftime('%H:%M')} "
               "(vast tarief, tijdstip maakt niet uit voor de prijs)")

    return sorted(chosen), how


def make_plan(inp: PlanInput) -> Plan:
    """Build the charging plan for the next deadline."""
    needed = needed_energy_kwh(inp)
    quarters = quarters_for(needed, inp.charge_power_kw)

    if not inp.plugged_in:
        if needed <= 0.05:
            return Plan(MODE_IDLE, 0.0, 0, [], "Auto niet aangesloten, doel-SoC al bereikt")
        # Show what would happen if the car were plugged in now; this plan is
        # only for the dashboard and is never steered.
        preview = make_plan(replace(inp, plugged_in=True))
        if preview.mode == MODE_DIRECT:
            how = "direct laden zodra de auto aangesloten is"
        else:
            how = preview.reason
        return Plan(
            MODE_PREVIEW,
            preview.needed_kwh,
            preview.quarters_needed,
            preview.slots,
            f"Voorlopig (auto niet aangesloten): {how}",
            feasible=preview.feasible,
            expected_surplus_kwh=preview.expected_surplus_kwh,
        )
    if needed <= 0.05:
        return Plan(MODE_IDLE, 0.0, 0, [], "Doel-SoC bereikt")
    if inp.car_done:
        # The car stopped on its own limit (or before our SoC reading caught
        # up): nothing more will go in, so plan nothing and ask nothing.
        return Plan(MODE_IDLE, 0.0, 0, [],
                    "Auto meldt laden voltooid (eigen laadgrens van de auto bereikt)")

    if inp.strategy == STRATEGY_DIRECT:
        return Plan(MODE_DIRECT, needed, quarters, [], "Direct laden tot het doel")

    surplus = max(0.0, inp.solar_before_deadline_kwh) * inp.solar_surplus_factor
    candidates = candidate_quarters(inp.now, inp.deadline)

    if inp.strategy == STRATEGY_SOLAR:
        return Plan(
            MODE_SOLAR,
            needed,
            quarters,
            [],
            f"Zon gekozen: paal op Groen (verwacht overschot {surplus:.1f} kWh)",
            feasible=surplus >= needed,
            expected_surplus_kwh=surplus,
        )

    if inp.strategy == STRATEGY_AUTO and surplus >= needed:
        return Plan(
            MODE_SOLAR,
            needed,
            quarters,
            [],
            f"Verwacht overschot {surplus:.1f} kWh dekt {needed:.1f} kWh: paal op Groen",
            expected_surplus_kwh=surplus,
        )

    # Quarters needed for the part the sun will not cover.
    if inp.strategy == STRATEGY_AUTO and surplus >= 0.2 * needed:
        rest = needed - surplus
        rest_quarters = quarters_for(rest, inp.charge_power_kw)
        night_or_late = [s for s in candidates if s.date() == inp.deadline.date()
                         or is_night(s, inp.night_start, inp.night_end)]
        slots, how = pick_quarters(inp, rest_quarters, night_or_late or candidates)
        feasible = len(slots) >= rest_quarters
        return Plan(
            MODE_SOLAR_TOPUP,
            needed,
            quarters,
            slots,
            f"Zon dekt ~{surplus:.1f} van {needed:.1f} kWh; rest {rest:.1f} kWh in {how}",
            feasible=feasible,
            expected_surplus_kwh=surplus,
        )

    slots, how = pick_quarters(inp, quarters, candidates)
    feasible = len(slots) >= quarters
    reason = f"{needed:.1f} kWh in {quarters} kwartieren: {how}"
    if not feasible:
        reason += f" — niet haalbaar voor de deadline ({len(slots)} kwartieren beschikbaar)"
    return Plan(
        MODE_QUARTERS,
        needed,
        quarters,
        slots,
        reason,
        feasible=feasible,
        expected_surplus_kwh=surplus,
    )


def solar_share_before(deadline: datetime, now: datetime,
                       remaining_today_kwh: float, tomorrow_kwh: float,
                       sun_start: time = time(8, 0),
                       sun_end: time = time(17, 0)) -> float:
    """Rough PV energy expected between now and the deadline.

    The forecast integration only gives day totals, so tomorrow's share is
    estimated linearly over a fixed sun window. Good enough to choose
    between green and quarters; refine later with an hourly forecast.
    """
    total = 0.0
    if deadline.date() == now.date():
        span = _fraction(now.time(), deadline.time(), sun_start, sun_end)
        rest = _fraction(now.time(), sun_end, sun_start, sun_end)
        if rest > 0:
            total += remaining_today_kwh * min(1.0, span / rest)
        return total
    total += max(0.0, remaining_today_kwh)
    if deadline.date() == (now + timedelta(days=1)).date():
        total += max(0.0, tomorrow_kwh) * _fraction(
            sun_start, deadline.time(), sun_start, sun_end
        )
    else:
        total += max(0.0, tomorrow_kwh)
    return total


def _fraction(a: time, b: time, sun_start: time, sun_end: time) -> float:
    """Share of the sun window covered by [a, b) on one day (0..1)."""
    def mins(t: time) -> int:
        return t.hour * 60 + t.minute

    lo, hi = mins(sun_start), mins(sun_end)
    start, end = max(mins(a), lo), min(mins(b), hi)
    if end <= start or hi <= lo:
        return 0.0
    return (end - start) / (hi - lo)


# --- Simulation: fixed vs dynamic -------------------------------------------


@dataclass
class Tariffs:
    """All prices per kWh, including VAT."""

    fixed_import: float
    fixed_export: float
    dyn_import_markup: float   # added to the price sensor for buying
    dyn_export_markup: float   # subtracted from the price sensor for selling


def quarter_costs(import_kwh: float, export_kwh: float, price: float | None,
                  tariffs: Tariffs) -> tuple[float, float | None]:
    """Cost of one interval on the fixed and on the dynamic contract."""
    fixed = import_kwh * tariffs.fixed_import - export_kwh * tariffs.fixed_export
    if price is None:
        return fixed, None
    dynamic = (import_kwh * (price + tariffs.dyn_import_markup)
               - export_kwh * (price - tariffs.dyn_export_markup))
    return fixed, dynamic
