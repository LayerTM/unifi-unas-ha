"""Base entities for the UniFi UNAS integration."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from aiounas import Disk

from .const import DOMAIN, MANUFACTURER
from .coordinator import UnasDataUpdateCoordinator


class UnasEntity(CoordinatorEntity[UnasDataUpdateCoordinator]):
    """Base entity attached to the UNAS hub device."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: UnasDataUpdateCoordinator, key: str) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        assert entry is not None
        self._attr_unique_id = f"{entry.unique_id}_{key}"
        info = coordinator.data.device_info
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            manufacturer=MANUFACTURER,
            name=info.name or "UNAS",
            model=info.model or None,
            sw_version=info.firmware_version or None,
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
