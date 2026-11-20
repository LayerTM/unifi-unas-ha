"""Action (write) client tests against the fake console."""

from __future__ import annotations

import pytest

from aiounas import ApiKeyAuth, UnasActionClient
from aiounas.exceptions import UnasApiError, UnasAuthError, UnasOperationBlocked


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


_BLOCKED = {
    "code": "CRITICAL_OPERATION_IN_PROGRESS",
    "data": {
        "blockers": [
            {
                "operationId": "op-1",
                "domain": "storage",
                "kind": "raid-rebuild",
                "description": "Rebuilding storage pool 1",
            },
            {
                "operationId": "op-2",
                "domain": "system",
                "kind": "firmware-install",
                "description": "",
            },
            "not an object",
        ]
    },
}


@pytest.mark.parametrize(
    ("action", "path"),
    [
        ("reboot", "/api/system/reboot"),
        ("shutdown", "/api/system/poweroff"),
        ("update_firmware", "/api/firmware/update"),
        ("update_drive_app", "/api/applications/drive/update"),
    ],
)
async def test_a_critical_operation_refusal_names_what_blocks_it(
    session, unas_server, action: str, path: str
) -> None:
    unas_server.replies[path] = (409, _BLOCKED)
    with pytest.raises(UnasOperationBlocked) as caught:
        await getattr(_client(session, unas_server), action)()
    assert caught.value.blockers == ("Rebuilding storage pool 1", "firmware-install")
    assert caught.value.status == 409
    assert "Rebuilding storage pool 1" in str(caught.value)
    assert unas_server.writes == []


@pytest.mark.parametrize(
    "body",
    [
        {"code": "SOMETHING_ELSE"},
        {"code": "CRITICAL_OPERATION_IN_PROGRESS", "data": None},
        ["not", "an", "object"],
    ],
)
async def test_any_other_409_is_an_ordinary_refusal(session, unas_server, body) -> None:
    unas_server.replies["/api/firmware/update"] = (409, body)
    with pytest.raises(UnasApiError) as caught:
        await _client(session, unas_server).update_firmware()
    blocked = isinstance(caught.value, UnasOperationBlocked)
    named = body == {"code": "CRITICAL_OPERATION_IN_PROGRESS", "data": None}
    assert blocked is named  # the code alone is the signal; no blockers listed then
    assert caught.value.status == 409
