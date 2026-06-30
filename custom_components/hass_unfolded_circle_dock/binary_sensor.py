"""Binary sensor platform for the Unfolded Circle Dock."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import UnfoldedCircleDockEntity
from .coordinator import DockConfigEntry, UnfoldedCircleDockCoordinator


@dataclass(frozen=True, kw_only=True)
class DockBinaryDescription(BinarySensorEntityDescription):
    """Describes a dock binary sensor backed by a sysinfo key."""

    value_fn: Callable[[dict[str, Any]], bool | None]


BINARY_SENSORS: tuple[DockBinaryDescription, ...] = (
    DockBinaryDescription(
        key="ethernet",
        translation_key="ethernet",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.get("ethernet"),
    ),
    DockBinaryDescription(
        key="wifi",
        translation_key="wifi",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.get("wifi"),
    ),
    DockBinaryDescription(
        key="ir_learning",
        translation_key="ir_learning",
        device_class=BinarySensorDeviceClass.RUNNING,
        value_fn=lambda d: d.get("ir_learning"),
    ),
    DockBinaryDescription(
        key="ntp",
        translation_key="ntp",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        # Dock 3 reports `ntp`; Dock Two firmware reports `sntp`.
        value_fn=lambda d: d.get("ntp") if "ntp" in d else d.get("sntp"),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DockConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up dock binary sensors."""
    coordinator = entry.runtime_data
    async_add_entities(
        DockBinarySensor(coordinator, description) for description in BINARY_SENSORS
    )


class DockBinarySensor(UnfoldedCircleDockEntity, BinarySensorEntity):
    """A boolean status sensor from the dock sysinfo."""

    entity_description: DockBinaryDescription

    def __init__(
        self,
        coordinator: UnfoldedCircleDockCoordinator,
        description: DockBinaryDescription,
    ) -> None:
        """Initialise the binary sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{self._serial}_{description.key}"

    @property
    def is_on(self) -> bool | None:
        """Return the boolean state."""
        return self.entity_description.value_fn(self.coordinator.data or {})
