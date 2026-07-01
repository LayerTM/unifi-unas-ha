"""Shared test helpers: sanitized-fixture loader + an in-process fake UNAS console.

The fake console is a real aiohttp app served over HTTP, so tests exercise the
genuine request/response stack (headers, cookies, status, auth scoping) without
depending on version-fragile response mocking.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

_FIXTURES = Path(__file__).parent / "fixtures"

# A realistic-length placeholder key (>=16 chars) so the client sends X-API-Key.
FAKE_API_KEY = "test-api-key-0123456789"
_API_KEY = web.AppKey("api_key", str)


def load_fixture(name: str) -> dict[str, Any]:
    """Load a sanitized JSON fixture by base name (no extension)."""
    return json.loads((_FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


@pytest.fixture
def fixture() -> Callable[[str], dict[str, Any]]:
    """Return the fixture loader as a pytest fixture."""
    return load_fixture


# --------------------------------------------------------------------------- #
# Fake UNAS console
# --------------------------------------------------------------------------- #
async def _root(request: web.Request) -> web.Response:
    return web.Response(text="", headers={"X-CSRF-Token": "csrf-root"})


async def _login(request: web.Request) -> web.Response:
    data = await request.json()
    if data.get("username") == "user" and data.get("password") == "pass":
        resp = web.json_response(
            {"unique_id": "u"}, headers={"X-Updated-CSRF-Token": "csrf-session"}
        )
        resp.set_cookie("TOKEN", "jwt-token-value", path="/")
        return resp
    return web.json_response({"error": {"code": 401, "message": "Unauthorized"}}, status=401)


def _auth_mode(request: web.Request) -> str | None:
    if request.headers.get("X-API-Key") == request.app[_API_KEY]:
        return "apikey"
    if "TOKEN=" in request.headers.get("Cookie", ""):
        return "session"
    return None


def _data(name: str, *, apikey_ok: bool = True) -> Callable[[web.Request], Any]:
    async def handler(request: web.Request) -> web.Response:
        mode = _auth_mode(request)
        if mode is None:
            return web.json_response(
                {"error": {"code": 401, "message": "Unauthorized"}}, status=401
            )
        if mode == "apikey" and not apikey_ok:
            return web.json_response({"error": {"code": 403, "message": "Forbidden"}}, status=403)
        return web.json_response(load_fixture(name))

    return handler


def make_app(*, api_key: str = FAKE_API_KEY) -> web.Application:
    app = web.Application()
    app[_API_KEY] = api_key
    app.router.add_get("/", _root)
    app.router.add_post("/api/auth/login", _login)
    app.router.add_get("/api/system", _data("system_short"))
    app.router.add_get("/proxy/drive/api/v2/storage", _data("storage"))
    app.router.add_get("/proxy/drive/api/v2/systems/device-info", _data("device_info"))
    app.router.add_get("/proxy/drive/api/v2/systems/network-io", _data("network_io"))
    app.router.add_get("/proxy/drive/api/v2/drives", _data("drives", apikey_ok=False))
    return app


@dataclass
class RunningServer:
    host: str
    port: int
    api_key: str

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"


@pytest.fixture
async def unas_server() -> AsyncIterator[RunningServer]:
    server = TestServer(make_app())
    await server.start_server()
    try:
        yield RunningServer(str(server.host), int(server.port), FAKE_API_KEY)
    finally:
        await server.close()
