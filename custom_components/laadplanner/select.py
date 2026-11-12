"""Select entities: strategy and contract."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import LaadplannerConfigEntry
from .const import SET_CONTRACT, SET_STRATEGY
from .entity import LaadplannerEntity
from .planner import CONTRACTS, STRATEGIES


async def async_setup_entry(
    hass: HomeAssistant, entry: LaadplannerConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        [
            SettingSelect(coordinator, "strategie", SET_STRATEGY, STRATEGIES),
            SettingSelect(coordinator, "contract", SET_CONTRACT, CONTRACTS),
        ]
    )


class SettingSelect(LaadplannerEntity, SelectEntity):
    """A select bound to one setting."""

    _platform_domain = "select"

    def __init__(self, coordinator, key: str, setting: str, options: list[str]) -> None:
        super().__init__(coordinator, key)
        self._setting = setting
        self._attr_options = options

    @property
    def current_option(self) -> str | None:
        return self.coordinator.settings.get(self._setting)

    async def async_select_option(self, option: str) -> None:
        await self.coordinator.async_set(self._setting, option)
