"""Sensor platform for the UniFi UNAS integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfDataRate,
    UnitOfInformation,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType

from . import UnasConfigEntry
from .aiounas import Disk, Pool, Share
from .coordinator import UnasData, UnasDataUpdateCoordinator
from .entity import UnasDiskEntity, UnasEntity, UnasPoolEntity, UnasShareEntity


@dataclass(frozen=True, kw_only=True)
class UnasSensorDescription(SensorEntityDescription):
    """Aggregate/system sensor bound to a UnasData accessor."""

    value_fn: Callable[[UnasData], StateType | datetime]


@dataclass(frozen=True, kw_only=True)
class UnasDiskSensorDescription(SensorEntityDescription):
    """Per-disk sensor bound to a Disk accessor."""

    value_fn: Callable[[Disk], StateType]


@dataclass(frozen=True, kw_only=True)
class UnasPoolSensorDescription(SensorEntityDescription):
    """Per-pool sensor bound to a Pool accessor."""

    value_fn: Callable[[Pool], StateType]


@dataclass(frozen=True, kw_only=True)
class UnasShareSensorDescription(SensorEntityDescription):
    """Per-share sensor bound to a Share accessor."""

    value_fn: Callable[[Share], StateType]


def _worst_pool_status(data: UnasData) -> StateType:
    pools = data.storage.pools
    if not pools:
        return None
    degraded = next((p.status for p in pools if p.status != "fullyOperational"), None)
    return degraded or pools[0].status


SENSORS: tuple[UnasSensorDescription, ...] = (
    UnasSensorDescription(
        key="storage_used",
        translation_key="storage_used",
        native_unit_of_measurement=UnitOfInformation.BYTES,
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_unit_of_measurement=UnitOfInformation.TEBIBYTES,
        suggested_display_precision=2,
        value_fn=lambda d: d.storage.total_usage,
    ),
    UnasSensorDescription(
        key="storage_total",
        translation_key="storage_total",
        native_unit_of_measurement=UnitOfInformation.BYTES,
        device_class=SensorDeviceClass.DATA_SIZE,
        suggested_unit_of_measurement=UnitOfInformation.TEBIBYTES,
        suggested_display_precision=2,
        value_fn=lambda d: d.storage.total_capacity,
    ),
    UnasSensorDescription(
        key="storage_free",
        translation_key="storage_free",
        native_unit_of_measurement=UnitOfInformation.BYTES,
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_unit_of_measurement=UnitOfInformation.TEBIBYTES,
        suggested_display_precision=2,
        value_fn=lambda d: d.storage.total_available,
    ),
    UnasSensorDescription(
        key="storage_usage",
        translation_key="storage_usage",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda d: d.storage.usage_percent,
    ),
    UnasSensorDescription(
        key="storage_status",
        translation_key="storage_status",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_worst_pool_status,
    ),
    UnasSensorDescription(
        key="raid_level",
        translation_key="raid_level",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.storage.pools[0].raid_level if d.storage.pools else None,
    ),
    UnasSensorDescription(
        key="pool_count",
        translation_key="pool_count",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: len(d.storage.pools),
    ),
    UnasSensorDescription(
        key="disks_at_risk",
        translation_key="disks_at_risk",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.storage.at_risk_disk_count,
    ),
    UnasSensorDescription(
        key="average_disk_temperature",
        translation_key="average_disk_temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.storage.average_disk_temperature,
    ),
    UnasSensorDescription(
        key="cpu_usage",
        translation_key="cpu_usage",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.device_info.cpu_percent,
    ),
    UnasSensorDescription(
        key="cpu_temperature",
        translation_key="cpu_temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.device_info.cpu_temperature,
    ),
    UnasSensorDescription(
        key="memory_usage",
        translation_key="memory_usage",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.device_info.memory_percent,
    ),
    UnasSensorDescription(
        key="network_rx",
        translation_key="network_rx",
        native_unit_of_measurement=UnitOfDataRate.KIBIBYTES_PER_SECOND,
        device_class=SensorDeviceClass.DATA_RATE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda d: d.network_io.rx_kbps,
    ),
    UnasSensorDescription(
        key="network_tx",
        translation_key="network_tx",
        native_unit_of_measurement=UnitOfDataRate.KIBIBYTES_PER_SECOND,
        device_class=SensorDeviceClass.DATA_RATE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda d: d.network_io.tx_kbps,
    ),
    UnasSensorDescription(
        key="unifi_os_version",
        translation_key="unifi_os_version",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.device_info.firmware_version or None,
    ),
    UnasSensorDescription(
        key="drive_version",
        translation_key="drive_version",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.device_info.version or None,
    ),
    UnasSensorDescription(
        key="last_boot",
        translation_key="last_boot",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.device_info.startup_time,
    ),
    UnasSensorDescription(
        key="link_speed",
        translation_key="link_speed",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.device_info.link_speed,
    ),
)

# Session-only: the number of local accounts (count only — no account PII is read).
USER_COUNT = UnasSensorDescription(
    key="user_count",
    translation_key="user_count",
    state_class=SensorStateClass.MEASUREMENT,
    entity_category=EntityCategory.DIAGNOSTIC,
    value_fn=lambda d: d.user_count,
)

DISK_SENSORS: tuple[UnasDiskSensorDescription, ...] = (
    UnasDiskSensorDescription(
        key="temperature",
        translation_key="disk_temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda disk: disk.temperature,
    ),
    UnasDiskSensorDescription(
        key="power_on_hours",
        translation_key="disk_power_on_hours",
        native_unit_of_measurement=UnitOfTime.HOURS,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda disk: disk.power_on_hours,
    ),
    UnasDiskSensorDescription(
        key="state",
        translation_key="disk_state",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda disk: disk.state or None,
    ),
    UnasDiskSensorDescription(
        key="health_score",
        translation_key="disk_health_score",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda disk: disk.health_score,
    ),
    UnasDiskSensorDescription(
        key="bad_sectors",
        translation_key="disk_bad_sectors",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda disk: disk.bad_sector_count,
    ),
    UnasDiskSensorDescription(
        key="read_rate",
        translation_key="disk_read_rate",
        native_unit_of_measurement=UnitOfDataRate.KIBIBYTES_PER_SECOND,
        device_class=SensorDeviceClass.DATA_RATE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda disk: disk.read_kbps,
    ),
    UnasDiskSensorDescription(
        key="write_rate",
        translation_key="disk_write_rate",
        native_unit_of_measurement=UnitOfDataRate.KIBIBYTES_PER_SECOND,
        device_class=SensorDeviceClass.DATA_RATE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda disk: disk.write_kbps,
    ),
)

POOL_SENSORS: tuple[UnasPoolSensorDescription, ...] = (
    UnasPoolSensorDescription(
        key="raid_level",
        translation_key="pool_raid_level",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda p: p.raid_level or None,
    ),
    UnasPoolSensorDescription(
        key="status",
        translation_key="pool_status",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda p: p.status or None,
    ),
    UnasPoolSensorDescription(
        key="usage",
        translation_key="pool_usage",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda p: p.usage_percent,
    ),
    UnasPoolSensorDescription(
        key="capacity",
        translation_key="pool_capacity",
        native_unit_of_measurement=UnitOfInformation.BYTES,
        device_class=SensorDeviceClass.DATA_SIZE,
        suggested_unit_of_measurement=UnitOfInformation.TEBIBYTES,
        suggested_display_precision=2,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda p: p.capacity,
    ),
    UnasPoolSensorDescription(
        key="used",
        translation_key="pool_used",
        native_unit_of_measurement=UnitOfInformation.BYTES,
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_unit_of_measurement=UnitOfInformation.TEBIBYTES,
        suggested_display_precision=2,
        value_fn=lambda p: p.usage,
    ),
    UnasPoolSensorDescription(
        key="scrubbing",
        translation_key="pool_scrubbing",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda p: p.scrubbing_status or None,
    ),
)

SHARE_SENSORS: tuple[UnasShareSensorDescription, ...] = (
    UnasShareSensorDescription(
        key="usage",
        translation_key="share_usage",
        native_unit_of_measurement=UnitOfInformation.BYTES,
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_unit_of_measurement=UnitOfInformation.GIBIBYTES,
        suggested_display_precision=1,
        value_fn=lambda s: s.usage,
    ),
    UnasShareSensorDescription(
        key="quota",
        translation_key="share_quota",
        native_unit_of_measurement=UnitOfInformation.BYTES,
        device_class=SensorDeviceClass.DATA_SIZE,
        suggested_unit_of_measurement=UnitOfInformation.GIBIBYTES,
        suggested_display_precision=1,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.quota_bytes,
    ),
    UnasShareSensorDescription(
        key="members",
        translation_key="share_members",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.member_count,
    ),
    UnasShareSensorDescription(
        key="encryption",
        translation_key="share_encryption",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.encryption_status or None,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: UnasConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up UNAS sensors from a config entry."""
    coordinator = entry.runtime_data.coordinator
    entities: list[SensorEntity] = [UnasSensor(coordinator, description) for description in SENSORS]
    if coordinator.capabilities.users:
        entities.append(UnasSensor(coordinator, USER_COUNT))
    for disk in coordinator.data.storage.disks:
        entities.extend(
            UnasDiskSensor(coordinator, disk.slot, description) for description in DISK_SENSORS
        )
    for pool in coordinator.data.storage.pools:
        entities.extend(
            UnasPoolSensor(coordinator, pool, description) for description in POOL_SENSORS
        )
    for share in coordinator.data.shares or []:
        entities.extend(
            UnasShareSensor(coordinator, share, description) for description in SHARE_SENSORS
        )
    async_add_entities(entities)


class UnasSensor(UnasEntity, SensorEntity):
    """An aggregate/system UNAS sensor."""

    entity_description: UnasSensorDescription

    def __init__(
        self, coordinator: UnasDataUpdateCoordinator, description: UnasSensorDescription
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> StateType | datetime:
        return self.entity_description.value_fn(self.coordinator.data)


class UnasDiskSensor(UnasDiskEntity, SensorEntity):
    """A per-disk UNAS sensor."""

    entity_description: UnasDiskSensorDescription

    def __init__(
        self,
        coordinator: UnasDataUpdateCoordinator,
        slot: str,
        description: UnasDiskSensorDescription,
    ) -> None:
        super().__init__(coordinator, slot, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> StateType:
        disk = self.disk
        return self.entity_description.value_fn(disk) if disk is not None else None


class UnasPoolSensor(UnasPoolEntity, SensorEntity):
    """A per-pool UNAS sensor."""

    entity_description: UnasPoolSensorDescription

    def __init__(
        self,
        coordinator: UnasDataUpdateCoordinator,
        pool: Pool,
        description: UnasPoolSensorDescription,
    ) -> None:
        super().__init__(coordinator, pool, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> StateType:
        pool = self.pool
        return self.entity_description.value_fn(pool) if pool is not None else None


class UnasShareSensor(UnasShareEntity, SensorEntity):
    """A per-share UNAS sensor."""

    entity_description: UnasShareSensorDescription

    def __init__(
        self,
        coordinator: UnasDataUpdateCoordinator,
        share: Share,
        description: UnasShareSensorDescription,
    ) -> None:
        super().__init__(coordinator, share, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> StateType:
        share = self.share
        return self.entity_description.value_fn(share) if share is not None else None
