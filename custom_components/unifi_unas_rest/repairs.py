"""Repair flows for the TLS trust of a UniFi UNAS entry.

Two things can go wrong with a pinned certificate, and neither is an
authentication problem, so neither belongs in the reauth flow:

* the console now serves a different certificate — it was reissued, or something
  is impersonating it. Only the user can tell those apart, so both fingerprints
  are shown and accepting the new one is an explicit act.
* the entry predates pinning and still verifies nothing. It keeps working; this
  offers the one-time step that starts pinning.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.components.repairs import RepairsFlow
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult

from .aiounas import TlsMode, UnasConnectionError, async_probe_fingerprint
from .const import (
    CONF_CERT_FINGERPRINT,
    CONF_TLS_MODE,
    DEFAULT_PORT,
    DOMAIN,
    ISSUE_CERT_MISMATCH,
)


class _PinCertificateFlow(RepairsFlow):
    """Shared tail: store a fingerprint on the entry and reload it."""

    def __init__(self, entry_id: str) -> None:
        self._entry_id = entry_id

    async def _async_pin(self, hass: HomeAssistant, fingerprint: str) -> FlowResult:
        entry = hass.config_entries.async_get_entry(self._entry_id)
        if entry is None:
            return self.async_abort(reason="entry_not_found")
        hass.config_entries.async_update_entry(
            entry,
            data={
                **entry.data,
                CONF_TLS_MODE: TlsMode.FINGERPRINT,
                CONF_CERT_FINGERPRINT: fingerprint,
            },
        )
        await hass.config_entries.async_reload(entry.entry_id)
        return self.async_create_entry(data={})


class CertMismatchRepairFlow(_PinCertificateFlow):
    """Accept a certificate that replaced the pinned one."""

    def __init__(self, entry_id: str, expected: str, got: str) -> None:
        super().__init__(entry_id)
        self._expected = expected
        self._got = got

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        return await self.async_step_confirm()

    async def async_step_confirm(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if user_input is not None:
            return await self._async_pin(self.hass, self._got)
        return self.async_show_form(
            step_id="confirm",
            data_schema=vol.Schema({}),
            description_placeholders={"expected": self._expected, "got": self._got},
        )


class TlsInsecureRepairFlow(_PinCertificateFlow):
    """Start pinning on an entry that currently verifies nothing."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        return await self.async_step_confirm()

    async def async_step_confirm(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        entry = self.hass.config_entries.async_get_entry(self._entry_id)
        if entry is None:
            return self.async_abort(reason="entry_not_found")
        try:
            fingerprint = await async_probe_fingerprint(
                entry.data[CONF_HOST], entry.data.get(CONF_PORT, DEFAULT_PORT)
            )
        except UnasConnectionError:
            return self.async_abort(reason="cannot_connect")
        if user_input is not None:
            return await self._async_pin(self.hass, fingerprint)
        return self.async_show_form(
            step_id="confirm",
            data_schema=vol.Schema({}),
            description_placeholders={"fingerprint": fingerprint},
        )


async def async_create_fix_flow(
    hass: HomeAssistant, issue_id: str, data: dict[str, str | int | float | None] | None
) -> RepairsFlow:
    """Build the flow for one of this integration's repair issues."""
    payload = data or {}
    entry_id = str(payload.get("entry_id", ""))
    if issue_id.startswith(ISSUE_CERT_MISMATCH):
        return CertMismatchRepairFlow(
            entry_id, str(payload.get("expected", "")), str(payload.get("fingerprint", ""))
        )
    return TlsInsecureRepairFlow(entry_id)


__all__ = ["DOMAIN", "async_create_fix_flow"]
