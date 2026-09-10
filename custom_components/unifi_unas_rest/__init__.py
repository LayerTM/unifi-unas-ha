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
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import DeviceEntry

from .aiounas import (
    ApiKeyAuth,
    SessionAuth,
    TlsMode,
    UnasActionClient,
    UnasAuthError,
    UnasCertificateMismatch,
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
    DOMAIN,
    ISSUE_CERT_MISMATCH,
    ISSUE_TLS_INSECURE,
    PLATFORMS,
)
from .coordinator import UnasDataUpdateCoordinator
from .entity import hub_device_info
from .tls import ssl_for_entry, tls_mode_of

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
    port = data.get(CONF_PORT, DEFAULT_PORT)
    ssl = ssl_for_entry(data)
    # The trust is decided per request, so the shared verifying session is the
    # right one to take even when a self-signed certificate is being pinned.
    session = async_get_clientsession(hass)
    client = UnasClient(
        session, data[CONF_HOST], build_auth(data), port=port, use_ssl=True, ssl=ssl
    )

    try:
        await client.async_prepare()
        capabilities = await probe(client)
    except UnasCertificateMismatch as err:
        # NOT ConfigEntryAuthFailed: the credentials are fine and asking for them
        # again would teach the user to retype a password at exactly the moment
        # something may be impersonating their console. Raise a repair instead,
        # which shows both fingerprints and lets them accept the new one.
        async_raise_cert_mismatch(hass, entry, err)
        raise ConfigEntryNotReady(str(err)) from err
    except UnasAuthError as err:
        raise ConfigEntryAuthFailed(str(err)) from err
    except UnasConnectionError as err:
        raise ConfigEntryNotReady(str(err)) from err

    _async_review_tls(hass, entry)

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
                ssl=ssl,
            )

    entry.runtime_data = UnasRuntimeData(coordinator, action_client)
    # Register the hub before the platforms load: a sub-device can only be linked
    # to it by device-registry id, which does not exist until the hub does.
    hub = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id, **hub_device_info(coordinator)
    )
    coordinator.hub_device_id = hub.id
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


def async_raise_cert_mismatch(
    hass: HomeAssistant, entry: UnasConfigEntry, err: UnasCertificateMismatch
) -> None:
    """Raise the repair that shows both fingerprints and offers the new one."""
    ir.async_create_issue(
        hass,
        DOMAIN,
        f"{ISSUE_CERT_MISMATCH}_{entry.entry_id}",
        is_fixable=True,
        severity=ir.IssueSeverity.ERROR,
        translation_key=ISSUE_CERT_MISMATCH,
        translation_placeholders={
            "host": entry.data[CONF_HOST],
            "expected": err.expected,
            "got": err.got,
        },
        data={
            "entry_id": entry.entry_id,
            "expected": err.expected,
            "fingerprint": err.got,
        },
    )


def _async_review_tls(hass: HomeAssistant, entry: UnasConfigEntry) -> None:
    """Clear a resolved mismatch, and flag an entry that verifies nothing.

    The insecure issue exists because entries created before pinning kept working
    unchanged on upgrade, which is deliberate — silently pinning whatever the
    console served during an upgrade would record a certificate nobody looked at.
    The user is asked once, here, and can dismiss it.
    """
    ir.async_delete_issue(hass, DOMAIN, f"{ISSUE_CERT_MISMATCH}_{entry.entry_id}")
    issue_id = f"{ISSUE_TLS_INSECURE}_{entry.entry_id}"
    if tls_mode_of(entry.data) is not TlsMode.INSECURE:
        ir.async_delete_issue(hass, DOMAIN, issue_id)
        return
    ir.async_create_issue(
        hass,
        DOMAIN,
        issue_id,
        is_fixable=True,
        severity=ir.IssueSeverity.WARNING,
        translation_key=ISSUE_TLS_INSECURE,
        translation_placeholders={"host": entry.data[CONF_HOST]},
        data={"entry_id": entry.entry_id},
    )
