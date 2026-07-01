"""Sensor platform for the UniFi UNAS integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

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
from .aiounas import Disk
from .coordinator import UnasData, UnasDataUpdateCoordinator
from .entity import UnasDiskEntity, UnasEntity


@dataclass(frozen=True, kw_only=True)
class UnasSensorDescription(SensorEntityDescription):
    """Aggregate/system sensor bound to a UnasData accessor."""

    value_fn: Callable[[UnasData], StateType]


@dataclass(frozen=True, kw_only=True)
class UnasDiskSensorDescription(SensorEntityDescription):
    """Per-disk sensor bound to a Disk accessor."""

    value_fn: Callable[[Disk], StateType]


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
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: UnasConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up UNAS sensors from a config entry."""
    coordinator = entry.runtime_data.coordinator
    entities: list[SensorEntity] = [UnasSensor(coordinator, description) for description in SENSORS]
    for disk in coordinator.data.storage.disks:
        entities.extend(
            UnasDiskSensor(coordinator, disk.slot, description) for description in DISK_SENSORS
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
    def native_value(self) -> StateType:
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
