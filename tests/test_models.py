"""Model parsing tests, validated against sanitized fixtures."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import pytest

from aiounas.models import (
    ConsoleBackup,
    DeviceInfo,
    Disk,
    LogSummary,
    NetworkIO,
    NotificationSummary,
    Pool,
    Share,
    Storage,
    StorageIO,
    SystemIdentity,
    UpdateInfo,
)

Fx = Callable[[str], dict[str, Any]]


def test_update_info_normalizes_versions_no_false_update() -> None:
    # Same marketing version, different format (real hardware) -> NOT an update.
    info = UpdateInfo.from_api(
        {
            "hardware": {"firmwareVersion": "5.1.19"},
            "firmware": {"latest": {"version": "v5.1.19+3fbc1da"}},
            "apps": {
                "controllers": [{"name": "drive", "version": "4.3.6", "updateAvailable": None}]
            },
        }
    )
    assert info.unifi_os_installed == "5.1.19"
    assert info.unifi_os_latest == "5.1.19"  # normalized -> equal -> no update
    assert info.drive_installed == "4.3.6"
    assert info.drive_latest is None


def test_update_info_names_the_offered_release_channel(fixture: Fx) -> None:
    info = UpdateInfo.from_api(
        {
            "firmware": {
                "releaseChannel": "release",
                "latest": {"channel": "release-candidate", "version": "v6.0.11+f63375a"},
            },
            "apps": {"controllers": [{"name": "drive", "releaseChannel": "release-candidate"}]},
        }
    )
    assert info.unifi_os_channel == "release-candidate"  # the offered build's own channel wins
    assert info.drive_channel == "release-candidate"
    full = UpdateInfo.from_api(fixture("system_full"))
    assert (full.unifi_os_channel, full.drive_channel) == ("release", "release")
    bare = UpdateInfo.from_api({})
    assert (bare.unifi_os_channel, bare.drive_channel) == (None, None)
    odd = UpdateInfo.from_api(
        {
            "firmware": {"latest": {"channel": "[beta](http://example.invalid)"}},
            "apps": {"controllers": [{"name": "drive", "releaseChannel": 7}]},
        }
    )
    assert (odd.unifi_os_channel, odd.drive_channel) == (None, None)


def test_storage_parses_pools_and_disks(fixture: Fx) -> None:
    s = Storage.from_api(fixture("storage"))
    assert len(s.pools) == 1
    assert len(s.disks) == 2

    p = s.pools[0]
    assert p.status == "fullyOperational"
    assert p.raid_level == "raid1"
    assert p.capacity == 23991544709120
    assert p.usage_percent == 37.1
    assert p.is_healthy is True

    d = s.disks[0]
    assert d.slot == "1"
    assert d.temperature == 47
    assert d.power_on_hours == 3357
    assert d.health_score == 5
    assert d.is_healthy is True
    assert d.model == "WDC WUH722424ALE6L4"

    assert s.total_capacity == 23991544709120
    assert s.at_risk_disk_count == 0
    assert s.average_disk_temperature == 48.0


def _pool(fixture: Fx, **changes: Any) -> Pool:
    raw = fixture("storage")["pools"][0]
    raw.update(changes)
    return Storage.from_api({"pools": [raw]}).pools[0]


def test_idle_pool_reports_no_operation_and_no_scrub_history(fixture: Fx) -> None:
    p = _pool(fixture)
    assert p.key == "00000000-0000-4000-8000-000000000001"
    assert p.operation_progress is None  # a stale 0 outside an operation is not progress
    assert p.scrubbing_scheduled is False
    assert (p.scrubbing_last_result, p.scrubbing_last_run, p.scrubbing_next_run) == ("", None, None)
    assert (p.is_at_risk, p.has_filesystem_issue) == (False, False)


@pytest.mark.parametrize("status", ["syncing", "expanding", "replacing", "repairing"])
def test_raid_operation_progress_comes_from_the_active_raid_group(fixture: Fx, status: str) -> None:
    raw = fixture("storage")["pools"][0]
    first = dict(raw["raidGroups"][0], progress=10)
    active = dict(first, id="00000000:00000000:00000000:00000002", number=2, progress=42)
    p = _pool(
        fixture,
        status=status,
        raidGroups=[first, active],
        activeRaidGroupId=active["id"],
    )
    assert p.operation_progress == 42


def test_raid_operation_without_an_active_group_id_uses_the_first_group(fixture: Fx) -> None:
    raw = fixture("storage")["pools"][0]
    group = dict(raw["raidGroups"][0], progress=17)
    p = _pool(fixture, status="syncing", raidGroups=[group], activeRaidGroupId=None)
    assert p.operation_progress == 17
    assert _pool(fixture, status="syncing", raidGroups=[]).operation_progress is None


@pytest.mark.parametrize("status", ["scrubbing", "scrubbingPaused"])
def test_scrub_progress_comes_from_the_scrub_not_the_raid_group(fixture: Fx, status: str) -> None:
    raw = fixture("storage")["pools"][0]
    scrub = dict(raw["dataScrubbing"], status="inProgress", progress=63)
    group = dict(raw["raidGroups"][0], progress=5)
    p = _pool(fixture, status=status, dataScrubbing=scrub, raidGroups=[group])
    assert p.operation_progress == 63


def test_scrub_schedule_and_last_run_are_parsed(fixture: Fx) -> None:
    raw = fixture("storage")["pools"][0]
    scrub = dict(
        raw["dataScrubbing"],
        schedule={"enabled": True},
        lastTaskRun={"status": "repaired", "finishedAt": "2026-01-04T03:00:00Z"},
        nextRun="2026-02-01T02:00:00Z",
    )
    p = _pool(fixture, dataScrubbing=scrub)
    assert p.scrubbing_scheduled is True
    assert p.scrubbing_last_result == "repaired"
    assert p.scrubbing_last_run == datetime(2026, 1, 4, 3, 0, tzinfo=UTC)
    assert p.scrubbing_next_run == datetime(2026, 2, 1, 2, 0, tzinfo=UTC)


def test_scrub_timestamps_also_read_epoch_milliseconds(fixture: Fx) -> None:
    raw = fixture("storage")["pools"][0]
    when = datetime(2026, 1, 4, 3, 0, tzinfo=UTC)
    scrub = dict(
        raw["dataScrubbing"],
        lastTaskRun={"status": "optimal", "finishedAt": int(when.timestamp() * 1000)},
        nextRun=True,
    )
    p = _pool(fixture, dataScrubbing=scrub)
    assert p.scrubbing_last_run == when
    assert p.scrubbing_next_run is None
    out_of_range = dict(scrub, nextRun=10**30)
    assert _pool(fixture, dataScrubbing=out_of_range).scrubbing_next_run is None


@pytest.mark.parametrize("status", ["atRisk", "raidBadBlocksDetected", "raidBadBlocksAtRisk"])
def test_pool_states_the_console_calls_at_risk(fixture: Fx, status: str) -> None:
    p = _pool(fixture, status=status)
    assert (p.is_at_risk, p.has_filesystem_issue) == (True, False)


@pytest.mark.parametrize("severity", ["warning", "atRisk"])
def test_bad_blocks_on_the_array_mark_the_pool_at_risk(fixture: Fx, severity: str) -> None:
    p = _pool(fixture, raidBadBlocks={"severity": severity})
    assert p.status == "fullyOperational"
    assert p.is_at_risk is True
    assert p.bad_blocks_severity == severity


def test_file_system_issue_is_its_own_condition(fixture: Fx) -> None:
    p = _pool(fixture, status="fileSystemIssue")
    assert (p.is_at_risk, p.has_filesystem_issue) == (False, True)


@pytest.mark.parametrize(
    ("changes", "problem"),
    [
        ({}, False),
        ({"status": "scrubbing"}, False),
        ({"status": "scrubbingPaused"}, False),
        ({"status": "syncing"}, True),
        ({"status": "replacing"}, True),
        ({"status": "atRisk"}, True),
        ({"status": "fileSystemIssue"}, True),
        ({"status": "failed"}, True),
        ({"raidBadBlocks": {"severity": "warning"}}, True),
    ],
)
def test_a_routine_scrub_is_not_a_problem_but_reduced_redundancy_is(
    fixture: Fx, changes: dict[str, Any], problem: bool
) -> None:
    assert _pool(fixture, **changes).has_problem is problem


def test_pool_without_an_id_is_keyed_by_number(fixture: Fx) -> None:
    assert _pool(fixture, id=None, number=3).key == "3"


def test_device_info_derived(fixture: Fx) -> None:
    di = DeviceInfo.from_api(fixture("device_info"))
    assert di.firmware_version == "5.1.19"
    assert di.model == "UNAS2B"
    assert di.cpu_percent == 9.8
    assert di.cpu_temperature == 66.3
    assert di.memory_total_kb == 3970688
    assert di.memory_percent == 39.4


def test_network_io(fixture: Fx) -> None:
    n = NetworkIO.from_api(fixture("network_io"))
    assert n.rx_kbps == 3.62
    assert n.tx_kbps == 15.30


def test_shares(fixture: Fx) -> None:
    shares = [Share.from_api(x) for x in fixture("drives")["drives"]]
    assert shares[0].name == "Share1"
    assert shares[0].quota_bytes is None  # -1 -> unlimited
    assert shares[0].snapshot_enabled is True
    assert shares[1].quota_bytes == 5000


def test_identity(fixture: Fx) -> None:
    ident = SystemIdentity.from_api(fixture("system_short"))
    assert ident.mac == "AABBCC000001"
    assert ident.model_shortname == "UNAS2B"


def test_share_quota_accepts_numeric_string() -> None:
    # some firmware encodes numbers as strings
    assert Share.from_api({"name": "x", "quota": "5000"}).quota_bytes == 5000
    assert Share.from_api({"name": "x", "quota": "-1"}).quota_bytes is None


def test_update_info_lists_installed_applications(fixture: Fx) -> None:
    info = UpdateInfo.from_api(fixture("system_full"))
    apps = {a.name: a.version for a in info.applications}
    assert apps == {"drive": "4.3.6", "users": "1.13.6"}


def test_notification_summary_counts_by_category_discards_bodies() -> None:
    summary = NotificationSummary.from_api(
        [
            {"category": "admins", "created_at": "2026-07-02T06:59:20Z", "cef_log": "secret"},
            {"category": "backups", "created_at": "2026-07-01T00:00:00Z", "event_data": {"x": 1}},
            {"category": "backups", "created_at": "2026-06-30T00:00:00Z"},
            {"created_at": "2026-06-29T00:00:00Z"},  # no category -> "other"
        ]
    )
    assert summary.total == 4
    assert dict(summary.by_category) == {"admins": 1, "backups": 2, "other": 1}
    assert summary.latest is not None
    assert summary.latest.day == 2  # newest of the four
    # PII (cef_log / event_data) is not retained anywhere on the frozen model.
    assert not hasattr(summary, "cef_log")


def test_notification_summary_reads_wrapped_and_empty_payloads() -> None:
    assert NotificationSummary.from_api({"data": [{"category": "a"}]}).total == 1
    assert NotificationSummary.from_api({"notifications": [{"category": "b"}]}).total == 1
    empty = NotificationSummary.from_api([])
    assert empty.total == 0
    assert empty.by_category == ()
    assert empty.latest is None


def test_log_summary_counts_and_latest_discards_bodies() -> None:
    summary = LogSummary.from_api(
        {
            "logs": [
                {"createdAt": "2026-07-02T06:00:00Z", "data": "secret-log-body"},
                {"createdAt": "2026-07-01T06:00:00Z"},
            ]
        }
    )
    assert summary.total == 2
    assert summary.latest is not None
    assert summary.latest.day == 2
    assert not hasattr(summary, "data")


def test_log_summary_tolerates_bare_list_and_empty() -> None:
    assert LogSummary.from_api([{"createdAt": "2026-07-02T06:00:00Z"}]).total == 1
    empty = LogSummary.from_api({"logs": []})
    assert empty.total == 0
    assert empty.latest is None


def test_summaries_fail_closed_on_malformed_payloads() -> None:
    # A null / bare-string / unexpected payload must not raise (it would otherwise
    # take the whole coordinator update down); it degrades to an empty summary.
    for bad in (None, "oops", 42, {"unexpected": True}):
        ns = NotificationSummary.from_api(bad)
        assert ns.total == 0 and ns.latest is None
        ls = LogSummary.from_api(bad)
        assert ls.total == 0 and ls.latest is None


def test_an_empty_bay_is_not_a_disk_at_risk(fixture: Fx) -> None:
    """A NAS that is not fully populated reports its empty bays in `disks`.

    An empty bay holds no drive, so it cannot be at risk: counting it made a
    4-bay console with 3 drives report one disk at risk, and switched the hub's
    storage-problem sensor on.
    """
    s = Storage.from_api(fixture("storage_partial"))
    assert len(s.disks) == 3
    empty = s.disks[2]
    assert empty.slot == "3"
    assert empty.is_present is False
    assert empty.is_at_risk is False
    assert s.at_risk_disk_count == 0
    # The bay's temperature of 0 is not a reading; the average is over drives.
    assert s.average_disk_temperature == 48.0


@pytest.mark.parametrize("state", ["empty", "EMPTY", "Empty"])
def test_empty_is_recognised_whatever_its_case(state: str) -> None:
    assert Disk.from_api({"slotId": "4", "state": state}).is_present is False


@pytest.mark.parametrize(
    ("state", "reasons"),
    [("degraded", []), ("failed", []), ("optimal", ["badSector"])],
)
def test_a_present_drive_that_is_not_healthy_is_still_at_risk(
    state: str, reasons: list[str]
) -> None:
    """The other branch: excluding empty bays must not hide a real problem."""
    d = Disk.from_api({"slotId": "1", "state": state, "riskReasons": reasons})
    assert d.is_present is True
    assert d.is_at_risk is True


def test_storage_io_takes_the_latest_bucket(fixture: Callable[[str], dict[str, Any]]) -> None:
    io = StorageIO.from_api(fixture("storage_io_stats"))
    assert io.read_kbps == pytest.approx(31.147149769341972)
    assert io.write_kbps == pytest.approx(547.8613425728477)
    assert io.window_end == 1791193500
    assert io.interval == 300


def test_storage_io_newest_sample_is_the_last() -> None:
    io = StorageIO.from_api(
        {"data": {"series": {"readKBPS": [1.0, 0], "writeKBPS": [5, 9.5]}, "window": {}}}
    )
    assert io.read_kbps == 0.0
    assert io.write_kbps == 9.5
    assert io.window_end is None
    assert io.interval is None


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"data": None},
        {"data": {"series": None, "window": None}},
        {"data": {"series": {"readKBPS": [], "writeKBPS": "x"}}},
        {"data": {"series": {"readKBPS": [None], "writeKBPS": [True]}}},
    ],
)
def test_storage_io_tolerates_missing_samples(payload: dict[str, Any]) -> None:
    io = StorageIO.from_api(payload)
    assert io.read_kbps is None
    assert io.write_kbps is None


@pytest.mark.parametrize(
    ("model", "vendor"),
    [
        ("WDC WUH722424ALE6L4", "Western Digital"),
        ("WDC  WD120EFBX-68B0EN0", "Western Digital"),
        ("WD120EFBX-68B0EN0", "Western Digital"),
        ("WD Red SN700 1000GB", "Western Digital"),
        ("WD_BLACK SN850X 2000GB", "Western Digital"),
        ("WD_Blue SA510 2.5 1000GB", "Western Digital"),
        ("ST12000VN0008-2YS101", "Seagate"),
        ("Seagate IronWolf ZA500NM10002", "Seagate"),
        ("HGST HUH721212ALE604", "HGST"),
        ("TOSHIBA MG09ACA18TE", "Toshiba"),
        ("Samsung SSD 870 EVO 1TB", "Samsung"),
        # A part number that names no maker we know is not a maker.
        ("CT1000MX500SSD1", None),
        ("STORAGE DEVICE", None),
        ("", None),
    ],
)
def test_disk_vendor(model: str, vendor: str | None) -> None:
    assert Disk.from_api({"model": model}).vendor == vendor


@pytest.mark.parametrize(
    ("payload", "enabled", "frequency"),
    [
        ({"autoBackupEnabled": True, "backupSchedule": {"frequency": "weekly"}}, True, "weekly"),
        ({"autoBackupEnabled": False, "backupSchedule": {"frequency": "DAILY"}}, False, "daily"),
        ({"autoBackupEnabled": "yes", "backupSchedule": {"frequency": ""}}, None, None),
        ({"backupSchedule": None}, None, None),
        ({}, None, None),
    ],
)
def test_console_backup_reads_only_what_is_there(
    payload: dict[str, Any], enabled: bool | None, frequency: str | None
) -> None:
    backup = ConsoleBackup.from_api(payload)
    assert (backup.enabled, backup.frequency) == (enabled, frequency)
    assert backup.has_data is (enabled is not None or frequency is not None)
