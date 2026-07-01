"""Setup, unload, and coordinator-failure tests."""

from __future__ import annotations

from unittest.mock import AsyncMock

from custom_components.unifi_unas_rest.const import DOMAIN
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from aiounas import UnasAuthError, UnasConnectionError


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_setup_creates_entities(
    hass: HomeAssistant, mock_aiounas: AsyncMock, config_entry: MockConfigEntry
) -> None:
    await _setup(hass, config_entry)
    assert config_entry.state is ConfigEntryState.LOADED

    registry = er.async_get(hass)
    entries = er.async_entries_for_config_entry(registry, config_entry.entry_id)
    # 16 aggregate + 2x5 disk sensors + connectivity + storage_problem + 2x disk_problem
    assert len(entries) >= 25

    def state_of(platform: str, key: str) -> str | None:
        eid = registry.async_get_entity_id(platform, DOMAIN, f"AABBCC000001_{key}")
        assert eid, key
        return hass.states.get(eid).state

    assert state_of("sensor", "storage_usage") == "37.1"
    assert state_of("sensor", "cpu_temperature") == "66.3"
    assert state_of("sensor", "raid_level") == "raid1"
    assert state_of("sensor", "disk1_temperature") == "47"
    assert state_of("binary_sensor", "disk1_problem") == "off"
    assert state_of("binary_sensor", "storage_problem") == "off"
    assert state_of("binary_sensor", "device_online") == "on"


async def test_unload(
    hass: HomeAssistant, mock_aiounas: AsyncMock, config_entry: MockConfigEntry
) -> None:
    await _setup(hass, config_entry)
    assert await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.NOT_LOADED


async def test_auth_failure_sets_error(
    hass: HomeAssistant, mock_aiounas: AsyncMock, config_entry: MockConfigEntry
) -> None:
    mock_aiounas.async_prepare = AsyncMock(side_effect=UnasAuthError("bad"))
    config_entry.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.SETUP_ERROR


async def test_connection_error_retries(
    hass: HomeAssistant, mock_aiounas: AsyncMock, config_entry: MockConfigEntry
) -> None:
    mock_aiounas.async_prepare = AsyncMock(side_effect=UnasConnectionError("down"))
    config_entry.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.SETUP_RETRY
