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

from aiounas import Disk

from . import UnasConfigEntry
from .coordinator import UnasData, UnasDataUpdateCoordinator
from .entity import UnasDiskEntity, UnasEntity


@dataclass(frozen=True, kw_only=True)
class UnasBinaryDescription(BinarySensorEntityDescription):
    value_fn: Callable[[UnasData], bool]


@dataclass(frozen=True, kw_only=True)
class UnasDiskBinaryDescription(BinarySensorEntityDescription):
    value_fn: Callable[[Disk], bool]


def _has_storage_problem(data: UnasData) -> bool:
    pools = data.storage.pools
    return any(p.status != "fullyOperational" for p in pools) or data.storage.at_risk_disk_count > 0


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
        value_fn=lambda disk: not disk.is_healthy,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: UnasConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up UNAS binary sensors from a config entry."""
    coordinator = entry.runtime_data
    entities: list[BinarySensorEntity] = [UnasConnectivity(coordinator)]
    entities.extend(UnasBinarySensor(coordinator, d) for d in BINARY_SENSORS)
    for disk in coordinator.data.storage.disks:
        entities.extend(
            UnasDiskBinarySensor(coordinator, disk.slot, d) for d in DISK_BINARY_SENSORS
        )
    async_add_entities(entities)


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
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool:
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
