"""Base entity for OpenEVSE Control."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import OpenEVSECoordinator


class OpenEVSEControlEntity(CoordinatorEntity[OpenEVSECoordinator]):
    """Common device info and unique IDs."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: OpenEVSECoordinator, key: str) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        entry = coordinator.config_entry
        device_id = entry.unique_id or entry.entry_id
        config = coordinator.data.config
        status = coordinator.data.status
        self._attr_unique_id = f"{device_id}_{key}"

        device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            name=entry.title,
            manufacturer="OpenEVSE",
            model=str(config.get("buildenv") or "OpenEVSE WiFi"),
            configuration_url=coordinator.client.url,
        )
        wifi_version = config.get("version")
        evse_version = config.get("firmware")
        if wifi_version and evse_version:
            device_info["sw_version"] = f"WiFi {wifi_version}; EVSE {evse_version}"
        elif wifi_version or evse_version:
            device_info["sw_version"] = str(wifi_version or evse_version)
        if mac := status.get("macaddress"):
            device_info["serial_number"] = str(mac)
        self._attr_device_info = device_info
