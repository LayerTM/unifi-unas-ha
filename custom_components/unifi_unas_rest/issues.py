"""Repair issues this integration raises.

Its own module because both setup and the coordinator raise the certificate
issue, and the coordinator importing the package root would be a cycle.
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from .aiounas import UnasCertificateMismatch
from .const import DOMAIN, ISSUE_API_KEY_SCOPE, ISSUE_CERT_MISMATCH


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


def review_api_key_scope(hass: HomeAssistant, entry: ConfigEntry, denied: list[str]) -> None:
    """Say which reads this API key is not authorized for, or withdraw the claim.

    UniFi OS scopes an API key to device-level reads, so shares, accounts,
    firmware detail, notifications and logs are simply not available to one. The
    integration degrades to what the key can read, and without this the only
    symptom is entities that never appear — which is what made a console that
    refuses those reads with 401 look like a broken credential. Raised once per
    entry and withdrawn the moment a reconfigure to a local account widens the
    scope, so it never outlives the condition.
    """
    issue_id = f"{ISSUE_API_KEY_SCOPE}_{entry.entry_id}"
    if not denied:
        ir.async_delete_issue(hass, DOMAIN, issue_id)
        return
    ir.async_create_issue(
        hass,
        DOMAIN,
        issue_id,
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key=ISSUE_API_KEY_SCOPE,
        translation_placeholders={
            "host": entry.data[CONF_HOST],
            "denied": ", ".join(denied),
        },
    )
