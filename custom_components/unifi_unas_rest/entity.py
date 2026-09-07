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


def hub_device_info(coordinator: UnasDataUpdateCoordinator) -> DeviceInfo:
    """Describe the UNAS hub device.

    One definition, used both by the hub entities and by ``async_setup_entry``,
    which registers this device before any platform loads so that every
    sub-device has a hub id to point at.
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
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        connections=connections,
        manufacturer=MANUFACTURER,
        name=info.name or "UNAS",
        model=info.model or None,
        sw_version=info.firmware_version or None,
        configuration_url=config_url,
    )


# Home Assistant 2026.8 replaced `via_device` (the hub's identifiers) with
# `via_device_id` (the hub's device-registry id) and removes the old spelling in
# 2027.8, warning about it in the log until then. Both state the same fact, so
# which one to send is asked of `DeviceInfo` itself rather than of a version
# number: that keeps the 2025.3 floor this integration supports, with nothing to
# revisit when the old key finally goes.
_ACCEPTS_VIA_DEVICE_ID = "via_device_id" in DeviceInfo.__optional_keys__


def link_to_hub(info: DeviceInfo, coordinator: UnasDataUpdateCoordinator) -> DeviceInfo:
    """Attach a sub-device to the hub device of its config entry."""
    entry = coordinator.config_entry
    assert entry is not None
    if _ACCEPTS_VIA_DEVICE_ID and (hub_id := coordinator.hub_device_id) is not None:
        info["via_device_id"] = hub_id
    else:
        info["via_device"] = (DOMAIN, entry.entry_id)  # type: ignore[typeddict-unknown-key]
    return info


class UnasEntity(CoordinatorEntity[UnasDataUpdateCoordinator]):
    """Base entity attached to the UNAS hub device."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: UnasDataUpdateCoordinator, key: str) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        assert entry is not None
        self._attr_unique_id = f"{entry.unique_id}_{key}"
        self._attr_device_info = hub_device_info(coordinator)


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
        self._attr_device_info = link_to_hub(
            DeviceInfo(
                identifiers={(DOMAIN, f"{entry.entry_id}_disk{slot}")},
                manufacturer=vendor,
                model=disk.model if disk else None,
                serial_number=disk.serial if disk else None,
                name=f"Disk {slot}",
            ),
            coordinator,
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
        self._attr_device_info = link_to_hub(
            DeviceInfo(
                identifiers={(DOMAIN, f"{entry.entry_id}_pool{self._pool_key}")},
                manufacturer=MANUFACTURER,
                model="Storage pool",
                name=f"Pool {pool.number}",
            ),
            coordinator,
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
        self._attr_device_info = link_to_hub(
            DeviceInfo(
                identifiers={(DOMAIN, f"{entry.entry_id}_share{share.id}")},
                manufacturer=MANUFACTURER,
                model="Shared drive",
                name=share.name or f"Share {share.id}",
            ),
            coordinator,
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
