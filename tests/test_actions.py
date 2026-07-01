"""Action (write) client tests against the fake console."""

from __future__ import annotations

import pytest

from aiounas import ApiKeyAuth, UnasActionClient
from aiounas.exceptions import UnasAuthError


def _client(session, srv, key: str | None = None) -> UnasActionClient:
    return UnasActionClient(
        session, srv.host, ApiKeyAuth(key or srv.api_key), port=srv.port, use_ssl=False
    )


async def test_reboot(session, unas_server) -> None:
    await _client(session, unas_server).reboot()
    assert unas_server.writes == [{"method": "POST", "path": "/api/system/reboot", "json": None}]


async def test_shutdown(session, unas_server) -> None:
    await _client(session, unas_server).shutdown()
    assert unas_server.writes[-1]["path"] == "/api/system/poweroff"


async def test_firmware_and_drive_update(session, unas_server) -> None:
    client = _client(session, unas_server)
    await client.update_firmware()
    await client.update_drive_app()
    assert [w["path"] for w in unas_server.writes] == [
        "/api/firmware/update",
        "/api/applications/drive/update",
    ]


async def test_set_fan_profile_sends_payload(session, unas_server) -> None:
    await _client(session, unas_server).set_fan_profile("cooling")
    call = unas_server.writes[-1]
    assert call["method"] == "PUT"
    assert call["path"] == "/proxy/drive/api/v2/systems/fan-control"
    assert call["json"] == {"profile": "cooling"}


async def test_write_auth_failure_raises(session, unas_server) -> None:
    with pytest.raises(UnasAuthError):
        await _client(session, unas_server, key="wrong-key-000000000000").reboot()
    assert unas_server.writes == []  # nothing recorded on failed auth
