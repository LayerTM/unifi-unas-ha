"""Setup, unload, and coordinator-failure tests."""

from __future__ import annotations

from unittest.mock import AsyncMock

from custom_components.unifi_unas_rest.aiounas import UnasAuthError, UnasConnectionError
from custom_components.unifi_unas_rest.const import DOMAIN
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry


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
    # 16 aggregate + 2x5 disk + 1x5 pool sensors + connectivity + storage_problem
    # + 2x disk_problem
    assert len(entries) >= 30

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


async def test_per_pool_sensors(
    hass: HomeAssistant, mock_aiounas: AsyncMock, config_entry: MockConfigEntry
) -> None:
    await _setup(hass, config_entry)
    registry = er.async_get(hass)
    # Pool sub-devices are keyed on the stable pool id (from the fixture).
    pool = "00000000-0000-4000-8000-000000000001"

    def state_of(key: str) -> str | None:
        eid = registry.async_get_entity_id("sensor", DOMAIN, f"AABBCC000001_pool{pool}_{key}")
        assert eid, key
        return hass.states.get(eid).state

    assert state_of("raid_level") == "raid1"
    assert state_of("status") == "fullyOperational"
    assert state_of("usage") == "37.1"
    # capacity + used exist as their own entities too
    assert registry.async_get_entity_id("sensor", DOMAIN, f"AABBCC000001_pool{pool}_capacity")
    assert registry.async_get_entity_id("sensor", DOMAIN, f"AABBCC000001_pool{pool}_used")


async def test_disk_io_and_scrub_sensors(
    hass: HomeAssistant, mock_aiounas: AsyncMock, config_entry: MockConfigEntry
) -> None:
    await _setup(hass, config_entry)
    registry = er.async_get(hass)
    pool = "00000000-0000-4000-8000-000000000001"

    def state(key: str) -> str | None:
        eid = registry.async_get_entity_id("sensor", DOMAIN, f"AABBCC000001_{key}")
        assert eid, key
        return hass.states.get(eid).state

    assert state("disk1_read_rate") == "1536"
    assert state("disk1_write_rate") == "768"
    assert state(f"pool{pool}_scrubbing") == "idle"


async def test_link_speed_and_last_boot(
    hass: HomeAssistant, mock_aiounas: AsyncMock, config_entry: MockConfigEntry
) -> None:
    await _setup(hass, config_entry)
    registry = er.async_get(hass)

    def state(key: str) -> str | None:
        eid = registry.async_get_entity_id("sensor", DOMAIN, f"AABBCC000001_{key}")
        assert eid, key
        return hass.states.get(eid).state

    assert state("link_speed") == "2.5 GbE"
    assert state("last_boot").startswith("2026-06-18")  # from fixture startupTime


async def test_user_count_sensor(
    hass: HomeAssistant, mock_aiounas: AsyncMock, config_entry: MockConfigEntry
) -> None:
    await _setup(hass, config_entry)
    registry = er.async_get(hass)
    eid = registry.async_get_entity_id("sensor", DOMAIN, "AABBCC000001_user_count")
    assert eid
    assert hass.states.get(eid).state == "6"


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
