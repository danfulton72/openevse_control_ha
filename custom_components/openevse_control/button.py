"""OpenEVSE charge-control buttons."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, override

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.core import HomeAssistant

from .const import MODE_AUTO, MODE_DISABLE, MODE_ENABLE
from .coordinator import OpenEVSEConfigEntry, OpenEVSECoordinator
from .entity import OpenEVSEControlEntity

if TYPE_CHECKING:
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class OpenEVSEModeButtonDescription(ButtonEntityDescription):
    """Describe a charge-mode button."""

    mode: str


BUTTONS: tuple[OpenEVSEModeButtonDescription, ...] = (
    OpenEVSEModeButtonDescription(
        key="enable_charge", translation_key="enable_charge", mode=MODE_ENABLE
    ),
    OpenEVSEModeButtonDescription(
        key="auto_charge", translation_key="auto_charge", mode=MODE_AUTO
    ),
    OpenEVSEModeButtonDescription(
        key="disable_charge", translation_key="disable_charge", mode=MODE_DISABLE
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: OpenEVSEConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up charge-control buttons."""
    coordinator = entry.runtime_data
    async_add_entities(
        OpenEVSEModeButton(coordinator, description)
        for description in BUTTONS
        if description.mode in coordinator.data.available_modes
    )


class OpenEVSEModeButton(OpenEVSEControlEntity, ButtonEntity):
    """Represent a charge-control button."""

    entity_description: OpenEVSEModeButtonDescription

    def __init__(
        self,
        coordinator: OpenEVSECoordinator,
        description: OpenEVSEModeButtonDescription,
    ) -> None:
        """Initialize the button."""
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @override
    async def async_press(self) -> None:
        """Send the matching charge-mode command."""
        await self.coordinator.async_set_mode(self.entity_description.mode)
