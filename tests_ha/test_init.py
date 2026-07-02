"""Setup, unload, and coordinator-failure tests."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from custom_components.unifi_unas_rest.aiounas import (
    Capabilities,
    UnasAuthError,
    UnasConnectionError,
)
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


async def test_applications_and_event_sensors(
    hass: HomeAssistant, mock_aiounas: AsyncMock, config_entry: MockConfigEntry
) -> None:
    await _setup(hass, config_entry)
    registry = er.async_get(hass)

    def entity(key: str):
        eid = registry.async_get_entity_id("sensor", DOMAIN, f"AABBCC000001_{key}")
        assert eid, key
        return hass.states.get(eid)

    apps = entity("applications")
    assert apps.state == "2"
    assert apps.attributes["drive"] == "4.3.6"
    assert apps.attributes["users"] == "1.13.6"

    events = entity("recent_events")
    assert events.state == "4"
    assert events.attributes["backups"] == 2
    assert events.attributes["admins"] == 1

    assert entity("last_event").state.startswith("2026-07-02")
    assert entity("log_entries").state == "2"


async def test_supplementary_sensors_absent_without_capability(
    hass: HomeAssistant, mock_aiounas: AsyncMock, config_entry: MockConfigEntry
) -> None:
    # When the probe reports no notifications/logs scope, those sensors are not created.
    caps = Capabilities(
        storage=True,
        device_info=True,
        network_io=True,
        shares=True,
        users=True,
        updates=True,
        notifications=False,
        logs=False,
    )
    with patch("custom_components.unifi_unas_rest.probe", AsyncMock(return_value=caps)):
        await _setup(hass, config_entry)

    registry = er.async_get(hass)
    assert registry.async_get_entity_id("sensor", DOMAIN, "AABBCC000001_recent_events") is None
    assert registry.async_get_entity_id("sensor", DOMAIN, "AABBCC000001_last_event") is None
    assert registry.async_get_entity_id("sensor", DOMAIN, "AABBCC000001_log_entries") is None
    # applications is gated on the (still-present) updates capability
    assert registry.async_get_entity_id("sensor", DOMAIN, "AABBCC000001_applications")


async def test_per_share_entities(
    hass: HomeAssistant, mock_aiounas: AsyncMock, config_entry: MockConfigEntry
) -> None:
    await _setup(hass, config_entry)
    registry = er.async_get(hass)
    s1 = "00000000-0000-4000-8000-000000000011"  # Share1 in the fixture

    def sensor(key: str) -> str | None:
        eid = registry.async_get_entity_id("sensor", DOMAIN, f"AABBCC000001_share{s1}_{key}")
        assert eid, key
        return hass.states.get(eid).state

    def binary(key: str) -> str | None:
        eid = registry.async_get_entity_id("binary_sensor", DOMAIN, f"AABBCC000001_share{s1}_{key}")
        assert eid, key
        return hass.states.get(eid).state

    assert sensor("members") == "4"
    assert sensor("encryption") == "unencrypted"
    assert binary("snapshot") == "on"  # Share1 has snapshots enabled
    assert binary("backup") == "off"
    # usage + quota entities exist (quota is unlimited -> unknown state, still an entity)
    assert registry.async_get_entity_id("sensor", DOMAIN, f"AABBCC000001_share{s1}_usage")
    assert registry.async_get_entity_id("sensor", DOMAIN, f"AABBCC000001_share{s1}_quota")


async def test_update_entities(
    hass: HomeAssistant, mock_aiounas: AsyncMock, config_entry: MockConfigEntry
) -> None:
    await _setup(hass, config_entry)
    registry = er.async_get(hass)
    eid = registry.async_get_entity_id("update", DOMAIN, "AABBCC000001_unifi_os_update")
    assert eid
    st = hass.states.get(eid)
    assert st.attributes["installed_version"] == "5.1.19"
    assert st.attributes["latest_version"] == "5.2.0"
    assert st.state == "on"  # update available (installed != latest)
    assert registry.async_get_entity_id("update", DOMAIN, "AABBCC000001_drive_update")


async def test_capability_error_degrades_gracefully(
    hass: HomeAssistant, mock_aiounas: AsyncMock, config_entry: MockConfigEntry
) -> None:
    from custom_components.unifi_unas_rest.aiounas import UnasCapabilityError

    # A transient scope denial on a supplementary fetch must NOT fail the update.
    mock_aiounas.get_user_count = AsyncMock(side_effect=UnasCapabilityError("forbidden"))
    await _setup(hass, config_entry)
    assert config_entry.state is ConfigEntryState.LOADED

    registry = er.async_get(hass)
    # core sensors keep working; only the account-count degraded
    assert registry.async_get_entity_id("sensor", DOMAIN, "AABBCC000001_storage_usage")


async def test_no_update_entities_without_capability(
    hass: HomeAssistant, mock_aiounas: AsyncMock, config_entry: MockConfigEntry
) -> None:
    caps = Capabilities(
        storage=True,
        device_info=True,
        network_io=True,
        shares=True,
        users=True,
        updates=False,
        notifications=True,
        logs=True,
    )
    with patch("custom_components.unifi_unas_rest.probe", AsyncMock(return_value=caps)):
        await _setup(hass, config_entry)
    registry = er.async_get(hass)
    assert registry.async_get_entity_id("update", DOMAIN, "AABBCC000001_unifi_os_update") is None


async def test_coordinator_auth_error_sets_setup_error(
    hass: HomeAssistant, mock_aiounas: AsyncMock, config_entry: MockConfigEntry
) -> None:
    # An auth error during the coordinator's data fetch -> ConfigEntryAuthFailed.
    mock_aiounas.get_storage = AsyncMock(side_effect=UnasAuthError("expired"))
    config_entry.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.SETUP_ERROR


async def test_coordinator_connection_error_retries(
    hass: HomeAssistant, mock_aiounas: AsyncMock, config_entry: MockConfigEntry
) -> None:
    # A connection error during the fetch -> UpdateFailed -> setup retry.
    mock_aiounas.get_storage = AsyncMock(side_effect=UnasConnectionError("down"))
    config_entry.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.SETUP_RETRY


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
