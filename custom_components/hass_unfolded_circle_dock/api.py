"""Async WebSocket client for the Unfolded Circle Dock JSON API.

This module is deliberately free of any Home Assistant imports so that it can
be unit-tested in isolation. It only depends on :mod:`aiohttp` and the standard
library.

Protocol summary (mirrors the dock firmware ``ucd_api.cpp``)::

    request  -> {"id": <int>, "type": "dock", "command": "<cmd>", ...}
    response <- {"req_id": <int>, "type": "dock", "msg": "<cmd>", "code": <int>, ...}

Authentication::

    on connect the dock sends   {"type": "auth_required", "model": ..., ...}
    client sends                {"id": <int>, "type": "auth", "token": "<token>"}
    dock responds               {"req_id": <int>, "type": "authentication", "code": 200}

Unsolicited events::

    {"type": "event", "msg": "serial_data", "port": 1, "data": "..."}
    {"type": "event", "msg": "log", "level": "I", "tag": "...", "log": "..."}
    {"type": "event", "msg": "ir_receive_on" | "ir_receive_off", ...}
    {"type": "event", "msg": "port_mode", ...}
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

import aiohttp

from .const import (
    CODE_OK,
    CODE_UNAUTHORIZED,
    DEFAULT_BAUD_RATE,
    DEFAULT_DATA_BITS,
    DEFAULT_PARITY,
    DEFAULT_PORT,
    DEFAULT_STOP_BITS,
    DEFAULT_WS_PATH,
    MSG_CODE,
    MSG_COMMAND,
    MSG_ERROR,
    MSG_ID,
    MSG_MSG,
    MSG_REQ_ID,
    MSG_TOKEN,
    MSG_TYPE,
    PORT_MODE_RS232,
    SUCCESS_CODES,
    TYPE_AUTH,
    TYPE_AUTH_REQUIRED,
    TYPE_AUTHENTICATION,
    TYPE_DOCK,
    TYPE_EVENT,
)

_LOGGER = logging.getLogger(__name__)

# Time to wait for a command response before giving up.
DEFAULT_COMMAND_TIMEOUT = 10.0
# Time to wait for the authentication handshake.
AUTH_TIMEOUT = 10.0
# ir_send may answer asynchronously (or not at all for repeats); use a short
# tolerant timeout and treat a missing reply as "accepted".
IR_SEND_TIMEOUT = 5.0
# Reconnect backoff bounds (seconds).
RECONNECT_MIN_BACKOFF = 1.0
RECONNECT_MAX_BACKOFF = 60.0
# Protocol-level WebSocket heartbeat (ping/pong frames).
WS_HEARTBEAT = 25.0


EventCallback = Callable[[dict[str, Any]], None]
ConnectCallback = Callable[[], Awaitable[None]]


class DockError(Exception):
    """Base error for all dock API failures."""


class DockConnectionError(DockError):
    """Raised when the dock cannot be reached or the connection drops."""


class DockAuthError(DockError):
    """Raised when authentication fails (invalid token)."""


class DockResponseError(DockError):
    """Raised when the dock returns a non-success response code."""

    def __init__(self, code: int, command: str | None = None, message: str | None = None) -> None:
        """Initialise with the dock response code and optional context."""
        self.code = code
        self.command = command
        self.dock_message = message
        detail = f" ({message})" if message else ""
        super().__init__(f"Command '{command}' failed with code {code}{detail}")


class UnfoldedCircleDockApi:
    """WebSocket client for a single Unfolded Circle Dock."""

    def __init__(
        self,
        host: str,
        token: str,
        *,
        port: int = DEFAULT_PORT,
        ws_path: str = DEFAULT_WS_PATH,
        use_tls: bool = False,
        session: aiohttp.ClientSession | None = None,
        command_timeout: float = DEFAULT_COMMAND_TIMEOUT,
    ) -> None:
        """Initialise the client.

        :param host: Dock IP address or hostname.
        :param token: Dock API token/password (default ``0000``).
        :param session: Optional shared ``aiohttp`` session. When omitted, an
            internal session is created and owned by this client.
        """
        self._host = host
        self._token = token
        self._port = port
        self._ws_path = ws_path if ws_path.startswith("/") else f"/{ws_path}"
        self._use_tls = use_tls
        self._command_timeout = command_timeout

        self._session = session
        self._owns_session = session is None

        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._receiver_task: asyncio.Task[None] | None = None
        self._connection_task: asyncio.Task[None] | None = None

        self._msg_id = 0
        self._pending: dict[int, asyncio.Future[dict[str, Any]]] = {}

        self._auth_required_event = asyncio.Event()
        self._connected_event = asyncio.Event()
        self._authenticated = False
        self._closing = False

        # Device metadata captured from the auth_required / get_sysinfo messages.
        self.device_info: dict[str, Any] = {}

        # Ports we should (re-)subscribe to serial events after a reconnect.
        self._serial_subscriptions: set[int] = set()

        self._event_callbacks: list[EventCallback] = []
        self._on_connect: ConnectCallback | None = None

    # -- Properties -------------------------------------------------------

    @property
    def host(self) -> str:
        """Return the configured host."""
        return self._host

    @property
    def url(self) -> str:
        """Return the full WebSocket URL."""
        scheme = "wss" if self._use_tls else "ws"
        return f"{scheme}://{self._host}:{self._port}{self._ws_path}"

    @property
    def connected(self) -> bool:
        """Return True if the WebSocket is open and authenticated."""
        return self._ws is not None and not self._ws.closed and self._authenticated

    # -- Callback registration -------------------------------------------

    def add_event_callback(self, callback: EventCallback) -> Callable[[], None]:
        """Register a callback for unsolicited dock events.

        Returns a function that removes the callback again.
        """
        self._event_callbacks.append(callback)

        def _remove() -> None:
            if callback in self._event_callbacks:
                self._event_callbacks.remove(callback)

        return _remove

    def set_on_connect(self, callback: ConnectCallback | None) -> None:
        """Set an async callback invoked after each successful (re)connect."""
        self._on_connect = callback

    # -- Lifecycle --------------------------------------------------------

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
            self._owns_session = True
        return self._session

    async def async_connect(self, *, authenticate: bool = True) -> None:
        """Open the WebSocket connection and optionally authenticate.

        Raises :class:`DockConnectionError` or :class:`DockAuthError` on
        failure. Safe to call before :meth:`async_start`, which will adopt the
        already-open connection instead of reconnecting.

        With ``authenticate=False`` the socket is opened but the auth handshake
        is skipped. Only ``get_sysinfo`` may be used in that state (the dock
        allows it unauthenticated), which is handy for discovery probes.
        """
        await self._open_and_auth(authenticate=authenticate)

    async def _open_and_auth(self, *, authenticate: bool = True) -> None:
        """Open the socket, start the receiver and (optionally) authenticate."""
        session = await self._ensure_session()
        self._auth_required_event.clear()
        try:
            self._ws = await session.ws_connect(
                self.url,
                heartbeat=WS_HEARTBEAT,
                autoping=True,
            )
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as err:
            raise DockConnectionError(f"Cannot connect to dock at {self.url}: {err}") from err

        # Start the receiver before authenticating so the handshake is read.
        self._receiver_task = asyncio.ensure_future(self._receiver_loop())

        # The dock pushes an `auth_required` frame immediately; wait briefly
        # for it so we can capture device metadata, but don't hard-fail if the
        # firmware skips it.
        try:
            await asyncio.wait_for(self._auth_required_event.wait(), timeout=AUTH_TIMEOUT)
        except asyncio.TimeoutError:
            _LOGGER.debug("No auth_required frame received from %s, continuing", self._host)

        if authenticate:
            await self.authenticate()

    async def async_start(self) -> None:
        """Start a self-healing connection loop (reconnect + re-auth)."""
        self._closing = False
        if self._connection_task is None or self._connection_task.done():
            self._connection_task = asyncio.ensure_future(self._connection_loop())

    async def async_disconnect(self) -> None:
        """Close the connection and stop all background tasks."""
        self._closing = True
        self._connected_event.clear()

        if self._connection_task is not None:
            self._connection_task.cancel()
            try:
                await self._connection_task
            except asyncio.CancelledError:
                pass
            self._connection_task = None

        await self._close_ws()

        if self._owns_session and self._session is not None and not self._session.closed:
            await self._session.close()

    async def _close_ws(self) -> None:
        """Close the WebSocket and fail any pending requests."""
        self._authenticated = False
        if self._receiver_task is not None:
            self._receiver_task.cancel()
            try:
                await self._receiver_task
            except asyncio.CancelledError:
                pass
            self._receiver_task = None

        if self._ws is not None and not self._ws.closed:
            await self._ws.close()
        self._ws = None

        self._fail_pending(DockConnectionError("Connection closed"))

    def _fail_pending(self, err: Exception) -> None:
        """Resolve all in-flight requests with an error."""
        for future in list(self._pending.values()):
            if not future.done():
                future.set_exception(err)
        self._pending.clear()

    # -- Connection supervisor -------------------------------------------

    async def _connection_loop(self) -> None:
        """Maintain the connection, reconnecting with exponential backoff."""
        backoff = RECONNECT_MIN_BACKOFF
        while not self._closing:
            if not self.connected:
                try:
                    await self._open_and_auth()
                except DockAuthError:
                    # A bad token will not fix itself - surface and stop trying.
                    _LOGGER.error("Authentication with dock %s failed; stopping", self._host)
                    return
                except DockError as err:
                    _LOGGER.debug("Dock %s connect failed: %s (retry in %.0fs)", self._host, err, backoff)
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, RECONNECT_MAX_BACKOFF)
                    continue

            backoff = RECONNECT_MIN_BACKOFF
            self._connected_event.set()
            _LOGGER.info("Connected to dock %s", self._host)

            # Re-subscribe serial events and notify listeners.
            await self._after_connect()

            # Block until the receiver task ends (i.e. the socket dropped).
            if self._receiver_task is not None:
                try:
                    await self._receiver_task
                except asyncio.CancelledError:
                    pass

            self._connected_event.clear()
            self._authenticated = False
            self._fail_pending(DockConnectionError("Connection lost"))

            if self._closing:
                break

            _LOGGER.warning("Dock %s disconnected; reconnecting in %.0fs", self._host, backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, RECONNECT_MAX_BACKOFF)

    async def _after_connect(self) -> None:
        """Restore subscriptions and run the on-connect callback."""
        for port in sorted(self._serial_subscriptions):
            try:
                await self._raw_command(TYPE_DOCK, command="enable_serial_events", port=port, enable=True)
            except DockError as err:
                _LOGGER.warning("Failed to restore serial events on port %s: %s", port, err)

        if self._on_connect is not None:
            try:
                await self._on_connect()
            except Exception:  # noqa: BLE001 - never let a listener break the loop
                _LOGGER.exception("on_connect callback raised")

    # -- Receiver ---------------------------------------------------------

    async def _receiver_loop(self) -> None:
        """Read and dispatch incoming WebSocket frames until close."""
        assert self._ws is not None
        try:
            async for msg in self._ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    self._handle_text(msg.data)
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    _LOGGER.debug("WebSocket error from %s: %s", self._host, self._ws.exception())
                    break
                elif msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSING, aiohttp.WSMsgType.CLOSED):
                    break
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Receiver loop for %s crashed", self._host)
        finally:
            self._fail_pending(DockConnectionError("Connection closed"))

    def _handle_text(self, raw: str) -> None:
        """Parse one text frame and route it appropriately."""
        try:
            data = aiohttp_json_loads(raw)
        except ValueError:
            _LOGGER.debug("Ignoring non-JSON frame from %s: %r", self._host, raw[:200])
            return

        if not isinstance(data, dict):
            return

        msg_type = data.get(MSG_TYPE)

        # 1) Correlated command/auth response.
        if MSG_REQ_ID in data:
            req_id = data[MSG_REQ_ID]
            future = self._pending.pop(req_id, None)
            if future is not None and not future.done():
                future.set_result(data)
            return

        # 2) Auth handshake prompt.
        if msg_type == TYPE_AUTH_REQUIRED:
            self.device_info.update(
                {
                    key: data[key]
                    for key in ("model", "revision", "version", "features")
                    if key in data
                }
            )
            self._auth_required_event.set()
            return

        # 3) Unsolicited events.
        if msg_type == TYPE_EVENT:
            self._dispatch_event(data)
            return

        _LOGGER.debug("Unhandled message from %s: %s", self._host, data)

    def _dispatch_event(self, data: dict[str, Any]) -> None:
        for callback in list(self._event_callbacks):
            try:
                callback(data)
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Event callback raised for %s", data.get(MSG_MSG))

    # -- Sending ----------------------------------------------------------

    def _next_id(self) -> int:
        self._msg_id += 1
        return self._msg_id

    async def _send(self, message: dict[str, Any], *, expect_response: bool, timeout: float) -> dict[str, Any]:
        """Send a message and optionally await its correlated response."""
        if self._ws is None or self._ws.closed:
            raise DockConnectionError("Not connected to dock")

        req_id = self._next_id()
        message[MSG_ID] = req_id

        future: asyncio.Future[dict[str, Any]] | None = None
        if expect_response:
            future = asyncio.get_running_loop().create_future()
            self._pending[req_id] = future

        try:
            await self._ws.send_json(message)
        except (aiohttp.ClientError, ConnectionError) as err:
            self._pending.pop(req_id, None)
            raise DockConnectionError(f"Failed to send to dock: {err}") from err

        if future is None:
            return {}

        try:
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError as err:
            self._pending.pop(req_id, None)
            raise DockConnectionError(
                f"Timed out waiting for response to '{message.get(MSG_COMMAND, message.get(MSG_TYPE))}'"
            ) from err
        finally:
            self._pending.pop(req_id, None)

    async def _raw_command(self, msg_type: str, *, timeout: float | None = None, **payload: Any) -> dict[str, Any]:
        """Send a typed message and validate the response code."""
        message: dict[str, Any] = {MSG_TYPE: msg_type, **payload}
        command = payload.get("command")
        response = await self._send(
            message,
            expect_response=True,
            timeout=timeout if timeout is not None else self._command_timeout,
        )
        self._check_code(response, command)
        return response

    @staticmethod
    def _check_code(response: dict[str, Any], command: str | None) -> None:
        """Raise an appropriate error for non-success response codes."""
        code = response.get(MSG_CODE)
        if code is None or code in SUCCESS_CODES:
            return
        message = response.get(MSG_ERROR)
        if code == CODE_UNAUTHORIZED:
            raise DockAuthError(message or "Not authenticated")
        raise DockResponseError(code, command, message)

    # -- High-level commands ---------------------------------------------

    async def authenticate(self) -> None:
        """Authenticate the open connection with the configured token."""
        response = await self._send(
            {MSG_TYPE: TYPE_AUTH, MSG_TOKEN: self._token},
            expect_response=True,
            timeout=AUTH_TIMEOUT,
        )
        if response.get(MSG_TYPE) != TYPE_AUTHENTICATION or response.get(MSG_CODE) != CODE_OK:
            self._authenticated = False
            raise DockAuthError(response.get(MSG_ERROR) or "Invalid token")
        self._authenticated = True
        _LOGGER.debug("Authenticated with dock %s", self._host)

    async def send_command(self, command: str, *, timeout: float | None = None, **payload: Any) -> dict[str, Any]:
        """Send a generic dock command and return its (validated) response."""
        return await self._raw_command(TYPE_DOCK, command=command, timeout=timeout, **payload)

    async def get_sysinfo(self) -> dict[str, Any]:
        """Return the dock system information (unauthenticated-capable)."""
        info = await self.send_command("get_sysinfo")
        # Cache the bits useful for the device registry.
        for key in ("name", "hostname", "version", "serial", "model", "revision", "features"):
            if key in info:
                self.device_info[key] = info[key]
        return info

    async def get_stats(self) -> dict[str, Any]:
        """Return runtime statistics (may be 503 if not built into firmware)."""
        return await self.send_command("get_stats")

    async def ping(self) -> dict[str, Any]:
        """Application-level heartbeat (returns a pong)."""
        return await self._raw_command(TYPE_DOCK, msg="ping")

    async def identify(self) -> None:
        """Flash the dock LEDs to locate it."""
        await self.send_command("identify")

    async def set_volume(self, volume: int) -> None:
        """Set the charging/beep volume (0-100)."""
        if not 0 <= volume <= 100:
            raise ValueError("volume must be between 0 and 100")
        await self.send_command("set_volume", volume=volume)

    async def set_brightness(
        self, status_led: int | None = None, eth_led: int | None = None
    ) -> None:
        """Set LED brightness for the status and/or ethernet LEDs."""
        payload: dict[str, Any] = {}
        if status_led is not None:
            payload["status_led"] = status_led
        if eth_led is not None:
            payload["eth_led"] = eth_led
        if not payload:
            raise ValueError("at least one of status_led or eth_led is required")
        await self.send_command("set_brightness", **payload)

    # -- Infrared ---------------------------------------------------------

    async def ir_send(
        self,
        code: str,
        ir_format: str,
        *,
        repeat: int = 0,
        hold: int = 0,
        int_side: bool = False,
        int_top: bool = False,
        ext1: bool = False,
        ext2: bool = False,
    ) -> dict[str, Any]:
        """Send an IR code.

        The dock may answer asynchronously (or not at all when repeating), so a
        missing reply within :data:`IR_SEND_TIMEOUT` is treated as accepted.
        """
        if not any((int_side, int_top, ext1, ext2)):
            # Default to the internal side blaster if no emitter was selected.
            int_side = True

        message = {
            MSG_TYPE: TYPE_DOCK,
            MSG_COMMAND: "ir_send",
            "code": code,
            "format": ir_format,
            "repeat": repeat,
            "hold": hold,
            "int_side": int_side,
            "int_top": int_top,
            "ext1": ext1,
            "ext2": ext2,
        }
        try:
            response = await self._send(message, expect_response=True, timeout=IR_SEND_TIMEOUT)
        except DockConnectionError:
            # No synchronous reply: the dock accepted an asynchronous send.
            return {MSG_CODE: 202, MSG_MSG: "ir_send"}
        self._check_code(response, "ir_send")
        return response

    async def ir_stop(self) -> None:
        """Stop an ongoing/repeating IR transmission."""
        await self.send_command("ir_stop")

    async def ir_receive_on(self, raw: bool = False) -> None:
        """Start IR learning mode."""
        await self.send_command("ir_receive_on", raw=raw)

    async def ir_receive_off(self) -> None:
        """Stop IR learning mode."""
        await self.send_command("ir_receive_off")

    # -- External ports ---------------------------------------------------

    async def get_port_modes(self) -> dict[str, Any]:
        """Return the mode of every external port."""
        return await self.send_command("get_port_modes")

    async def get_port_mode(self, port: int) -> dict[str, Any]:
        """Return the mode of a single external port."""
        return await self.send_command("get_port_mode", port=port)

    async def set_port_mode(
        self,
        port: int,
        mode: str,
        *,
        baud_rate: int = DEFAULT_BAUD_RATE,
        data_bits: int = DEFAULT_DATA_BITS,
        parity: str = DEFAULT_PARITY,
        stop_bits: str = DEFAULT_STOP_BITS,
        uart: dict[str, Any] | None = None,
    ) -> None:
        """Set the mode of an external port.

        When switching to ``RS232`` a ``uart`` object is sent to the dock. Pass
        ``baud_rate`` (and optionally ``data_bits``/``parity``/``stop_bits``) to
        configure the line, or supply a complete ``uart`` dict to override all
        of them. The parameters are ignored for non-RS232 modes.
        """
        payload: dict[str, Any] = {"port": port, "mode": mode}
        if mode == PORT_MODE_RS232:
            payload["uart"] = uart or {
                "baud_rate": baud_rate,
                "data_bits": data_bits,
                "parity": parity,
                "stop_bits": str(stop_bits),
            }
        await self.send_command("set_port_mode", **payload)

    async def get_port_trigger(self, port: int) -> dict[str, Any]:
        """Return the 5V trigger state of a port (port must be TRIGGER_5V)."""
        return await self.send_command("get_port_trigger", port=port)

    async def set_port_trigger(self, port: int, trigger: bool, duration: int = 0) -> None:
        """Set or pulse a 5V trigger output."""
        payload: dict[str, Any] = {"port": port, "trigger": trigger}
        if duration:
            payload["duration"] = duration
        await self.send_command("set_port_trigger", **payload)

    # -- Serial -----------------------------------------------------------

    async def send_serial(self, port: int, data: str) -> None:
        """Write data to a serial (RS232) port."""
        await self.send_command("send_serial", port=port, data=data)

    async def enable_serial_events(self, port: int, enable: bool = True) -> None:
        """Subscribe/unsubscribe to incoming serial data events for a port."""
        await self.send_command("enable_serial_events", port=port, enable=enable)
        if enable:
            self._serial_subscriptions.add(port)
        else:
            self._serial_subscriptions.discard(port)

    async def set_serial_config(
        self,
        port: int,
        *,
        buffering: str | None = None,
        terminator: str | None = None,
        buffer_size: int | None = None,
        timeout_ms: int | None = None,
    ) -> None:
        """Configure serial buffering behaviour for a port."""
        payload: dict[str, Any] = {"port": port}
        if buffering is not None:
            payload["buffering"] = buffering
        if terminator is not None:
            payload["terminator"] = terminator
        if buffer_size is not None:
            payload["buffer_size"] = buffer_size
        if timeout_ms is not None:
            payload["timeout_ms"] = timeout_ms
        await self.send_command("set_serial_config", **payload)

    async def get_serial_config(self, port: int) -> dict[str, Any]:
        """Return the serial buffering configuration for a port."""
        return await self.send_command("get_serial_config", port=port)

    # -- Misc toggles -----------------------------------------------------

    async def get_serial_tcp(self) -> bool:
        """Return whether the serial-over-TCP bridge is enabled."""
        response = await self.send_command("get_serial_tcp")
        return bool(response.get("serial_tcp", False))

    async def set_serial_tcp(self, enable: bool) -> None:
        """Enable/disable the serial-over-TCP bridge."""
        await self.send_command("set_serial_tcp", enable=enable)

    async def enable_log_events(self, enable: bool = True) -> None:
        """Subscribe/unsubscribe to dock log streaming."""
        await self.send_command("enable_log_events", enable=enable)


def aiohttp_json_loads(raw: str) -> Any:
    """JSON decode helper kept separate so it can be patched in tests."""
    import json

    return json.loads(raw)
