"""Model parsing tests, validated against sanitized fixtures."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from aiounas.models import (
    DeviceInfo,
    LogSummary,
    NetworkIO,
    NotificationSummary,
    Share,
    Storage,
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
