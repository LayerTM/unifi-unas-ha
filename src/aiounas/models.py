"""Immutable typed models parsed from UNAS Drive REST API responses.

Pure parsing + derived properties; no I/O. Field names follow the verified
API schema documented in ``docs/API.md``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

_TB = 1_000_000_000_000


def _f(value: Any, default: float = 0.0) -> float:
    """Coerce to float; bools and non-numerics fall back to *default*."""
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    return default


def _i(value: Any) -> int | None:
    """Coerce to int or None (bools are treated as absent).

    Numeric strings (e.g. ``"5000"``, ``"-1"``) are accepted, since some
    firmware encodes numbers as strings.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value.strip())
    return None


def _i0(value: Any) -> int:
    """Coerce to int, defaulting to 0."""
    parsed = _i(value)
    return parsed if parsed is not None else 0


def _s(value: Any, default: str = "") -> str:
    """Return the string value, else *default*."""
    return value if isinstance(value, str) else default


def _b(value: Any) -> bool:
    """True only for a literal boolean True."""
    return value is True


@dataclass(frozen=True, slots=True)
class Disk:
    """A physical drive with SMART-derived health fields."""

    slot: str
    pool_id: str
    type: str
    state: str
    model: str
    serial: str
    firmware: str
    size: int  # bytes
    rpm: int
    temperature: int | None  # °C
    power_on_hours: int | None
    bad_sector_count: int
    uncorrectable_sector_count: int
    read_error_rate: int
    health_score: int | None
    smart_test_supported: bool
    read_kbps: int
    write_kbps: int
    risk_reasons: tuple[str, ...]

    @property
    def is_healthy(self) -> bool:
        return self.state.lower() == "optimal" and not self.risk_reasons

    @property
    def size_tb(self) -> float:
        return round(self.size / _TB, 2)

    @classmethod
    def from_api(cls, d: dict[str, Any]) -> Disk:
        reasons = d.get("riskReasons") or []
        return cls(
            slot=_s(d.get("slotId")),
            pool_id=_s(d.get("poolId")),
            type=_s(d.get("type")),
            state=_s(d.get("state")),
            model=_s(d.get("model")).strip(),
            serial=_s(d.get("serial")),
            firmware=_s(d.get("firmware")),
            size=_i0(d.get("size")),
            rpm=_i0(d.get("rpm")),
            temperature=_i(d.get("temperature")),
            power_on_hours=_i(d.get("powerOnHours")),
            bad_sector_count=_i0(d.get("badSectorCount")),
            uncorrectable_sector_count=_i0(d.get("uncorrectableSectorCount")),
            read_error_rate=_i0(d.get("readErrorRate")),
            health_score=_i(d.get("healthScore")),
            smart_test_supported=_b(d.get("smartTestSupported")),
            read_kbps=_i0(d.get("readKBPS")),
            write_kbps=_i0(d.get("writeKBPS")),
            risk_reasons=tuple(str(r) for r in reasons),
        )


@dataclass(frozen=True, slots=True)
class RaidGroup:
    """A RAID group within a pool."""

    number: int
    current_level: str
    config_level: str
    current_protection: int
    expected_protection: int
    is_ssd_cache: bool
    progress: int

    @classmethod
    def from_api(cls, d: dict[str, Any]) -> RaidGroup:
        return cls(
            number=_i0(d.get("number")),
            current_level=_s(d.get("currentLevel")),
            config_level=_s(d.get("configLevel")),
            current_protection=_i0(d.get("currentProtection")),
            expected_protection=_i0(d.get("expectedProtection")),
            is_ssd_cache=_b(d.get("isSSDCache")),
            progress=_i0(d.get("progress")),
        )


@dataclass(frozen=True, slots=True)
class Pool:
    """A storage pool."""

    number: int
    id: str
    prefer_level: str
    type: str
    status: str
    capacity: int  # bytes
    usage: int  # bytes
    raid_groups: tuple[RaidGroup, ...]
    initializing_status: str
    scrubbing_status: str

    @property
    def raid_level(self) -> str:
        if self.raid_groups:
            return self.raid_groups[0].current_level
        return self.prefer_level

    @property
    def available(self) -> int:
        return max(self.capacity - self.usage, 0)

    @property
    def usage_percent(self) -> float:
        return round(self.usage / self.capacity * 100, 1) if self.capacity else 0.0

    @property
    def is_healthy(self) -> bool:
        return self.status == "fullyOperational"

    @classmethod
    def from_api(cls, d: dict[str, Any]) -> Pool:
        groups = tuple(RaidGroup.from_api(g) for g in d.get("raidGroups") or [])
        scrub = d.get("dataScrubbing") or {}
        return cls(
            number=_i0(d.get("number")),
            id=_s(d.get("id")),
            prefer_level=_s(d.get("preferLevel")),
            type=_s(d.get("type")),
            status=_s(d.get("status")),
            capacity=_i0(d.get("capacity")),
            usage=_i0(d.get("usage")),
            raid_groups=groups,
            initializing_status=_s(d.get("initializingStatus")),
            scrubbing_status=_s(scrub.get("status")),
        )


@dataclass(frozen=True, slots=True)
class Storage:
    """The full storage snapshot: pools + disks + cache slots."""

    pools: tuple[Pool, ...]
    disks: tuple[Disk, ...]
    cache_slot_count: int

    @property
    def total_capacity(self) -> int:
        return sum(p.capacity for p in self.pools)

    @property
    def total_usage(self) -> int:
        return sum(p.usage for p in self.pools)

    @property
    def total_available(self) -> int:
        return max(self.total_capacity - self.total_usage, 0)

    @property
    def usage_percent(self) -> float:
        cap = self.total_capacity
        return round(self.total_usage / cap * 100, 1) if cap else 0.0

    @property
    def at_risk_disk_count(self) -> int:
        return sum(1 for d in self.disks if not d.is_healthy)

    @property
    def average_disk_temperature(self) -> float | None:
        temps = [d.temperature for d in self.disks if d.temperature is not None]
        return round(sum(temps) / len(temps), 1) if temps else None

    def disks_for_pool(self, pool_id: str) -> tuple[Disk, ...]:
        return tuple(d for d in self.disks if d.pool_id == pool_id)

    @classmethod
    def from_api(cls, d: dict[str, Any]) -> Storage:
        pools = tuple(Pool.from_api(p) for p in d.get("pools") or [])
        disks = tuple(Disk.from_api(x) for x in d.get("disks") or [])
        cache = d.get("cacheSlots") or []
        return cls(pools=pools, disks=disks, cache_slot_count=len(cache))


@dataclass(frozen=True, slots=True)
class DeviceInfo:
    """System telemetry from the Drive device-info endpoint."""

    name: str
    model: str
    version: str  # Drive app version
    firmware_version: str  # UniFi OS version
    status: str
    cpu_load: float  # fraction 0..1
    cpu_temperature: float | None  # °C
    memory_total_kb: int
    memory_free_kb: int
    memory_available_kb: int

    @property
    def cpu_percent(self) -> float:
        return round(self.cpu_load * 100, 1)

    @property
    def memory_used_kb(self) -> int:
        return max(self.memory_total_kb - self.memory_available_kb, 0)

    @property
    def memory_percent(self) -> float:
        total = self.memory_total_kb
        return round(self.memory_used_kb / total * 100, 1) if total else 0.0

    @classmethod
    def from_api(cls, d: dict[str, Any]) -> DeviceInfo:
        cpu = d.get("cpu") or {}
        mem = d.get("memory") or {}
        temp = cpu.get("temperature")
        return cls(
            name=_s(d.get("name")),
            model=_s(d.get("model")),
            version=_s(d.get("version")),
            firmware_version=_s(d.get("firmwareVersion")),
            status=_s(d.get("status")),
            cpu_load=_f(cpu.get("currentload")),
            cpu_temperature=_f(temp) if temp is not None else None,
            memory_total_kb=_i0(mem.get("total")),
            memory_free_kb=_i0(mem.get("free")),
            memory_available_kb=_i0(mem.get("available")),
        )


@dataclass(frozen=True, slots=True)
class NetworkIO:
    """Instantaneous network throughput."""

    rx_kbps: float
    tx_kbps: float
    timestamp: str

    @classmethod
    def from_api(cls, d: dict[str, Any]) -> NetworkIO:
        return cls(
            rx_kbps=_f(d.get("receiveKBPS")),
            tx_kbps=_f(d.get("transmitKBPS")),
            timestamp=_s(d.get("timestamp")),
        )


@dataclass(frozen=True, slots=True)
class Share:
    """A shared drive (SMB/NFS share)."""

    id: str
    name: str
    type: str
    status: str
    storage_pool_id: str
    quota_bytes: int | None  # None == unlimited
    usage: int
    member_count: int
    snapshot_enabled: bool
    encryption_status: str
    remote_backup_enabled: bool

    @classmethod
    def from_api(cls, d: dict[str, Any]) -> Share:
        prot = d.get("protections") or {}
        quota = _i(d.get("quota"))
        return cls(
            id=_s(d.get("id")),
            name=_s(d.get("name")),
            type=_s(d.get("type")),
            status=_s(d.get("status")),
            storage_pool_id=_s(d.get("storagePoolId")),
            quota_bytes=None if quota is None or quota < 0 else quota,
            usage=_i0(d.get("usage")),
            member_count=_i0(d.get("memberCount")),
            snapshot_enabled=_b(prot.get("snapshotEnabled")),
            encryption_status=_s(prot.get("encryptionStatus")),
            remote_backup_enabled=_b(prot.get("remoteBackupEnabled")),
        )


@dataclass(frozen=True, slots=True)
class SystemIdentity:
    """Public device identity from the short /api/system payload."""

    mac: str
    name: str
    model_shortname: str
    device_state: str

    @classmethod
    def from_api(cls, d: dict[str, Any]) -> SystemIdentity:
        hw = d.get("hardware") or {}
        return cls(
            mac=_s(d.get("mac")),
            name=_s(d.get("name")),
            model_shortname=_s(hw.get("shortname")),
            device_state=_s(d.get("deviceState")),
        )
