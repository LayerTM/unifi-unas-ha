"""UnasClient endpoint tests (against the fake console)."""

from __future__ import annotations

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from aiounas.auth import ApiKeyAuth, SessionAuth
from aiounas.client import UnasClient
from aiounas.exceptions import UnasApiError, UnasCapabilityError


def _client(session, srv, auth) -> UnasClient:
    return UnasClient(session, srv.host, auth, port=srv.port, use_ssl=False)


async def test_get_storage(session, unas_server) -> None:
    client = _client(session, unas_server, ApiKeyAuth(unas_server.api_key))
    storage = await client.get_storage()
    assert len(storage.disks) == 2
    assert storage.pools[0].raid_level == "raid1"
    assert storage.total_capacity == 23991544709120


async def test_get_device_info(session, unas_server) -> None:
    client = _client(session, unas_server, ApiKeyAuth(unas_server.api_key))
    info = await client.get_device_info()
    assert info.firmware_version == "5.1.19"
    assert info.cpu_percent == 9.8


async def test_get_network_io(session, unas_server) -> None:
    client = _client(session, unas_server, ApiKeyAuth(unas_server.api_key))
    net = await client.get_network_io()
    assert net.rx_kbps == 3.62


async def test_get_identity(session, unas_server) -> None:
    client = _client(session, unas_server, ApiKeyAuth(unas_server.api_key))
    ident = await client.get_identity()
    assert ident.model_shortname == "UNAS2B"


async def test_get_shares_with_session_auth(session, unas_server) -> None:
    client = _client(session, unas_server, SessionAuth("user", "pass"))
    shares = await client.get_shares()
    assert len(shares) == 2
    assert shares[0].name == "Share1"
    assert shares[0].quota_bytes is None


async def test_get_shares_api_key_denied(session, unas_server) -> None:
    client = _client(session, unas_server, ApiKeyAuth(unas_server.api_key))
    with pytest.raises(UnasCapabilityError, match="session"):
        await client.get_shares()


async def test_get_user_count_with_session_auth(session, unas_server) -> None:
    client = _client(session, unas_server, SessionAuth("user", "pass"))
    assert await client.get_user_count() == 6  # from the fake console's `total`


async def test_get_user_count_api_key_denied(session, unas_server) -> None:
    client = _client(session, unas_server, ApiKeyAuth(unas_server.api_key))
    with pytest.raises(UnasCapabilityError, match="session"):
        await client.get_user_count()


async def test_get_update_info_session(session, unas_server) -> None:
    client = _client(session, unas_server, SessionAuth("user", "pass"))
    info = await client.get_update_info()
    assert info.unifi_os_installed == "5.1.19"
    assert info.unifi_os_latest == "5.2.0"
    assert info.drive_installed == "4.3.6"
    assert info.drive_latest == "4.4.0"
    assert info.has_data is True


async def test_get_update_info_api_key_short_payload_has_no_latest(session, unas_server) -> None:
    client = _client(session, unas_server, ApiKeyAuth(unas_server.api_key))
    info = await client.get_update_info()  # short payload: no firmware/apps data
    assert info.unifi_os_latest is None
    assert info.has_data is False


async def test_base_url_and_prepare(session, unas_server) -> None:
    client = _client(session, unas_server, ApiKeyAuth(unas_server.api_key))
    assert client.base_url == f"http://{unas_server.host}:{unas_server.port}"
    await client.async_prepare()  # idempotent no-op for API-key auth


async def test_get_shares_propagates_non_capability_error() -> None:
    async def root(_: web.Request) -> web.Response:
        return web.Response(text="", headers={"X-CSRF-Token": "c"})

    async def login(_: web.Request) -> web.Response:
        resp = web.json_response({"ok": True})
        resp.set_cookie("TOKEN", "tok", path="/")
        return resp

    async def drives(_: web.Request) -> web.Response:
        return web.json_response({"error": {"code": 502}}, status=502)

    app = web.Application()
    app.router.add_get("/", root)
    app.router.add_post("/api/auth/login", login)
    app.router.add_get("/proxy/drive/api/v2/drives", drives)
    server = TestServer(app)
    await server.start_server()
    try:
        async with aiohttp.ClientSession() as http:
            client = UnasClient(
                http,
                str(server.host),
                SessionAuth("user", "pass"),
                port=int(server.port),
                use_ssl=False,
            )
            with pytest.raises(UnasApiError):
                await client.get_shares()
    finally:
        await server.close()


async def test_get_shares_tolerates_non_dict_payload() -> None:
    async def root(_: web.Request) -> web.Response:
        return web.Response(text="", headers={"X-CSRF-Token": "c"})

    async def login(_: web.Request) -> web.Response:
        resp = web.json_response({"ok": True})
        resp.set_cookie("TOKEN", "tok", path="/")
        return resp

    async def drives(_: web.Request) -> web.Response:
        return web.json_response([1, 2, 3])  # a list, not the expected dict

    app = web.Application()
    app.router.add_get("/", root)
    app.router.add_post("/api/auth/login", login)
    app.router.add_get("/proxy/drive/api/v2/drives", drives)
    server = TestServer(app)
    await server.start_server()
    try:
        async with aiohttp.ClientSession() as http:
            client = UnasClient(
                http,
                str(server.host),
                SessionAuth("user", "pass"),
                port=int(server.port),
                use_ssl=False,
            )
            assert await client.get_shares() == []
    finally:
        await server.close()


async def test_close_is_noop_and_leaves_session_open(session, unas_server) -> None:
    client = _client(session, unas_server, ApiKeyAuth(unas_server.api_key))
    await client.close()
    assert session.closed is False
