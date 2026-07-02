"""The UniFi UNAS (non-invasive) integration."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
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
from homeassistant.helpers.device_registry import DeviceEntry

from .aiounas import (
    ApiKeyAuth,
    SessionAuth,
    UnasActionClient,
    UnasAuthError,
    UnasClient,
    UnasConnectionError,
    probe,
)
from .aiounas.auth import AbstractAuth
from .const import (
    CONF_ENABLE_CONTROLS,
    DEFAULT_ENABLE_CONTROLS,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_VERIFY_SSL,
    DOMAIN,
    PLATFORMS,
)
from .coordinator import UnasDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


@dataclass
class UnasRuntimeData:
    """Per-entry runtime state."""

    coordinator: UnasDataUpdateCoordinator
    action_client: UnasActionClient | None


type UnasConfigEntry = ConfigEntry[UnasRuntimeData]


def build_auth(data: Mapping[str, Any]) -> AbstractAuth:
    """Construct the auth strategy from stored config-entry data."""
    if data.get(CONF_API_KEY):
        return ApiKeyAuth(data[CONF_API_KEY])
    return SessionAuth(data[CONF_USERNAME], data[CONF_PASSWORD])


async def async_setup_entry(hass: HomeAssistant, entry: UnasConfigEntry) -> bool:
    """Set up UniFi UNAS from a config entry."""
    data = entry.data
    verify_ssl = data.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL)
    port = data.get(CONF_PORT, DEFAULT_PORT)
    session = async_get_clientsession(hass, verify_ssl=verify_ssl)
    client = UnasClient(
        session, data[CONF_HOST], build_auth(data), port=port, use_ssl=True, verify_ssl=verify_ssl
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

    action_client: UnasActionClient | None = None
    if entry.options.get(CONF_ENABLE_CONTROLS, DEFAULT_ENABLE_CONTROLS):
        if data.get(CONF_API_KEY):
            # The UNAS API key is read-only (writes -> 401/500); control actions
            # require username/password auth. Don't create buttons that can't work.
            _LOGGER.warning(
                "UniFi UNAS controls are enabled but this entry uses API-key auth, "
                "which cannot perform writes. Reconfigure with a username/password "
                "(an owner account for power/firmware) to use control actions."
            )
        else:
            action_client = UnasActionClient(
                session,
                data[CONF_HOST],
                build_auth(data),
                port=port,
                use_ssl=True,
                verify_ssl=verify_ssl,
            )

    entry.runtime_data = UnasRuntimeData(coordinator, action_client)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: UnasConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: UnasConfigEntry, device: DeviceEntry
) -> bool:
    """Allow deleting a disk/pool/share sub-device that no longer exists.

    The hub device and any sub-device still present in the latest poll are kept;
    a stale one (a removed disk, pool or share) can be deleted by the user.
    """
    data = entry.runtime_data.coordinator.data
    prefix = f"{entry.entry_id}_"
    known = {entry.entry_id}
    known |= {f"{prefix}disk{disk.slot}" for disk in data.storage.disks}
    known |= {f"{prefix}pool{pool.id or pool.number}" for pool in data.storage.pools}
    known |= {f"{prefix}share{share.id}" for share in (data.shares or [])}
    return not any(ident in known for domain, ident in device.identifiers if domain == DOMAIN)


async def _async_reload(hass: HomeAssistant, entry: UnasConfigEntry) -> None:
    """Reload the entry when its options change."""
    await hass.config_entries.async_reload(entry.entry_id)
