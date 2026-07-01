"""MCP server tests — clients mocked, no network."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from aiounas import DeviceInfo, Storage
from aiounas.mcp import build_server

_FX = Path(__file__).parent / "fixtures"


def _load(name: str) -> dict:
    return json.loads((_FX / f"{name}.json").read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UNAS_HOST", "192.0.2.10")
    monkeypatch.setenv("UNAS_APIKEY", "test-api-key-0123456789")


def _read_client() -> AsyncMock:
    client = AsyncMock()
    client.get_storage = AsyncMock(return_value=Storage.from_api(_load("storage")))
    client.get_device_info = AsyncMock(return_value=DeviceInfo.from_api(_load("device_info")))
    return client


async def test_read_only_by_default() -> None:
    tools = {t.name for t in await build_server(allow_writes=False).list_tools()}
    assert "get_status" in tools
    assert "reboot" not in tools


async def test_write_tools_present_when_enabled() -> None:
    tools = {t.name for t in await build_server(allow_writes=True).list_tools()}
    assert {"get_status", "reboot", "shutdown", "update_firmware"} <= tools


async def test_get_status_returns_data() -> None:
    with patch("aiounas.mcp.UnasClient", return_value=_read_client()):
        server = build_server(allow_writes=False)
        result = await server.call_tool("get_status", {})
    assert "UNAS2B" in str(result)


async def test_reboot_requires_confirm() -> None:
    action = AsyncMock()
    with patch("aiounas.mcp.UnasActionClient", return_value=action):
        server = build_server(allow_writes=True)
        await server.call_tool("reboot", {"confirm": False})
        action.reboot.assert_not_awaited()
        await server.call_tool("reboot", {"confirm": True})
        action.reboot.assert_awaited_once()


async def test_new_write_tools_present() -> None:
    tools = {t.name for t in await build_server(allow_writes=True).list_tools()}
    assert {"update_drive_app", "set_fan_profile"} <= tools
    # read tool available without allow_writes
    ro = {t.name for t in await build_server(allow_writes=False).list_tools()}
    assert "get_fan_profile" in ro
    assert "set_fan_profile" not in ro


async def test_set_fan_profile_requires_confirm() -> None:
    action = AsyncMock()
    with patch("aiounas.mcp.UnasActionClient", return_value=action):
        server = build_server(allow_writes=True)
        await server.call_tool("set_fan_profile", {"profile": "quiet", "confirm": False})
        action.set_fan_profile.assert_not_awaited()
        await server.call_tool("set_fan_profile", {"profile": "quiet", "confirm": True})
        action.set_fan_profile.assert_awaited_once_with("quiet")


async def test_get_fan_profile_reads() -> None:
    from aiounas import FanControl

    client = AsyncMock()
    client.get_fan_control = AsyncMock(return_value=FanControl.from_api(_load("fan_control")))
    with patch("aiounas.mcp.UnasClient", return_value=client):
        result = await build_server(allow_writes=False).call_tool("get_fan_profile", {})
    assert "default" in str(result)


async def test_shutdown_and_update_firmware_confirmed() -> None:
    action = AsyncMock()
    with patch("aiounas.mcp.UnasActionClient", return_value=action):
        server = build_server(allow_writes=True)
        await server.call_tool("shutdown", {"confirm": True})
        await server.call_tool("update_firmware", {"confirm": True})
    action.shutdown.assert_awaited_once()
    action.update_firmware.assert_awaited_once()


async def test_get_status_with_session_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("UNAS_APIKEY", raising=False)
    monkeypatch.setenv("UNAS_USER", "u")
    monkeypatch.setenv("UNAS_PASS", "p")
    with patch("aiounas.mcp.UnasClient", return_value=_read_client()):
        result = await build_server(allow_writes=False).call_tool("get_status", {})
    assert "UNAS2B" in str(result)


@pytest.mark.parametrize(
    ("value", "enabled"),
    [
        ("1", True),
        ("true", True),
        ("TRUE", True),
        ("yes", True),
        ("on", True),
        ("", False),
        ("0", False),
        ("false", False),
        ("False", False),
        ("FALSE", False),
        ("off", False),
        ("no", False),
        ("disabled", False),
    ],
)
def test_writes_enabled_env(monkeypatch: pytest.MonkeyPatch, value: str, enabled: bool) -> None:
    # Fail closed: only explicit truthy values enable writes; "off"/"no"/"FALSE"
    # must NOT silently enable the destructive tools.
    from aiounas.mcp import _writes_enabled

    monkeypatch.setenv("UNAS_MCP_ALLOW_WRITES", value)
    assert _writes_enabled() is enabled
