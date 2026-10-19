"""A drive at risk reaches Settings -> Repairs, and leaves it when it recovers."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock

from custom_components.unifi_unas_rest.aiounas import Storage, UnasConnectionError
from custom_components.unifi_unas_rest.const import DOMAIN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry

_FX = Path(__file__).resolve().parents[1] / "tests" / "fixtures"


def _partial() -> Storage:
    return Storage.from_api(json.loads((_FX / "storage_partial.json").read_text()))


def _with_state(storage: Storage, index: int, state: str) -> Storage:
    disks = list(storage.disks)
    disks[index] = replace(disks[index], state=state)
    return replace(storage, disks=tuple(disks))


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


def _disk_issues(hass: HomeAssistant) -> dict[str, ir.IssueEntry]:
    return {
        issue_id: issue
        for (domain, issue_id), issue in ir.async_get(hass).issues.items()
        if domain == DOMAIN and issue_id.startswith("disk_at_risk_")
    }


async def test_healthy_drives_raise_nothing(
    hass: HomeAssistant, mock_aiounas: AsyncMock, config_entry: MockConfigEntry
) -> None:
    await _setup(hass, config_entry)

    assert _disk_issues(hass) == {}


async def test_a_failing_drive_raises_one_repair_naming_bay_and_model_not_serial(
    hass: HomeAssistant, mock_aiounas: AsyncMock, config_entry: MockConfigEntry
) -> None:
    storage = _with_state(_partial(), 0, "degraded")
    mock_aiounas.get_storage = AsyncMock(return_value=storage)
    await _setup(hass, config_entry)

    issues = _disk_issues(hass)
    disk = storage.disks[0]
    assert list(issues) == [f"disk_at_risk_{config_entry.entry_id}_{disk.slot}"]
    issue = next(iter(issues.values()))
    assert issue.translation_key == "disk_at_risk"
    assert issue.severity is ir.IssueSeverity.WARNING
    assert not issue.is_fixable
    placeholders = issue.translation_placeholders or {}
    assert placeholders["bay"] == disk.slot
    assert placeholders["model"] == disk.model
    assert placeholders["state"] == "degraded"
    assert disk.serial not in json.dumps(placeholders)


async def test_an_empty_bay_next_to_a_failing_drive_raises_only_for_the_drive(
    hass: HomeAssistant, mock_aiounas: AsyncMock, config_entry: MockConfigEntry
) -> None:
    """Not fully populated NAS: the empty bay is not a drive at risk."""
    storage = _with_state(_partial(), 0, "degraded")
    assert any(not d.is_present for d in storage.disks)
    mock_aiounas.get_storage = AsyncMock(return_value=storage)
    await _setup(hass, config_entry)

    assert list(_disk_issues(hass)) == [
        f"disk_at_risk_{config_entry.entry_id}_{storage.disks[0].slot}"
    ]


async def test_an_empty_bay_alone_raises_nothing(
    hass: HomeAssistant, mock_aiounas: AsyncMock, config_entry: MockConfigEntry
) -> None:
    mock_aiounas.get_storage = AsyncMock(return_value=_partial())
    await _setup(hass, config_entry)

    assert _disk_issues(hass) == {}


async def test_the_repair_is_withdrawn_when_the_drive_recovers(
    hass: HomeAssistant, mock_aiounas: AsyncMock, config_entry: MockConfigEntry
) -> None:
    healthy = _partial()
    mock_aiounas.get_storage = AsyncMock(return_value=_with_state(healthy, 0, "degraded"))
    await _setup(hass, config_entry)
    assert len(_disk_issues(hass)) == 1

    mock_aiounas.get_storage = AsyncMock(return_value=healthy)
    await config_entry.runtime_data.coordinator.async_refresh()

    assert _disk_issues(hass) == {}


async def test_a_second_drive_turning_bad_adds_a_second_repair(
    hass: HomeAssistant, mock_aiounas: AsyncMock, config_entry: MockConfigEntry
) -> None:
    base = _partial()
    mock_aiounas.get_storage = AsyncMock(return_value=_with_state(base, 0, "degraded"))
    await _setup(hass, config_entry)
    assert len(_disk_issues(hass)) == 1

    both = _with_state(_with_state(base, 0, "degraded"), 1, "failed")
    mock_aiounas.get_storage = AsyncMock(return_value=both)
    await config_entry.runtime_data.coordinator.async_refresh()

    assert len(_disk_issues(hass)) == 2


async def test_unloading_the_entry_withdraws_its_repairs(
    hass: HomeAssistant, mock_aiounas: AsyncMock, config_entry: MockConfigEntry
) -> None:
    mock_aiounas.get_storage = AsyncMock(return_value=_with_state(_partial(), 0, "degraded"))
    await _setup(hass, config_entry)
    assert len(_disk_issues(hass)) == 1

    assert await hass.config_entries.async_unload(config_entry.entry_id)

    assert _disk_issues(hass) == {}


async def test_a_failed_poll_keeps_an_existing_repair(
    hass: HomeAssistant, mock_aiounas: AsyncMock, config_entry: MockConfigEntry
) -> None:
    """Not knowing the drives' state is not the same as the drive recovering."""
    mock_aiounas.get_storage = AsyncMock(return_value=_with_state(_partial(), 0, "degraded"))
    await _setup(hass, config_entry)
    before = set(_disk_issues(hass))
    assert len(before) == 1

    mock_aiounas.get_storage = AsyncMock(side_effect=UnasConnectionError("console restarting"))
    coordinator = config_entry.runtime_data.coordinator
    await coordinator.async_refresh()

    assert not coordinator.last_update_success
    assert set(_disk_issues(hass)) == before


async def test_two_entries_with_the_same_bay_keep_separate_repairs(
    hass: HomeAssistant, mock_aiounas: AsyncMock, config_entry: MockConfigEntry
) -> None:
    other = MockConfigEntry(
        domain=DOMAIN,
        unique_id="AABBCC000002",
        title="Second console",
        data={**config_entry.data, "host": "192.0.2.11"},
    )
    mock_aiounas.get_storage = AsyncMock(return_value=_with_state(_partial(), 0, "degraded"))
    await _setup(hass, config_entry)
    await _setup(hass, other)

    slot = _partial().disks[0].slot
    assert set(_disk_issues(hass)) == {
        f"disk_at_risk_{config_entry.entry_id}_{slot}",
        f"disk_at_risk_{other.entry_id}_{slot}",
    }

    assert await hass.config_entries.async_unload(other.entry_id)

    assert set(_disk_issues(hass)) == {f"disk_at_risk_{config_entry.entry_id}_{slot}"}
