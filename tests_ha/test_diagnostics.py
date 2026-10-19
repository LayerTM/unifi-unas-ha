"""Diagnostics redaction tests."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

from custom_components.unifi_unas_rest.diagnostics import (
    async_get_config_entry_diagnostics,
)
from homeassistant.const import CONF_API_KEY
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry


async def test_diagnostics_redacts_secrets(
    hass: HomeAssistant, mock_aiounas: AsyncMock, config_entry: MockConfigEntry
) -> None:
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    diag = await async_get_config_entry_diagnostics(hass, config_entry)

    assert diag["entry"]["data"][CONF_API_KEY] == "**REDACTED**"
    assert diag["capabilities"]["shares"] is True
    assert diag["device_info"]["firmware_version"] == "5.1.19"
    assert diag["share_count"] == 2
    for disk in diag["storage"]["disks"]:
        assert disk["serial"] == "**REDACTED**"
        assert disk["pool_id"] == "**REDACTED**"
        assert disk["temperature"] in (47, 49)  # non-secret data preserved


async def test_diagnostics_carries_no_identifier_of_the_console_or_its_drives(
    hass: HomeAssistant, mock_aiounas: AsyncMock, config_entry: MockConfigEntry
) -> None:
    """The whole report, searched for every value that identifies a person's NAS.

    Checking the keys that are redacted would pass for a field that is not; this
    looks for the values wherever they ended up.
    """
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    coordinator = config_entry.runtime_data.coordinator
    storage = coordinator.data.storage

    report = json.dumps(await async_get_config_entry_diagnostics(hass, config_entry), default=str)

    sensitive = {
        "host": config_entry.data["host"],
        "api key": config_entry.data[CONF_API_KEY],
        "console MAC": config_entry.unique_id,
        "title": config_entry.title,
        **{f"serial of bay {d.slot}": d.serial for d in storage.disks if d.serial},
        **{f"pool id {p.id}": p.id for p in storage.pools if p.id},
    }
    assert all(sensitive.values()), "a canary value is empty, so it proves nothing"
    leaked = [name for name, value in sensitive.items() if value in report]
    assert leaked == []
