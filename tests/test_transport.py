"""Transport tests against the fake console."""

from __future__ import annotations

import asyncio
import contextlib
import itertools
import logging
import ssl
import time
from collections.abc import AsyncIterator
from unittest.mock import MagicMock

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from aiounas.auth import ApiKeyAuth, SessionAuth
from aiounas.exceptions import (
    UnasApiError,
    UnasAuthError,
    UnasCapabilityError,
    UnasConnectionError,
)
from aiounas.tls import UnasCertificateMismatch
from aiounas.transport import UnasTransport


def _transport(session: aiohttp.ClientSession, srv, auth) -> UnasTransport:
    return UnasTransport(session, srv.host, auth, port=srv.port, use_ssl=False)


async def test_get_json_ok(unas_server) -> None:
    async with aiohttp.ClientSession() as session:
        t = _transport(session, unas_server, ApiKeyAuth(unas_server.api_key))
        data = await t.get_json("/proxy/drive/api/v2/storage")
        assert "pools" in data


async def test_403_maps_to_capability_error(unas_server) -> None:
    async with aiohttp.ClientSession() as session:
        t = _transport(session, unas_server, ApiKeyAuth(unas_server.api_key))
        with pytest.raises(UnasCapabilityError):
            await t.get_json("/proxy/drive/api/v1/users")


async def test_401_without_reauth_raises_auth(unas_server) -> None:
    async with aiohttp.ClientSession() as session:
        t = _transport(session, unas_server, ApiKeyAuth("wrong-key-000000000000"))
        with pytest.raises(UnasAuthError):
            await t.get_json("/proxy/drive/api/v2/storage")


async def test_base_url_port_handling() -> None:
    async with aiohttp.ClientSession() as session:
        assert (
            UnasTransport(session, "unas.local", ApiKeyAuth("k")).base_url == "https://unas.local"
        )
        assert (
            UnasTransport(session, "unas.local", ApiKeyAuth("k"), port=8443).base_url
            == "https://unas.local:8443"
        )


async def test_connection_error_on_closed_port() -> None:
    async with aiohttp.ClientSession() as session:
        t = UnasTransport(session, "127.0.0.1", ApiKeyAuth("k"), port=1, use_ssl=False, timeout=2)
        with pytest.raises(UnasConnectionError):
            await t.get_json("/proxy/drive/api/v2/storage")


async def test_timeout_names_the_request_and_the_cause() -> None:
    """``str(TimeoutError())`` is empty; the error must still say what failed."""

    async def hang(_: web.Request) -> web.Response:
        await asyncio.sleep(5)
        return web.json_response({})

    app = web.Application()
    app.router.add_get("/proxy/drive/api/v2/storage", hang)
    server = TestServer(app)
    await server.start_server()
    try:
        async with aiohttp.ClientSession() as session:
            t = UnasTransport(
                session, server.host, ApiKeyAuth("k"), port=server.port, use_ssl=False, timeout=1
            )
            with pytest.raises(UnasConnectionError) as exc_info:
                await t.get_json("/proxy/drive/api/v2/storage")
        assert str(exc_info.value) == "GET /proxy/drive/api/v2/storage: TimeoutError"
    finally:
        await server.close()


async def test_session_reauth_on_401() -> None:
    state = {"first": True}

    async def root(_: web.Request) -> web.Response:
        return web.Response(text="", headers={"X-CSRF-Token": "c"})

    async def login(_: web.Request) -> web.Response:
        resp = web.json_response({"ok": True}, headers={"X-Updated-CSRF-Token": "c2"})
        resp.set_cookie("TOKEN", "tok", path="/")
        return resp

    async def storage(_: web.Request) -> web.Response:
        if state["first"]:
            state["first"] = False
            return web.json_response({"error": {"code": 401}}, status=401)
        return web.json_response({"pools": [], "disks": []})

    app = web.Application()
    app.router.add_get("/", root)
    app.router.add_post("/api/auth/login", login)
    app.router.add_get("/proxy/drive/api/v2/storage", storage)
    server = TestServer(app)
    await server.start_server()
    try:
        async with aiohttp.ClientSession() as session:
            t = UnasTransport(
                session,
                str(server.host),
                SessionAuth("user", "pass"),
                port=int(server.port),
                use_ssl=False,
            )
            data = await t.get_json("/proxy/drive/api/v2/storage")
            assert data == {"pools": [], "disks": []}
            assert state["first"] is False
    finally:
        await server.close()


async def test_2xx_non_json_is_api_error_without_leaking_credentials() -> None:
    """The console serving its UI is unavailability, not a rejected credential.

    Classifying it as auth makes Home Assistant raise ConfigEntryAuthFailed, which
    is terminal: one such response during a firmware update permanently detaches
    the config entry even though the credential is still valid.
    """

    async def root(_: web.Request) -> web.Response:
        return web.Response(text="", headers={"X-CSRF-Token": "c"})

    async def storage(_: web.Request) -> web.Response:
        # 200 with an HTML body: the UniFi OS UI shell served while the
        # application behind the proxy is booting, updating or restarting.
        return web.Response(text="<html>login</html>", content_type="text/html")

    app = web.Application()
    app.router.add_get("/", root)
    app.router.add_get("/proxy/drive/api/v2/storage", storage)
    server = TestServer(app)
    await server.start_server()
    try:
        async with aiohttp.ClientSession() as session:
            secret = "api-key-must-not-leak-0123456789"
            t = UnasTransport(
                session, str(server.host), ApiKeyAuth(secret), port=int(server.port), use_ssl=False
            )
            with pytest.raises(UnasApiError) as excinfo:
                await t.get_json("/proxy/drive/api/v2/storage")
            # The source ContentTypeError carries the request headers (incl. the
            # API key); it must NOT be chained onto the raised error.
            assert excinfo.value.__cause__ is None
            assert secret not in repr(excinfo.value.__cause__)
    finally:
        await server.close()


async def test_2xx_non_json_reauths_once_when_supported() -> None:
    """A session-based auth still gets its one re-login: the body may be a login shell."""
    state = {"served_shell": False}

    async def root(_: web.Request) -> web.Response:
        return web.Response(text="", headers={"X-CSRF-Token": "c"})

    async def login(_: web.Request) -> web.Response:
        return web.json_response(
            {"ok": True},
            headers={"Set-Cookie": "TOKEN=t; Path=/", "X-CSRF-Token": "c"},
        )

    async def storage(_: web.Request) -> web.Response:
        if not state["served_shell"]:
            state["served_shell"] = True
            return web.Response(text="<html>login</html>", content_type="text/html")
        return web.json_response({"pools": [], "disks": []})

    app = web.Application()
    app.router.add_get("/", root)
    app.router.add_post("/api/auth/login", login)
    app.router.add_get("/proxy/drive/api/v2/storage", storage)
    server = TestServer(app)
    await server.start_server()
    try:
        async with aiohttp.ClientSession() as session:
            t = UnasTransport(
                session,
                str(server.host),
                SessionAuth("u", "p"),
                port=int(server.port),
                use_ssl=False,
            )
            assert await t.get_json("/proxy/drive/api/v2/storage") == {"pools": [], "disks": []}
            assert state["served_shell"] is True
    finally:
        await server.close()


async def test_redirect_to_ui_is_api_error_not_auth() -> None:
    """aiohttp follows redirects by default; a redirect to the UI would then arrive
    as a 200 text/html and be misread as an expired session."""

    async def root(_: web.Request) -> web.Response:
        return web.Response(text="", headers={"X-CSRF-Token": "c"})

    async def storage(_: web.Request) -> web.Response:
        raise web.HTTPFound(location="/manage")

    async def manage(_: web.Request) -> web.Response:
        return web.Response(text="<html>ui</html>", content_type="text/html")

    app = web.Application()
    app.router.add_get("/", root)
    app.router.add_get("/proxy/drive/api/v2/storage", storage)
    app.router.add_get("/manage", manage)
    server = TestServer(app)
    await server.start_server()
    try:
        async with aiohttp.ClientSession() as session:
            t = UnasTransport(
                session, str(server.host), ApiKeyAuth("k"), port=int(server.port), use_ssl=False
            )
            with pytest.raises(UnasApiError) as excinfo:
                await t.get_json("/proxy/drive/api/v2/storage")
            assert excinfo.value.status == 302
            assert "/manage" in str(excinfo.value)
    finally:
        await server.close()


# --- a network failure during login is not a refused credential ---------------


async def test_unreachable_console_during_login_is_a_connection_error() -> None:
    """Filed as an auth error, Home Assistant would ask for a password that is fine."""
    async with aiohttp.ClientSession() as session:
        t = UnasTransport(
            session, "127.0.0.1", SessionAuth("u", "p"), port=1, use_ssl=False, timeout=2
        )
        with pytest.raises(UnasConnectionError, match="could not reach console"):
            await t.get_json("/proxy/drive/api/v2/storage")


async def test_login_that_never_answers_times_out_as_a_connection_error() -> None:
    async def hang(_: web.Request) -> web.Response:
        await asyncio.sleep(10)
        return web.Response(text="")

    app = web.Application()
    app.router.add_get("/", hang)
    server = TestServer(app)
    await server.start_server()
    try:
        async with aiohttp.ClientSession() as session:
            t = UnasTransport(
                session,
                server.host,
                SessionAuth("u", "p"),
                port=server.port,
                use_ssl=False,
                timeout=1,
            )
            started = time.monotonic()
            with pytest.raises(UnasConnectionError) as exc_info:
                await t.get_json("/proxy/drive/api/v2/storage")
            elapsed = time.monotonic() - started
        assert str(exc_info.value) == "login did not finish within 1s: TimeoutError"
        assert elapsed < 3
    finally:
        await server.close()


async def test_refused_login_is_still_an_auth_error(unas_server) -> None:
    async with aiohttp.ClientSession() as session:
        t = _transport(session, unas_server, SessionAuth("user", "bad"))
        with pytest.raises(UnasAuthError, match="invalid credentials"):
            await t.get_json("/proxy/drive/api/v2/storage")


async def test_relogin_that_never_answers_times_out_as_a_connection_error() -> None:
    """The re-login after a 401 is bounded by the same timeout as the first one."""
    state = {"logged_in": False}

    async def root(_: web.Request) -> web.Response:
        return web.Response(text="", headers={"X-CSRF-Token": "c"})

    async def login(_: web.Request) -> web.Response:
        if state["logged_in"]:
            await asyncio.sleep(10)
        state["logged_in"] = True
        resp = web.json_response({"ok": True})
        resp.set_cookie("TOKEN", "tok", path="/")
        return resp

    async def storage(_: web.Request) -> web.Response:
        return web.json_response({}, status=401)

    app = web.Application()
    app.router.add_get("/", root)
    app.router.add_post("/api/auth/login", login)
    app.router.add_get("/proxy/drive/api/v2/storage", storage)
    server = TestServer(app)
    await server.start_server()
    try:
        async with aiohttp.ClientSession() as session:
            t = UnasTransport(
                session,
                server.host,
                SessionAuth("u", "p"),
                port=server.port,
                use_ssl=False,
                timeout=1,
            )
            started = time.monotonic()
            with pytest.raises(UnasConnectionError) as exc_info:
                await t.get_json("/proxy/drive/api/v2/storage")
            elapsed = time.monotonic() - started
        assert str(exc_info.value) == "login did not finish within 1s: TimeoutError"
        assert elapsed < 3
    finally:
        await server.close()


_READ_PATH = "/proxy/drive/api/v2/storage"


@contextlib.asynccontextmanager
async def _scripted_console(
    *answers: int | str,
) -> AsyncIterator[tuple[TestServer, list[str]]]:
    """A console that answers each request with the next entry, the last one for good.

    An entry is a status, or ``"drop"`` / ``"hang"`` for no answer at all. Yields
    the server and the methods of the requests it received.
    """
    seen: list[str] = []

    async def handle(request: web.Request) -> web.StreamResponse:
        seen.append(request.method)
        answer = answers[min(len(seen), len(answers)) - 1]
        if answer == "hang":
            await asyncio.sleep(1.5)
        if answer in ("drop", "hang"):
            assert request.transport is not None
            request.transport.close()
            return web.Response()
        return web.json_response({}, status=int(answer))

    app = web.Application()
    app.router.add_route("*", "/{tail:.*}", handle)
    server = TestServer(app)
    await server.start_server()
    try:
        yield server, seen
    finally:
        await server.close()


@pytest.mark.parametrize("failure", [502, 503, 504, "drop", "hang"])
async def test_failed_read_is_asked_once_more(failure: int | str) -> None:
    async with _scripted_console(failure, 200) as (server, seen), aiohttp.ClientSession() as http:
        t = UnasTransport(
            http, server.host, ApiKeyAuth("k"), port=server.port, use_ssl=False, timeout=1
        )
        t.allow_one_retry(0)
        assert await t.get_json(_READ_PATH) == {}
        assert seen == ["GET", "GET"]


async def test_second_failure_is_final() -> None:
    async with _scripted_console(502) as (server, seen), aiohttp.ClientSession() as http:
        t = _transport(http, server, ApiKeyAuth("k"))
        t.allow_one_retry(0)
        with pytest.raises(UnasApiError) as caught:
            await t.get_json(_READ_PATH)
        assert caught.value.status == 502
        assert len(seen) == 2


@pytest.mark.parametrize("status", [401, 403, 404, 500])
async def test_other_statuses_are_not_retried(status: int) -> None:
    async with _scripted_console(status) as (server, seen), aiohttp.ClientSession() as http:
        t = _transport(http, server, ApiKeyAuth("k"))
        t.allow_one_retry(0)
        with pytest.raises((UnasApiError, UnasAuthError, UnasCapabilityError)):
            await t.get_json(_READ_PATH)
        assert len(seen) == 1


async def test_no_retry_unless_asked_for() -> None:
    async with _scripted_console(502) as (server, seen), aiohttp.ClientSession() as http:
        with pytest.raises(UnasApiError):
            await _transport(http, server, ApiKeyAuth("k")).get_json(_READ_PATH)
        assert len(seen) == 1


@pytest.mark.parametrize(
    ("method", "failure"),
    [
        *itertools.product(["POST", "PUT", "PATCH", "DELETE"], [502, 503, 504]),
        # aiohttp itself resends a PUT or DELETE whose connection drops (they are
        # idempotent, RFC 9112 section 9.3.1), so a drop says nothing about this
        # library for those two.
        ("POST", "drop"),
        ("PATCH", "drop"),
    ],
)
async def test_a_write_is_never_retried(method: str, failure: int | str) -> None:
    async with _scripted_console(failure, 200) as (server, seen), aiohttp.ClientSession() as http:
        t = _transport(http, server, ApiKeyAuth("k"))
        t.allow_one_retry(0)
        with pytest.raises((UnasApiError, UnasConnectionError)):
            await t.send(method, _READ_PATH)
        assert seen == [method]


@pytest.mark.parametrize(
    ("refused", "raised"),
    [
        pytest.param(
            aiohttp.ServerFingerprintMismatch(b"a" * 32, b"b" * 32, "192.0.2.10", 443),
            UnasCertificateMismatch,
            id="pinned",
        ),
        pytest.param(
            aiohttp.ClientConnectorCertificateError(
                MagicMock(), ssl.SSLCertVerificationError("self-signed certificate")
            ),
            UnasConnectionError,
            id="ca",
        ),
    ],
)
async def test_a_refused_certificate_is_not_retried(
    refused: aiohttp.ClientError, raised: type[UnasConnectionError]
) -> None:
    session = MagicMock()
    session.request.side_effect = refused
    t = UnasTransport(session, "192.0.2.10", ApiKeyAuth("k"))
    t.allow_one_retry(0)
    with pytest.raises(raised):
        await t.get_json(_READ_PATH)
    assert session.request.call_count == 1


async def test_a_new_allowance_ends_the_wait_of_the_previous_one() -> None:
    async with _scripted_console(502, 200) as (server, seen), aiohttp.ClientSession() as http:
        t = _transport(http, server, ApiKeyAuth("k"))
        t.allow_one_retry(60)
        read = asyncio.create_task(t.get_json(_READ_PATH))
        await asyncio.sleep(0.2)  # long enough for the first answer
        assert not read.done()
        t.allow_one_retry(60)
        with pytest.raises(UnasApiError):
            await asyncio.wait_for(read, 1)
        assert seen == ["GET"]


async def test_reads_in_flight_share_one_wait_and_later_ones_fail_at_once() -> None:
    async with _scripted_console(502) as (server, seen), aiohttp.ClientSession() as http:
        t = _transport(http, server, ApiKeyAuth("k"))
        t.allow_one_retry(0.3)
        started = time.monotonic()
        results = await asyncio.gather(
            *(t.get_json(_READ_PATH) for _ in range(3)), return_exceptions=True
        )
        for _ in range(4):
            with pytest.raises(UnasApiError):
                await t.get_json(_READ_PATH)
        assert 0.3 <= time.monotonic() - started < 0.6  # one wait, not seven
        assert all(isinstance(result, UnasApiError) for result in results)
        assert len(seen) == 3 * 2 + 4


async def test_a_new_poll_gets_a_new_retry() -> None:
    async with _scripted_console(502) as (server, seen), aiohttp.ClientSession() as http:
        t = _transport(http, server, ApiKeyAuth("k"))
        for polls in (1, 2):
            t.allow_one_retry(0)
            with pytest.raises(UnasApiError):
                await t.get_json(_READ_PATH)
            assert len(seen) == 2 * polls


async def test_cancelling_the_retry_ends_the_wait_at_once() -> None:
    async with _scripted_console(502, 200) as (server, seen), aiohttp.ClientSession() as http:
        t = _transport(http, server, ApiKeyAuth("k"))
        t.allow_one_retry(60)
        read = asyncio.create_task(t.get_json(_READ_PATH))
        await asyncio.sleep(0.2)  # long enough for the first answer
        assert seen == ["GET"]
        assert not read.done()
        t.cancel_retry()
        with pytest.raises(UnasApiError):
            await asyncio.wait_for(read, 1)
        assert len(seen) == 1


async def test_a_retry_is_logged_at_debug_only(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="aiounas")
    async with _scripted_console(502, 200) as (server, _), aiohttp.ClientSession() as http:
        t = _transport(http, server, ApiKeyAuth("k"))
        t.allow_one_retry(0)
        await t.get_json(_READ_PATH)
    ours = [r for r in caplog.records if r.name.startswith("aiounas")]
    assert [r.levelno for r in ours] == [logging.DEBUG]
    assert "status 502" in ours[0].getMessage()
