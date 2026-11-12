"""Switch entity: allow the planner to steer the charger."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import LaadplannerConfigEntry
from .const import SET_ACTIVE
from .entity import LaadplannerEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: LaadplannerConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([ActiveSwitch(entry.runtime_data, "sturing_actief")])


class ActiveSwitch(LaadplannerEntity, SwitchEntity):
    """Off = shadow mode: plan and simulate only, never touch the charger."""

    _platform_domain = "switch"

    _attr_icon = "mdi:ev-station"

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.settings.get(SET_ACTIVE))

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_set(SET_ACTIVE, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_set(SET_ACTIVE, False)
