"""Auth strategy tests (against the in-process fake console)."""

from __future__ import annotations

import asyncio

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from aiounas.auth import ApiKeyAuth, SessionAuth
from aiounas.exceptions import UnasAuthError, UnasConnectionError


def test_apikey_headers() -> None:
    auth = ApiKeyAuth("KEY-EXAMPLE")
    assert auth.headers()["X-API-Key"] == "KEY-EXAMPLE"
    assert auth.can_reauth is False


async def test_session_login_captures_csrf_and_token(unas_server) -> None:
    async with aiohttp.ClientSession() as session:
        auth = SessionAuth("user", "pass")
        assert auth.can_reauth is True
        await auth.async_prepare(session, unas_server.base_url, ssl=False)
        headers = auth.headers()
        assert headers["X-CSRF-Token"] == "csrf-session"
        assert headers["Cookie"] == "TOKEN=jwt-token-value"


async def test_session_login_bad_creds_raises(unas_server) -> None:
    async with aiohttp.ClientSession() as session:
        with pytest.raises(UnasAuthError):
            await SessionAuth("user", "bad").async_prepare(session, unas_server.base_url, ssl=False)


async def test_session_login_no_token_raises() -> None:
    async def root(_: web.Request) -> web.Response:
        return web.Response(text="")

    async def login_no_cookie(_: web.Request) -> web.Response:
        return web.json_response({"ok": True})

    app = web.Application()
    app.router.add_get("/", root)
    app.router.add_post("/api/auth/login", login_no_cookie)
    server = TestServer(app)
    await server.start_server()
    try:
        base = f"http://{server.host}:{server.port}"
        async with aiohttp.ClientSession() as session:
            with pytest.raises(UnasAuthError, match="token"):
                await SessionAuth("user", "pass").async_prepare(session, base, ssl=False)
    finally:
        await server.close()


async def test_session_timeout_during_login_is_a_connection_error() -> None:
    """A session-level ``ClientTimeout`` raises a bare ``TimeoutError``, not a
    ``ClientError``; it must still arrive typed, and not as bad credentials."""

    async def hang(_: web.Request) -> web.Response:
        await asyncio.sleep(10)
        return web.Response(text="")

    app = web.Application()
    app.router.add_get("/", hang)
    server = TestServer(app)
    await server.start_server()
    try:
        base = f"http://{server.host}:{server.port}"
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=0.3)) as session:
            with pytest.raises(UnasConnectionError, match="could not reach console: TimeoutError"):
                await SessionAuth("user", "pass").async_prepare(session, base, ssl=False)
    finally:
        await server.close()


async def _login_answering(status: int) -> TestServer:
    async def root(_: web.Request) -> web.Response:
        return web.Response(text="")

    async def login(_: web.Request) -> web.Response:
        headers = {"Location": "/manage"} if 300 <= status < 400 else None
        return web.Response(status=status, text="", headers=headers)

    async def manage(_: web.Request) -> web.Response:
        return web.Response(text="<html></html>", content_type="text/html")

    app = web.Application()
    app.router.add_get("/", root)
    app.router.add_post("/api/auth/login", login)
    app.router.add_get("/manage", manage)
    server = TestServer(app)
    await server.start_server()
    return server


@pytest.mark.parametrize("status", [302, 408, 429, 502, 503])
async def test_console_not_ready_to_log_in_is_a_connection_error(status: int) -> None:
    """A console that cannot answer yet must be retried, not asked for a new password."""
    server = await _login_answering(status)
    try:
        base = f"http://{server.host}:{server.port}"
        async with aiohttp.ClientSession() as session:
            with pytest.raises(UnasConnectionError, match=str(status)):
                await SessionAuth("user", "pass").async_prepare(session, base, ssl=False)
    finally:
        await server.close()


@pytest.mark.parametrize("status", [400, 401, 403])
async def test_refused_login_is_an_auth_error(status: int) -> None:
    server = await _login_answering(status)
    try:
        base = f"http://{server.host}:{server.port}"
        async with aiohttp.ClientSession() as session:
            with pytest.raises(UnasAuthError):
                await SessionAuth("user", "pass").async_prepare(session, base, ssl=False)
    finally:
        await server.close()
