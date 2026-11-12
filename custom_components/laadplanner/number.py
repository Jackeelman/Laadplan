"""Number entities: target SoC, tariffs and tuning."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.number import NumberEntity, NumberEntityDescription, NumberMode
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfPower, UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import LaadplannerConfigEntry
from .const import (
    SET_DYN_EXPORT,
    SET_DYN_IMPORT,
    SET_EFFICIENCY,
    SET_FALLBACK,
    SET_FIXED_EXPORT,
    SET_FIXED_IMPORT,
    SET_POWER,
    SET_SURPLUS,
    SET_TARGET,
)
from .entity import LaadplannerEntity

EUR_KWH = "EUR/kWh"


@dataclass(frozen=True, kw_only=True)
class SettingNumberDescription(NumberEntityDescription):
    setting: str
    scale: float = 1.0  # stored value = shown value / scale


NUMBERS = (
    SettingNumberDescription(key="doel_soc", setting=SET_TARGET, native_min_value=20,
                             native_max_value=100, native_step=5,
                             native_unit_of_measurement=PERCENTAGE, mode=NumberMode.SLIDER),
    SettingNumberDescription(key="vast_tarief_inkoop", setting=SET_FIXED_IMPORT,
                             native_min_value=0, native_max_value=1, native_step=0.0001,
                             native_unit_of_measurement=EUR_KWH, mode=NumberMode.BOX,
                             entity_category=EntityCategory.CONFIG),
    SettingNumberDescription(key="vast_tarief_teruglevering", setting=SET_FIXED_EXPORT,
                             native_min_value=-1, native_max_value=1, native_step=0.0001,
                             native_unit_of_measurement=EUR_KWH, mode=NumberMode.BOX,
                             entity_category=EntityCategory.CONFIG),
    SettingNumberDescription(key="dynamisch_opslag_inkoop", setting=SET_DYN_IMPORT,
                             native_min_value=-1, native_max_value=1, native_step=0.0001,
                             native_unit_of_measurement=EUR_KWH, mode=NumberMode.BOX,
                             entity_category=EntityCategory.CONFIG),
    SettingNumberDescription(key="dynamisch_opslag_teruglevering", setting=SET_DYN_EXPORT,
                             native_min_value=-1, native_max_value=1, native_step=0.0001,
                             native_unit_of_measurement=EUR_KWH, mode=NumberMode.BOX,
                             entity_category=EntityCategory.CONFIG),
    SettingNumberDescription(key="zon_overschot_factor", setting=SET_SURPLUS,
                             native_min_value=0, native_max_value=100, native_step=5,
                             native_unit_of_measurement=PERCENTAGE, scale=100,
                             mode=NumberMode.SLIDER, entity_category=EntityCategory.CONFIG),
    SettingNumberDescription(key="laadvermogen", setting=SET_POWER, native_min_value=1.4,
                             native_max_value=22, native_step=0.1,
                             native_unit_of_measurement=UnitOfPower.KILO_WATT,
                             mode=NumberMode.BOX, entity_category=EntityCategory.CONFIG),
    SettingNumberDescription(key="laadrendement", setting=SET_EFFICIENCY,
                             native_min_value=50, native_max_value=100, native_step=1,
                             native_unit_of_measurement=PERCENTAGE, scale=100,
                             mode=NumberMode.BOX, entity_category=EntityCategory.CONFIG),
    SettingNumberDescription(key="vaste_hoeveelheid", setting=SET_FALLBACK,
                             native_min_value=0, native_max_value=100, native_step=1,
                             native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
                             mode=NumberMode.BOX, entity_category=EntityCategory.CONFIG),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: LaadplannerConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(SettingNumber(coordinator, d) for d in NUMBERS)


class SettingNumber(LaadplannerEntity, NumberEntity):
    """A number bound to one setting."""

    _platform_domain = "number"

    entity_description: SettingNumberDescription

    def __init__(self, coordinator, description: SettingNumberDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> float | None:
        value = self.coordinator.settings.get(self.entity_description.setting)
        return None if value is None else float(value) * self.entity_description.scale

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_set(
            self.entity_description.setting, value / self.entity_description.scale
        )
