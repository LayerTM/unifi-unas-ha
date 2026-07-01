"""Model parsing tests, validated against sanitized fixtures."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from aiounas.models import DeviceInfo, NetworkIO, Share, Storage, SystemIdentity

Fx = Callable[[str], dict[str, Any]]


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
