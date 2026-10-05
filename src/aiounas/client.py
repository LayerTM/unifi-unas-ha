"""High-level UNAS client: endpoint methods returning typed models."""

from __future__ import annotations

import time
from typing import Any

import aiohttp

from .auth import AbstractAuth
from .const import (
    DEFAULT_PORT,
    DEFAULT_TIMEOUT,
    PATH_DEVICE_INFO,
    PATH_FAN_CONTROL,
    PATH_LOGS,
    PATH_NETWORK_IO,
    PATH_NOTIFICATIONS,
    PATH_SHARES,
    PATH_STORAGE,
    PATH_STORAGE_IO,
    PATH_SYSTEM,
    PATH_USERS,
    STORAGE_IO_INTERVAL,
)
from .exceptions import UnasApiError, UnasCapabilityError
from .models import (
    DeviceInfo,
    FanControl,
    LogSummary,
    NetworkIO,
    NotificationSummary,
    Share,
    Storage,
    StorageIO,
    SystemIdentity,
    UpdateInfo,
)
from .transport import UnasTransport

_SHARES_HINT = "shares require session (username/password) auth"
_USERS_HINT = "the user count requires session (username/password) auth"
_SESSION_HINT = "requires session (username/password) auth"


class UnasClient:
    """Read-only client for the UNAS Drive REST API.

    The caller owns *session*; the client never closes it.
    """

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
        """Run the auth handshake once (optional; done lazily otherwise)."""
        await self._transport.async_prepare()

    async def get_storage(self) -> Storage:
        return Storage.from_api(await self._transport.get_json(PATH_STORAGE))

    async def get_device_info(self) -> DeviceInfo:
        return DeviceInfo.from_api(await self._transport.get_json(PATH_DEVICE_INFO))

    async def get_network_io(self) -> NetworkIO:
        return NetworkIO.from_api(await self._transport.get_json(PATH_NETWORK_IO))

    async def get_fan_control(self) -> FanControl:
        """Return the fan profile and available profiles (readable with either auth)."""
        return FanControl.from_api(await self._transport.get_json(PATH_FAN_CONTROL))

    async def get_identity(self) -> SystemIdentity:
        return SystemIdentity.from_api(await self._transport.get_json(PATH_SYSTEM))

    async def get_update_info(self) -> UpdateInfo:
        """Firmware/app update availability from the full /api/system.

        The full payload is returned to session auth; an API key gets a short
        payload with no firmware/apps data (the latest-version fields are None).
        """
        return UpdateInfo.from_api(await self._transport.get_json(PATH_SYSTEM))

    async def get_shares(self) -> list[Share]:
        """Return shared drives (session auth only).

        An API key is denied here (403, or 500 on some firmware); both are
        surfaced as :class:`UnasCapabilityError` with a clear hint.
        """
        data = await self._get_session_only(PATH_SHARES, _SHARES_HINT)
        drives = data.get("drives") if isinstance(data, dict) else None
        return [Share.from_api(item) for item in (drives or []) if isinstance(item, dict)]

    async def get_user_count(self) -> int:
        """Return the number of local accounts, retaining no account data.

        Only the total is read; the user list (which is PII — names, emails) is
        never returned or stored. Session auth only; an API key is denied
        (403, or 500 on some firmware), surfaced as :class:`UnasCapabilityError`.
        """
        data = await self._get_session_only(PATH_USERS, _USERS_HINT)
        if isinstance(data, dict):
            total = data.get("total")
            if isinstance(total, int):
                return total
            rows = data.get("data")
            return len(rows) if isinstance(rows, list) else 0
        return len(data) if isinstance(data, list) else 0

    async def get_notification_summary(self) -> NotificationSummary:
        """Recent-notification counts by category (session-only).

        Only counts and the latest timestamp are kept; the notification bodies
        (``event_data`` / ``cef_log``) are PII and are never returned or stored.
        """
        return NotificationSummary.from_api(await self._get_session_only(PATH_NOTIFICATIONS))

    async def get_log_summary(self) -> LogSummary:
        """Recent-log entry count + latest timestamp (session-only).

        Log bodies (the ``data`` field) are PII and are never returned or stored.
        """
        return LogSummary.from_api(await self._get_session_only(PATH_LOGS))

    async def get_storage_io(self) -> StorageIO:
        """System-wide disk throughput over the latest completed bucket (session-only).

        Asks for exactly one bucket ending now; the console snaps the window to
        completed buckets, so the answer is the most recent finished average.
        """
        end = int(time.time())
        start = end - STORAGE_IO_INTERVAL
        path = f"{PATH_STORAGE_IO}?interval={STORAGE_IO_INTERVAL}&start={start}&end={end}"
        return StorageIO.from_api(await self._get_session_only(path))

    async def _get_session_only(self, path: str, hint: str = _SESSION_HINT) -> Any:
        """GET a read that UniFi OS serves to a local account only.

        An API key is refused with 403, or 500 on some firmware; both surface as
        :class:`UnasCapabilityError` carrying *hint*.
        """
        try:
            return await self._transport.get_json(path)
        except UnasCapabilityError as err:
            raise UnasCapabilityError(hint) from err
        except UnasApiError as err:
            if err.status == 500:
                raise UnasCapabilityError(hint) from err
            raise

    async def close(self) -> None:
        """Release client resources.

        A no-op: the ``aiohttp`` session is owned by the caller and is never
        closed here. Present so consumers (CLI/MCP) can call it unconditionally.
        """
