"""DataUpdateCoordinator for the Unfolded Circle Dock integration."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    DockAuthError,
    DockConnectionError,
    DockError,
    UnfoldedCircleDockApi,
)
from .const import (
    CONF_HOST,
    CONF_PORT,
    CONF_TOKEN,
    CONF_USE_TLS,
    CONF_WS_PATH,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_WS_PATH,
    DOMAIN,
    EVENT_IR_LEARN,
    EVENT_LOG,
    EVENT_PORT_MODE,
    EVENT_SERIAL_DATA,
    MSG_MSG,
    PORT_MODE_TRIGGER_5V,
    SIGNAL_DOCK_EVENT,
    SIGNAL_SERIAL_DATA,
    TYPE_EVENT,
)

_LOGGER = logging.getLogger(__name__)

type DockConfigEntry = ConfigEntry[UnfoldedCircleDockCoordinator]


class UnfoldedCircleDockCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinate polling and event handling for one dock."""

    config_entry: DockConfigEntry

    def __init__(self, hass: HomeAssistant, entry: DockConfigEntry) -> None:
        """Initialise the coordinator and underlying API client."""
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{entry.data[CONF_HOST]}",
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
            config_entry=entry,
        )

        self.api = UnfoldedCircleDockApi(
            host=entry.data[CONF_HOST],
            token=entry.data[CONF_TOKEN],
            port=entry.data.get(CONF_PORT, DEFAULT_PORT),
            ws_path=entry.data.get(CONF_WS_PATH, DEFAULT_WS_PATH),
            use_tls=entry.data.get(CONF_USE_TLS, False),
            session=async_get_clientsession(hass),
        )
        self.api.add_event_callback(self._handle_dock_event)
        self.api.set_on_connect(self._on_reconnect)

        self.serial_state: dict[int, str] = {}

    @property
    def serial(self) -> str:
        """Return the dock serial (used for unique IDs)."""
        return str(self.api.device_info.get("serial", self.config_entry.entry_id))

    async def async_setup(self) -> None:
        """Validate connectivity, then start the self-healing connection."""
        try:
            await self.api.async_connect()
        except DockAuthError as err:
            await self.api.async_disconnect()
            # Authentication problems are not transient.
            raise UpdateFailed(f"Authentication failed: {err}") from err
        except DockConnectionError as err:
            await self.api.async_disconnect()
            raise UpdateFailed(f"Cannot connect to dock: {err}") from err

        # Adopt the now-open connection in the supervised reconnect loop.
        await self.api.async_start()

    async def _async_update_data(self) -> dict[str, Any]:
        """Poll the dock for sysinfo and a couple of extra states."""
        try:
            data = await self.api.get_sysinfo()
        except DockError as err:
            raise UpdateFailed(f"Error polling dock: {err}") from err

        # serial_tcp is not part of sysinfo; fetch it best-effort.
        try:
            data["serial_tcp"] = await self.api.get_serial_tcp()
        except DockError:
            data.setdefault("serial_tcp", None)

        # Poll the 5V trigger state for any port currently in TRIGGER_5V mode.
        triggers: dict[int, bool] = {}
        for port_info in data.get("ports", []):
            port = port_info.get("port")
            mode = port_info.get("active_mode") or port_info.get("mode")
            if port is None or mode != PORT_MODE_TRIGGER_5V:
                continue
            try:
                result = await self.api.get_port_trigger(int(port))
                triggers[int(port)] = bool(result.get("trigger"))
            except DockError:
                continue
        data["port_triggers"] = triggers

        return data

    async def _on_reconnect(self) -> None:
        """Refresh data after the socket reconnects."""
        await self.async_request_refresh()

    @callback
    def _handle_dock_event(self, message: dict[str, Any]) -> None:
        """Route an unsolicited dock event to the HA bus and dispatcher."""
        if message.get("type") != TYPE_EVENT:
            return

        kind = message.get(MSG_MSG)
        base = {"entry_id": self.config_entry.entry_id, "serial": self.serial}

        if kind == "serial_data":
            port = message.get("port")
            data = message.get("data")
            if port is not None:
                self.serial_state[int(port)] = data or ""
            self.hass.bus.async_fire(EVENT_SERIAL_DATA, {**base, "port": port, "data": data})
            async_dispatcher_send(
                self.hass, f"{SIGNAL_SERIAL_DATA}_{self.config_entry.entry_id}", port, data
            )
        elif kind == "log":
            self.hass.bus.async_fire(
                EVENT_LOG,
                {
                    **base,
                    "level": message.get("level"),
                    "tag": message.get("tag"),
                    "log": message.get("log"),
                    "ts": message.get("ts"),
                },
            )
        elif kind in ("ir_receive_on", "ir_receive_off"):
            self.hass.bus.async_fire(
                EVENT_IR_LEARN,
                {**base, "active": kind == "ir_receive_on", "raw": message.get("raw", False)},
            )
            # Reflect learning state quickly without waiting for the next poll.
            if isinstance(self.data, dict):
                self.data["ir_learning"] = kind == "ir_receive_on"
                self.async_update_listeners()
        elif kind == "port_mode":
            self.hass.bus.async_fire(EVENT_PORT_MODE, {**base, **message})
            self.hass.async_create_task(self.async_request_refresh())

        async_dispatcher_send(
            self.hass, f"{SIGNAL_DOCK_EVENT}_{self.config_entry.entry_id}", message
        )

    async def async_shutdown(self) -> None:
        """Disconnect cleanly on unload."""
        await super().async_shutdown()
        await self.api.async_disconnect()
