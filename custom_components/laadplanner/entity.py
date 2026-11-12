"""Base entity for Laadplanner."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import LaadplannerCoordinator


class LaadplannerEntity(CoordinatorEntity[LaadplannerCoordinator]):
    """Shared device and naming."""

    _attr_has_entity_name = True

    _platform_domain: str = ""

    def __init__(self, coordinator: LaadplannerCoordinator, key: str) -> None:
        super().__init__(coordinator)
        # Fixed entity ids, independent of the UI language
        self.entity_id = f"{self._platform_domain}.{DOMAIN}_{key}"
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.entry.entry_id)},
            name="Laadplanner",
            manufacturer="Eigen bouw",
            model="EV-module",
            entry_type=DeviceEntryType.SERVICE,
        )
