"""A pool's running operation, its scrub schedule and its health reach Home Assistant."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest
from custom_components.unifi_unas_rest.aiounas import Storage
from custom_components.unifi_unas_rest.const import DOMAIN
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant.common import MockConfigEntry

_FX = Path(__file__).resolve().parents[1] / "tests" / "fixtures"
POOL_ID = "00000000-0000-4000-8000-000000000001"
POOL = f"AABBCC000001_pool{POOL_ID}"


def _storage(**pool_changes: Any) -> Storage:
    raw = json.loads((_FX / "storage.json").read_text())
    raw["pools"][0].update(pool_changes)
    return Storage.from_api(raw)


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


def _state(hass: HomeAssistant, platform: str, key: str) -> str:
    eid = er.async_get(hass).async_get_entity_id(platform, DOMAIN, f"{POOL}_{key}")
    assert eid, key
    state = hass.states.get(eid)
    assert state is not None, eid
    return state.state


def _pool_issues(hass: HomeAssistant) -> dict[str, ir.IssueEntry]:
    return {
        issue_id: issue
        for (domain, issue_id), issue in ir.async_get(hass).issues.items()
        if domain == DOMAIN and issue_id.startswith("pool_")
    }


async def test_a_healthy_idle_pool(
    hass: HomeAssistant, mock_aiounas: AsyncMock, config_entry: MockConfigEntry
) -> None:
    await _setup(hass, config_entry)

    assert _state(hass, "sensor", "operation_progress") == STATE_UNKNOWN
    assert _state(hass, "sensor", "scrubbing_last_result") == STATE_UNKNOWN
    assert _state(hass, "sensor", "scrubbing_last_run") == STATE_UNKNOWN
    assert _state(hass, "sensor", "scrubbing_next_run") == STATE_UNKNOWN
    assert _state(hass, "binary_sensor", "scrubbing_scheduled") == STATE_OFF
    assert _state(hass, "binary_sensor", "at_risk") == STATE_OFF
    assert _state(hass, "binary_sensor", "filesystem_issue") == STATE_OFF
    assert _pool_issues(hass) == {}


async def test_a_rebuild_shows_its_progress(
    hass: HomeAssistant, mock_aiounas: AsyncMock, config_entry: MockConfigEntry
) -> None:
    raw = json.loads((_FX / "storage.json").read_text())["pools"][0]
    group = dict(raw["raidGroups"][0], progress=37)
    mock_aiounas.get_storage = AsyncMock(
        return_value=_storage(status="syncing", raidGroups=[group])
    )
    await _setup(hass, config_entry)

    assert _state(hass, "sensor", "operation_progress") == "37"
    assert _pool_issues(hass) == {}  # a rebuild is not a pool at risk


async def test_a_scheduled_scrub_and_its_last_result(
    hass: HomeAssistant, mock_aiounas: AsyncMock, config_entry: MockConfigEntry
) -> None:
    scrub = {
        "status": "idle",
        "schedule": {"enabled": True},
        "lastTaskRun": {"status": "optimal", "finishedAt": "2026-01-04T03:00:00Z"},
        "nextRun": "2026-02-01T02:00:00Z",
    }
    mock_aiounas.get_storage = AsyncMock(return_value=_storage(dataScrubbing=scrub))
    await _setup(hass, config_entry)

    assert _state(hass, "binary_sensor", "scrubbing_scheduled") == STATE_ON
    assert _state(hass, "sensor", "scrubbing_last_result") == "optimal"
    assert _state(hass, "sensor", "scrubbing_last_run") == "2026-01-04T03:00:00+00:00"
    assert _state(hass, "sensor", "scrubbing_next_run") == "2026-02-01T02:00:00+00:00"


@pytest.mark.parametrize(
    "changes",
    [{"status": "raidBadBlocksAtRisk"}, {"raidBadBlocks": {"severity": "warning"}}],
)
async def test_a_pool_at_risk_raises_one_repair_and_withdraws_it_on_recovery(
    hass: HomeAssistant,
    mock_aiounas: AsyncMock,
    config_entry: MockConfigEntry,
    changes: dict[str, Any],
) -> None:
    mock_aiounas.get_storage = AsyncMock(return_value=_storage(**changes))
    await _setup(hass, config_entry)

    assert _state(hass, "binary_sensor", "at_risk") == STATE_ON
    issues = _pool_issues(hass)
    assert list(issues) == [f"pool_at_risk_{config_entry.entry_id}_{POOL_ID}"]
    issue = next(iter(issues.values()))
    assert issue.translation_key == "pool_at_risk"
    assert issue.severity is ir.IssueSeverity.WARNING
    assert not issue.is_fixable
    assert (issue.translation_placeholders or {})["pool"] == "1"

    mock_aiounas.get_storage = AsyncMock(return_value=_storage())
    await config_entry.runtime_data.coordinator.async_refresh()
    await hass.async_block_till_done()

    assert _state(hass, "binary_sensor", "at_risk") == STATE_OFF
    assert _pool_issues(hass) == {}


async def test_file_system_errors_raise_a_repair_that_never_offers_a_fix(
    hass: HomeAssistant, mock_aiounas: AsyncMock, config_entry: MockConfigEntry
) -> None:
    mock_aiounas.get_storage = AsyncMock(return_value=_storage(status="fileSystemIssue"))
    await _setup(hass, config_entry)

    assert _state(hass, "binary_sensor", "filesystem_issue") == STATE_ON
    assert _state(hass, "binary_sensor", "at_risk") == STATE_OFF
    issues = _pool_issues(hass)
    assert list(issues) == [f"pool_filesystem_issue_{config_entry.entry_id}_{POOL_ID}"]
    assert not next(iter(issues.values())).is_fixable


async def test_unloading_withdraws_the_pool_repairs(
    hass: HomeAssistant, mock_aiounas: AsyncMock, config_entry: MockConfigEntry
) -> None:
    mock_aiounas.get_storage = AsyncMock(return_value=_storage(status="fileSystemIssue"))
    await _setup(hass, config_entry)
    assert _pool_issues(hass)

    assert await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()

    assert _pool_issues(hass) == {}


@pytest.mark.parametrize(
    ("status", "problem"),
    [
        ("scrubbing", STATE_OFF),
        ("scrubbingPaused", STATE_OFF),
        ("atRisk", STATE_ON),
        ("fileSystemIssue", STATE_ON),
        ("replacing", STATE_ON),
    ],
)
async def test_storage_problem_ignores_a_routine_scrub(
    hass: HomeAssistant,
    mock_aiounas: AsyncMock,
    config_entry: MockConfigEntry,
    status: str,
    problem: str,
) -> None:
    mock_aiounas.get_storage = AsyncMock(return_value=_storage(status=status))
    await _setup(hass, config_entry)

    eid = er.async_get(hass).async_get_entity_id(
        "binary_sensor", DOMAIN, "AABBCC000001_storage_problem"
    )
    assert eid
    state = hass.states.get(eid)
    assert state is not None
    assert state.state == problem
