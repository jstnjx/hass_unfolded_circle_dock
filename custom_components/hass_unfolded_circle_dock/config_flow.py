"""Config flow for the Unfolded Circle Dock integration.

Setup is designed to need as little from the user as possible:

* Docks are auto-discovered over mDNS/zeroconf and DHCP, so in most cases the
  dock simply appears in Home Assistant and the user only confirms the token.
* For manual setup the user enters just a host and token; the integration
  probes the known Dock 3 (port 80, /ws) and Dock Two (port 946, /) endpoints
  and figures out the model itself. Port/path are optional advanced overrides.
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.service_info.dhcp import DhcpServiceInfo
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo

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
    DEFAULT_TOKEN,
    DEFAULT_WS_PATH,
    DOMAIN,
    ENDPOINT_DOCK2,
    ENDPOINT_DOCK3,
    HOSTNAME_PREFIX_DOCK2,
    HOSTNAME_PREFIX_DOCK3,
)

_LOGGER = logging.getLogger(__name__)

# Manual setup: host + token is all that's normally needed. Port/path are
# optional advanced overrides; left blank, both docks are probed automatically.
STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Optional(CONF_TOKEN, default=DEFAULT_TOKEN): str,
        vol.Optional(CONF_NAME): str,
        vol.Optional(CONF_USE_TLS, default=False): bool,
        vol.Optional(CONF_PORT): vol.All(vol.Coerce(int), vol.Range(min=1, max=65535)),
        vol.Optional(CONF_WS_PATH): str,
    }
)

# Discovery confirm: the user only supplies the token (and optional name).
STEP_DISCOVERY_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_TOKEN, default=DEFAULT_TOKEN): str,
        vol.Optional(CONF_NAME): str,
    }
)

# Reconfigure exposes the full connection details.
RECONFIGURE_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Optional(CONF_PORT, default=DEFAULT_PORT): vol.Coerce(int),
        vol.Optional(CONF_WS_PATH, default=DEFAULT_WS_PATH): str,
        vol.Optional(CONF_TOKEN, default=DEFAULT_TOKEN): str,
        vol.Optional(CONF_USE_TLS, default=False): bool,
        vol.Optional(CONF_NAME): str,
    }
)


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""


def _ordered_endpoints(hostname: str | None) -> list[tuple[int, str]]:
    """Order the endpoint probes using the hostname as a hint."""
    host = (hostname or "").lower()
    if host.startswith(HOSTNAME_PREFIX_DOCK3):
        return [ENDPOINT_DOCK3, ENDPOINT_DOCK2]
    if host.startswith(HOSTNAME_PREFIX_DOCK2):
        return [ENDPOINT_DOCK2, ENDPOINT_DOCK3]
    return [ENDPOINT_DOCK3, ENDPOINT_DOCK2]


async def _async_probe(
    hass: Any,
    host: str,
    *,
    use_tls: bool,
    token: str | None,
    authenticate: bool,
    candidates: list[tuple[int, str]],
) -> tuple[dict[str, Any], int, str]:
    """Try each (port, path) candidate and return (sysinfo, port, ws_path).

    With ``authenticate=False`` the unauthenticated ``get_sysinfo`` is used,
    which is enough to identify the dock during discovery. A reachable dock that
    rejects the token raises :class:`InvalidAuth`; if nothing is reachable on
    any candidate, :class:`CannotConnect` is raised.
    """
    last_conn_err: Exception | None = None
    for port, ws_path in candidates:
        api = UnfoldedCircleDockApi(
            host=host,
            token=token or DEFAULT_TOKEN,
            port=port,
            ws_path=ws_path,
            use_tls=use_tls,
            session=async_get_clientsession(hass),
        )
        try:
            await api.async_connect(authenticate=authenticate)
            info = await api.get_sysinfo()
            return info, port, ws_path
        except DockAuthError as err:
            # Reachable dock, wrong token -> no point trying other endpoints.
            raise InvalidAuth from err
        except DockConnectionError as err:
            last_conn_err = err
            continue
        finally:
            await api.async_disconnect()
    raise CannotConnect from last_conn_err


class UnfoldedCircleDockConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Unfolded Circle Dock."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialise discovery state."""
        self._discovered: dict[str, Any] = {}

    # -- Manual setup -----------------------------------------------------

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manual setup: host + token, with auto-detection of the model."""
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_HOST]
            token = user_input.get(CONF_TOKEN) or DEFAULT_TOKEN
            use_tls = user_input.get(CONF_USE_TLS, False)
            name = user_input.get(CONF_NAME)

            # Honour an explicit port/path override, otherwise probe both docks.
            port = user_input.get(CONF_PORT)
            ws_path = user_input.get(CONF_WS_PATH)
            if port and ws_path:
                candidates = [(int(port), ws_path)]
            else:
                candidates = [ENDPOINT_DOCK3, ENDPOINT_DOCK2]

            try:
                info, port, ws_path = await _async_probe(
                    self.hass,
                    host,
                    use_tls=use_tls,
                    token=token,
                    authenticate=True,
                    candidates=candidates,
                )
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected error validating dock connection")
                errors["base"] = "unknown"
            else:
                serial = str(info.get("serial") or host)
                await self.async_set_unique_id(serial)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=name or info.get("name") or info.get("hostname") or DEFAULT_NAME,
                    data={
                        CONF_HOST: host,
                        CONF_PORT: port,
                        CONF_WS_PATH: ws_path,
                        CONF_TOKEN: token,
                        CONF_USE_TLS: use_tls,
                        CONF_NAME: name,
                    },
                )

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_SCHEMA, errors=errors
        )

    # -- Discovery (zeroconf / DHCP) --------------------------------------

    async def async_step_zeroconf(
        self, discovery_info: ZeroconfServiceInfo
    ) -> ConfigFlowResult:
        """Handle a dock discovered over mDNS."""
        return await self._async_handle_discovery(
            str(discovery_info.host), discovery_info.hostname
        )

    async def async_step_dhcp(
        self, discovery_info: DhcpServiceInfo
    ) -> ConfigFlowResult:
        """Handle a dock discovered over DHCP."""
        return await self._async_handle_discovery(
            discovery_info.ip, discovery_info.hostname
        )

    async def _async_handle_discovery(
        self, host: str, hostname: str | None
    ) -> ConfigFlowResult:
        """Probe a discovered dock (no token needed) and offer confirmation."""
        try:
            info, port, ws_path = await _async_probe(
                self.hass,
                host,
                use_tls=False,
                token=None,
                authenticate=False,
                candidates=_ordered_endpoints(hostname),
            )
        except Exception:  # noqa: BLE001
            return self.async_abort(reason="cannot_connect")

        clean_host = (hostname or host).rstrip(".")
        serial = str(info.get("serial") or clean_host)
        await self.async_set_unique_id(serial)
        self._abort_if_unique_id_configured(updates={CONF_HOST: host})

        friendly = info.get("name") or info.get("hostname") or clean_host
        self._discovered = {
            CONF_HOST: host,
            CONF_PORT: port,
            CONF_WS_PATH: ws_path,
            CONF_NAME: info.get("name"),
            "friendly": friendly,
        }
        self.context["title_placeholders"] = {"name": friendly}
        return await self.async_step_discovery_confirm()

    async def async_step_discovery_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm a discovered dock; the user only supplies the token."""
        errors: dict[str, str] = {}
        disc = self._discovered

        if user_input is not None:
            token = user_input.get(CONF_TOKEN) or DEFAULT_TOKEN
            name = user_input.get(CONF_NAME)
            try:
                info, port, ws_path = await _async_probe(
                    self.hass,
                    disc[CONF_HOST],
                    use_tls=False,
                    token=token,
                    authenticate=True,
                    candidates=[(disc[CONF_PORT], disc[CONF_WS_PATH])],
                )
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected error validating dock connection")
                errors["base"] = "unknown"
            else:
                return self.async_create_entry(
                    title=name or disc.get(CONF_NAME) or disc["friendly"] or DEFAULT_NAME,
                    data={
                        CONF_HOST: disc[CONF_HOST],
                        CONF_PORT: port,
                        CONF_WS_PATH: ws_path,
                        CONF_TOKEN: token,
                        CONF_USE_TLS: False,
                        CONF_NAME: name,
                    },
                )

        return self.async_show_form(
            step_id="discovery_confirm",
            data_schema=STEP_DISCOVERY_SCHEMA,
            errors=errors,
            description_placeholders={"name": disc.get("friendly", "")},
        )

    # -- Reconfigure ------------------------------------------------------

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Allow changing host/port/path/token of an existing entry."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_HOST]
            token = user_input.get(CONF_TOKEN) or DEFAULT_TOKEN
            use_tls = user_input.get(CONF_USE_TLS, False)
            port = user_input.get(CONF_PORT, DEFAULT_PORT)
            ws_path = user_input.get(CONF_WS_PATH, DEFAULT_WS_PATH)
            try:
                await _async_probe(
                    self.hass,
                    host,
                    use_tls=use_tls,
                    token=token,
                    authenticate=True,
                    candidates=[(int(port), ws_path)],
                )
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
