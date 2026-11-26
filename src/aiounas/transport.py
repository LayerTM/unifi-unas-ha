"""HTTP transport over the UNAS local REST API.

Maps HTTP status codes to the typed exception hierarchy and retries once through
the auth strategy on 401. Reads use :meth:`get_json`; writes use :meth:`send`.
The read client (``UnasClient``) only ever calls ``get_json`` — that is its
no-write guarantee; state-changing calls live in ``UnasActionClient``.

**Only a 401 is an authorization failure.** A redirect to the console UI, or a 2xx
carrying the UI shell instead of JSON, means the console is not serving the API
right now — it is booting, updating or restarting. Those are transient and must
stay retryable: Home Assistant treats ``ConfigEntryAuthFailed`` as terminal, so
misfiling one of them permanently detaches the config entry while the credential
is still perfectly valid.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

import aiohttp

from .auth import AbstractAuth
from .const import DEFAULT_PORT, DEFAULT_TIMEOUT
from .exceptions import (
    UnasApiError,
    UnasAuthError,
    UnasCapabilityError,
    UnasConnectionError,
    UnasOperationBlocked,
    describe,
)
from .tls import mismatch_from

_LOGGER = logging.getLogger(__name__)

# What a console answers while the application behind its proxy is briefly away.
_TRANSIENT_STATUSES = frozenset({502, 503, 504})

# A certificate that was refused (pinned or CA-verified) is refused again.
_CERTIFICATE_REFUSALS = (aiohttp.ServerFingerprintMismatch, aiohttp.ClientConnectorCertificateError)


class _DelayedRetry:
    """One wait, shared by the reads that fail around the same time.

    The first failure starts the wait. A read that was sent before the wait ended
    joins it and may be sent once more; one sent afterwards has had its chance.
    However many reads fail, the caller is therefore held up by one wait.
    """

    def __init__(self, delay: float) -> None:
        self._delay = delay
        self._ends: float | None = None
        self._cancelled = asyncio.Event()

    async def wait(self, sent_at: float) -> bool:
        """Wait out the delay for a read sent at *sent_at*; True to send it again."""
        if self._ends is None:
            self._ends = asyncio.get_running_loop().time() + self._delay
        elif sent_at >= self._ends:
            return False
        try:
            async with asyncio.timeout_at(self._ends):
                await self._cancelled.wait()
        except TimeoutError:
            return True
        return False

    def cancel(self) -> None:
        self._cancelled.set()


class _NonJsonBody:
    """Marker for a 2xx whose body is not JSON (the console served its UI)."""

    __slots__ = ()


_NON_JSON = _NonJsonBody()

CRITICAL_OPERATION_IN_PROGRESS = "CRITICAL_OPERATION_IN_PROGRESS"


def _critical_blockers(status: int, data: Any) -> tuple[str, ...] | None:
    """The operations a ``409`` names as blocking the request, else None.

    The console's own UI reads this body: ``{"code": "CRITICAL_OPERATION_IN_PROGRESS",
    "data": {"blockers": [{"description", "kind", "domain", ...}]}}``. Each
    blocker is named by its description, falling back to its kind and domain.
    Any other 409 is an ordinary refusal.
    """
    if status != 409 or not isinstance(data, dict):
        return None
    if data.get("code") != CRITICAL_OPERATION_IN_PROGRESS:
        return None
    body = data.get("data")
    raw = body.get("blockers") if isinstance(body, dict) else None
    names: list[str] = []
    for blocker in raw if isinstance(raw, list) else []:
        if not isinstance(blocker, dict):
            continue
        name = next(
            (
                v.strip()
                for v in (blocker.get("description"), blocker.get("kind"), blocker.get("domain"))
                if isinstance(v, str) and v.strip()
            ),
            None,
        )
        if name is not None:
            names.append(name)
    return tuple(names)


_T = TypeVar("_T")


class UnasTransport:
    """Issue authenticated requests and map failures to typed errors."""

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
        self._session = session
        self._auth = auth
        self._timeout = timeout
        self._ssl = ssl
        scheme = "https" if use_ssl else "http"
        default_port = 443 if use_ssl else 80
        netloc = host if port == default_port else f"{host}:{port}"
        self._base_url = f"{scheme}://{netloc}"
        self._prepared = False
        self._retry: _DelayedRetry | None = None

    @property
    def base_url(self) -> str:
        return self._base_url

    def allow_one_retry(self, delay: float) -> None:
        """Let the reads that follow share one second attempt, *delay* seconds later.

        See :class:`_DelayedRetry`. Applies to a ``GET`` that got no answer (a
        timeout or a connection failure) or a 502, 503 or 504; writes and the
        login are never sent twice by this, nor is a read whose certificate was
        refused. Each call replaces the previous allowance and ends a wait it
        still has pending.
        """
        self.cancel_retry()
        self._retry = _DelayedRetry(delay)

    def cancel_retry(self) -> None:
        """End a wait in progress at once; its reads fail with what they got."""
        if self._retry is not None:
            self._retry.cancel()

    async def async_prepare(self) -> None:
        """Run the auth handshake once (idempotent)."""
        if not self._prepared:
            await self._handshake(self._auth.async_prepare)
            self._prepared = True

    async def _handshake(self, step: Callable[..., Awaitable[_T]]) -> _T:
        """Run an auth handshake *step* under the same budget as every request.

        Without it a console that accepts the connection and never answers the
        login holds the caller for as long as the session allows, and then fails
        with a bare ``TimeoutError`` that no typed handler expects.
        """
        try:
            async with asyncio.timeout(self._timeout):
                return await step(self._session, self._base_url, ssl=self._ssl)
        except TimeoutError as err:
            raise UnasConnectionError(
                f"login did not finish within {self._timeout}s: {describe(err)}"
            ) from err

    async def get_json(self, path: str, *, allow_reauth: bool = True) -> Any:
        """GET *path* and return parsed JSON, or raise a typed error."""
        return await self._call("GET", path, expect_json=True, allow_reauth=allow_reauth)

    async def send(
        self,
        method: str,
        path: str,
        *,
        json_body: Any = None,
        allow_reauth: bool = True,
    ) -> Any:
        """Issue a write (POST/PUT/DELETE). Returns parsed JSON if present, else None."""
        return await self._call(
            method, path, json_body=json_body, expect_json=False, allow_reauth=allow_reauth
        )

    async def _call(
        self,
        method: str,
        path: str,
        *,
        json_body: Any = None,
        expect_json: bool = True,
        allow_reauth: bool = True,
    ) -> Any:
        await self.async_prepare()
        status, data = await self._exchange(
            method, path, json_body=json_body, expect_json=expect_json
        )

        # A login shell in place of JSON can also mean a silently expired session,
        # so a session-based auth still gets its single re-login attempt here.
        if (
            (status == 401 or data is _NON_JSON)
            and allow_reauth
            and self._auth.can_reauth
            and await self._handshake(self._auth.async_reauth)
        ):
            status, data = await self._exchange(
                method, path, json_body=json_body, expect_json=expect_json
            )

        if status == 401:
            raise UnasAuthError(f"unauthorized for {path}")
        if status == 403:
            raise UnasCapabilityError(f"forbidden for {path}")
        if 300 <= status < 400:
            raise UnasApiError(
                f"console redirected {path} to its web UI "
                f"({self._location(data)}) instead of serving the API; "
                "it is most likely booting, updating or restarting",
                status=status,
            )
        blockers = _critical_blockers(status, data)
        if blockers is not None:
            raise UnasOperationBlocked(path, blockers)
        if not (200 <= status < 300):
            raise UnasApiError(f"unexpected status {status} for {path}", status=status)
        if data is _NON_JSON:
            raise UnasApiError(
                f"non-JSON response for {path}: the console served its web UI "
                "instead of the API; it is most likely booting, updating or restarting",
                status=status,
            )
        return data

    async def _exchange(
        self, method: str, path: str, *, json_body: Any, expect_json: bool
    ) -> tuple[int, Any]:
        """:meth:`_request`, sent once more if it is a read the allowance covers."""

        async def attempt() -> tuple[int, Any]:
            return await self._request(method, path, json_body=json_body, expect_json=expect_json)

        # Taken before sending: a later allowance is not this request's.
        retry = self._retry if method == "GET" else None
        if retry is None:
            return await attempt()
        sent_at = asyncio.get_running_loop().time()
        try:
            answer = await attempt()
        except UnasConnectionError as err:
            refused = isinstance(err.__cause__, _CERTIFICATE_REFUSALS)
            if refused or not await retry.wait(sent_at):
                raise
            reason = str(err)
        else:
            if answer[0] not in _TRANSIENT_STATUSES or not await retry.wait(sent_at):
                return answer
            reason = f"status {answer[0]}"
        _LOGGER.debug("Asking for %s again after: %s", path, reason)
        return await attempt()

    @staticmethod
    def _location(data: Any) -> str:
        """Redirect target captured by :meth:`_request`, for the error message."""
        return data if isinstance(data, str) else "no Location header"

    async def _request(
        self, method: str, path: str, *, json_body: Any = None, expect_json: bool = True
    ) -> tuple[int, Any]:
        url = f"{self._base_url}{path}"
        headers = {"Accept": "application/json", **self._auth.headers()}
        try:
            async with (
                asyncio.timeout(self._timeout),
                self._session.request(
                    method,
                    url,
                    headers=headers,
                    json=json_body,
                    ssl=self._ssl,
                    # aiohttp follows redirects by default. A UniFi OS console can
                    # answer an API path with a redirect to its web UI while the
                    # application behind the proxy is not up, and following it turns
                    # that into a 200 text/html that reads exactly like an expired
                    # session. Keep the redirect visible so it can be classified.
                    allow_redirects=False,
                ) as resp,
            ):
                status = resp.status
                if 300 <= status < 400:
                    await resp.read()
                    return status, resp.headers.get("Location")
                if 200 <= status < 300:
                    if expect_json:
                        try:
                            return status, await resp.json()
                        except aiohttp.ContentTypeError:
                            # The console served its UI instead of JSON. DO NOT chain
                            # the source exception: its request_info carries the
                            # session cookie / API key.
                            return status, _NON_JSON
                    # writes: an empty 2xx body is a bodyless success and a JSON
                    # body is returned as-is; any other non-empty 2xx body is the
                    # UI shell — never a false success (mirrors the read path's
                    # no-silent-failure guarantee).
                    raw = await resp.read()
                    if not raw:
                        return status, None
                    try:
                        return status, json.loads(raw)
                    except (ValueError, UnicodeDecodeError):
                        return status, _NON_JSON
                raw = await resp.read()
                if status == 409:
                    # The one refusal whose body carries a reason the caller
                    # must see (see `_critical_blockers`).
                    try:
                        return status, json.loads(raw)
                    except (ValueError, UnicodeDecodeError):
                        return status, None
                return status, None
        except aiohttp.ServerFingerprintMismatch as err:
            # Must precede ClientError: this IS one, and collapsing it into a
            # generic connection failure hides the one condition a user has to
            # act on.
            raise mismatch_from(err) from err
        except (aiohttp.ClientError, TimeoutError) as err:
            raise UnasConnectionError(f"{method} {path}: {describe(err)}") from err
