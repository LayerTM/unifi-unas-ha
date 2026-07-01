"""Diagnostics redaction tests."""

from __future__ import annotations

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
