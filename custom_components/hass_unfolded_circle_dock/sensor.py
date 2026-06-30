"""Sensor platform for the Unfolded Circle Dock."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfInformation
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import UnfoldedCircleDockEntity
from .const import DOMAIN
from .coordinator import DockConfigEntry, UnfoldedCircleDockCoordinator


@dataclass(frozen=True, kw_only=True)
class DockSensorDescription(SensorEntityDescription):
    """Describes a dock sensor backed by a sysinfo key."""

    value_fn: Callable[[dict[str, Any]], Any]


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


SENSORS: tuple[DockSensorDescription, ...] = (
    DockSensorDescription(
        key="name",
        translation_key="name",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.get("name"),
    ),
    DockSensorDescription(
        key="hostname",
        translation_key="hostname",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.get("hostname"),
    ),
    DockSensorDescription(
        key="version",
        translation_key="version",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.get("version"),
    ),
    DockSensorDescription(
        key="serial",
        translation_key="serial",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.get("serial"),
    ),
    DockSensorDescription(
        key="model",
        translation_key="model",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.get("model"),
    ),
    DockSensorDescription(
        key="revision",
        translation_key="revision",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.get("revision"),
    ),
    DockSensorDescription(
        key="uptime",
        translation_key="uptime",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.get("uptime"),
    ),
    DockSensorDescription(
        key="ssid",
        translation_key="ssid",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.get("ssid") or None,
    ),
    DockSensorDescription(
        key="volume",
        translation_key="volume",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: _as_int(d.get("volume")),
    ),
    DockSensorDescription(
        key="free_heap",
        translation_key="free_heap",
        native_unit_of_measurement=UnitOfInformation.BYTES,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda d: _as_int(d.get("free_heap")),
    ),
    DockSensorDescription(
        key="led_brightness",
        translation_key="led_brightness",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda d: _as_int(d.get("led_brightness")),
    ),
    DockSensorDescription(
        key="reset_reason",
        translation_key="reset_reason",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda d: d.get("reset_reason"),
    ),
)

# Created only when the dock actually reports the value (model/hardware
# dependent), to avoid permanently-unknown entities.
OPTIONAL_SENSORS: tuple[DockSensorDescription, ...] = (
    DockSensorDescription(
        key="eth_led_brightness",
        translation_key="eth_led_brightness",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda d: _as_int(d.get("eth_led_brightness")),
    ),
    DockSensorDescription(
        key="poe_mode",
        translation_key="poe_mode",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.get("poe_mode"),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DockConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up dock sensors."""
    coordinator = entry.runtime_data

    entities: list[SensorEntity] = [
        DockSensor(coordinator, description) for description in SENSORS
    ]

    # Optional sensors only when the dock reports them.
    data = coordinator.data or {}
    entities.extend(
        DockSensor(coordinator, description)
        for description in OPTIONAL_SENSORS
        if description.key in data
    )

    # One mode sensor per external port reported in sysinfo.
    for port_info in (coordinator.data or {}).get("ports", []):
        port = port_info.get("port")
        if port is not None:
            entities.append(DockPortModeSensor(coordinator, int(port)))

    async_add_entities(entities)


class DockSensor(UnfoldedCircleDockEntity, SensorEntity):
    """A simple value sensor from the dock sysinfo."""

    entity_description: DockSensorDescription

    def __init__(
        self,
        coordinator: UnfoldedCircleDockCoordinator,
        description: DockSensorDescription,
    ) -> None:
        """Initialise the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{self._serial}_{description.key}"

    @property
    def native_value(self) -> Any:
        """Return the current value."""
        return self.entity_description.value_fn(self.coordinator.data or {})


class DockPortModeSensor(UnfoldedCircleDockEntity, SensorEntity):
    """Reports the active mode of one external port."""

    _attr_translation_key = "port_mode"

    def __init__(self, coordinator: UnfoldedCircleDockCoordinator, port: int) -> None:
        """Initialise for a specific port number."""
        super().__init__(coordinator)
        self._port = port
        self._attr_translation_placeholders = {"port": str(port)}
        self._attr_unique_id = f"{self._serial}_port_{port}_mode"

    def _port_info(self) -> dict[str, Any]:
        for port_info in (self.coordinator.data or {}).get("ports", []):
            if port_info.get("port") == self._port:
                return port_info
        return {}

    @property
    def native_value(self) -> str | None:
        """Return the active mode (or configured mode) of the port."""
        info = self._port_info()
        return info.get("active_mode") or info.get("mode")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose supported modes and UART config as attributes."""
        info = self._port_info()
        attrs: dict[str, Any] = {"port": self._port}
        if "mode" in info:
            attrs["configured_mode"] = info["mode"]
        if "supported_modes" in info:
            attrs["supported_modes"] = info["supported_modes"]
        if "uart" in info:
            attrs["uart"] = info["uart"]
        return attrs
