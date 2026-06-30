"""Number platform for the Unfolded Circle Dock.

Exposes settable values (speaker volume, LED brightness) as number entities so
they can be adjusted directly from the dashboard, in addition to the matching
services. Entities are only created when the dock actually reports the value.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.number import (
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.const import PERCENTAGE, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import UnfoldedCircleDockEntity
from .api import DockError
from .const import BRIGHTNESS_MAX, BRIGHTNESS_MIN
from .coordinator import DockConfigEntry, UnfoldedCircleDockCoordinator


@dataclass(frozen=True, kw_only=True)
class DockNumberDescription(NumberEntityDescription):
    """Describes a settable dock number."""

    source_key: str
    value_fn: Callable[[dict[str, Any]], float | None]
    set_fn: Callable[[UnfoldedCircleDockCoordinator, int], Awaitable[None]]


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


NUMBERS: tuple[DockNumberDescription, ...] = (
    DockNumberDescription(
        key="volume",
        translation_key="volume",
        source_key="volume",
        native_min_value=0,
        native_max_value=100,
        native_step=1,
        native_unit_of_measurement=PERCENTAGE,
        mode=NumberMode.SLIDER,
        value_fn=lambda d: _as_int(d.get("volume")),
        set_fn=lambda c, v: c.api.set_volume(v),
    ),
    DockNumberDescription(
        key="status_led_brightness",
        translation_key="status_led_brightness",
        source_key="led_brightness",
        native_min_value=BRIGHTNESS_MIN,
        native_max_value=BRIGHTNESS_MAX,
        native_step=1,
        mode=NumberMode.SLIDER,
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda d: _as_int(d.get("led_brightness")),
        set_fn=lambda c, v: c.api.set_brightness(status_led=v),
    ),
    DockNumberDescription(
        key="eth_led_brightness",
        translation_key="eth_led_brightness",
        source_key="eth_led_brightness",
        native_min_value=BRIGHTNESS_MIN,
        native_max_value=BRIGHTNESS_MAX,
        native_step=1,
        mode=NumberMode.SLIDER,
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda d: _as_int(d.get("eth_led_brightness")),
        set_fn=lambda c, v: c.api.set_brightness(eth_led=v),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DockConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up dock number entities for values the dock reports."""
    coordinator = entry.runtime_data
    data = coordinator.data or {}
    async_add_entities(
        DockNumber(coordinator, description)
        for description in NUMBERS
        if description.source_key in data
    )


class DockNumber(UnfoldedCircleDockEntity, NumberEntity):
    """A settable numeric dock value."""

    entity_description: DockNumberDescription

    def __init__(
        self,
        coordinator: UnfoldedCircleDockCoordinator,
        description: DockNumberDescription,
    ) -> None:
        """Initialise the number entity."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{self._serial}_{description.key}"

    @property
    def native_value(self) -> float | None:
        """Return the current value from coordinator data."""
        return self.entity_description.value_fn(self.coordinator.data or {})

    async def async_set_native_value(self, value: float) -> None:
        """Send the new value to the dock."""
        try:
            await self.entity_description.set_fn(self.coordinator, int(value))
        except DockError as err:
            raise HomeAssistantError(f"Dock command failed: {err}") from err
        await self.coordinator.async_request_refresh()
