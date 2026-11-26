"""Probe which endpoints the active auth method is allowed to reach."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol

from .client import UnasClient
from .exceptions import (
    UnasApiError,
    UnasAuthError,
    UnasCapabilityError,
    UnasConnectionError,
)
from .tls import UnasCertificateMismatch


@dataclass(frozen=True, slots=True)
class Capabilities:
    """Reachability of each read endpoint under the current auth."""

    storage: bool
    device_info: bool
    network_io: bool
    shares: bool
    users: bool
    updates: bool
    notifications: bool
    logs: bool
    storage_io: bool
    # Defaulted so a Capabilities built before these readings existed still works.
    backup_tasks: bool = False
    console_backup: bool = False


async def _reachable(call: Callable[[], Awaitable[object]]) -> bool:
    """True if *call* succeeds; False only on a capability (scope) denial.

    Connection and auth failures propagate — they are not capability signals.
    """
    try:
        await call()
    except UnasCapabilityError:
        return False
    return True


async def _in_scope(call: Callable[[], Awaitable[object]]) -> bool:
    """False only if *call* is refused or this console does not serve it.

    Used only once the credential has already answered a core read, which makes
    a 401 here a statement about the endpoint rather than about the credential.
    A console refuses an API key on its session-only reads with whatever status
    that firmware picked — 403 and 500 were observed on UniFi OS 5.1.19 with
    Drive 4.3.6, 401 on 5.1.33 with Drive 4.4.9 — so a probe that trusts the
    status to say which kind of refusal it is breaks on the next firmware.
    Reading the 401 as a bad credential is the worse half: setup fails, Home
    Assistant asks for the credential again, the flow validates it against a
    read the key *can* reach and reports success, and setup fails again on the
    same endpoint. The user cannot leave that loop, because nothing about their
    credential is wrong. (The 500 reaches here as a refusal only for an API
    key; see ``UnasClient._get_session_only``.)

    A 404 means the same for a supplementary read: this firmware does not serve
    it, so the reading is out of reach.

    Any other failure (a server error, a timeout, a dropped connection, a
    redirect or a page where JSON belongs) says nothing about scope, so the read
    stays in it: its entities are kept, and one failing supplementary read does
    not hold back the rest. A changed certificate propagates.
    """
    try:
        await call()
    except (UnasCapabilityError, UnasAuthError):
        return False
    except UnasCertificateMismatch:
        # Must precede UnasConnectionError, its base class.
        raise
    except UnasApiError as err:
        return err.status != 404
    except UnasConnectionError:
        return True
    return True


class _SessionReading(Protocol):
    @property
    def has_data(self) -> bool: ...


async def _carries_data(
    in_scope: Callable[[Callable[[], Awaitable[object]]], Awaitable[bool]],
    call: Callable[[], Awaitable[_SessionReading]],
) -> bool:
    """True if *call* is in scope and, when it answered, carries the reading.

    The full ``/api/system`` goes to a session; an API key gets a short payload
    with the same status, so being answered is not enough. Whether a failure
    means "out of scope" is decided by *in_scope* as for every other read.
    """
    answers: list[_SessionReading] = []

    async def read() -> None:
        answers.append(await call())

    if not await in_scope(read):
        return False
    return not answers or answers[0].has_data


async def probe(client: UnasClient) -> Capabilities:
    """Determine endpoint reachability for the client's auth method.

    The two core reads go first and keep auth failures fatal — they are what
    proves the credential. Every later read is supplementary, and is asked with
    that proof in hand.
    """
    storage = await _reachable(client.get_storage)
    device_info = await _reachable(client.get_device_info)
    # Without a single success the credential is unproven, so stay strict.
    optional = _in_scope if (storage or device_info) else _reachable
    return Capabilities(
        storage=storage,
        device_info=device_info,
        network_io=await optional(client.get_network_io),
        shares=await optional(client.get_shares),
        users=await optional(client.get_user_count),
        updates=await _carries_data(optional, client.get_update_info),
        notifications=await optional(client.get_notification_summary),
        logs=await optional(client.get_log_summary),
        storage_io=await optional(client.get_storage_io),
        backup_tasks=await optional(client.get_backup_task_count),
        console_backup=await _carries_data(optional, client.get_console_backup),
    )
