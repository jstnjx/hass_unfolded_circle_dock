"""The Unfolded Circle Dock integration."""

from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_HOST, DOMAIN, MANUFACTURER, PLATFORMS
from .coordinator import DockConfigEntry, UnfoldedCircleDockCoordinator
from .services import async_setup_services

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: DockConfigEntry) -> bool:
    """Set up Unfolded Circle Dock from a config entry."""
    coordinator = UnfoldedCircleDockCoordinator(hass, entry)

    # Open the connection (raises ConfigEntryNotReady via UpdateFailed mapping).
    from homeassistant.exceptions import ConfigEntryNotReady

    try:
        await coordinator.async_setup()
    except Exception as err:  # noqa: BLE001
        raise ConfigEntryNotReady(str(err)) from err

    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register integration services once.
    async_setup_services(hass)

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: DockConfigEntry) -> bool:
    """Unload a config entry and clean up the connection."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator = entry.runtime_data
        await coordinator.async_shutdown()
    return unload_ok


async def _async_update_listener(hass: HomeAssistant, entry: DockConfigEntry) -> None:
    """Reload the entry when its options change."""
    await hass.config_entries.async_reload(entry.entry_id)


class UnfoldedCircleDockEntity(CoordinatorEntity[UnfoldedCircleDockCoordinator]):
    """Base entity tying every entity to the dock device."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: UnfoldedCircleDockCoordinator) -> None:
        """Initialise with the shared coordinator."""
        super().__init__(coordinator)
        self._entry = coordinator.config_entry

    @property
    def _serial(self) -> str:
        return self.coordinator.serial

    @property
    def device_info(self) -> DeviceInfo:
        """Return device registry info keyed on the dock serial."""
        data = self.coordinator.data or {}
        info = self.coordinator.api.device_info
        return DeviceInfo(
            identifiers={(DOMAIN, self._serial)},
            manufacturer=MANUFACTURER,
            name=data.get("name") or info.get("name") or self._entry.data.get(CONF_HOST),
            model=data.get("model") or info.get("model"),
            sw_version=data.get("version") or info.get("version"),
            hw_version=data.get("revision") or info.get("revision"),
            serial_number=self._serial,
            configuration_url=f"http://{self._entry.data.get(CONF_HOST)}",
        )

    @property
    def available(self) -> bool:
        """Available only while polling succeeds and the socket is up."""
        return super().available and self.coordinator.api.connected
