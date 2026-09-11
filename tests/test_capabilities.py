"""Capability-probe tests (auth-method reachability)."""

from __future__ import annotations

import pytest

from aiounas.auth import ApiKeyAuth, SessionAuth
from aiounas.capabilities import probe
from aiounas.client import UnasClient
from aiounas.exceptions import UnasAuthError


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


async def test_probe_session_allows_shares(session, unas_server) -> None:
    caps = await probe(_client(session, unas_server, SessionAuth("user", "pass")))
    assert caps.storage is True
    assert caps.shares is True
    assert caps.users is True
    assert caps.updates is True
    assert caps.notifications is True
    assert caps.logs is True


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
