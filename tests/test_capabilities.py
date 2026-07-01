"""Capability-probe tests (auth-method reachability)."""

from __future__ import annotations

from aiounas.auth import ApiKeyAuth, SessionAuth
from aiounas.capabilities import probe
from aiounas.client import UnasClient


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


async def test_probe_session_allows_shares(session, unas_server) -> None:
    caps = await probe(_client(session, unas_server, SessionAuth("user", "pass")))
    assert caps.storage is True
    assert caps.shares is True
    assert caps.users is True
    assert caps.updates is True
