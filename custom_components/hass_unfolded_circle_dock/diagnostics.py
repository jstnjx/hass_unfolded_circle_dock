"""Diagnostics support for the Unfolded Circle Dock."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .const import CONF_TOKEN
from .coordinator import DockConfigEntry

TO_REDACT = {CONF_TOKEN, "token", "ssid", "serial"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: DockConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data
    return {
        "entry": {
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "unique_id": entry.unique_id,
        },
        "connected": coordinator.api.connected,
        "url": coordinator.api.url,
        "device_info": async_redact_data(dict(coordinator.api.device_info), TO_REDACT),
        "data": async_redact_data(dict(coordinator.data or {}), TO_REDACT),
    }
