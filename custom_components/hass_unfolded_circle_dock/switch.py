"""Switch platform for the Unfolded Circle Dock."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import (
    SwitchEntity,
    SwitchEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import UnfoldedCircleDockEntity
from .api import DockError
from .coordinator import DockConfigEntry, UnfoldedCircleDockCoordinator


@dataclass(frozen=True, kw_only=True)
class DockSwitchDescription(SwitchEntityDescription):
    """Describes a dock switch."""

    value_fn: Callable[[dict[str, Any]], bool | None]
    turn_on_fn: Callable[[UnfoldedCircleDockCoordinator], Awaitable[None]]
    turn_off_fn: Callable[[UnfoldedCircleDockCoordinator], Awaitable[None]]


SWITCHES: tuple[DockSwitchDescription, ...] = (
    DockSwitchDescription(
        key="serial_tcp",
        translation_key="serial_tcp",
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda d: d.get("serial_tcp"),
        turn_on_fn=lambda c: c.api.set_serial_tcp(True),
        turn_off_fn=lambda c: c.api.set_serial_tcp(False),
    ),
    DockSwitchDescription(
        key="ir_learning",
        translation_key="ir_learning_switch",
        value_fn=lambda d: d.get("ir_learning"),
        turn_on_fn=lambda c: c.api.ir_receive_on(),
        turn_off_fn=lambda c: c.api.ir_receive_off(),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DockConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up dock switches."""
    coordinator = entry.runtime_data
    async_add_entities(DockSwitch(coordinator, description) for description in SWITCHES)


class DockSwitch(UnfoldedCircleDockEntity, SwitchEntity):
    """A toggleable dock setting."""

    entity_description: DockSwitchDescription

    def __init__(
        self,
        coordinator: UnfoldedCircleDockCoordinator,
        description: DockSwitchDescription,
    ) -> None:
        """Initialise the switch."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{self._serial}_{description.key}"

    @property
    def is_on(self) -> bool | None:
        """Return the switch state from coordinator data."""
        return self.entity_description.value_fn(self.coordinator.data or {})

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the setting on."""
        try:
            await self.entity_description.turn_on_fn(self.coordinator)
        except DockError as err:
            raise HomeAssistantError(f"Dock command failed: {err}") from err
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the setting off."""
        try:
            await self.entity_description.turn_off_fn(self.coordinator)
        except DockError as err:
            raise HomeAssistantError(f"Dock command failed: {err}") from err
        await self.coordinator.async_request_refresh()
