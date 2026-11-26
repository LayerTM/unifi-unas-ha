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
    PATH_M365_BACKUP_TASKS,
    PATH_NETWORK_IO,
    PATH_NOTIFICATIONS,
    PATH_REMOTE_BACKUP_TASKS,
    PATH_SHARES,
    PATH_STORAGE,
    PATH_STORAGE_IO,
    PATH_SYSTEM,
    PATH_USERS,
    STORAGE_IO_INTERVAL,
)
from .exceptions import UnasApiError, UnasCapabilityError
from .models import (
    ConsoleBackup,
    DeviceInfo,
    FanControl,
    LogSummary,
    NetworkIO,
    NotificationSummary,
    Share,
    Storage,
    StorageIO,
    SystemIdentity,
    SystemReadings,
    UpdateInfo,
)
from .transport import UnasTransport

_SHARES_HINT = "shares require session (username/password) auth"
_USERS_HINT = "the user count requires session (username/password) auth"
_SESSION_HINT = "requires session (username/password) auth"


def _task_total(body: Any, rows_key: str) -> int:
    """The number of tasks in one backup task list; 0 for an unexpected shape."""
    if not isinstance(body, dict):
        return 0
    total = body.get("total")
    if isinstance(total, int) and not isinstance(total, bool):
        return total
    rows = body.get(rows_key)
    return len(rows) if isinstance(rows, list) else 0


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
        # Only a session can log in again, so this is "is not a local account".
        self._refused_with_500 = not auth.can_reauth
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

    async def get_system_readings(self) -> SystemReadings:
        """Update availability and console backup setting from ONE /api/system read."""
        return SystemReadings.from_api(await self._transport.get_json(PATH_SYSTEM))

    async def get_console_backup(self) -> ConsoleBackup:
        """Console auto-backup setting and schedule frequency from the full /api/system.

        Like :meth:`get_update_info`, an API key gets the short payload, so both
        values come back None (``has_data`` is False).
        """
        return ConsoleBackup.from_api(await self._transport.get_json(PATH_SYSTEM))

    async def get_backup_task_count(self) -> int:
        """Return how many Drive backup tasks exist (remote plus Microsoft 365).

        Only the totals are read; task names, targets and run history are never
        returned. Both lists must answer: a count of one list would read as the
        count of all of them. A refusal surfaces as :class:`UnasCapabilityError`.
        """
        remote = await self._get_session_only(PATH_REMOTE_BACKUP_TASKS)
        m365 = await self._get_session_only(PATH_M365_BACKUP_TASKS)
        return _task_total(remote, "data") + _task_total(m365, "tasks")

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

        A refusal surfaces as :class:`UnasCapabilityError` carrying *hint*: a 403,
        or for an API key also the 500 some firmware refuses it with. A 500 to a
        local account is the console failing and stays :class:`UnasApiError`, so
        it is never taken to mean the reading is out of scope.
        """
        try:
            return await self._transport.get_json(path)
        except UnasCapabilityError as err:
            raise UnasCapabilityError(hint) from err
        except UnasApiError as err:
            if err.status == 500 and self._refused_with_500:
                raise UnasCapabilityError(hint) from err
            raise

    def allow_one_retry(self, delay: float) -> None:
        """Let the reads that follow share one delayed second attempt.

        Meant to be called once per round of reads, such as a poll. A read that
        gets no answer, or a 502, 503 or 504, waits *delay* seconds and is sent
        once more. Reads failing in the same wait join it; a read sent after it
        fails at once, so a console that is away costs one wait. Without this
        call nothing is retried.
        """
        self._transport.allow_one_retry(delay)

    def cancel_retry(self) -> None:
        """End a wait in progress at once, for example on shutdown."""
        self._transport.cancel_retry()

    async def close(self) -> None:
        """Release client resources.

        A no-op: the ``aiohttp`` session is owned by the caller and is never
        closed here. Present so consumers (CLI/MCP) can call it unconditionally.
        """
