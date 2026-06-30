"""Button platform for the Unfolded Circle Dock."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import UnfoldedCircleDockEntity
from .api import DockError
from .coordinator import DockConfigEntry, UnfoldedCircleDockCoordinator


@dataclass(frozen=True, kw_only=True)
class DockButtonDescription(ButtonEntityDescription):
    """Describes a dock button and its action."""

    press_fn: Callable[[UnfoldedCircleDockCoordinator], Awaitable[None]]


BUTTONS: tuple[DockButtonDescription, ...] = (
    DockButtonDescription(
        key="identify",
        translation_key="identify",
        press_fn=lambda c: c.api.identify(),
    ),
    DockButtonDescription(
        key="stop_ir",
        translation_key="stop_ir",
        press_fn=lambda c: c.api.ir_stop(),
    ),
    DockButtonDescription(
        key="refresh",
        translation_key="refresh",
        entity_category=EntityCategory.DIAGNOSTIC,
        press_fn=lambda c: c.async_request_refresh(),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DockConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up dock buttons."""
    coordinator = entry.runtime_data
    async_add_entities(DockButton(coordinator, description) for description in BUTTONS)


class DockButton(UnfoldedCircleDockEntity, ButtonEntity):
    """A pressable dock action."""

    entity_description: DockButtonDescription

    def __init__(
        self,
        coordinator: UnfoldedCircleDockCoordinator,
        description: DockButtonDescription,
    ) -> None:
        """Initialise the button."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{self._serial}_{description.key}"

    async def async_press(self) -> None:
        """Run the button's action."""
        try:
            await self.entity_description.press_fn(self.coordinator)
        except DockError as err:
            raise HomeAssistantError(f"Dock command failed: {err}") from err
