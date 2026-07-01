"""Config flow for the UniFi UNAS integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import (
    CONF_API_KEY,
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
)
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .aiounas import (
    ApiKeyAuth,
    SessionAuth,
    SystemIdentity,
    UnasAuthError,
    UnasCapabilityError,
    UnasClient,
    UnasConnectionError,
)
from .aiounas.auth import AbstractAuth
from .const import (
    AUTH_API_KEY,
    AUTH_PASSWORD,
    CONF_AUTH_METHOD,
    DEFAULT_PORT,
    DEFAULT_VERIFY_SSL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

_API_KEY_SCHEMA = vol.Schema({vol.Required(CONF_API_KEY): str})
_PASSWORD_SCHEMA = vol.Schema({vol.Required(CONF_USERNAME): str, vol.Required(CONF_PASSWORD): str})


def _auth_from_input(method: str, user_input: dict[str, Any]) -> AbstractAuth:
    if method == AUTH_API_KEY:
        return ApiKeyAuth(user_input[CONF_API_KEY])
    return SessionAuth(user_input[CONF_USERNAME], user_input[CONF_PASSWORD])


class UnifiUnasConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for UniFi UNAS."""

    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Collect host / port / TLS and the chosen auth method."""
        if user_input is not None:
            self._data.update(user_input)
            if user_input[CONF_AUTH_METHOD] == AUTH_API_KEY:
                return await self.async_step_api_key()
            return await self.async_step_password()

        schema = vol.Schema(
            {
                vol.Required(CONF_HOST): str,
                vol.Required(CONF_PORT, default=DEFAULT_PORT): int,
                vol.Required(CONF_VERIFY_SSL, default=DEFAULT_VERIFY_SSL): bool,
                vol.Required(CONF_AUTH_METHOD, default=AUTH_API_KEY): SelectSelector(
                    SelectSelectorConfig(
                        options=[AUTH_API_KEY, AUTH_PASSWORD],
                        translation_key="auth_method",
                        mode=SelectSelectorMode.LIST,
                    )
                ),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema)

    async def async_step_api_key(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Collect and validate an API key."""
        return await self._auth_step("api_key", AUTH_API_KEY, _API_KEY_SCHEMA, user_input)

    async def async_step_password(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Collect and validate a local account."""
        return await self._auth_step("password", AUTH_PASSWORD, _PASSWORD_SCHEMA, user_input)

    async def _auth_step(
        self,
        step_id: str,
        method: str,
        schema: vol.Schema,
        user_input: dict[str, Any] | None,
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            data = {**self._data, CONF_AUTH_METHOD: method, **user_input}
            try:
                identity = await self._probe(data, _auth_from_input(method, user_input))
            except UnasAuthError:
                errors["base"] = "invalid_auth"
            except UnasConnectionError:
                errors["base"] = "cannot_connect"
            except UnasCapabilityError:
                errors["base"] = "insufficient_permissions"
            except Exception:
                _LOGGER.exception("Unexpected error validating UNAS connection")
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(identity.mac)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=_title(identity, data), data=data)
        return self.async_show_form(step_id=step_id, data_schema=schema, errors=errors)

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        """Handle re-authentication when credentials stop working."""
        self._data = dict(entry_data)
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        method = self._data.get(CONF_AUTH_METHOD, AUTH_API_KEY)
        schema = _API_KEY_SCHEMA if method == AUTH_API_KEY else _PASSWORD_SCHEMA
        if user_input is not None:
            data = {**self._data, **user_input}
            try:
                identity = await self._probe(data, _auth_from_input(method, user_input))
            except UnasAuthError:
                errors["base"] = "invalid_auth"
            except UnasConnectionError:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error during UNAS reauth")
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(identity.mac)
                self._abort_if_unique_id_mismatch(reason="wrong_device")
                return self.async_update_reload_and_abort(self._get_reauth_entry(), data=data)
        return self.async_show_form(step_id="reauth_confirm", data_schema=schema, errors=errors)

    async def _probe(self, data: dict[str, Any], auth: AbstractAuth) -> SystemIdentity:
        """Validate connectivity + auth; return the device identity (for unique_id)."""
        session = async_get_clientsession(self.hass, verify_ssl=data[CONF_VERIFY_SSL])
        client = UnasClient(
            session,
            data[CONF_HOST],
            auth,
            port=data[CONF_PORT],
            use_ssl=True,
            verify_ssl=data[CONF_VERIFY_SSL],
        )
        await client.async_prepare()
        identity = await client.get_identity()
        await client.get_storage()  # confirm the Drive API is reachable with this auth
        return identity


def _title(identity: SystemIdentity, data: dict[str, Any]) -> str:
    name = identity.name or "UNAS"
    return f"{name} ({data[CONF_HOST]})"
