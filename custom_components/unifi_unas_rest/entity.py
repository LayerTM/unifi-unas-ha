"""Base entities for the UniFi UNAS integration."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.helpers.device_registry import (
    CONNECTION_NETWORK_MAC,
    DeviceInfo,
    format_mac,
)
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .aiounas import Disk, Pool, Share
from .const import DEFAULT_PORT, DOMAIN, MANUFACTURER
from .coordinator import Read, UnasDataUpdateCoordinator


def add_new_entities(
    async_add_entities: AddConfigEntryEntitiesCallback,
    seen: set[str],
    keys: Callable[[], Iterable[str]],
    make: Callable[[str], list[Entity]],
) -> Callable[[], None]:
    """Build a sync function that adds entities for keys not yet seen.

    Call the returned function once immediately and register it via
    ``coordinator.async_add_listener`` so disks/pools/shares that appear at
    runtime get their entities without a reload (the ``dynamic-devices`` rule).
    """

    def _sync() -> None:
        fresh: list[Entity] = []
        for key in keys():
            if key not in seen:
                seen.add(key)
                fresh.extend(make(key))
        if fresh:
            async_add_entities(fresh)

    return _sync


def console_name(coordinator: UnasDataUpdateCoordinator) -> str:
    """The console's own name — the hub device's name and every sub-device's prefix.

    Entities name themselves after their device, so a sub-device named only
    "Disk 1" gave its entities no trace of which console they belong to: nothing
    to search or group by, and a second console's disks came out with the very
    same names. Each sub-device's name therefore starts with this, and this is
    defined once so the hub and its sub-devices cannot drift apart.

    Only the name the integration supplies changes. Home Assistant keeps an
    existing entity ID when a device is renamed, and a name the user gave a
    device still takes precedence.
    """
    return coordinator.data.device_info.name or "UNAS"


def hub_device_fields(coordinator: UnasDataUpdateCoordinator) -> dict[str, Any]:
    """Describe the UNAS hub device.

    One definition, used both by the hub entities and by ``async_setup_entry``,
    which registers this device before any platform loads so that every
    sub-device has a hub id to point at. These are keyword arguments rather than
    a ``DeviceInfo`` because the registry takes them as keywords, and a
    ``DeviceInfo`` must not be unpacked.
    """
    entry = coordinator.config_entry
    assert entry is not None
    info = coordinator.data.device_info
    host = entry.data[CONF_HOST]
    port = entry.data.get(CONF_PORT, DEFAULT_PORT)
    config_url = f"https://{host}" if port == DEFAULT_PORT else f"https://{host}:{port}"
    connections: set[tuple[str, str]] = set()
    if entry.unique_id:
        connections = {(CONNECTION_NETWORK_MAC, format_mac(entry.unique_id))}
    return {
        "identifiers": {(DOMAIN, entry.entry_id)},
        "connections": connections,
        "manufacturer": MANUFACTURER,
        "name": console_name(coordinator),
        "model": info.model or None,
        "sw_version": info.firmware_version or None,
        "configuration_url": config_url,
    }


# Home Assistant 2026.8 replaced `via_device` (the hub's identifiers) with
# `via_device_id` (the hub's device-registry id) and removes the old spelling in
# 2027.8, warning about it in the log until then. Both state the same fact, so
# which one to send is asked of `DeviceInfo` itself rather than of a version
# number: that keeps the 2025.8 floor this integration supports, with nothing to
# revisit when the old key finally goes. `__annotations__` is read rather than
# `__optional_keys__` because it exists on a TypedDict and on the dataclass core
# is moving `DeviceInfo` to alike; `__optional_keys__` only survives there in a
# compatibility layer.
_ACCEPTS_VIA_DEVICE_ID = "via_device_id" in DeviceInfo.__annotations__


def hub_link(coordinator: UnasDataUpdateCoordinator) -> dict[str, Any]:
    """Return the field that attaches a sub-device to its config entry's hub."""
    entry = coordinator.config_entry
    assert entry is not None
    if _ACCEPTS_VIA_DEVICE_ID and (hub_id := coordinator.hub_device_id) is not None:
        return {"via_device_id": hub_id}
    return {"via_device": (DOMAIN, entry.entry_id)}


class UnasEntity(CoordinatorEntity[UnasDataUpdateCoordinator]):
    """Base entity attached to the UNAS hub device."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: UnasDataUpdateCoordinator, key: str, read: Read | None = None
    ) -> None:
        """*read* is the one the entity depends on beyond the anchor reads."""
        super().__init__(coordinator)
        self._read = read
        entry = coordinator.config_entry
        assert entry is not None
        self._attr_unique_id = f"{entry.unique_id}_{key}"
        self._attr_device_info = DeviceInfo(**hub_device_fields(coordinator))

    @property
    def available(self) -> bool:
        return super().available and self._read not in self.coordinator.data.failed_reads


class UnasDiskEntity(CoordinatorEntity[UnasDataUpdateCoordinator]):
    """Base entity attached to a per-disk sub-device (grouped under the hub)."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: UnasDataUpdateCoordinator, slot: str, key: str) -> None:
        super().__init__(coordinator)
        self._slot = slot
        entry = coordinator.config_entry
        assert entry is not None
        self._attr_unique_id = f"{entry.unique_id}_disk{slot}_{key}"
        disk = self.disk
        vendor = (disk.vendor if disk else None) or MANUFACTURER
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{entry.entry_id}_disk{slot}")},
            manufacturer=vendor,
            model=disk.model if disk else None,
            serial_number=disk.serial if disk else None,
            name=f"{console_name(coordinator)} Disk {slot}",
            **hub_link(coordinator),
        )

    @property
    def disk(self) -> Disk | None:
        """Return the current model for this disk slot, if present."""
        return next(
            (d for d in self.coordinator.data.storage.disks if d.slot == self._slot),
            None,
        )

    @property
    def available(self) -> bool:
        return super().available and self.disk is not None


class UnasPoolEntity(CoordinatorEntity[UnasDataUpdateCoordinator]):
    """Base entity attached to a per-pool sub-device (grouped under the hub)."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: UnasDataUpdateCoordinator, pool: Pool, key: str) -> None:
        super().__init__(coordinator)
        self._pool_key = pool.key
        entry = coordinator.config_entry
        assert entry is not None
        self._attr_unique_id = f"{entry.unique_id}_pool{self._pool_key}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{entry.entry_id}_pool{self._pool_key}")},
            manufacturer=MANUFACTURER,
            model="Storage pool",
            name=f"{console_name(coordinator)} Pool {pool.number}",
            **hub_link(coordinator),
        )

    @property
    def pool(self) -> Pool | None:
        """Return the current model for this pool, if present."""
        return next(
            (p for p in self.coordinator.data.storage.pools if p.key == self._pool_key),
            None,
        )

    @property
    def available(self) -> bool:
        return super().available and self.pool is not None


class UnasShareEntity(CoordinatorEntity[UnasDataUpdateCoordinator]):
    """Base entity attached to a per-share sub-device (grouped under the hub)."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: UnasDataUpdateCoordinator, share: Share, key: str) -> None:
        super().__init__(coordinator)
        self._share_id = share.id
        entry = coordinator.config_entry
        assert entry is not None
        self._attr_unique_id = f"{entry.unique_id}_share{share.id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{entry.entry_id}_share{share.id}")},
            manufacturer=MANUFACTURER,
            model="Shared drive",
            name=f"{console_name(coordinator)} {share.name or f'Share {share.id}'}",
            **hub_link(coordinator),
        )

    @property
    def share(self) -> Share | None:
        """Return the current model for this share, if present."""
        return next(
            (s for s in (self.coordinator.data.shares or []) if s.id == self._share_id),
            None,
        )

    @property
    def available(self) -> bool:
        return super().available and self.share is not None
