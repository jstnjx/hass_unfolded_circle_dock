"""Service handlers for the Unfolded Circle Dock integration."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv, device_registry as dr

from .api import DockError
from .const import (
    BAUD_RATE_MAX,
    BAUD_RATE_MIN,
    BRIGHTNESS_MAX,
    BRIGHTNESS_MIN,
    DOMAIN,
    SERVICE_ENABLE_SERIAL_EVENTS,
    SERVICE_IDENTIFY,
    SERVICE_REBOOT,
    SERVICE_REFRESH,
    SERVICE_SEND_IR,
    SERVICE_SEND_SERIAL,
    SERVICE_SET_BRIGHTNESS,
    SERVICE_SET_PORT_MODE,
    SERVICE_SET_PORT_TRIGGER,
    SERVICE_SET_VOLUME,
    SERVICE_STOP_IR,
)

if TYPE_CHECKING:
    from .coordinator import UnfoldedCircleDockCoordinator

_LOGGER = logging.getLogger(__name__)

ATTR_DEVICE_ID = "device_id"

_DEVICE_TARGET = {vol.Optional(ATTR_DEVICE_ID): vol.All(cv.ensure_list, [cv.string])}

SEND_IR_SCHEMA = vol.Schema(
    {
        **_DEVICE_TARGET,
        vol.Required("code"): cv.string,
        vol.Required("format"): cv.string,
        vol.Optional("repeat", default=0): cv.positive_int,
        vol.Optional("hold", default=0): cv.positive_int,
        vol.Optional("int_side", default=False): cv.boolean,
        vol.Optional("int_top", default=False): cv.boolean,
        vol.Optional("ext1", default=False): cv.boolean,
        vol.Optional("ext2", default=False): cv.boolean,
    }
)

SET_VOLUME_SCHEMA = vol.Schema(
    {**_DEVICE_TARGET, vol.Required("volume"): vol.All(vol.Coerce(int), vol.Range(min=0, max=100))}
)

SET_BRIGHTNESS_SCHEMA = vol.Schema(
    {
        **_DEVICE_TARGET,
        vol.Optional("status_led"): vol.All(
            vol.Coerce(int), vol.Range(min=BRIGHTNESS_MIN, max=BRIGHTNESS_MAX)
        ),
        vol.Optional("eth_led"): vol.All(
            vol.Coerce(int), vol.Range(min=BRIGHTNESS_MIN, max=BRIGHTNESS_MAX)
        ),
    }
)

SEND_SERIAL_SCHEMA = vol.Schema(
    {
        **_DEVICE_TARGET,
        vol.Required("port"): vol.All(vol.Coerce(int), vol.Range(min=1)),
        vol.Required("data"): cv.string,
    }
)

SET_PORT_MODE_SCHEMA = vol.Schema(
    {
        **_DEVICE_TARGET,
        vol.Required("port"): vol.All(vol.Coerce(int), vol.Range(min=1)),
        vol.Required("mode"): cv.string,
        # RS232 line settings (used only when mode is RS232).
        vol.Optional("baud_rate"): vol.All(
            vol.Coerce(int), vol.Range(min=BAUD_RATE_MIN, max=BAUD_RATE_MAX)
        ),
        vol.Optional("data_bits"): vol.All(vol.Coerce(int), vol.In((5, 6, 7, 8))),
        vol.Optional("parity"): vol.In(("none", "even", "odd")),
        vol.Optional("stop_bits"): vol.All(cv.string, vol.In(("1", "1.5", "2"))),
    }
)

ENABLE_SERIAL_EVENTS_SCHEMA = vol.Schema(
    {
        **_DEVICE_TARGET,
        vol.Required("port"): vol.All(vol.Coerce(int), vol.Range(min=1)),
        vol.Optional("enable", default=True): cv.boolean,
    }
)

SET_PORT_TRIGGER_SCHEMA = vol.Schema(
    {
        **_DEVICE_TARGET,
        vol.Required("port"): vol.All(vol.Coerce(int), vol.Range(min=1)),
        vol.Optional("trigger", default=True): cv.boolean,
        # Optional pulse length in milliseconds (auto-release after duration).
        vol.Optional("duration"): vol.All(vol.Coerce(int), vol.Range(min=1)),
    }
)

SIMPLE_SCHEMA = vol.Schema(_DEVICE_TARGET)


def _resolve_coordinators(
    hass: HomeAssistant, call: ServiceCall
) -> list["UnfoldedCircleDockCoordinator"]:
    """Find the dock coordinator(s) targeted by a service call."""
    entries = list(hass.config_entries.async_loaded_entries(DOMAIN))
    if not entries:
        raise ServiceValidationError("No Unfolded Circle Dock is configured")

    device_ids = call.data.get(ATTR_DEVICE_ID)
    if not device_ids:
        if len(entries) == 1:
            return [entries[0].runtime_data]
        raise ServiceValidationError(
            "Multiple docks are configured; specify a device_id for this service"
        )

    device_reg = dr.async_get(hass)
    coordinators: list[UnfoldedCircleDockCoordinator] = []
    seen: set[str] = set()
    for device_id in device_ids:
        device = device_reg.async_get(device_id)
        if device is None:
            raise ServiceValidationError(f"Unknown device_id: {device_id}")
        for entry_id in device.config_entries:
            if entry_id in seen:
                continue
            entry = hass.config_entries.async_get_entry(entry_id)
            if entry and entry.domain == DOMAIN and hasattr(entry, "runtime_data"):
                seen.add(entry_id)
                coordinators.append(entry.runtime_data)

    if not coordinators:
        raise ServiceValidationError("No Unfolded Circle Dock matched the target device(s)")
    return coordinators


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register integration services (idempotent)."""
    if hass.services.has_service(DOMAIN, SERVICE_IDENTIFY):
        return

    async def _run(call: ServiceCall, action) -> None:
        for coordinator in _resolve_coordinators(hass, call):
            try:
                await action(coordinator)
            except DockError as err:
                raise HomeAssistantError(f"Dock command failed: {err}") from err

    async def handle_send_ir(call: ServiceCall) -> None:
        await _run(
            call,
            lambda c: c.api.ir_send(
                code=call.data["code"],
                ir_format=call.data["format"],
                repeat=call.data["repeat"],
                hold=call.data["hold"],
                int_side=call.data["int_side"],
                int_top=call.data["int_top"],
                ext1=call.data["ext1"],
                ext2=call.data["ext2"],
            ),
        )

    async def handle_stop_ir(call: ServiceCall) -> None:
        await _run(call, lambda c: c.api.ir_stop())

    async def handle_identify(call: ServiceCall) -> None:
        await _run(call, lambda c: c.api.identify())

    async def handle_set_volume(call: ServiceCall) -> None:
        await _run(call, lambda c: c.api.set_volume(call.data["volume"]))

    async def handle_set_brightness(call: ServiceCall) -> None:
        if "status_led" not in call.data and "eth_led" not in call.data:
            raise ServiceValidationError("Provide status_led and/or eth_led")
        await _run(
            call,
            lambda c: c.api.set_brightness(
                status_led=call.data.get("status_led"),
                eth_led=call.data.get("eth_led"),
            ),
        )

    async def handle_send_serial(call: ServiceCall) -> None:
        await _run(call, lambda c: c.api.send_serial(call.data["port"], call.data["data"]))

    async def handle_set_port_mode(call: ServiceCall) -> None:
        kwargs: dict[str, Any] = {}
        for key in ("baud_rate", "data_bits", "parity", "stop_bits"):
            if key in call.data:
                kwargs[key] = call.data[key]
        await _run(
            call,
            lambda c: c.api.set_port_mode(
                call.data["port"], call.data["mode"], **kwargs
            ),
        )

    async def handle_enable_serial_events(call: ServiceCall) -> None:
        await _run(
            call,
            lambda c: c.api.enable_serial_events(call.data["port"], call.data["enable"]),
        )

    async def handle_set_port_trigger(call: ServiceCall) -> None:
        await _run(
            call,
            lambda c: c.api.set_port_trigger(
                call.data["port"],
                call.data["trigger"],
                call.data.get("duration", 0),
            ),
        )

    async def handle_reboot(call: ServiceCall) -> None:
        await _run(call, lambda c: c.api.reboot())

    async def handle_refresh(call: ServiceCall) -> None:
        await _run(call, lambda c: c.async_request_refresh())

    hass.services.async_register(DOMAIN, SERVICE_SEND_IR, handle_send_ir, schema=SEND_IR_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_STOP_IR, handle_stop_ir, schema=SIMPLE_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_IDENTIFY, handle_identify, schema=SIMPLE_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_SET_VOLUME, handle_set_volume, schema=SET_VOLUME_SCHEMA)
    hass.services.async_register(
        DOMAIN, SERVICE_SET_BRIGHTNESS, handle_set_brightness, schema=SET_BRIGHTNESS_SCHEMA
    )
    hass.services.async_register(DOMAIN, SERVICE_SEND_SERIAL, handle_send_serial, schema=SEND_SERIAL_SCHEMA)
    hass.services.async_register(
        DOMAIN, SERVICE_SET_PORT_MODE, handle_set_port_mode, schema=SET_PORT_MODE_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_ENABLE_SERIAL_EVENTS, handle_enable_serial_events, schema=ENABLE_SERIAL_EVENTS_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_SET_PORT_TRIGGER, handle_set_port_trigger, schema=SET_PORT_TRIGGER_SCHEMA
    )
    hass.services.async_register(DOMAIN, SERVICE_REBOOT, handle_reboot, schema=SIMPLE_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_REFRESH, handle_refresh, schema=SIMPLE_SCHEMA)
