"""Constants for the Unfolded Circle Dock integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "hass_unfolded_circle_dock"

# --- Connection defaults -------------------------------------------------
# Dock 3 serves the WebSocket Dock-API at ws://<ip>/ws on port 80.
# (Dock Two used ws://<ip>:946 - configurable here for completeness.)
DEFAULT_PORT: Final = 80
DEFAULT_WS_PATH: Final = "/ws"
DEFAULT_NAME: Final = "Unfolded Circle Dock"
# If no custom password/token was set during dock setup, "0000" is used.
DEFAULT_TOKEN: Final = "0000"

# --- Config entry keys ---------------------------------------------------
CONF_HOST: Final = "host"
CONF_PORT: Final = "port"
CONF_WS_PATH: Final = "ws_path"
CONF_TOKEN: Final = "token"
CONF_NAME: Final = "name"
CONF_USE_TLS: Final = "use_tls"

# --- Coordinator ---------------------------------------------------------
# How often we poll get_sysinfo (seconds).
DEFAULT_SCAN_INTERVAL: Final = 30

# --- Manufacturer / device ----------------------------------------------
MANUFACTURER: Final = "Unfolded Circle"

# --- WebSocket message field names (mirrors the firmware) ----------------
MSG_TYPE: Final = "type"
MSG_ID: Final = "id"
MSG_REQ_ID: Final = "req_id"
MSG_COMMAND: Final = "command"
MSG_MSG: Final = "msg"
MSG_CODE: Final = "code"
MSG_ERROR: Final = "error"
MSG_TOKEN: Final = "token"

TYPE_DOCK: Final = "dock"
TYPE_AUTH: Final = "auth"
TYPE_AUTH_REQUIRED: Final = "auth_required"
TYPE_AUTHENTICATION: Final = "authentication"
TYPE_EVENT: Final = "event"

# --- Dock response codes -------------------------------------------------
CODE_OK: Final = 200
CODE_ACCEPTED: Final = 202
CODE_BAD_REQUEST: Final = 400
CODE_UNAUTHORIZED: Final = 401
CODE_NOT_FOUND: Final = 404
CODE_CONFLICT: Final = 409
CODE_LOCKED: Final = 423
CODE_NOT_IMPLEMENTED: Final = 501
CODE_INTERNAL_ERROR: Final = 500
CODE_UNAVAILABLE: Final = 503

SUCCESS_CODES: Final = frozenset({CODE_OK, CODE_ACCEPTED})

# --- Feature flags (advertised in `features` bitmask) --------------------
FEATURE_IR_REPEAT_NO_RESPONSE: Final = 1 << 0  # ir_send may answer asynchronously
FEATURE_IR_SEND_HOLD: Final = 1 << 1  # ir_send supports the `hold` parameter

# --- HA bus event names (unsolicited dock events) ------------------------
EVENT_SERIAL_DATA: Final = f"{DOMAIN}_serial_data"
EVENT_LOG: Final = f"{DOMAIN}_log"
EVENT_IR_LEARN: Final = f"{DOMAIN}_ir_learn"
EVENT_PORT_MODE: Final = f"{DOMAIN}_port_mode"

# Dispatcher signal emitted when a serial_data event arrives (per entry).
SIGNAL_SERIAL_DATA: Final = f"{DOMAIN}_serial_data_signal"
SIGNAL_DOCK_EVENT: Final = f"{DOMAIN}_dock_event_signal"

# --- Port modes ----------------------------------------------------------
# Known modes from the firmware. The dock also advertises a per-port
# `supported_modes` list, which is authoritative at runtime.
PORT_MODE_RS232: Final = "RS232"
PORT_MODE_TRIGGER_5V: Final = "TRIGGER_5V"

# --- Service names -------------------------------------------------------
SERVICE_SEND_IR: Final = "send_ir"
SERVICE_STOP_IR: Final = "stop_ir"
SERVICE_IDENTIFY: Final = "identify"
SERVICE_SET_VOLUME: Final = "set_volume"
SERVICE_SET_BRIGHTNESS: Final = "set_brightness"
SERVICE_SEND_SERIAL: Final = "send_serial"
SERVICE_SET_PORT_MODE: Final = "set_port_mode"
SERVICE_ENABLE_SERIAL_EVENTS: Final = "enable_serial_events"
SERVICE_REFRESH: Final = "refresh"

PLATFORMS: Final = ["sensor", "binary_sensor", "button", "switch"]
