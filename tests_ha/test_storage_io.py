"""System-wide storage throughput sensors."""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from custom_components.unifi_unas_rest.aiounas import (
    Capabilities,
    UnasApiError,
    UnasCapabilityError,
    probe,
)
from custom_components.unifi_unas_rest.const import DOMAIN
from homeassistant.const import STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

# The fixture's bucket ends at this instant and is 300 s long, so the next one
# completes at WINDOW_END + 300.
WINDOW_END = 1791193500
INTERVAL = 300


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


def _entity_id(hass: HomeAssistant, key: str) -> str | None:
    return er.async_get(hass).async_get_entity_id("sensor", DOMAIN, f"AABBCC000001_{key}")


@pytest.fixture
def clock() -> Iterator[MagicMock]:
    """The coordinator's wall clock, set inside the fixture's current bucket."""
    fake = MagicMock()
    fake.time.return_value = WINDOW_END + 60
    with patch("custom_components.unifi_unas_rest.coordinator.time", fake):
        yield fake


async def test_rates_are_enabled_and_shown_in_mib_per_second(
    hass: HomeAssistant, mock_aiounas: AsyncMock, config_entry: MockConfigEntry, clock: MagicMock
) -> None:
    await _setup(hass, config_entry)
    registry = er.async_get(hass)
    for key, kib_per_s in (
        ("storage_read_rate", 31.147149769341972),
        ("storage_write_rate", 547.8613425728477),
    ):
        entity_id = _entity_id(hass, key)
        assert entity_id, key
        assert registry.async_get(entity_id).disabled_by is None
        state = hass.states.get(entity_id)
        assert state.attributes["unit_of_measurement"] == "MiB/s"
        assert float(state.state) == pytest.approx(kib_per_s / 1024)


async def test_rates_absent_without_capability(
    hass: HomeAssistant, mock_aiounas: AsyncMock, config_entry: MockConfigEntry, clock: MagicMock
) -> None:
    caps = Capabilities(
        storage=True,
        device_info=True,
        network_io=True,
        shares=True,
        users=True,
        updates=True,
        notifications=True,
        logs=True,
        storage_io=False,
    )
    with patch("custom_components.unifi_unas_rest.probe", AsyncMock(return_value=caps)):
        await _setup(hass, config_entry)
    assert _entity_id(hass, "storage_read_rate") is None
    assert _entity_id(hass, "storage_write_rate") is None
    mock_aiounas.get_storage_io.assert_not_called()


async def test_fetched_once_per_completed_bucket(
    hass: HomeAssistant, mock_aiounas: AsyncMock, config_entry: MockConfigEntry, clock: MagicMock
) -> None:
    await _setup(hass, config_entry)
    coordinator = config_entry.runtime_data.coordinator
    assert mock_aiounas.get_storage_io.await_count == 1

    # Still inside the bucket after the reported one: the console has nothing newer.
    await coordinator.async_refresh()
    assert mock_aiounas.get_storage_io.await_count == 1
    assert coordinator.data.storage_io is not None

    # The next bucket has completed: ask again.
    clock.time.return_value = WINDOW_END + INTERVAL
    await coordinator.async_refresh()
    assert mock_aiounas.get_storage_io.await_count == 2


async def test_refused_read_is_unknown_and_retried(
    hass: HomeAssistant, mock_aiounas: AsyncMock, config_entry: MockConfigEntry, clock: MagicMock
) -> None:
    mock_aiounas.get_storage_io.side_effect = UnasCapabilityError("refused")
    await _setup(hass, config_entry)
    entity_id = _entity_id(hass, "storage_write_rate")
    assert entity_id
    assert hass.states.get(entity_id).state == STATE_UNKNOWN
    # Core sensors are unaffected by the failed supplementary read.
    assert hass.states.get(_entity_id(hass, "storage_usage")).state != STATE_UNKNOWN

    # A failure is not cached: the next cycle asks again.
    await config_entry.runtime_data.coordinator.async_refresh()
    assert mock_aiounas.get_storage_io.await_count == 2


async def test_firmware_without_the_endpoint_still_sets_up(
    hass: HomeAssistant, mock_aiounas: AsyncMock, config_entry: MockConfigEntry, clock: MagicMock
) -> None:
    """A 404 on the throughput read leaves it out; the entry itself loads."""
    mock_aiounas.get_storage_io.side_effect = UnasApiError("not found", status=404)
    with patch("custom_components.unifi_unas_rest.probe", probe):  # the real probe
        await _setup(hass, config_entry)
    assert config_entry.runtime_data.coordinator.capabilities.storage_io is False
    assert _entity_id(hass, "storage_read_rate") is None
    assert _entity_id(hass, "storage_usage")
