"""Config flow for the Unfolded Circle Dock integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import DockAuthError, DockConnectionError, UnfoldedCircleDockApi
from .const import (
    CONF_HOST,
    CONF_NAME,
    CONF_PORT,
    CONF_TOKEN,
    CONF_USE_TLS,
    CONF_WS_PATH,
    DEFAULT_NAME,
    DEFAULT_PORT,
    DEFAULT_PORT_DOCK2,
    DEFAULT_TOKEN,
    DEFAULT_WS_PATH,
    DEFAULT_WS_PATH_DOCK2,
    DOMAIN,
    MODEL_DOCK2,
    MODEL_DOCK3,
)

_LOGGER = logging.getLogger(__name__)


def _connection_schema(default_port: int, default_ws_path: str) -> vol.Schema:
    """Build the connection form schema with model-specific defaults."""
    return vol.Schema(
        {
            vol.Required(CONF_HOST): str,
            vol.Optional(CONF_PORT, default=default_port): vol.Coerce(int),
            vol.Optional(CONF_WS_PATH, default=default_ws_path): str,
            vol.Optional(CONF_TOKEN, default=DEFAULT_TOKEN): str,
            vol.Optional(CONF_USE_TLS, default=False): bool,
            vol.Optional(CONF_NAME): str,
        }
    )


# Used for reconfigure (seeded with the existing entry's values).
RECONFIGURE_SCHEMA = _connection_schema(DEFAULT_PORT, DEFAULT_WS_PATH)


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""


async def validate_input(hass: Any, data: dict[str, Any]) -> dict[str, Any]:
    """Validate the user input by connecting and reading sysinfo."""
    api = UnfoldedCircleDockApi(
        host=data[CONF_HOST],
        token=data.get(CONF_TOKEN, DEFAULT_TOKEN),
        port=data.get(CONF_PORT, DEFAULT_PORT),
        ws_path=data.get(CONF_WS_PATH, DEFAULT_WS_PATH),
        use_tls=data.get(CONF_USE_TLS, False),
        session=async_get_clientsession(hass),
    )

    try:
        await api.async_connect()
        info = await api.get_sysinfo()
    except DockAuthError as err:
        raise InvalidAuth from err
    except DockConnectionError as err:
        raise CannotConnect from err
    finally:
        await api.async_disconnect()

    return info


class UnfoldedCircleDockConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Unfolded Circle Dock."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """First step: let the user pick the dock model."""
        return self.async_show_menu(
            step_id="user",
            menu_options=[MODEL_DOCK3, MODEL_DOCK2],
        )

    async def async_step_dock3(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Connection form pre-filled with Dock 3 defaults (port 80, /ws)."""
        return await self._async_connection_step(
            MODEL_DOCK3,
            _connection_schema(DEFAULT_PORT, DEFAULT_WS_PATH),
            user_input,
        )

    async def async_step_dock_two(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Connection form pre-filled with Dock Two defaults (port 946, /)."""
        return await self._async_connection_step(
            MODEL_DOCK2,
            _connection_schema(DEFAULT_PORT_DOCK2, DEFAULT_WS_PATH_DOCK2),
            user_input,
        )

    async def _async_connection_step(
        self,
        step_id: str,
        schema: vol.Schema,
        user_input: dict[str, Any] | None,
    ) -> ConfigFlowResult:
        """Shared connect-and-create logic for both dock models."""
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                info = await validate_input(self.hass, user_input)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected error validating dock connection")
                errors["base"] = "unknown"
            else:
                serial = str(info.get("serial") or user_input[CONF_HOST])
                await self.async_set_unique_id(serial)
                self._abort_if_unique_id_configured()

                title = (
                    user_input.get(CONF_NAME)
                    or info.get("name")
                    or info.get("hostname")
                    or DEFAULT_NAME
                )
                return self.async_create_entry(title=title, data=user_input)

        return self.async_show_form(
            step_id=step_id,
            data_schema=schema,
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Allow changing host/port/path/token of an existing entry."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                await validate_input(self.hass, user_input)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected error validating dock connection")
                errors["base"] = "unknown"
            else:
                return self.async_update_reload_and_abort(entry, data=user_input)

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                RECONFIGURE_SCHEMA, entry.data
            ),
            errors=errors,
        )
