"""Diagnostics support for the UniFi UNAS integration."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_API_KEY, CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from . import UnasConfigEntry

CONFIG_REDACT = {CONF_API_KEY, CONF_PASSWORD, CONF_USERNAME, CONF_HOST}
DATA_REDACT = {"serial", "id", "pool_id", "raid_group_id"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: UnasConfigEntry
) -> dict[str, Any]:
    """Return redacted diagnostics for a config entry."""
    coordinator = entry.runtime_data
    data = coordinator.data
    caps = coordinator.capabilities
    storage = {
        "usage_percent": data.storage.usage_percent,
        "total_capacity": data.storage.total_capacity,
        "total_usage": data.storage.total_usage,
        "pools": [asdict(pool) for pool in data.storage.pools],
        "disks": [asdict(disk) for disk in data.storage.disks],
    }
    return {
        "entry": {
            "data": async_redact_data(dict(entry.data), CONFIG_REDACT),
            "options": dict(entry.options),
            "unique_id_set": entry.unique_id is not None,
        },
        "capabilities": {
            "storage": caps.storage,
            "device_info": caps.device_info,
            "network_io": caps.network_io,
            "shares": caps.shares,
        },
        "device_info": {
            "model": data.device_info.model,
            "firmware_version": data.device_info.firmware_version,
            "drive_version": data.device_info.version,
            "cpu_percent": data.device_info.cpu_percent,
            "cpu_temperature": data.device_info.cpu_temperature,
            "memory_percent": data.device_info.memory_percent,
        },
        "storage": async_redact_data(storage, DATA_REDACT),
        "share_count": len(data.shares) if data.shares is not None else None,
    }
