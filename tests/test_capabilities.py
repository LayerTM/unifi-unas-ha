"""Capability-probe tests (auth-method reachability)."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from aiounas.auth import ApiKeyAuth, SessionAuth
from aiounas.capabilities import probe
from aiounas.client import UnasClient
from aiounas.const import (
    PATH_LOGS,
    PATH_M365_BACKUP_TASKS,
    PATH_NOTIFICATIONS,
    PATH_REMOTE_BACKUP_TASKS,
    PATH_SHARES,
    PATH_STORAGE_IO,
    PATH_USERS,
)
from aiounas.exceptions import (
    UnasApiError,
    UnasAuthError,
    UnasCapabilityError,
    UnasConnectionError,
)
from conftest import make_app


def _client(session, srv, auth) -> UnasClient:
    return UnasClient(session, srv.host, auth, port=srv.port, use_ssl=False)


async def test_probe_api_key_denies_shares(session, unas_server) -> None:
    caps = await probe(_client(session, unas_server, ApiKeyAuth(unas_server.api_key)))
    assert caps.storage is True
    assert caps.device_info is True
    assert caps.network_io is True
    assert caps.shares is False
    assert caps.users is False
    assert caps.updates is False
    assert caps.notifications is False
    assert caps.logs is False
    assert caps.storage_io is False
    assert caps.backup_tasks is False
    assert caps.console_backup is False


async def test_probe_session_allows_shares(session, unas_server) -> None:
    caps = await probe(_client(session, unas_server, SessionAuth("user", "pass")))
    assert caps.storage is True
    assert caps.shares is True
    assert caps.users is True
    assert caps.updates is True
    assert caps.notifications is True
    assert caps.logs is True
    assert caps.storage_io is True
    assert caps.backup_tasks is True
    assert caps.console_backup is True


async def test_probe_api_key_401_on_notifications_is_a_scope_answer(
    session, unas_server_401_notifications
) -> None:
    """A 401 on one supplementary read must not read as a bad credential.

    UniFi OS 5.1.33 / Drive 4.4.9 answers an API key with 401 there where the
    firmware modelled by `unas_server` answers 403. Before this was handled the
    probe raised UnasAuthError, setup failed with "unauthorized for
    /api/notifications", and the entry entered a re-auth loop it could not leave.
    """
    srv = unas_server_401_notifications
    caps = await probe(_client(session, srv, ApiKeyAuth(srv.api_key)))
    assert caps.notifications is False
    # The rest of the probe is unaffected: the credential is good and says so.
    assert caps.storage is True
    assert caps.device_info is True
    assert caps.network_io is True


async def test_probe_401_on_a_core_read_still_fails(session, unas_server) -> None:
    """The other branch: a credential that answers nothing is a credential fault."""
    with pytest.raises(UnasAuthError):
        await probe(_client(session, unas_server, ApiKeyAuth("not-the-key")))


async def test_probe_session_unaffected_by_the_relaxed_rule(
    session, unas_server_401_notifications
) -> None:
    """A local account still reaches notifications on that same console."""
    srv = unas_server_401_notifications
    caps = await probe(_client(session, srv, SessionAuth("user", "pass")))
    assert caps.notifications is True


async def test_probe_absent_supplementary_read_is_out_of_scope(
    session, unas_server_without_storage_io
) -> None:
    """Firmware without an endpoint answers 404; that reading is skipped, setup is not failed."""
    srv = unas_server_without_storage_io
    caps = await probe(_client(session, srv, SessionAuth("user", "pass")))
    assert caps.storage_io is False
    assert caps.storage is True
    assert caps.shares is True
    assert caps.logs is True


async def test_probe_absent_backup_task_lists_are_out_of_scope(
    session, unas_server_without_backup_tasks
) -> None:
    """A console that serves neither task list gets no backup-task reading and still sets up."""
    srv = unas_server_without_backup_tasks
    caps = await probe(_client(session, srv, SessionAuth("user", "pass")))
    assert caps.backup_tasks is False
    assert caps.console_backup is True
    assert caps.storage is True
    assert caps.logs is True


async def test_probe_propagates_other_api_errors_on_supplementary_reads() -> None:
    """Only a 404 means "not served"; a 502 is a real failure and still surfaces."""
    client = AsyncMock()
    client.get_storage = AsyncMock(return_value=None)
    client.get_device_info = AsyncMock(return_value=None)
    client.get_network_io = AsyncMock(side_effect=UnasApiError("bad gateway", status=502))
    with pytest.raises(UnasApiError):
        await probe(client)


def _answering_client() -> AsyncMock:
    client = AsyncMock()
    for method in ("get_storage", "get_device_info", "get_network_io"):
        getattr(client, method).return_value = None
    return client


@pytest.mark.parametrize(
    ("method", "capability"),
    [("get_update_info", "updates"), ("get_console_backup", "console_backup")],
)
@pytest.mark.parametrize(
    "refusal",
    [
        UnasCapabilityError("forbidden"),
        UnasAuthError("unauthorized"),
        UnasApiError("not found", status=404),
    ],
)
async def test_probe_refused_system_read_is_out_of_scope(
    method: str, capability: str, refusal: Exception
) -> None:
    client = _answering_client()
    getattr(client, method).side_effect = refusal
    caps = await probe(client)
    assert getattr(caps, capability) is False


@pytest.mark.parametrize("method", ["get_update_info", "get_console_backup"])
@pytest.mark.parametrize(
    "failure",
    [UnasConnectionError("timed out"), UnasApiError("bad gateway", status=502)],
)
async def test_probe_transient_failure_of_a_system_read_is_not_a_scope_answer(
    method: str, failure: Exception
) -> None:
    """Read as "out of scope", it would delete the entities from the registry."""
    client = _answering_client()
    getattr(client, method).side_effect = failure
    with pytest.raises(type(failure)):
        await probe(client)


@pytest.mark.parametrize(
    "path",
    [
        PATH_SHARES,
        PATH_USERS,
        PATH_NOTIFICATIONS,
        PATH_LOGS,
        PATH_STORAGE_IO,
        PATH_REMOTE_BACKUP_TASKS,
        PATH_M365_BACKUP_TASKS,
    ],
)
async def test_probe_500_to_a_local_account_is_not_a_scope_answer(session, path: str) -> None:
    """Only an API key is refused with a 500. For a session it is a failing console."""

    @web.middleware
    async def broken(request: web.Request, handler):
        if request.path == path:
            return web.json_response({"error": {"code": 500}}, status=500)
        return await handler(request)

    app = make_app()
    app.middlewares.append(broken)
    server = TestServer(app)
    await server.start_server()
    try:
        client = UnasClient(
            session,
            str(server.host),
            SessionAuth("user", "pass"),
            port=int(server.port),
            use_ssl=False,
        )
        with pytest.raises(UnasApiError) as err:
            await probe(client)
    finally:
        await server.close()
    assert err.value.status == 500
