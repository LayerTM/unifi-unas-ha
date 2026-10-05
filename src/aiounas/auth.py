"""Authentication strategies for the UNAS local REST API.

Two interchangeable strategies:

* :class:`ApiKeyAuth` — sends ``X-API-Key`` on every request; no handshake.
* :class:`SessionAuth` — primes a CSRF token from the console root, logs in via
  ``POST /api/auth/login``, and captures the ``TOKEN`` cookie manually (a shared
  ``aiohttp`` session backed by an IP host will not persist it otherwise).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from http import HTTPStatus

import aiohttp

from .const import (
    COOKIE_TOKEN,
    HEADER_API_KEY,
    HEADER_CSRF,
    HEADER_CSRF_UPDATED,
    PATH_LOGIN,
)
from .exceptions import UnasAuthError, UnasConnectionError, describe
from .tls import mismatch_from


class AbstractAuth(ABC):
    """Strategy interface consumed by the transport."""

    can_reauth: bool = False

    @abstractmethod
    def headers(self) -> dict[str, str]:
        """Return auth headers to attach to every request."""

    async def async_prepare(
        self,
        session: aiohttp.ClientSession,
        base_url: str,
        *,
        ssl: bool | aiohttp.Fingerprint = True,
    ) -> None:
        """Perform any handshake needed before the first request (default: none)."""
        return None

    async def async_reauth(
        self,
        session: aiohttp.ClientSession,
        base_url: str,
        *,
        ssl: bool | aiohttp.Fingerprint = True,
    ) -> bool:
        """Re-authenticate after a 401. Return True if a retry is worthwhile."""
        return False


class ApiKeyAuth(AbstractAuth):
    """Static ``X-API-Key`` authentication (recommended for read-only)."""

    can_reauth = False

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    def headers(self) -> dict[str, str]:
        return {HEADER_API_KEY: self._api_key}


# 4xx answers that defer the login instead of refusing the credential.
_LOGIN_NOT_NOW = frozenset({HTTPStatus.REQUEST_TIMEOUT, HTTPStatus.TOO_MANY_REQUESTS})


def _raise_for_login_status(status: int) -> None:
    """Classify the console's answer to the login request.

    Only a refusal of the credential is an auth error: a 4xx, or a 2xx without a
    token (checked by the caller). Home Assistant answers an auth error by asking
    the user to retype the password, so everything that means "the console could
    not answer yet" — a redirect to its UI, a 5xx while it boots, a 4xx that says
    "not now" rather than "no" — is a connection error, which is retried instead.
    """
    if 300 <= status < 400 or status >= 500:
        raise UnasConnectionError(
            f"console answered the login with status {status}; "
            "it is most likely booting, updating or restarting"
        )
    if status in _LOGIN_NOT_NOW:
        raise UnasConnectionError(
            f"console could not take the login now (status {status} {HTTPStatus(status).phrase})"
        )
    if status in (401, 403):
        raise UnasAuthError("invalid credentials")
    if status >= 400:
        raise UnasAuthError(f"login refused with status {status}")


class SessionAuth(AbstractAuth):
    """Local-account session authentication (CSRF + TOKEN cookie)."""

    can_reauth = True

    def __init__(self, username: str, password: str) -> None:
        self._username = username
        self._password = password
        self._csrf: str | None = None
        self._token: str | None = None

    def headers(self) -> dict[str, str]:
        headers: dict[str, str] = {}
        if self._csrf:
            headers[HEADER_CSRF] = self._csrf
        if self._token:
            headers["Cookie"] = f"{COOKIE_TOKEN}={self._token}"
        return headers

    async def async_prepare(
        self,
        session: aiohttp.ClientSession,
        base_url: str,
        *,
        ssl: bool | aiohttp.Fingerprint = True,
    ) -> None:
        await self._login(session, base_url, ssl)

    async def async_reauth(
        self,
        session: aiohttp.ClientSession,
        base_url: str,
        *,
        ssl: bool | aiohttp.Fingerprint = True,
    ) -> bool:
        await self._login(session, base_url, ssl)
        return True

    async def _login(
        self, session: aiohttp.ClientSession, base_url: str, ssl: bool | aiohttp.Fingerprint
    ) -> None:
        # 1) prime CSRF from the console root
        try:
            async with session.get(f"{base_url}/", ssl=ssl) as resp:
                self._capture(resp)
        except aiohttp.ServerFingerprintMismatch as err:
            raise mismatch_from(err) from err
        except (aiohttp.ClientError, TimeoutError) as err:
            # Not a refusal: the credentials were never checked. Filed as an auth
            # error, Home Assistant would ask the user to retype a password that
            # is fine, for a console that was merely unreachable. A session-level
            # ``aiohttp.ClientTimeout`` raises a bare ``TimeoutError``, which is
            # not a ``ClientError``.
            raise UnasConnectionError(f"could not reach console: {describe(err)}") from err

        # 2) log in
        payload = {
            "username": self._username,
            "password": self._password,
            "rememberMe": True,
            "remember": True,
        }
        request_headers = {HEADER_CSRF: self._csrf} if self._csrf else {}
        try:
            async with session.post(
                f"{base_url}{PATH_LOGIN}",
                json=payload,
                headers=request_headers,
                ssl=ssl,
                # A console that is not serving its API yet redirects to its web
                # UI; followed, that ends as a 200 page without a token and reads
                # exactly like a refused login. Keep it visible.
                allow_redirects=False,
            ) as resp:
                _raise_for_login_status(resp.status)
                self._capture(resp)
        except aiohttp.ServerFingerprintMismatch as err:
            # A swapped certificate is not a bad password. Misfiling it as one
            # makes Home Assistant tear the entry down and demand credentials
            # that were always correct.
            raise mismatch_from(err) from err
        except (aiohttp.ClientError, TimeoutError) as err:
            raise UnasConnectionError(f"login request failed: {describe(err)}") from err

        if not self._token:
            raise UnasAuthError("login did not return a session token")

    def _capture(self, resp: aiohttp.ClientResponse) -> None:
        csrf = resp.headers.get(HEADER_CSRF) or resp.headers.get(HEADER_CSRF_UPDATED)
        if csrf:
            self._csrf = csrf
        for raw in resp.headers.getall("Set-Cookie", []):
            first = raw.split(";", 1)[0].strip()
            if first.startswith(f"{COOKIE_TOKEN}="):
                self._token = first[len(COOKIE_TOKEN) + 1 :]
                break
