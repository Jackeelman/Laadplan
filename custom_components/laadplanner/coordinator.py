"""Coordinator: reads HA states, plans, simulates and (optionally) steers."""

from __future__ import annotations

from datetime import datetime, time, timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant, State
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from . import planner as pl
from .const import (
    CAR_CHARGING_STATES,
    START_CONFIRM_S,
    STOP_MAX_RESENDS,
    STOP_RESEND_S,
    CURRENT_SETTLE_S,
    DEFAULT_CHARGE_FACTOR,
    LEARN_SETTLE_S,
    VIN_PLACEHOLDER,
    VOLTAGE,
    CAR_DONE_STATES,
    CONF_CAPACITY,
    CONF_CAR_REFRESH,
    CONF_CAR_STATUS,
    CONF_CHARGER_CURRENT,
    CONF_CHARGER_MODE,
    CONF_CHARGER_PHASES,
    CONF_CHARGER_POWER,
    CONF_CHARGER_SWITCH,
    CONF_EXPORT,
    CONF_GREEN_OPTION,
    CONF_IMPORT,
    CONF_MANUAL_OPTION,
    CONF_PLUG,
    CONF_PRICE,
    CONF_SOC,
    CONF_SOLAR_TODAY,
    CONF_SOLAR_TOMORROW,
    DEFAULTS,
    DOMAIN,
    MIN_SWITCH_INTERVAL_S,
    SET_ACTIVE,
    SET_CONTRACT,
    SET_DEADLINE,
    SET_DYN_EXPORT,
    SET_DYN_IMPORT,
    SET_EFFICIENCY,
    SET_FALLBACK,
    SET_FIXED_EXPORT,
    SET_FIXED_IMPORT,
    SET_NIGHT_START,
    SET_POWER,
    SET_STRATEGY,
    SET_SURPLUS,
    SET_TARGET,
    SETTING_DEFAULTS,
    STORAGE_VERSION,
    UPDATE_SECONDS,
)

_LOGGER = logging.getLogger(__name__)

_BAD = (None, "", STATE_UNKNOWN, STATE_UNAVAILABLE)
_PLUGGED_WORDS = {"on", "true", "connected", "plugged", "plugged_in",
                  "aangesloten", "ingeplugd", "charging", "laden"}


def _float(state: State | None) -> float | None:
    if state is None or state.state in _BAD:
        return None
    try:
        return float(state.state)
    except (TypeError, ValueError):
        return None


def parse_prices(state: State | None) -> list[pl.PriceSlot]:
    """Read a price series from common price integrations.

    Supports the Nord Pool custom integration (raw_today / raw_tomorrow)
    and Zonneplan ONE (forecast list with electricity_price x 10^7).
    """
    if state is None:
        return []
    attrs = state.attributes
    slots: list[pl.PriceSlot] = []

    for key in ("raw_today", "raw_tomorrow"):
        for item in attrs.get(key) or []:
            try:
                start = _as_dt(item["start"])
                end = _as_dt(item["end"])
                value = float(item["value"])
            except (KeyError, TypeError, ValueError):
                continue
            if start and end:
                slots.append(pl.PriceSlot(start, end, value))
    if slots:
        return slots

    forecast = attrs.get("forecast") or []
    points: list[tuple[datetime, float]] = []
    for item in forecast:
        try:
            start = _as_dt(item["datetime"])
            raw = float(item["electricity_price"])
        except (KeyError, TypeError, ValueError):
            continue
        if start:
            points.append((start, raw / 10_000_000))
    points.sort()
    for i, (start, price) in enumerate(points):
        end = points[i + 1][0] if i + 1 < len(points) else start + timedelta(hours=1)
        if end - start > timedelta(hours=1):
            end = start + timedelta(hours=1)
        slots.append(pl.PriceSlot(start, end, price))
    return slots


def _as_dt(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return dt_util.as_local(value)
    if isinstance(value, str):
        parsed = dt_util.parse_datetime(value)
        return dt_util.as_local(parsed) if parsed else None
    return None


def price_at(slots: list[pl.PriceSlot], moment: datetime) -> float | None:
    for slot in slots:
        if slot.start <= moment < slot.end:
            return slot.price
    return None


class LaadplannerCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Plans EV charging and simulates fixed vs dynamic costs."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=UPDATE_SECONDS),
            config_entry=entry,
        )
        self.entry = entry
        self._store: Store = Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}")
        self.settings: dict[str, Any] = dict(SETTING_DEFAULTS)
        self.sim: dict[str, Any] = {}
        self.measured_power_kw: float | None = None
        # Set charging current (A), phases and the learned share of that
        # power the car really takes (0..1).
        self.charger_amps: float | None = None
        self.charger_phases: int | None = None
        self.charge_factor: float | None = None
        self._last_switch: datetime | None = None
        # What the planner itself last told the charger, and when. The
        # Enphase cloud reports the switch minutes late, so this is trusted
        # over the reported state.
        self._commanded: bool | None = None
        self._commanded_at: datetime | None = None
        self._off_sends = 0
        self._last_power_update: datetime | None = None
        self._save_scheduled = False
        self._sim_shown: dict[str, Any] = {}
        self._sim_shown_quarter: datetime | None = None
        self._steer_failing = False
        self.plan: pl.Plan | None = None

    # -- config helpers -----------------------------------------------------

    def conf(self, key: str) -> Any:
        merged = {**DEFAULTS, **self.entry.data, **self.entry.options}
        value = merged.get(key)
        if isinstance(value, str) and VIN_PLACEHOLDER in value:
            # A FordPass default that was never filled in (fields added in a
            # later version): take the car id from the configured SoC sensor,
            # e.g. sensor.fordpass_<id>_soc.
            soc = str(merged.get(CONF_SOC) or "")
            if (soc.startswith("sensor.fordpass_") and soc.endswith("_soc")
                    and VIN_PLACEHOLDER not in soc):
                car = soc[len("sensor.fordpass_"):-len("_soc")]
                value = value.replace(VIN_PLACEHOLDER, car)
        return value

    def _state(self, key: str) -> State | None:
        entity_id = self.conf(key)
        return self.hass.states.get(entity_id) if entity_id else None

    # -- persistence ----------------------------------------------------------

    async def async_load(self) -> None:
        stored = await self._store.async_load() or {}
        self.settings.update(stored.get("settings", {}))
        self.sim = stored.get("sim", {})
        self.measured_power_kw = stored.get("measured_power_kw")
        self.charge_factor = stored.get("charge_factor")
        self.charger_phases = stored.get("charger_phases")

    async def async_save(self) -> None:
        # A direct save also cancels a pending delayed save.
        self._save_scheduled = False
        await self._store.async_save(self._stored_data())

    def _schedule_save(self) -> None:
        """Write to the own .storage file at most once every 5 minutes.

        Store.async_delay_save postpones a pending write on every call, so
        calling it each minute would only ever write on shutdown (and lose
        the simulation after a crash). Only schedule when nothing is pending.
        """
        if self._save_scheduled:
            return
        self._save_scheduled = True
        self._store.async_delay_save(self._delayed_save_data, 300)

    def _delayed_save_data(self) -> dict[str, Any]:
        self._save_scheduled = False
        return self._stored_data()

    async def async_set(self, key: str, value: Any) -> None:
        """Change a setting from one of the integration's entities."""
        self.settings[key] = value
        self._sim_shown_quarter = None  # show new tariffs' effect right away
        await self.async_save()
        await self.async_request_refresh()

    # -- main loop ------------------------------------------------------------

    async def _async_update_data(self) -> dict[str, Any]:
        now = dt_util.now()
        prices = parse_prices(self._state(CONF_PRICE))
        self._read_charger_setting(now)
        self._learn_power(now)
        plan_input = self._build_input(now, prices)
        plan = pl.make_plan(plan_input)
        self.plan = plan
        sim = self._simulate(now, prices)
        # The cost sensors change almost every minute by a cent. Show them
        # once per quarter (the price interval) to keep the recorder small;
        # the counting itself still happens every minute.
        quarter = pl.floor_quarter(now)
        if quarter != self._sim_shown_quarter:
            self._sim_shown = sim
            self._sim_shown_quarter = quarter

        if self.settings.get(SET_ACTIVE):
            try:
                await self._steer(plan, now)
            except HomeAssistantError as err:
                # Keep the plan visible and try again next minute, but warn
                # only once per outage so the log does not fill up.
                if not self._steer_failing:
                    _LOGGER.warning("Laadplanner: sturen mislukt: %s", err)
                else:
                    _LOGGER.debug("Laadplanner: sturen nog steeds mislukt: %s", err)
                self._steer_failing = True
            else:
                if self._steer_failing:
                    _LOGGER.info("Laadplanner: sturen werkt weer")
                self._steer_failing = False

        nxt = plan.next_start(now)
        return {
            "plan": plan,
            "deadline": plan_input.deadline,
            "next_start": nxt,
            "charge_now": plan.charge_now(now),
            "power_kw": plan_input.charge_power_kw,
            "charger_amps": self.charger_amps,
            "charger_phases": self.charger_phases,
            "solar_before_deadline": plan_input.solar_before_deadline_kwh,
            "prices_known": len(prices),
            "sim": self._sim_shown,
        }

    def _setting_time(self, key: str, default: time) -> time:
        raw = str(self.settings.get(key, default.strftime("%H:%M")))
        try:
            hour, minute = raw.split(":")[:2]
            return time(int(hour), int(minute))
        except ValueError:
            return default

    def _deadline_time(self) -> time:
        return self._setting_time(SET_DEADLINE, time(7, 0))

    def _night_start_time(self) -> time:
        return self._setting_time(SET_NIGHT_START, time(0, 0))

    def _plugged(self) -> bool:
        state = self._state(CONF_PLUG)
        if state is None or state.state in _BAD:
            return False
        return state.state == STATE_ON or state.state.lower() in _PLUGGED_WORDS

    def _car_done(self) -> bool:
        """True if the car reports that it finished charging (own limit).

        Only trusted while the charger sees the car plugged in; the car's
        own plug status flickers and is not used.

        The car's data comes from the cloud and can lag hours behind. A
        "completed" left over from the previous session must not count, or
        the car would not charge tonight. So it only counts if the car's
        data was refreshed after the moment it was plugged in. When in
        doubt (unknown refresh time, just restarted) it does not count:
        planning a charge for a full car costs nothing, the car just
        doesn't take it.
        """
        state = self._state(CONF_CAR_STATUS)
        if state is None or state.state in _BAD:
            return False
        if str(state.state).lower() not in CAR_DONE_STATES:
            return False
        plug = self._state(CONF_PLUG)
        if plug is None or not self._plugged():
            return False
        plugged_since = plug.last_changed
        if self.conf(CONF_CAR_REFRESH):
            refresh = self._state(CONF_CAR_REFRESH)
            if refresh is None or refresh.state in _BAD:
                return False
            refreshed = dt_util.parse_datetime(str(refresh.state))
            return refreshed is not None and refreshed > plugged_since
        # No refresh sensor: the status itself must have changed after
        # plugging in.
        return state.last_changed > plugged_since

    def _read_charger_setting(self, now: datetime) -> None:
        """Read the charging current set on the charger, and its phases.

        Short changes (a few seconds at 6 A, as seen in practice) are
        ignored: a new current only counts once it has held for 2 minutes.
        """
        state = self._state(CONF_CHARGER_CURRENT)
        amps = _float(state)
        if state is not None and amps is not None and amps > 0:
            steady = (now - state.last_changed).total_seconds() >= CURRENT_SETTLE_S
            if steady or self.charger_amps is None:
                self.charger_amps = amps
        phases = self._phases()
        if phases:
            self.charger_phases = phases

    def _phases(self) -> int | None:
        state = self._state(CONF_CHARGER_PHASES)
        if state is None:
            return None
        raw = state.attributes.get("phase_mode_raw")
        if raw in (1, 3):
            return int(raw)
        text = str(state.state).lower()
        if any(w in text for w in ("three", "drie", "3")):
            return 3
        if any(w in text for w in ("single", "één", "een", "one", "1")):
            return 1
        return None  # unknown (e.g. right after a restart): keep the last one

    def _set_power_kw(self) -> float | None:
        """Power the set current allows: amps x 230 V x phases."""
        if not self.charger_amps:
            return None
        return self.charger_amps * VOLTAGE * (self.charger_phases or 3) / 1000

    def _charge_power_kw(self) -> float:
        """Power to plan with.

        With the charger's current known: the power that current allows,
        times the share the car has been seen to take. Otherwise the
        learned average, or the configured starting value.
        """
        set_kw = self._set_power_kw()
        if set_kw:
            factor = self.charge_factor
            if factor is None and self.measured_power_kw:
                # first run after updating: start from what was learned
                factor = min(1.0, self.measured_power_kw / set_kw)
            return set_kw * (factor if factor is not None else DEFAULT_CHARGE_FACTOR)
        return self.measured_power_kw or float(self.settings[SET_POWER])

    def _learn_power(self, now: datetime) -> None:
        """Remember what the charger really delivers.

        The Enphase charger power comes from the cloud and updates slowly, so
        only learn from a value that actually changed; it is a session
        average, not a control signal. With the set current known, learn the
        share of that power the car takes, only at a steady current.
        """
        state = self._state(CONF_CHARGER_POWER)
        value = _float(state)
        if value is None or state is None:
            return
        if state.last_updated == self._last_power_update:
            return
        self._last_power_update = state.last_updated
        unit = str(state.attributes.get("unit_of_measurement", "W")).lower()
        kw = value if unit == "kw" else value / 1000
        if kw < 1.0:  # not charging
            return
        if self.measured_power_kw is None:
            self.measured_power_kw = kw
        else:
            self.measured_power_kw = 0.9 * self.measured_power_kw + 0.1 * kw

        set_kw = self._set_power_kw()
        amps_state = self._state(CONF_CHARGER_CURRENT)
        if not set_kw or amps_state is None:
            return
        if (now - amps_state.last_changed).total_seconds() < LEARN_SETTLE_S:
            return  # the measurement window may still hold the old current
        if not self._mode_is(self.conf(CONF_MANUAL_OPTION)):
            return  # green mode may charge on one phase or at a lower current
        ratio = max(0.3, min(1.0, kw / set_kw))
        if self.charge_factor is None:
            self.charge_factor = ratio
        else:
            self.charge_factor = 0.9 * self.charge_factor + 0.1 * ratio

    def _build_input(self, now: datetime, prices: list[pl.PriceSlot]) -> pl.PlanInput:
        deadline = pl.next_deadline(now, self._deadline_time())
        solar = pl.solar_share_before(
            deadline,
            now,
            _float(self._state(CONF_SOLAR_TODAY)) or 0.0,
            _float(self._state(CONF_SOLAR_TOMORROW)) or 0.0,
        )
        power = self._charge_power_kw()
        return pl.PlanInput(
            now=now,
            soc_pct=_float(self._state(CONF_SOC)),
            target_pct=float(self.settings[SET_TARGET]),
            capacity_kwh=float(self.conf(CONF_CAPACITY)),
            efficiency=float(self.settings[SET_EFFICIENCY]),
            charge_power_kw=power,
            deadline=deadline,
            plugged_in=self._plugged(),
            car_done=self._car_done(),
            strategy=str(self.settings[SET_STRATEGY]),
            contract=str(self.settings[SET_CONTRACT]),
            prices=prices,
            solar_before_deadline_kwh=solar,
            solar_surplus_factor=float(self.settings[SET_SURPLUS]),
            fallback_kwh=float(self.settings[SET_FALLBACK]),
            night_start=self._night_start_time(),
            night_end=self._deadline_time(),
        )

    # -- simulation -----------------------------------------------------------

    def _simulate(self, now: datetime, prices: list[pl.PriceSlot]) -> dict[str, Any]:
        sim = self.sim
        day, month = now.date().isoformat(), now.strftime("%Y-%m")
        if sim.get("day") != day:
            sim.update(day=day, fixed_day=0.0, dyn_day=0.0, dyn_missing_day=0.0)
        if sim.get("month") != month:
            sim.update(month=month, fixed_month=0.0, dyn_month=0.0)

        imp = _float(self._state(CONF_IMPORT))
        exp = _float(self._state(CONF_EXPORT))
        last_imp, last_exp = sim.get("last_import"), sim.get("last_export")
        if imp is not None and exp is not None:
            if last_imp is not None and last_exp is not None:
                d_imp, d_exp = imp - last_imp, exp - last_exp
                # ignore meter resets and gaps (> 5 kWh per minute is not real)
                if 0 <= d_imp < 5 and 0 <= d_exp < 5:
                    tariffs = pl.Tariffs(
                        float(self.settings[SET_FIXED_IMPORT]),
                        float(self.settings[SET_FIXED_EXPORT]),
                        float(self.settings[SET_DYN_IMPORT]),
                        float(self.settings[SET_DYN_EXPORT]),
                    )
                    fixed, dyn = pl.quarter_costs(
                        d_imp, d_exp, price_at(prices, now), tariffs
                    )
                    sim["fixed_day"] += fixed
                    sim["fixed_month"] += fixed
                    if dyn is None:
                        sim["dyn_missing_day"] += d_imp + d_exp
                    else:
                        sim["dyn_day"] += dyn
                        sim["dyn_month"] += dyn
            sim["last_import"], sim["last_export"] = imp, exp
            # Batch writes to the own .storage file (not the recorder DB):
            # at most once every 5 minutes, and always on shutdown.
            self._schedule_save()
        return dict(sim)

    def _stored_data(self) -> dict[str, Any]:
        return {
            "settings": self.settings,
            "sim": self.sim,
            "measured_power_kw": self.measured_power_kw,
            "charge_factor": self.charge_factor,
            "charger_phases": self.charger_phases,
        }

    # -- steering (only when the active switch is on) -------------------------

    async def _steer(self, plan: pl.Plan, now: datetime) -> None:
        """Set the charger's mode and on/off. Never touches the current."""
        green = self.conf(CONF_GREEN_OPTION)
        manual = self.conf(CONF_MANUAL_OPTION)

        if plan.mode == pl.MODE_PREVIEW:
            return
        if plan.mode == pl.MODE_IDLE:
            # Target reached while plugged in: stop a manual charge that the
            # planner started, otherwise it would charge past the target.
            # Green mode is left alone (free solar is fine).
            if self._plugged() and self._mode_is(manual):
                await self._set_charging(False, now)
            return
        if plan.mode == pl.MODE_SOLAR:
            await self._set_mode(green)
            return
        if plan.mode == pl.MODE_SOLAR_TOPUP and not plan.charge_now(now):
            # Green before the first and after the last top-up quarter; in
            # between stay manual so the mode does not flip between quarters.
            if (not plan.slots or now < min(plan.slots)
                    or plan.next_start(now) is None):
                await self._set_mode(green)
                return
        await self._set_mode(manual)
        await self._set_charging(plan.charge_now(now), now)

    def _mode_is(self, option: str) -> bool:
        entity_id = self.conf(CONF_CHARGER_MODE)
        state = self.hass.states.get(entity_id) if entity_id else None
        return state is not None and state.state == option

    async def _set_mode(self, option: str) -> None:
        entity_id = self.conf(CONF_CHARGER_MODE)
        state = self.hass.states.get(entity_id) if entity_id else None
        if state is None or state.state == option:
            return
        _LOGGER.info("Laadplanner: laadmodus %s -> %s", state.state, option)
        await self.hass.services.async_call(
            "select", "select_option", {"entity_id": entity_id, "option": option},
            blocking=True,
        )

    def _power_shows_charging(self) -> bool:
        state = self._state(CONF_CHARGER_POWER)
        value = _float(state)
        if value is None or state is None:
            return False
        unit = str(state.attributes.get("unit_of_measurement", "W")).lower()
        return (value if unit == "kw" else value / 1000) >= 1.0

    def _car_says_charging(self) -> bool:
        state = self._state(CONF_CAR_STATUS)
        if state is None or state.state in _BAD:
            return False
        return str(state.state).lower() in CAR_CHARGING_STATES

    async def _set_charging(self, on: bool, now: datetime) -> None:
        """Switch the charger, robust against the slow Enphase cloud.

        The reported switch state can lag minutes behind. A start is not
        repeated while it may still be on its way; a stop is sent whenever
        anything suggests the car is charging (reported switch, charger
        power, car status or our own last command), and repeated a few
        times until that stops.
        """
        entity_id = self.conf(CONF_CHARGER_SWITCH)
        state = self.hass.states.get(entity_id) if entity_id else None
        if state is None or state.state in _BAD:
            return
        reported_on = state.state == STATE_ON
        since = ((now - self._commanded_at).total_seconds()
                 if self._commanded_at else None)

        if on:
            if reported_on or self._power_shows_charging():
                self._commanded = True
                self._off_sends = 0
                return
            if self._commanded is True and since is not None and since < START_CONFIRM_S:
                return  # started recently; the cloud just hasn't caught up
            if self._last_switch and (now - self._last_switch).total_seconds() < MIN_SWITCH_INTERVAL_S:
                return
            await self._send(entity_id, True, now)
            return

        busy = (reported_on or self._power_shows_charging()
                or self._car_says_charging() or self._commanded is True)
        if not busy:
            return
        if self._commanded is False:
            if self._off_sends >= STOP_MAX_RESENDS:
                return
            if since is not None and since < STOP_RESEND_S:
                return
        await self._send(entity_id, False, now)

    async def _send(self, entity_id: str, on: bool, now: datetime) -> None:
        attempt = 0 if on else (self._off_sends + 1 if self._commanded is False else 1)
        self._last_switch = now
        _LOGGER.info("Laadplanner: laadpaal %s%s", "aan" if on else "uit",
                     f" (poging {attempt})" if attempt > 1 else "")
        await self.hass.services.async_call(
            "switch", "turn_on" if on else "turn_off", {"entity_id": entity_id},
            blocking=True,
        )
        # Only remember the command once it was accepted.
        self._commanded = on
        self._commanded_at = now
        self._off_sends = attempt
