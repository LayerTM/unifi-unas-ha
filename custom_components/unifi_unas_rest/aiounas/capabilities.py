"""Probe which endpoints the active auth method is allowed to reach."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from .client import UnasClient
from .exceptions import UnasCapabilityError, UnasError


@dataclass(frozen=True, slots=True)
class Capabilities:
    """Reachability of each read endpoint under the current auth."""

    storage: bool
    device_info: bool
    network_io: bool
    shares: bool
    users: bool
    updates: bool


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


async def probe(client: UnasClient) -> Capabilities:
    """Determine endpoint reachability for the client's auth method."""
    return Capabilities(
        storage=await _reachable(client.get_storage),
        device_info=await _reachable(client.get_device_info),
        network_io=await _reachable(client.get_network_io),
        shares=await _reachable(client.get_shares),
        users=await _reachable(client.get_user_count),
        updates=await _has_update_data(client),
    )
