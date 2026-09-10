"""MCP server exposing a UniFi UNAS to LLMs/agents.

Read tools are always available. Write tools are registered **only** when the
``UNAS_MCP_ALLOW_WRITES`` environment variable is set, and each still requires
``confirm=true`` — a per-operation gate so an agent cannot change device state
by accident.

Credentials come from the environment (``UNAS_HOST`` + ``UNAS_APIKEY``, or
``UNAS_USER``/``UNAS_PASS``). Install with the ``mcp`` extra
(``pip install aiounas[mcp]``) and run ``unifi-unas-mcp``.
"""

from __future__ import annotations

import os
from collections.abc import Awaitable, Callable
from typing import Any

import aiohttp
from mcp.server.mcpserver import MCPServer

from .actions import UnasActionClient
from .auth import AbstractAuth, ApiKeyAuth, SessionAuth
from .client import UnasClient
from .tls import ssl_from_env


def _auth() -> AbstractAuth:
    key = os.environ.get("UNAS_APIKEY")
    if key:
        return ApiKeyAuth(key)
    user, password = os.environ.get("UNAS_USER", ""), os.environ.get("UNAS_PASS", "")
    return SessionAuth(user, password)


def _host() -> str:
    host = os.environ.get("UNAS_HOST")
    if not host:
        raise RuntimeError("UNAS_HOST is not set")
    return host


async def _with_read[T](func: Callable[[UnasClient], Awaitable[T]]) -> T:
    async with aiohttp.ClientSession() as session:
        return await func(UnasClient(session, _host(), _auth(), ssl=ssl_from_env()))


async def _with_action(func: Callable[[UnasActionClient], Awaitable[None]]) -> None:
    async with aiohttp.ClientSession() as session:
        await func(UnasActionClient(session, _host(), _auth(), ssl=ssl_from_env()))


def build_server(*, allow_writes: bool) -> MCPServer:
    """Build the MCP server. Write tools are present only when *allow_writes*."""
    server = MCPServer("unifi-unas")

    @server.tool()
    async def get_status() -> dict[str, Any]:
        """Return storage, per-disk health, and system telemetry for the UNAS."""

        async def fetch(client: UnasClient) -> dict[str, Any]:
            storage = await client.get_storage()
            info = await client.get_device_info()
            return {
                "name": info.name,
                "model": info.model,
                "unifi_os_version": info.firmware_version,
                "drive_version": info.version,
                "cpu_percent": info.cpu_percent,
                "cpu_temperature": info.cpu_temperature,
                "memory_percent": info.memory_percent,
                "storage_usage_percent": storage.usage_percent,
                "at_risk_disks": storage.at_risk_disk_count,
                "disks": [
                    {
                        "slot": d.slot,
                        "state": d.state,
                        "temperature": d.temperature,
                        "power_on_hours": d.power_on_hours,
                        "health_score": d.health_score,
                        "model": d.model,
                    }
                    for d in storage.disks
                ],
                "pools": [
                    {
                        "number": p.number,
                        "status": p.status,
                        "raid_level": p.raid_level,
                        "usage_percent": p.usage_percent,
                    }
                    for p in storage.pools
                ],
            }

        return await _with_read(fetch)

    @server.tool()
    async def get_fan_profile() -> dict[str, Any]:
        """Return the current fan profile and the available profiles."""

        async def fetch(client: UnasClient) -> dict[str, Any]:
            fan = await client.get_fan_control()
            return {"current": fan.current_profile, "available": list(fan.available_profiles)}

        return await _with_read(fetch)

    if allow_writes:
        _register_write_tools(server)

    return server


def _register_write_tools(server: MCPServer) -> None:
    @server.tool()
    async def reboot(confirm: bool = False) -> str:
        """Reboot the console. Requires confirm=true."""
        if not confirm:
            return "Refused: pass confirm=true to reboot the UNAS."
        await _with_action(lambda client: client.reboot())
        return "reboot requested"

    @server.tool()
    async def shutdown(confirm: bool = False) -> str:
        """Power the console off. Requires confirm=true."""
        if not confirm:
            return "Refused: pass confirm=true to shut down the UNAS."
        await _with_action(lambda client: client.shutdown())
        return "shutdown requested"

    @server.tool()
    async def update_firmware(confirm: bool = False) -> str:
        """Install the available UniFi OS firmware update. Requires confirm=true."""
        if not confirm:
            return "Refused: pass confirm=true to install a firmware update."
        await _with_action(lambda client: client.update_firmware())
        return "firmware update requested"

    @server.tool()
    async def update_drive_app(confirm: bool = False) -> str:
        """Install the available Drive app update. Requires confirm=true."""
        if not confirm:
            return "Refused: pass confirm=true to install a Drive app update."
        await _with_action(lambda client: client.update_drive_app())
        return "drive app update requested"

    @server.tool()
    async def set_fan_profile(profile: str, confirm: bool = False) -> str:
        """Set the fan profile (cooling / default / quiet). Requires confirm=true."""
        if not confirm:
            return "Refused: pass confirm=true to change the fan profile."
        await _with_action(lambda client: client.set_fan_profile(profile))
        return f"fan profile set to {profile}"


def _writes_enabled() -> bool:
    # Fail closed: only explicit truthy values enable writes; anything else
    # (unset, "off", "no", "false", a typo) keeps the server read-only.
    return os.environ.get("UNAS_MCP_ALLOW_WRITES", "").strip().lower() in ("1", "true", "yes", "on")


def main() -> None:  # pragma: no cover
    build_server(allow_writes=_writes_enabled()).run()


if __name__ == "__main__":  # pragma: no cover
    main()
