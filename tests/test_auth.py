"""Auth strategy tests (against the in-process fake console)."""

from __future__ import annotations

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from aiounas.auth import ApiKeyAuth, SessionAuth
from aiounas.exceptions import UnasAuthError


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
