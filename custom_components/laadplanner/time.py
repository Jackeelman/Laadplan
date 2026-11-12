"""Time entity: deadline."""

from __future__ import annotations

from datetime import time

from homeassistant.components.time import TimeEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import LaadplannerConfigEntry
from .const import SET_DEADLINE, SET_NIGHT_START
from .entity import LaadplannerEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: LaadplannerConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities(
        [
            DeadlineTime(entry.runtime_data, "deadline"),
            NightStartTime(entry.runtime_data, "laden_vanaf"),
        ]
    )


class DeadlineTime(LaadplannerEntity, TimeEntity):
    """When the car must be ready."""

    _platform_domain = "time"

    @property
    def native_value(self) -> time | None:
        return self.coordinator._deadline_time()  # noqa: SLF001

    async def async_set_value(self, value: time) -> None:
        await self.coordinator.async_set(SET_DEADLINE, value.strftime("%H:%M"))


class NightStartTime(LaadplannerEntity, TimeEntity):
    """From when charging may start on a fixed contract (everyone asleep)."""

    _platform_domain = "time"

    @property
    def native_value(self) -> time | None:
        return self.coordinator._night_start_time()  # noqa: SLF001

    async def async_set_value(self, value: time) -> None:
        await self.coordinator.async_set(SET_NIGHT_START, value.strftime("%H:%M"))
