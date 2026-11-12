"""Sensor entities: plan, remaining demand and cost simulation."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import LaadplannerConfigEntry
from .entity import LaadplannerEntity
from .planner import (
    MODE_DIRECT,
    MODE_IDLE,
    MODE_PREVIEW,
    MODE_QUARTERS,
    MODE_SOLAR,
    MODE_SOLAR_TOPUP,
)


def _sim(key: str) -> Callable[[dict[str, Any]], Any]:
    def get(data: dict[str, Any]) -> Any:
        value = data["sim"].get(key)
        return None if value is None else round(value, 2)
    return get


def _diff(data: dict[str, Any]) -> Any:
    sim = data["sim"]
    if sim.get("fixed_month") is None or sim.get("dyn_month") is None:
        return None
    return round(sim["fixed_month"] - sim["dyn_month"], 2)


@dataclass(frozen=True, kw_only=True)
class PlannerSensorDescription(SensorEntityDescription):
    value: Callable[[dict[str, Any]], Any]


SENSORS = (
    PlannerSensorDescription(
        key="resterende_vraag",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        suggested_display_precision=1,
        value=lambda d: round(d["plan"].needed_kwh, 1),
    ),
    PlannerSensorDescription(
        key="plan",
        device_class=SensorDeviceClass.ENUM,
        options=[MODE_IDLE, MODE_PREVIEW, MODE_SOLAR, MODE_SOLAR_TOPUP, MODE_QUARTERS, MODE_DIRECT],
        value=lambda d: d["plan"].mode,
    ),
    PlannerSensorDescription(
        key="volgende_start",
        device_class=SensorDeviceClass.TIMESTAMP,
        value=lambda d: d["next_start"],
    ),
    PlannerSensorDescription(key="kosten_vast_vandaag", native_unit_of_measurement="EUR",
                             device_class=SensorDeviceClass.MONETARY,
                             suggested_display_precision=2, value=_sim("fixed_day")),
    PlannerSensorDescription(key="kosten_dynamisch_vandaag", native_unit_of_measurement="EUR",
                             device_class=SensorDeviceClass.MONETARY,
                             suggested_display_precision=2, value=_sim("dyn_day")),
    PlannerSensorDescription(key="kosten_vast_maand", native_unit_of_measurement="EUR",
                             device_class=SensorDeviceClass.MONETARY,
                             suggested_display_precision=2, value=_sim("fixed_month")),
    PlannerSensorDescription(key="kosten_dynamisch_maand", native_unit_of_measurement="EUR",
                             device_class=SensorDeviceClass.MONETARY,
                             suggested_display_precision=2, value=_sim("dyn_month")),
    PlannerSensorDescription(key="verschil_dynamisch_maand", native_unit_of_measurement="EUR",
                             device_class=SensorDeviceClass.MONETARY,
                             suggested_display_precision=2, value=_diff),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: LaadplannerConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(PlannerSensor(coordinator, d) for d in SENSORS)


class PlannerSensor(LaadplannerEntity, SensorEntity):
    """Sensor reading from the coordinator's data."""

    _platform_domain = "sensor"

    # Keep the recorder database small: these attributes are only for the
    # dashboard and are never written to the history.
    _unrecorded_attributes = frozenset(
        {
            "reden",
            "haalbaar",
            "benodigd_kwh",
            "kwartieren_nodig",
            "kwartieren",
            "nu_laden",
            "verwacht_overschot_kwh",
            "zon_voor_deadline_kwh",
            "deadline",
            "laadvermogen_kw",
            "bekende_prijzen",
            "sturing_actief",
            "kwh_zonder_prijs",
        }
    )

    entity_description: PlannerSensorDescription

    def __init__(self, coordinator, description: PlannerSensorDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        if not self.coordinator.data:
            return None
        return self.entity_description.value(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        data = self.coordinator.data
        if not data:
            return None
        key = self.entity_description.key
        if key == "plan":
            plan = data["plan"]
            return {
                "reden": plan.reason,
                "haalbaar": plan.feasible,
                "benodigd_kwh": round(plan.needed_kwh, 1),
                "kwartieren_nodig": plan.quarters_needed,
                "kwartieren": [s.isoformat() for s in plan.slots],
                "nu_laden": data["charge_now"],
                # 0.1 precision: finer values change every minute by day and
                # would write a new state row to the database each time.
                "verwacht_overschot_kwh": round(plan.expected_surplus_kwh, 1),
                "zon_voor_deadline_kwh": round(data["solar_before_deadline"], 1),
                "deadline": data["deadline"].isoformat(),
                "laadvermogen_kw": round(data["power_kw"], 1),
                "bekende_prijzen": data["prices_known"],
                "sturing_actief": bool(self.coordinator.settings.get("active")),
            }
        if key == "kosten_dynamisch_vandaag":
            return {"kwh_zonder_prijs": round(data["sim"].get("dyn_missing_day", 0.0), 3)}
        return None
