"""A disk sub-device names the drive's maker, never its part number."""

from __future__ import annotations

from dataclasses import replace
from unittest.mock import AsyncMock

import pytest
from custom_components.unifi_unas_rest.aiounas import Storage
from custom_components.unifi_unas_rest.const import DOMAIN, MANUFACTURER
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry


@pytest.mark.parametrize(
    ("model", "manufacturer"),
    [
        ("ST12000VN0008-2YS101", "Seagate"),
        ("WDC WUH722424ALE6L4", "Western Digital"),
        ("CT1000MX500SSD1", MANUFACTURER),
    ],
)
async def test_disk_manufacturer(
    hass: HomeAssistant,
    mock_aiounas: AsyncMock,
    config_entry: MockConfigEntry,
    model: str,
    manufacturer: str,
) -> None:
    storage: Storage = await mock_aiounas.get_storage()
    disks = tuple(replace(d, model=model) for d in storage.disks)
    mock_aiounas.get_storage = AsyncMock(return_value=replace(storage, disks=disks))
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    disk_id = (DOMAIN, f"{config_entry.entry_id}_disk1")
    devices = dr.async_entries_for_config_entry(dr.async_get(hass), config_entry.entry_id)
    device = next((d for d in devices if disk_id in d.identifiers), None)
    assert device is not None
    assert device.manufacturer == manufacturer
    assert device.model == model
