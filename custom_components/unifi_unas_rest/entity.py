"""Base entities for the UniFi UNAS integration."""

from __future__ import annotations

from collections.abc import Callable, Iterable

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
from .coordinator import UnasDataUpdateCoordinator


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


class UnasEntity(CoordinatorEntity[UnasDataUpdateCoordinator]):
    """Base entity attached to the UNAS hub device."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: UnasDataUpdateCoordinator, key: str) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        assert entry is not None
        self._attr_unique_id = f"{entry.unique_id}_{key}"
        info = coordinator.data.device_info
        host = entry.data[CONF_HOST]
        port = entry.data.get(CONF_PORT, DEFAULT_PORT)
        config_url = f"https://{host}" if port == DEFAULT_PORT else f"https://{host}:{port}"
        connections: set[tuple[str, str]] = set()
        if entry.unique_id:
            connections = {(CONNECTION_NETWORK_MAC, format_mac(entry.unique_id))}
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            connections=connections,
            manufacturer=MANUFACTURER,
            name=info.name or "UNAS",
            model=info.model or None,
            sw_version=info.firmware_version or None,
            configuration_url=config_url,
        )


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
        vendor = disk.model.split()[0] if disk and disk.model else MANUFACTURER
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{entry.entry_id}_disk{slot}")},
            via_device=(DOMAIN, entry.entry_id),
            manufacturer=vendor,
            model=disk.model if disk else None,
            serial_number=disk.serial if disk else None,
            name=f"Disk {slot}",
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
        # Identity uses the stable pool id; `number` can default to 0 on firmware
        # that omits the field, which would collide across multiple pools.
        self._pool_key = pool.id or str(pool.number)
        entry = coordinator.config_entry
        assert entry is not None
        self._attr_unique_id = f"{entry.unique_id}_pool{self._pool_key}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{entry.entry_id}_pool{self._pool_key}")},
            via_device=(DOMAIN, entry.entry_id),
            manufacturer=MANUFACTURER,
            model="Storage pool",
            name=f"Pool {pool.number}",
        )

    @property
    def pool(self) -> Pool | None:
        """Return the current model for this pool, if present."""
        return next(
            (
                p
                for p in self.coordinator.data.storage.pools
                if (p.id or str(p.number)) == self._pool_key
            ),
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
            via_device=(DOMAIN, entry.entry_id),
            manufacturer=MANUFACTURER,
            model="Shared drive",
            name=share.name or f"Share {share.id}",
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
