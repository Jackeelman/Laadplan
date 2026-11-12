"""Laadplanner: plans EV charging around Omnibattery and simulates tariffs."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .coordinator import LaadplannerCoordinator

PLATFORMS = [Platform.SELECT, Platform.NUMBER, Platform.TIME, Platform.SWITCH, Platform.SENSOR]

type LaadplannerConfigEntry = ConfigEntry[LaadplannerCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: LaadplannerConfigEntry) -> bool:
    """Set up Laadplanner from a config entry."""
    coordinator = LaadplannerCoordinator(hass, entry)
    await coordinator.async_load()
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: LaadplannerConfigEntry) -> bool:
    """Unload a config entry."""
    await entry.runtime_data.async_save()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_reload(hass: HomeAssistant, entry: LaadplannerConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
