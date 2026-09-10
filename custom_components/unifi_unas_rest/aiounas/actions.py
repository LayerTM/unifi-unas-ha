"""Write / action client for the UNAS local REST API.

Constructing a :class:`UnasActionClient` is a deliberate opt-in to state-changing
operations — it is intentionally separate from the read-only :class:`UnasClient`
so read paths (including a read-only MCP mode) keep their no-write guarantee.

Power and firmware/app-update endpoints are well-established. ``set_fan_profile``
targets the undocumented Drive fan-control endpoint; its payload was confirmed
against live hardware — ``PUT`` expects ``{"profile": <name>}`` (note the GET
response reports the value under ``currentProfile`` instead). Known profiles:
``cooling``, ``default``, ``quiet``.
"""

from __future__ import annotations

import aiohttp

from .auth import AbstractAuth
from .const import (
    DEFAULT_PORT,
    DEFAULT_TIMEOUT,
    PATH_DRIVE_UPDATE,
    PATH_FAN_CONTROL,
    PATH_FIRMWARE_UPDATE,
    PATH_POWEROFF,
    PATH_REBOOT,
)
from .transport import UnasTransport


class UnasActionClient:
    """Opt-in client for state-changing UNAS operations."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        host: str,
        auth: AbstractAuth,
        *,
        port: int = DEFAULT_PORT,
        use_ssl: bool = True,
        ssl: bool | aiohttp.Fingerprint = True,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> None:
        self._transport = UnasTransport(
            session,
            host,
            auth,
            port=port,
            use_ssl=use_ssl,
            ssl=ssl,
            timeout=timeout,
        )

    @property
    def base_url(self) -> str:
        return self._transport.base_url

    async def async_prepare(self) -> None:
        await self._transport.async_prepare()

    async def reboot(self) -> None:
        """Reboot the console."""
        await self._transport.send("POST", PATH_REBOOT)

    async def shutdown(self) -> None:
        """Power the console off."""
        await self._transport.send("POST", PATH_POWEROFF)

    async def update_firmware(self) -> None:
        """Install the available UniFi OS firmware update."""
        await self._transport.send("POST", PATH_FIRMWARE_UPDATE)

    async def update_drive_app(self) -> None:
        """Install the available UniFi Drive application update."""
        await self._transport.send("POST", PATH_DRIVE_UPDATE)

    async def set_fan_profile(self, profile: str) -> None:
        """Set the fan profile. Known values: 'cooling', 'default', 'quiet'."""
        await self._transport.send("PUT", PATH_FAN_CONTROL, json_body={"profile": profile})
