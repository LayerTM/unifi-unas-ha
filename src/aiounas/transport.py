"""GET-only HTTP transport over the UNAS local REST API.

Read-only by construction: only ``GET`` is issued. Maps HTTP status codes to the
typed exception hierarchy and retries once through the auth strategy on 401.
"""

from __future__ import annotations

import asyncio
from typing import Any

import aiohttp

from .auth import AbstractAuth
from .const import DEFAULT_PORT, DEFAULT_TIMEOUT, DEFAULT_VERIFY_SSL
from .exceptions import (
    UnasApiError,
    UnasAuthError,
    UnasCapabilityError,
    UnasConnectionError,
)


class UnasTransport:
    """Issue authenticated GET requests and map failures to typed errors."""

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
        self._session = session
        self._auth = auth
        self._timeout = timeout
        self._ssl = verify_ssl
        scheme = "https" if use_ssl else "http"
        default_port = 443 if use_ssl else 80
        netloc = host if port == default_port else f"{host}:{port}"
        self._base_url = f"{scheme}://{netloc}"
        self._prepared = False

    @property
    def base_url(self) -> str:
        return self._base_url

    async def async_prepare(self) -> None:
        """Run the auth handshake once (idempotent)."""
        if not self._prepared:
            await self._auth.async_prepare(self._session, self._base_url, ssl=self._ssl)
            self._prepared = True

    async def get_json(self, path: str, *, allow_reauth: bool = True) -> Any:
        """GET *path* and return parsed JSON, or raise a typed error."""
        await self.async_prepare()
        status, data = await self._request(path)

        if (
            status == 401
            and allow_reauth
            and self._auth.can_reauth
            and await self._auth.async_reauth(self._session, self._base_url, ssl=self._ssl)
        ):
            status, data = await self._request(path)

        if status == 401:
            raise UnasAuthError(f"unauthorized for {path}")
        if status == 403:
            raise UnasCapabilityError(f"forbidden for {path}")
        if status >= 400:
            raise UnasApiError(f"unexpected status {status} for {path}", status=status)
        return data

    async def _request(self, path: str) -> tuple[int, Any]:
        url = f"{self._base_url}{path}"
        headers = {"Accept": "application/json", **self._auth.headers()}
        try:
            async with (
                asyncio.timeout(self._timeout),
                self._session.get(url, headers=headers, ssl=self._ssl) as resp,
            ):
                if resp.status < 400:
                    return resp.status, await resp.json()
                await resp.read()
                return resp.status, None
        except (aiohttp.ClientError, TimeoutError) as err:
            raise UnasConnectionError(str(err)) from err
