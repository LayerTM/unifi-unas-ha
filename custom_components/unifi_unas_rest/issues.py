"""Repair issues this integration raises.

Its own module because setup and the coordinator both raise issues, and the
coordinator importing the package root would be a cycle.
"""

from __future__ import annotations

from collections.abc import Callable

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from .aiounas import Pool, Storage, UnasCertificateMismatch
from .const import (
    DOMAIN,
    ISSUE_CERT_MISMATCH,
    ISSUE_DISK_AT_RISK,
    ISSUE_POOL_AT_RISK,
    ISSUE_POOL_FILESYSTEM,
)


def raise_cert_mismatch(
    hass: HomeAssistant, entry: ConfigEntry, err: UnasCertificateMismatch
) -> None:
    """Raise the repair that shows both fingerprints and offers the new one."""
    ir.async_create_issue(
        hass,
        DOMAIN,
        f"{ISSUE_CERT_MISMATCH}_{entry.entry_id}",
        is_fixable=True,
        severity=ir.IssueSeverity.ERROR,
        translation_key=ISSUE_CERT_MISMATCH,
        translation_placeholders={
            "host": entry.data[CONF_HOST],
            "expected": err.expected,
            "got": err.got,
        },
        data={
            "entry_id": entry.entry_id,
            "expected": err.expected,
            "fingerprint": err.got,
        },
    )


def clear_cert_mismatch(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Withdraw the certificate repair; a no-op when none is raised."""
    ir.async_delete_issue(hass, DOMAIN, f"{ISSUE_CERT_MISMATCH}_{entry.entry_id}")


def _sync(hass: HomeAssistant, prefix: str, wanted: dict[str, tuple[str, dict[str, str]]]) -> None:
    """Raise every wanted repair under *prefix* and withdraw the rest.

    *wanted* maps an issue id to its translation key and placeholders. A repair
    stays exactly as long as the console reports its condition, so one that
    recovered never leaves a stale warning behind.
    """
    for issue_id, (translation_key, placeholders) in wanted.items():
        ir.async_create_issue(
            hass,
            DOMAIN,
            issue_id,
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key=translation_key,
            translation_placeholders=placeholders,
        )
    for domain, issue_id in list(ir.async_get(hass).issues):
        if domain == DOMAIN and issue_id.startswith(prefix) and issue_id not in wanted:
            ir.async_delete_issue(hass, DOMAIN, issue_id)


def sync_storage_issues(
    hass: HomeAssistant, entry: ConfigEntry, console: str, storage: Storage | None
) -> None:
    """Make the storage repairs match what the console reports right now.

    The "problem" binary sensors say the same thing, but a sensor nobody watches
    is not a warning; Repairs is where a failing drive or pool reaches the
    person who can act on it.

    - One repair per bay whose drive is at risk. An empty bay is never at risk
      (`Disk.is_at_risk`), so a NAS that is not fully populated raises nothing
      for its empty slots. The serial number stays out of the text: a repair is
      shown in notifications and copied into screenshots.
    - One repair per pool the console flags at risk or with bad blocks on its
      array; the vendor's remedy is a data scrub.
    - One repair per pool with file-system errors. Repairing a file system is
      invasive and can lose data, so the repair points to UniFi Drive and this
      integration never starts it.
    """
    disks = storage.disks if storage is not None else ()
    pools = storage.pools if storage is not None else ()
    disk_prefix = f"{ISSUE_DISK_AT_RISK}_{entry.entry_id}_"
    _sync(
        hass,
        disk_prefix,
        {
            f"{disk_prefix}{disk.slot}": (
                ISSUE_DISK_AT_RISK,
                {
                    "console": console,
                    "bay": disk.slot,
                    "model": disk.model or "unknown model",
                    "state": disk.state or "unknown",
                    "reasons": ", ".join(disk.risk_reasons) or "none reported",
                },
            )
            for disk in disks
            if disk.is_at_risk
        },
    )
    pool_conditions: tuple[tuple[str, Callable[[Pool], bool]], ...] = (
        (ISSUE_POOL_AT_RISK, lambda pool: pool.is_at_risk),
        (ISSUE_POOL_FILESYSTEM, lambda pool: pool.has_filesystem_issue),
    )
    for translation_key, condition in pool_conditions:
        prefix = f"{translation_key}_{entry.entry_id}_"
        _sync(
            hass,
            prefix,
            {
                f"{prefix}{pool.key}": (
                    translation_key,
                    {
                        "console": console,
                        "pool": str(pool.number),
                        "state": pool.status or "unknown",
                    },
                )
                for pool in pools
                if condition(pool)
            },
        )


def clear_storage_issues(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Withdraw every storage repair of this entry (it is unloaded or removed)."""
    sync_storage_issues(hass, entry, "", None)
