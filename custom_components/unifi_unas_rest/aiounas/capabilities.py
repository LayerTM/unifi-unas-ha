"""Probe which endpoints the active auth method is allowed to reach."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from .client import UnasClient
from .exceptions import UnasAuthError, UnasCapabilityError, UnasError


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


async def _has_update_data(client: UnasClient) -> bool:
    """True if the full /api/system (session) exposes firmware update info."""
    try:
        return (await client.get_update_info()).has_data
    except UnasError:
        return False


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
    """True if *call* succeeds; False on any refusal aimed at the auth method.

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
    credential is wrong.
    """
    try:
        await call()
    except (UnasCapabilityError, UnasAuthError):
        return False
    return True


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
        updates=await _has_update_data(client),
        notifications=await optional(client.get_notification_summary),
        logs=await optional(client.get_log_summary),
    )
