"""Repair issues this integration raises.

Its own module because setup and the coordinator both raise issues, and the
coordinator importing the package root would be a cycle.
"""

from __future__ import annotations

from collections.abc import Iterable

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from .aiounas import Disk, UnasCertificateMismatch
from .const import DOMAIN, ISSUE_CERT_MISMATCH, ISSUE_DISK_AT_RISK


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


def _disk_issue_prefix(entry: ConfigEntry) -> str:
    return f"{ISSUE_DISK_AT_RISK}_{entry.entry_id}_"


def sync_disk_risk(
    hass: HomeAssistant, entry: ConfigEntry, console: str, disks: Iterable[Disk]
) -> None:
    """Make the disk-at-risk repairs match the drives that are at risk right now.

    The "problem" binary sensor on each disk says the same thing, but a sensor
    nobody watches is not a warning; Repairs is where a failing drive reaches
    the person who can replace it. One repair per bay, raised when the drive
    turns at risk and withdrawn when it recovers or is pulled. An empty bay is
    never at risk (`Disk.is_at_risk`), so a NAS that is not fully populated
    raises nothing for its empty slots. The serial number stays out of the text:
    a repair is shown in notifications and copied into screenshots.
    """
    prefix = _disk_issue_prefix(entry)
    raised: set[str] = set()
    for disk in disks:
        if not disk.is_at_risk:
            continue
        issue_id = f"{prefix}{disk.slot}"
        raised.add(issue_id)
        ir.async_create_issue(
            hass,
            DOMAIN,
            issue_id,
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key=ISSUE_DISK_AT_RISK,
            translation_placeholders={
                "console": console,
                "bay": disk.slot,
                "model": disk.model or "unknown model",
                "state": disk.state or "unknown",
                "reasons": ", ".join(disk.risk_reasons) or "none reported",
            },
        )
    for domain, issue_id in list(ir.async_get(hass).issues):
        if domain == DOMAIN and issue_id.startswith(prefix) and issue_id not in raised:
            ir.async_delete_issue(hass, DOMAIN, issue_id)


def clear_disk_risk(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Withdraw every disk repair of this entry (it is unloaded or removed)."""
    sync_disk_risk(hass, entry, "", ())
