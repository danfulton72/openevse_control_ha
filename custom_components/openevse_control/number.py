"""OpenEVSE charge-current number entity."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, override

from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberMode
from homeassistant.const import EntityCategory, UnitOfElectricCurrent
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
    """Set up the charge-current number."""
    async_add_entities([OpenEVSEChargeRateNumber(entry.runtime_data)])


class OpenEVSEChargeRateNumber(OpenEVSEControlEntity, NumberEntity):
    """Configure the EVSE current capacity."""

    _attr_translation_key = "charge_rate"
    _attr_device_class = NumberDeviceClass.CURRENT
    _attr_native_unit_of_measurement = UnitOfElectricCurrent.AMPERE
    _attr_native_step = 1
    _attr_mode = NumberMode.SLIDER
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: OpenEVSECoordinator) -> None:
        """Initialize the number."""
        super().__init__(coordinator, "charge_rate")

    @property
    @override
    def native_min_value(self) -> float:
        """Return minimum current supported by the charger."""
        return self.coordinator.data.min_charge_rate

    @property
    @override
    def native_max_value(self) -> float:
        """Return maximum current supported/configured by the charger."""
        return self.coordinator.data.max_charge_rate

    @property
    @override
    def native_value(self) -> float | None:
        """Return current capacity set point."""
        return self.coordinator.data.charge_rate

    @property
    @override
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose modern claim ownership when available."""
        owner = self.coordinator.data.charge_rate_controlled_by
        return {"controlled_by": owner} if owner is not None else {}

    @override
    async def async_set_native_value(self, value: float) -> None:
        """Set the charge-current limit."""
        await self.coordinator.async_set_charge_rate(round(value))
