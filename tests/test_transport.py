"""Transport tests against the fake console."""

from __future__ import annotations

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from aiounas.auth import ApiKeyAuth, SessionAuth
from aiounas.exceptions import UnasAuthError, UnasCapabilityError, UnasConnectionError
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
            await t.get_json("/proxy/drive/api/v2/drives")


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
