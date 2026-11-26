"""Binary sensor platform for the UniFi UNAS integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import UnasConfigEntry
from .aiounas import Disk, Pool, Share
from .coordinator import Read, UnasData, UnasDataUpdateCoordinator
from .entity import (
    UnasDiskEntity,
    UnasEntity,
    UnasPoolEntity,
    UnasShareEntity,
    add_new_entities,
)


@dataclass(frozen=True, kw_only=True)
class UnasBinaryDescription(BinarySensorEntityDescription):
    value_fn: Callable[[UnasData], bool | None]
    read: Read | None = None


@dataclass(frozen=True, kw_only=True)
class UnasDiskBinaryDescription(BinarySensorEntityDescription):
    value_fn: Callable[[Disk], bool]


@dataclass(frozen=True, kw_only=True)
class UnasPoolBinaryDescription(BinarySensorEntityDescription):
    value_fn: Callable[[Pool], bool]


@dataclass(frozen=True, kw_only=True)
class UnasShareBinaryDescription(BinarySensorEntityDescription):
    value_fn: Callable[[Share], bool]


def _has_storage_problem(data: UnasData) -> bool:
    pools = data.storage.pools
    return any(p.has_problem for p in pools) or data.storage.at_risk_disk_count > 0


BINARY_SENSORS: tuple[UnasBinaryDescription, ...] = (
    UnasBinaryDescription(
        key="storage_problem",
        translation_key="storage_problem",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=_has_storage_problem,
    ),
)

DISK_BINARY_SENSORS: tuple[UnasDiskBinaryDescription, ...] = (
    UnasDiskBinaryDescription(
        key="problem",
        translation_key="disk_problem",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=lambda disk: disk.is_at_risk,
    ),
)

POOL_BINARY_SENSORS: tuple[UnasPoolBinaryDescription, ...] = (
    UnasPoolBinaryDescription(
        key="at_risk",
        translation_key="pool_at_risk",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=lambda p: p.is_at_risk,
    ),
    UnasPoolBinaryDescription(
        key="filesystem_issue",
        translation_key="pool_filesystem_issue",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=lambda p: p.has_filesystem_issue,
    ),
    UnasPoolBinaryDescription(
        key="scrubbing_scheduled",
        translation_key="pool_scrubbing_scheduled",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda p: p.scrubbing_scheduled,
    ),
)

SHARE_BINARY_SENSORS: tuple[UnasShareBinaryDescription, ...] = (
    UnasShareBinaryDescription(
        key="snapshot",
        translation_key="share_snapshot",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.snapshot_enabled,
    ),
    UnasShareBinaryDescription(
        key="backup",
        translation_key="share_backup",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.remote_backup_enabled,
    ),
)


# Session-only. Whether the console backs itself up on a schedule (a setting).
CONSOLE_AUTO_BACKUP = UnasBinaryDescription(
    key="console_auto_backup",
    translation_key="console_auto_backup",
    read=Read.SYSTEM,
    entity_category=EntityCategory.DIAGNOSTIC,
    value_fn=lambda d: d.console_backup.enabled if d.console_backup else None,
)


PARALLEL_UPDATES = 0  # read-only; all data comes from the shared coordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: UnasConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up UNAS binary sensors from a config entry."""
    coordinator = entry.runtime_data.coordinator
    aggregate: list[BinarySensorEntity] = [UnasConnectivity(coordinator)]
    aggregate.extend(UnasBinarySensor(coordinator, d) for d in BINARY_SENSORS)
    if coordinator.capabilities.console_backup:
        aggregate.append(UnasBinarySensor(coordinator, CONSOLE_AUTO_BACKUP))
    async_add_entities(aggregate)

    def _pool(key: str) -> Pool:
        return next(p for p in coordinator.data.storage.pools if p.key == key)

    def _share(key: str) -> Share:
        return next(s for s in (coordinator.data.shares or []) if s.id == key)

    syncers = [
        add_new_entities(
            async_add_entities,
            set(),
            lambda: [d.slot for d in coordinator.data.storage.disks],
            lambda slot: [UnasDiskBinarySensor(coordinator, slot, d) for d in DISK_BINARY_SENSORS],
        ),
        add_new_entities(
            async_add_entities,
            set(),
            lambda: [p.key for p in coordinator.data.storage.pools],
            lambda key: [
                UnasPoolBinarySensor(coordinator, _pool(key), d) for d in POOL_BINARY_SENSORS
            ],
        ),
        add_new_entities(
            async_add_entities,
            set(),
            lambda: [s.id for s in (coordinator.data.shares or [])],
            lambda key: [
                UnasShareBinarySensor(coordinator, _share(key), d) for d in SHARE_BINARY_SENSORS
            ],
        ),
    ]
    for sync in syncers:
        sync()
        entry.async_on_unload(coordinator.async_add_listener(sync))


class UnasConnectivity(UnasEntity, BinarySensorEntity):
    """Reports OFF (not unavailable) when polling fails."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "device_online"

    def __init__(self, coordinator: UnasDataUpdateCoordinator) -> None:
        super().__init__(coordinator, "device_online")

    @property
    def available(self) -> bool:
        return True

    @property
    def is_on(self) -> bool:
        return self.coordinator.last_update_success


class UnasBinarySensor(UnasEntity, BinarySensorEntity):
    entity_description: UnasBinaryDescription

    def __init__(
        self, coordinator: UnasDataUpdateCoordinator, description: UnasBinaryDescription
    ) -> None:
        super().__init__(coordinator, description.key, description.read)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        return self.entity_description.value_fn(self.coordinator.data)


class UnasDiskBinarySensor(UnasDiskEntity, BinarySensorEntity):
    entity_description: UnasDiskBinaryDescription

    def __init__(
        self,
        coordinator: UnasDataUpdateCoordinator,
        slot: str,
        description: UnasDiskBinaryDescription,
    ) -> None:
        super().__init__(coordinator, slot, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        disk = self.disk
        return self.entity_description.value_fn(disk) if disk is not None else None


class UnasPoolBinarySensor(UnasPoolEntity, BinarySensorEntity):
    entity_description: UnasPoolBinaryDescription

    def __init__(
        self,
        coordinator: UnasDataUpdateCoordinator,
        pool: Pool,
        description: UnasPoolBinaryDescription,
    ) -> None:
        super().__init__(coordinator, pool, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        pool = self.pool
        return self.entity_description.value_fn(pool) if pool is not None else None


class UnasShareBinarySensor(UnasShareEntity, BinarySensorEntity):
    entity_description: UnasShareBinaryDescription

    def __init__(
        self,
        coordinator: UnasDataUpdateCoordinator,
        share: Share,
        description: UnasShareBinaryDescription,
    ) -> None:
        super().__init__(coordinator, share, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        share = self.share
        return self.entity_description.value_fn(share) if share is not None else None
