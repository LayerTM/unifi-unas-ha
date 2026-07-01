"""High-level UNAS client: endpoint methods returning typed models."""

from __future__ import annotations

import aiohttp

from .auth import AbstractAuth
from .const import (
    DEFAULT_PORT,
    DEFAULT_TIMEOUT,
    DEFAULT_VERIFY_SSL,
    PATH_DEVICE_INFO,
    PATH_NETWORK_IO,
    PATH_SHARES,
    PATH_STORAGE,
    PATH_SYSTEM,
    PATH_USERS,
)
from .exceptions import UnasApiError, UnasCapabilityError
from .models import DeviceInfo, NetworkIO, Share, Storage, SystemIdentity, UpdateInfo
from .transport import UnasTransport

_SHARES_HINT = "shares require session (username/password) auth"
_USERS_HINT = "the user count requires session (username/password) auth"


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
        verify_ssl: bool = DEFAULT_VERIFY_SSL,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> None:
        self._transport = UnasTransport(
            session,
            host,
            auth,
            port=port,
            use_ssl=use_ssl,
            verify_ssl=verify_ssl,
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
        try:
            data = await self._transport.get_json(PATH_SHARES)
        except UnasCapabilityError as err:
            raise UnasCapabilityError(_SHARES_HINT) from err
        except UnasApiError as err:
            if err.status == 500:
                raise UnasCapabilityError(_SHARES_HINT) from err
            raise
        drives = data.get("drives") if isinstance(data, dict) else None
        return [Share.from_api(item) for item in (drives or []) if isinstance(item, dict)]

    async def get_user_count(self) -> int:
        """Return the number of local accounts, retaining no account data.

        Only the total is read; the user list (which is PII — names, emails) is
        never returned or stored. Session auth only; an API key is denied
        (403, or 500 on some firmware), surfaced as :class:`UnasCapabilityError`.
        """
        try:
            data = await self._transport.get_json(PATH_USERS)
        except UnasCapabilityError as err:
            raise UnasCapabilityError(_USERS_HINT) from err
        except UnasApiError as err:
            if err.status == 500:
                raise UnasCapabilityError(_USERS_HINT) from err
            raise
        if isinstance(data, dict):
            total = data.get("total")
            if isinstance(total, int):
                return total
            rows = data.get("data")
            return len(rows) if isinstance(rows, list) else 0
        return len(data) if isinstance(data, list) else 0

    async def close(self) -> None:
        """Release client resources.

        A no-op: the ``aiohttp`` session is owned by the caller and is never
        closed here. Present so consumers (CLI/MCP) can call it unconditionally.
        """
