"""A failed read hides only the entities that depend on it."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import Counter
from collections.abc import Iterator
from contextlib import AbstractContextManager
from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest
from custom_components.unifi_unas_rest.aiounas import (
    UnasApiError,
    UnasAuthError,
    UnasCapabilityError,
    UnasCertificateMismatch,
    UnasConnectionError,
    const,
    probe,
)
from custom_components.unifi_unas_rest.aiounas.transport import UnasTransport
from custom_components.unifi_unas_rest.const import (
    AUTH_PASSWORD,
    CONF_AUTH_METHOD,
    CONF_ENABLE_CONTROLS,
    CONF_TLS_MODE,
    DOMAIN,
)
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_SCAN_INTERVAL,
    CONF_USERNAME,
    EVENT_HOMEASSISTANT_STOP,
    STATE_UNAVAILABLE,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant.common import MockConfigEntry

_PREFIX = "AABBCC000001_"
_FIXTURE_DIR = Path(__file__).resolve().parents[1] / "tests" / "fixtures"


def _load(name: str) -> object:
    return json.loads((_FIXTURE_DIR / f"{name}.json").read_text(encoding="utf-8"))


# Past the end of the throughput fixture's bucket and the one after it, so the
# coordinator asks for throughput again on every cycle.
_AFTER_NEXT_BUCKET = 1791193500 + 600

_SHARES = "every share entity"

# client method -> the entity keys that exist only because of that read
_READS: dict[str, tuple[str, ...] | str] = {
    "get_network_io": ("network_rx", "network_tx"),
    "get_shares": _SHARES,
    "get_user_count": ("user_count",),
    "get_system_readings": (
        "applications",
        "unifi_os_update",
        "drive_update",
        "console_auto_backup",
        "console_backup_frequency",
    ),
    "get_fan_control": ("fan_profile",),
    "get_notification_summary": ("recent_events", "last_event"),
    "get_log_summary": ("log_entries",),
    "get_storage_io": ("storage_read_rate", "storage_write_rate"),
    "get_backup_task_count": ("backup_tasks",),
}

_ANCHORS = ["get_storage", "get_device_info"]

_PATH = "/proxy/drive/example"
_FAILURES = {
    "bad gateway": UnasApiError(f"unexpected status 502 for {_PATH}", status=502),
    "timeout": UnasConnectionError(f"GET {_PATH}: TimeoutError"),
    "refusal": UnasCapabilityError(f"forbidden for {_PATH}"),
    "unauthorized": UnasAuthError(f"unauthorized for {_PATH}"),
    "server error": UnasApiError(f"unexpected status 500 for {_PATH}", status=500),
}

_COORDINATOR_LOGGER = "custom_components.unifi_unas_rest.coordinator"


@pytest.fixture(autouse=True)
def clock() -> Iterator[MagicMock]:
    fake = MagicMock()
    fake.time.return_value = _AFTER_NEXT_BUCKET
    with patch("custom_components.unifi_unas_rest.coordinator.time", fake):
        yield fake


@pytest.fixture
def every_entity_enabled() -> Iterator[None]:
    """Enable the entities shipped disabled, so each has a state to look at.

    The harness's own fixture for this is absent from the oldest supported one.
    """
    with patch(
        "homeassistant.helpers.entity.Entity.entity_registry_enabled_default",
        new_callable=PropertyMock,
        return_value=True,
    ):
        yield


@pytest.fixture
def controls_entry() -> MockConfigEntry:
    """A local account with controls on, so every platform has its entities."""
    return MockConfigEntry(
        domain=DOMAIN,
        unique_id="AABBCC000001",
        data={
            CONF_HOST: "192.0.2.10",
            CONF_PORT: 443,
            CONF_TLS_MODE: "insecure",
            CONF_USERNAME: "user",
            CONF_PASSWORD: "pass",
            CONF_AUTH_METHOD: AUTH_PASSWORD,
        },
        options={CONF_ENABLE_CONTROLS: True},
    )


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    if hass.config_entries.async_get_entry(entry.entry_id) is None:
        entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def _refresh(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    await entry.runtime_data.coordinator.async_refresh()
    await hass.async_block_till_done()


def _states(hass: HomeAssistant, entry: MockConfigEntry) -> dict[str, str]:
    """State of every entity of the entry, by the entity's own part of its unique id."""
    states = {}
    for row in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id):
        state = hass.states.get(row.entity_id)
        assert state, row.entity_id
        states[row.unique_id.removeprefix(_PREFIX)] = state.state
    return states


def _dependants(method: str, states: dict[str, str]) -> set[str]:
    keys = _READS[method]
    if keys == _SHARES:
        found = {key for key in states if key.startswith("share")}
    else:
        found = set(keys)
        assert found <= states.keys()
    assert found
    return found


@pytest.mark.parametrize("failure", ["bad gateway", "timeout", "refusal", "unauthorized"])
@pytest.mark.parametrize("method", _READS)
async def test_failed_read_hides_only_its_own_entities(
    hass: HomeAssistant,
    every_entity_enabled: None,
    mock_aiounas: AsyncMock,
    controls_entry: MockConfigEntry,
    method: str,
    failure: str,
) -> None:
    await _setup(hass, controls_entry)
    before = _states(hass, controls_entry)
    dependants = _dependants(method, before)
    assert STATE_UNAVAILABLE not in {before[key] for key in dependants}
    read = getattr(mock_aiounas, method)

    read.side_effect = _FAILURES[failure]
    await _refresh(hass, controls_entry)

    assert controls_entry.runtime_data.coordinator.last_update_success
    assert _states(hass, controls_entry) == {
        **before,
        **dict.fromkeys(dependants, STATE_UNAVAILABLE),
    }
    assert not hass.config_entries.flow.async_progress()  # never a re-authentication

    # The following poll asks again, and a success brings the entities back.
    asked = read.await_count
    read.side_effect = None
    await _refresh(hass, controls_entry)
    assert read.await_count == asked + 1
    assert _states(hass, controls_entry) == before


@pytest.mark.parametrize("failure", ["bad gateway", "timeout"])
@pytest.mark.parametrize("method", _ANCHORS)
async def test_failed_anchor_read_hides_everything(
    hass: HomeAssistant,
    every_entity_enabled: None,
    mock_aiounas: AsyncMock,
    controls_entry: MockConfigEntry,
    method: str,
    failure: str,
) -> None:
    await _setup(hass, controls_entry)

    getattr(mock_aiounas, method).side_effect = _FAILURES[failure]
    await _refresh(hass, controls_entry)

    states = _states(hass, controls_entry)
    assert states.pop("device_online") == "off"
    assert set(states.values()) == {STATE_UNAVAILABLE}


async def test_certificate_change_on_any_read_fails_the_update(
    hass: HomeAssistant, mock_aiounas: AsyncMock, config_entry: MockConfigEntry
) -> None:
    """A changed certificate is a connection error that must not be absorbed."""
    await _setup(hass, config_entry)

    mock_aiounas.get_user_count.side_effect = UnasCertificateMismatch("AA" * 32, "BB" * 32)
    with patch("custom_components.unifi_unas_rest.coordinator.raise_cert_mismatch") as repair:
        await _refresh(hass, config_entry)

    assert not config_entry.runtime_data.coordinator.last_update_success
    repair.assert_called_once()


async def test_read_that_never_answered_leaves_its_entities_unavailable(
    hass: HomeAssistant,
    every_entity_enabled: None,
    mock_aiounas: AsyncMock,
    config_entry: MockConfigEntry,
) -> None:
    mock_aiounas.get_network_io.side_effect = _FAILURES["bad gateway"]
    await _setup(hass, config_entry)

    states = _states(hass, config_entry)
    assert states["network_rx"] == states["network_tx"] == STATE_UNAVAILABLE
    assert states["storage_usage"] != STATE_UNAVAILABLE


async def test_failure_is_logged_once_and_so_is_the_recovery(
    hass: HomeAssistant,
    mock_aiounas: AsyncMock,
    config_entry: MockConfigEntry,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG, logger=_COORDINATOR_LOGGER)
    await _setup(hass, config_entry)

    def _logged() -> list[int]:
        return [
            record.levelno
            for record in caplog.records
            if record.name == _COORDINATOR_LOGGER and "user count" in record.getMessage()
        ]

    caplog.clear()
    mock_aiounas.get_user_count.side_effect = _FAILURES["bad gateway"]
    for _ in range(3):
        await _refresh(hass, config_entry)
    assert _logged() == [logging.WARNING, logging.DEBUG, logging.DEBUG]
    assert f"unexpected status 502 for {_PATH}" in caplog.text

    caplog.clear()
    mock_aiounas.get_user_count.side_effect = None
    await _refresh(hass, config_entry)
    await _refresh(hass, config_entry)
    assert _logged() == [logging.INFO]

    caplog.clear()
    mock_aiounas.get_user_count.side_effect = _FAILURES["timeout"]
    await _refresh(hass, config_entry)
    assert _logged() == [logging.WARNING]


async def test_network_throughput_out_of_scope_is_neither_read_nor_shown(
    hass: HomeAssistant,
    every_entity_enabled: None,
    mock_aiounas: AsyncMock,
    config_entry: MockConfigEntry,
) -> None:
    caps = await probe(mock_aiounas)
    registry = er.async_get(hass)
    config_entry.add_to_hass(hass)
    stale = registry.async_get_or_create(
        "sensor", DOMAIN, f"{_PREFIX}network_rx", config_entry=config_entry
    )
    mock_aiounas.get_network_io.reset_mock()
    with patch(
        "custom_components.unifi_unas_rest.probe",
        AsyncMock(return_value=replace(caps, network_io=False)),
    ):
        await _setup(hass, config_entry)

    mock_aiounas.get_network_io.assert_not_called()
    states = _states(hass, config_entry)
    assert not {"network_rx", "network_tx"} & states.keys()
    assert registry.async_get(stale.entity_id) is None


async def test_fan_select_appears_once_a_failed_first_read_succeeds(
    hass: HomeAssistant,
    every_entity_enabled: None,
    mock_aiounas: AsyncMock,
    controls_entry: MockConfigEntry,
) -> None:
    mock_aiounas.get_fan_control.side_effect = _FAILURES["timeout"]
    await _setup(hass, controls_entry)
    assert "fan_profile" not in _states(hass, controls_entry)

    mock_aiounas.get_fan_control.side_effect = None
    await _refresh(hass, controls_entry)

    assert _states(hass, controls_entry)["fan_profile"] != STATE_UNAVAILABLE


async def test_fan_control_never_served_is_not_warned_about(
    hass: HomeAssistant,
    mock_aiounas: AsyncMock,
    config_entry: MockConfigEntry,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Fan control is the one read the setup probe does not check for."""
    caplog.set_level(logging.DEBUG, logger=_COORDINATOR_LOGGER)

    def _logged() -> list[int]:
        return [
            record.levelno
            for record in caplog.records
            if record.name == _COORDINATOR_LOGGER and "fan control" in record.getMessage()
        ]

    mock_aiounas.get_fan_control.side_effect = UnasApiError("not found", status=404)
    await _setup(hass, config_entry)
    await _refresh(hass, config_entry)
    assert set(_logged()) == {logging.DEBUG}

    # Once it has answered, losing it is worth a warning like any other read.
    caplog.clear()
    mock_aiounas.get_fan_control.side_effect = None
    await _refresh(hass, config_entry)
    assert _logged() == []
    mock_aiounas.get_fan_control.side_effect = _FAILURES["bad gateway"]
    await _refresh(hass, config_entry)
    await _refresh(hass, config_entry)
    assert _logged() == [logging.WARNING, logging.DEBUG]


# read -> the client methods that fail with it, in the setup probe and in a poll
_SETUP_METHODS = {method: (method,) for method in _READS} | {
    "get_system_readings": ("get_system_readings", "get_update_info", "get_console_backup")
}


@pytest.mark.parametrize("failure", ["server error", "timeout"])
@pytest.mark.parametrize("method", _READS)
async def test_read_failing_through_setup_keeps_its_entities(
    hass: HomeAssistant,
    every_entity_enabled: None,
    mock_aiounas: AsyncMock,
    controls_entry: MockConfigEntry,
    method: str,
    failure: str,
) -> None:
    """A restart while one read fails: the entry loads and nothing is removed."""
    readings = await mock_aiounas.get_system_readings()
    mock_aiounas.get_update_info.return_value = readings.update_info
    mock_aiounas.get_console_backup.return_value = readings.console_backup
    with patch("custom_components.unifi_unas_rest.probe", probe):  # the real probe
        await _setup(hass, controls_entry)
        before = _states(hass, controls_entry)
        dependants = _dependants(method, before)
        broken = {name: getattr(mock_aiounas, name).side_effect for name in _SETUP_METHODS[method]}
        for name in broken:
            getattr(mock_aiounas, name).side_effect = _FAILURES[failure]

        assert await hass.config_entries.async_reload(controls_entry.entry_id)
        await hass.async_block_till_done()
        await _refresh(hass, controls_entry)  # still failing: a permanent failure

        assert controls_entry.state is ConfigEntryState.LOADED
        assert _states(hass, controls_entry) == {
            **before,
            **dict.fromkeys(dependants, STATE_UNAVAILABLE),
        }

        for name, original in broken.items():
            getattr(mock_aiounas, name).side_effect = original
        await _refresh(hass, controls_entry)
        assert _states(hass, controls_entry) == before


@pytest.mark.parametrize("method", _ANCHORS)
async def test_anchor_failing_during_setup_retries(
    hass: HomeAssistant, mock_aiounas: AsyncMock, config_entry: MockConfigEntry, method: str
) -> None:
    getattr(mock_aiounas, method).side_effect = _FAILURES["timeout"]
    with patch("custom_components.unifi_unas_rest.probe", probe):
        await _setup(hass, config_entry)
    assert config_entry.state is ConfigEntryState.SETUP_RETRY


# ---------------------------------------------------------------------------
# The delayed second attempt. These run the real client against a scripted
# console, because the retry lives below the client the other tests replace.
# ---------------------------------------------------------------------------

_FIXTURES = {
    const.PATH_STORAGE: "storage",
    const.PATH_DEVICE_INFO: "device_info",
    const.PATH_NETWORK_IO: "network_io",
    const.PATH_FAN_CONTROL: "fan_control",
    const.PATH_SHARES: "drives",
    const.PATH_NOTIFICATIONS: "notifications",
    const.PATH_LOGS: "logs",
    const.PATH_STORAGE_IO: "storage_io_stats",
    const.PATH_REMOTE_BACKUP_TASKS: "remote_backup_tasks",
    const.PATH_M365_BACKUP_TASKS: "m365_backup_tasks",
    const.PATH_SYSTEM: "system_full",
}


class _Console:
    """Answers every read from the fixtures, except where a failure is scripted."""

    def __init__(self) -> None:
        self.failing: dict[str, list[int]] = {}
        """path -> statuses still to answer with, before it works again."""
        self.asked: Counter[str] = Counter()
        self.refused = asyncio.Event()

    def fail(self, *paths: str, times: int = 1000) -> None:
        for path in paths or tuple(_FIXTURES):
            self.failing[path] = [502] * times

    async def request(self, method: str, path: str, **_: object) -> tuple[int, object]:
        assert method == "GET"
        path = path.partition("?")[0]
        self.asked[path] += 1
        if self.failing.get(path):
            self.refused.set()
            return self.failing[path].pop(), None
        if path == const.PATH_USERS:
            return 200, []
        return 200, _load(_FIXTURES[path])


@pytest.fixture
def console() -> Iterator[_Console]:
    fake = _Console()

    async def request(_: UnasTransport, method: str, path: str, **kwargs: object) -> object:
        return await fake.request(method, path, **kwargs)

    with patch.object(UnasTransport, "_request", request):
        yield fake


def _retry_delay(seconds: float) -> AbstractContextManager[object]:
    return patch(
        "custom_components.unifi_unas_rest.coordinator.MAX_RETRY_DELAY", seconds, create=True
    )


def _online(hass: HomeAssistant, entry: MockConfigEntry) -> str:
    entity_id = er.async_get(hass).async_get_entity_id(
        "binary_sensor", DOMAIN, f"{_PREFIX}device_online"
    )
    assert entity_id
    state = hass.states.get(entity_id)
    assert state
    return state.state


async def test_anchor_502_once_recovers_within_the_poll(
    hass: HomeAssistant, console: _Console, config_entry: MockConfigEntry
) -> None:
    with _retry_delay(0):
        await _setup(hass, config_entry)
        console.asked.clear()
        console.fail(const.PATH_STORAGE, times=1)
        await _refresh(hass, config_entry)

    assert config_entry.runtime_data.coordinator.last_update_success
    assert _online(hass, config_entry) == "on"
    assert console.asked[const.PATH_STORAGE] == 2


async def test_persistent_502_fails_the_first_poll_after_one_retry(
    hass: HomeAssistant, console: _Console, config_entry: MockConfigEntry
) -> None:
    with _retry_delay(0):
        await _setup(hass, config_entry)
        console.asked.clear()
        console.fail(const.PATH_STORAGE)
        await _refresh(hass, config_entry)

    assert not config_entry.runtime_data.coordinator.last_update_success
    assert _online(hass, config_entry) == "off"
    assert console.asked[const.PATH_STORAGE] == 2


async def test_one_retry_per_poll_when_every_optional_read_fails(
    hass: HomeAssistant, console: _Console, config_entry: MockConfigEntry
) -> None:
    anchors = {const.PATH_STORAGE, const.PATH_DEVICE_INFO}
    with _retry_delay(0.3):
        await _setup(hass, config_entry)
        console.asked.clear()
        console.fail(*(set(_FIXTURES) - anchors), const.PATH_USERS)
        started = time.monotonic()
        await _refresh(hass, config_entry)

    assert 0.3 <= time.monotonic() - started < 0.6
    assert config_entry.runtime_data.coordinator.last_update_success
    repeats = {path: n for path, n in console.asked.items() if n > 1}
    assert repeats == {const.PATH_NETWORK_IO: 2}


async def test_setup_does_not_wait_to_retry(
    hass: HomeAssistant, console: _Console, config_entry: MockConfigEntry
) -> None:
    """Home Assistant retries a setup itself, and an unload cannot end one."""
    console.fail(const.PATH_STORAGE)
    await _setup(hass, config_entry)

    assert config_entry.state is ConfigEntryState.SETUP_RETRY
    assert console.asked[const.PATH_STORAGE] == 1


@pytest.mark.parametrize(("scan_interval", "delay"), [(10, 5), (20, 10), (30, 15), (600, 15)])
async def test_the_wait_never_exceeds_half_the_scan_interval(
    hass: HomeAssistant,
    console: _Console,
    config_entry: MockConfigEntry,
    scan_interval: int,
    delay: float,
) -> None:
    config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        config_entry, options={CONF_SCAN_INTERVAL: scan_interval}
    )
    await _setup(hass, config_entry)
    with patch.object(UnasTransport, "allow_one_retry", autospec=True) as allow:
        await _refresh(hass, config_entry)
    assert [call.args[1] for call in allow.call_args_list] == [delay]


@pytest.mark.parametrize("end", ["unload", "reload", "stop"])
async def test_ending_the_entry_ends_the_wait_at_once(
    hass: HomeAssistant, console: _Console, config_entry: MockConfigEntry, end: str
) -> None:
    with _retry_delay(60):
        config_entry.add_to_hass(hass)
        hass.config_entries.async_update_entry(config_entry, options={CONF_SCAN_INTERVAL: 600})
        await _setup(hass, config_entry)
        coordinator = config_entry.runtime_data.coordinator
        console.asked.clear()
        console.fail(const.PATH_STORAGE, times=1)
        poll = hass.async_create_task(coordinator.async_refresh())
        await console.refused.wait()
        await asyncio.sleep(0.05)
        assert not poll.done()

        async with asyncio.timeout(2):
            if end == "unload":
                assert await hass.config_entries.async_unload(config_entry.entry_id)
            elif end == "reload":
                assert await hass.config_entries.async_reload(config_entry.entry_id)
            else:
                hass.bus.async_fire(EVENT_HOMEASSISTANT_STOP)
            await poll

    assert not coordinator.last_update_success
