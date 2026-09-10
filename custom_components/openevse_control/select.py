"""OpenEVSE charge-mode select."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, override

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant

from .coordinator import OpenEVSEConfigEntry, OpenEVSECoordinator
from .entity import OpenEVSEControlEntity

if TYPE_CHECKING:
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: OpenEVSEConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the charge-mode select."""
    async_add_entities([OpenEVSEChargeModeSelect(entry.runtime_data)])


class OpenEVSEChargeModeSelect(OpenEVSEControlEntity, SelectEntity):
    """Select a charge-control mode supported by the connected firmware."""

    _attr_translation_key = "charge_mode"

    def __init__(self, coordinator: OpenEVSECoordinator) -> None:
        """Initialize the select."""
        super().__init__(coordinator, "charge_mode")

    @property
    @override
    def options(self) -> list[str]:
        """Return firmware-supported options."""
        return self.coordinator.data.available_modes

    @property
    @override
    def current_option(self) -> str | None:
        """Return the active mode."""
        return self.coordinator.data.mode

    @property
    @override
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose modern claim ownership when available."""
        owner = self.coordinator.data.state_controlled_by
        return {"controlled_by": owner} if owner is not None else {}

    @override
    async def async_select_option(self, option: str) -> None:
        """Set the selected mode."""
        await self.coordinator.async_set_mode(option)
