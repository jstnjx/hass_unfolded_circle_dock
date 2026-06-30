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
from .const import PORT_MODE_TRIGGER_5V
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
    entities: list[SwitchEntity] = [
        DockSwitch(coordinator, description) for description in SWITCHES
    ]

    # One 5V-trigger switch per external port that supports TRIGGER_5V.
    for port_info in (coordinator.data or {}).get("ports", []):
        port = port_info.get("port")
        supported = port_info.get("supported_modes") or []
        active = port_info.get("active_mode") or port_info.get("mode")
        if port is None:
            continue
        if PORT_MODE_TRIGGER_5V in supported or active == PORT_MODE_TRIGGER_5V:
            entities.append(DockPortTriggerSwitch(coordinator, int(port)))

    async_add_entities(entities)


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


class DockPortTriggerSwitch(UnfoldedCircleDockEntity, SwitchEntity):
    """Controls the 5V trigger output of an external port."""

    _attr_translation_key = "port_trigger"

    def __init__(self, coordinator: UnfoldedCircleDockCoordinator, port: int) -> None:
        """Initialise for a specific port number."""
        super().__init__(coordinator)
        self._port = port
        self._attr_translation_placeholders = {"port": str(port)}
        self._attr_unique_id = f"{self._serial}_port_{port}_trigger"

    def _port_info(self) -> dict[str, Any]:
        for port_info in (self.coordinator.data or {}).get("ports", []):
            if port_info.get("port") == self._port:
                return port_info
        return {}

    @property
    def available(self) -> bool:
        """Available only while the port is actively in TRIGGER_5V mode."""
        info = self._port_info()
        active = info.get("active_mode") or info.get("mode")
        return super().available and active == PORT_MODE_TRIGGER_5V

    @property
    def is_on(self) -> bool | None:
        """Return the polled trigger state for this port."""
        triggers = (self.coordinator.data or {}).get("port_triggers", {})
        return triggers.get(self._port)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Assert the 5V trigger."""
        try:
            await self.coordinator.api.set_port_trigger(self._port, True)
        except DockError as err:
            raise HomeAssistantError(f"Dock command failed: {err}") from err
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Release the 5V trigger."""
        try:
            await self.coordinator.api.set_port_trigger(self._port, False)
        except DockError as err:
            raise HomeAssistantError(f"Dock command failed: {err}") from err
        await self.coordinator.async_request_refresh()
