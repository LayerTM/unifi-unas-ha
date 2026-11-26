"""Backup readings: the Drive backup task count and the console's auto-backup setting."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from custom_components.unifi_unas_rest.aiounas import (
    Capabilities,
    ConsoleBackup,
    SystemReadings,
    UnasApiError,
    UnasCapabilityError,
)
from custom_components.unifi_unas_rest.const import DOMAIN
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant.common import MockConfigEntry


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


def _entity_id(hass: HomeAssistant, domain: str, key: str) -> str | None:
    return er.async_get(hass).async_get_entity_id(domain, DOMAIN, f"AABBCC000001_{key}")


def _set_backup(client: AsyncMock, backup: ConsoleBackup) -> None:
    current = client.get_system_readings.return_value
    client.get_system_readings.return_value = SystemReadings(
        update_info=current.update_info, console_backup=backup
    )


def _caps(**overrides: bool) -> Capabilities:
    base = dict(
        storage=True,
        device_info=True,
        network_io=True,
        shares=True,
        users=True,
        updates=True,
        notifications=True,
        logs=True,
        storage_io=True,
        backup_tasks=True,
        console_backup=True,
    )
    return Capabilities(**{**base, **overrides})


async def test_backup_readings_are_diagnostic_and_carry_the_values(
    hass: HomeAssistant, mock_aiounas: AsyncMock, config_entry: MockConfigEntry
) -> None:
    await _setup(hass, config_entry)
    registry = er.async_get(hass)

    tasks = _entity_id(hass, "sensor", "backup_tasks")
    auto = _entity_id(hass, "binary_sensor", "console_auto_backup")
    frequency = _entity_id(hass, "sensor", "console_backup_frequency")
    assert tasks and auto and frequency
    for entity_id in (tasks, auto, frequency):
        entry = registry.async_get(entity_id)
        assert entry.entity_category is not None
        assert entry.disabled_by is None

    assert hass.states.get(tasks).state == "3"
    assert hass.states.get(auto).state == STATE_ON
    assert hass.states.get(frequency).state == "weekly"
    assert hass.states.get(frequency).attributes["options"] == ["daily", "weekly", "monthly"]


async def test_auto_backup_off_reads_off(
    hass: HomeAssistant, mock_aiounas: AsyncMock, config_entry: MockConfigEntry
) -> None:
    _set_backup(mock_aiounas, ConsoleBackup(enabled=False, frequency="daily"))
    await _setup(hass, config_entry)
    assert (
        hass.states.get(_entity_id(hass, "binary_sensor", "console_auto_backup")).state == STATE_OFF
    )
    assert hass.states.get(_entity_id(hass, "sensor", "console_backup_frequency")).state == "daily"


async def test_unknown_frequency_is_no_value_not_an_error(
    hass: HomeAssistant, mock_aiounas: AsyncMock, config_entry: MockConfigEntry
) -> None:
    """A schedule word this release does not know must not break the enum sensor."""
    _set_backup(mock_aiounas, ConsoleBackup(enabled=True, frequency="hourly"))
    await _setup(hass, config_entry)
    assert config_entry.state is ConfigEntryState.LOADED
    state = hass.states.get(_entity_id(hass, "sensor", "console_backup_frequency"))
    assert state.state == STATE_UNKNOWN


async def test_readings_absent_without_capability(
    hass: HomeAssistant, mock_aiounas: AsyncMock, config_entry: MockConfigEntry
) -> None:
    """The endpoints refuse (403): no entities, the entry still loads, nothing is fetched."""
    caps = _caps(backup_tasks=False, console_backup=False, updates=False)
    with patch("custom_components.unifi_unas_rest.probe", AsyncMock(return_value=caps)):
        await _setup(hass, config_entry)
    assert config_entry.state is ConfigEntryState.LOADED
    assert _entity_id(hass, "sensor", "backup_tasks") is None
    assert _entity_id(hass, "binary_sensor", "console_auto_backup") is None
    assert _entity_id(hass, "sensor", "console_backup_frequency") is None
    mock_aiounas.get_backup_task_count.assert_not_called()
    mock_aiounas.get_system_readings.assert_not_called()


async def test_a_refusal_after_setup_is_unavailable_and_never_a_reauth(
    hass: HomeAssistant, mock_aiounas: AsyncMock, config_entry: MockConfigEntry
) -> None:
    """A refusal on the task lists hides that sensor only; the entry is not torn down."""
    mock_aiounas.get_backup_task_count.side_effect = UnasCapabilityError("refused")
    await _setup(hass, config_entry)
    assert config_entry.state is ConfigEntryState.LOADED
    assert hass.states.get(_entity_id(hass, "sensor", "backup_tasks")).state == STATE_UNAVAILABLE
    assert hass.states.get(_entity_id(hass, "sensor", "storage_usage")).state != STATE_UNKNOWN

    mock_aiounas.get_backup_task_count.side_effect = UnasApiError("gone", status=404)
    await config_entry.runtime_data.coordinator.async_refresh()
    assert config_entry.state is ConfigEntryState.LOADED
    assert not list(hass.config_entries.flow.async_progress())


async def test_system_payload_is_read_once_per_poll(
    hass: HomeAssistant, mock_aiounas: AsyncMock, config_entry: MockConfigEntry
) -> None:
    """Update info and the console backup setting come from the same payload."""
    await _setup(hass, config_entry)
    mock_aiounas.get_system_readings.reset_mock()
    await config_entry.runtime_data.coordinator.async_refresh()
    assert mock_aiounas.get_system_readings.await_count == 1
    mock_aiounas.get_update_info.assert_not_called()
    mock_aiounas.get_console_backup.assert_not_called()
