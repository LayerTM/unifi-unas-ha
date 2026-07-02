"""Switch platform: per-share scheduled-snapshots toggle (opt-in control).

A switch appears per share only when control actions are opted in (a session is
required to write) and the device exposes shares. It reflects the share's
``snapshotEnabled`` flag and toggles scheduled snapshots.

The UNAS local REST API exposes no snapshot list/create endpoint; this scheduled
flag is the only snapshot control surface, and its write path is inferred from
the share resource and not yet verified against live hardware (see
``aiounas.actions.set_share_snapshots``).
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import UnasConfigEntry
from .aiounas import Share, UnasActionClient
from .aiounas.exceptions import (
    UnasAuthError,
    UnasCapabilityError,
    UnasConnectionError,
    UnasError,
)
from .coordinator import UnasDataUpdateCoordinator
from .entity import UnasShareEntity

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: UnasConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create per-share snapshot switches when controls are opted in."""
    runtime = entry.runtime_data
    if runtime.action_client is None:
        return
    async_add_entities(
        UnasShareSnapshotSwitch(runtime.coordinator, share, runtime.action_client)
        for share in (runtime.coordinator.data.shares or [])
    )


class UnasShareSnapshotSwitch(UnasShareEntity, SwitchEntity):
    """Toggle scheduled snapshots for a share (opt-in; live-write untested)."""

    _attr_translation_key = "share_snapshots"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: UnasDataUpdateCoordinator,
        share: Share,
        action_client: UnasActionClient,
    ) -> None:
        super().__init__(coordinator, share, "snapshots")
        self._action_client = action_client

    @property
    def is_on(self) -> bool | None:
        share = self.share
        return share.snapshot_enabled if share is not None else None

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._set(False)

    async def _set(self, enabled: bool) -> None:
        share = self.share
        if share is None:
            raise HomeAssistantError("The share is no longer present.")
        try:
            await self._action_client.set_share_snapshots(share.id, enabled)
        except UnasCapabilityError as err:
            raise HomeAssistantError(
                "The UNAS account is not permitted to change snapshot settings."
            ) from err
        except UnasAuthError as err:
            raise HomeAssistantError("Authentication with the UNAS failed.") from err
        except UnasConnectionError as err:
            raise HomeAssistantError(f"Could not reach the UNAS: {err}") from err
        except UnasError as err:
            status = getattr(err, "status", None)
            detail = f" (HTTP {status})" if status else ""
            raise HomeAssistantError(f"The UNAS rejected the snapshot change{detail}.") from err
        await self.coordinator.async_request_refresh()
