"""The UniFi UNAS (non-invasive) integration."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_API_KEY,
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_SCAN_INTERVAL,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from aiounas import (
    ApiKeyAuth,
    SessionAuth,
    UnasAuthError,
    UnasClient,
    UnasConnectionError,
    probe,
)
from aiounas.auth import AbstractAuth

from .const import DEFAULT_PORT, DEFAULT_SCAN_INTERVAL, DEFAULT_VERIFY_SSL, PLATFORMS
from .coordinator import UnasDataUpdateCoordinator

type UnasConfigEntry = ConfigEntry[UnasDataUpdateCoordinator]


def build_auth(data: Mapping[str, Any]) -> AbstractAuth:
    """Construct the auth strategy from stored config-entry data."""
    if data.get(CONF_API_KEY):
        return ApiKeyAuth(data[CONF_API_KEY])
    return SessionAuth(data[CONF_USERNAME], data[CONF_PASSWORD])


async def async_setup_entry(hass: HomeAssistant, entry: UnasConfigEntry) -> bool:
    """Set up UniFi UNAS from a config entry."""
    data = entry.data
    verify_ssl = data.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL)
    session = async_get_clientsession(hass, verify_ssl=verify_ssl)
    client = UnasClient(
        session,
        data[CONF_HOST],
        build_auth(data),
        port=data.get(CONF_PORT, DEFAULT_PORT),
        use_ssl=True,
        verify_ssl=verify_ssl,
    )

    try:
        await client.async_prepare()
        capabilities = await probe(client)
    except UnasAuthError as err:
        raise ConfigEntryAuthFailed(str(err)) from err
    except UnasConnectionError as err:
        raise ConfigEntryNotReady(str(err)) from err

    scan_interval = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    coordinator = UnasDataUpdateCoordinator(hass, entry, client, capabilities, scan_interval)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: UnasConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_reload(hass: HomeAssistant, entry: UnasConfigEntry) -> None:
    """Reload the entry when its options change."""
    await hass.config_entries.async_reload(entry.entry_id)
