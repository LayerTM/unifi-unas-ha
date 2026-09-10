"""Data update coordinator for the UniFi UNAS integration."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .aiounas import (
    Capabilities,
    DeviceInfo,
    FanControl,
    LogSummary,
    NetworkIO,
    NotificationSummary,
    Share,
    Storage,
    UnasApiError,
    UnasAuthError,
    UnasCapabilityError,
    UnasCertificateMismatch,
    UnasClient,
    UnasConnectionError,
    UpdateInfo,
)
from .const import DOMAIN
from .issues import raise_cert_mismatch

_LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class UnasData:
    """Snapshot of everything the coordinator fetches each cycle."""

    storage: Storage
    device_info: DeviceInfo
    network_io: NetworkIO
    shares: list[Share] | None
    user_count: int | None
    update_info: UpdateInfo | None
    fan_control: FanControl | None
    notification_summary: NotificationSummary | None
    log_summary: LogSummary | None


class UnasDataUpdateCoordinator(DataUpdateCoordinator[UnasData]):
    """Polls the UNAS Drive REST API and exposes typed models."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: UnasClient,
        capabilities: Capabilities,
        scan_interval: int,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(seconds=scan_interval),
        )
        self.client = client
        self.capabilities = capabilities
        self.hub_device_id: str | None = None
        """Device-registry id of the hub, set by `async_setup_entry` before the
        platforms load. Sub-devices point at it (see `entity.link_to_hub`)."""

    async def _optional[T](self, call: Callable[[], Awaitable[T]]) -> T | None:
        """Run a supplementary (capability-scoped) fetch.

        A scope denial (UnasCapabilityError) or API error degrades that field to
        None instead of failing the whole update — so a transient 403 on shares/
        users/updates/fan does not take the core sensors unavailable. Auth (401)
        and connection errors still propagate so re-auth / retry fire.
        """
        try:
            return await call()
        except (UnasCapabilityError, UnasApiError):
            return None

    async def _async_update_data(self) -> UnasData:
        try:
            storage, device_info, network_io = await asyncio.gather(
                self.client.get_storage(),
                self.client.get_device_info(),
                self.client.get_network_io(),
            )
            shares = (
                await self._optional(self.client.get_shares) if self.capabilities.shares else None
            )
            user_count = (
                await self._optional(self.client.get_user_count)
                if self.capabilities.users
                else None
            )
            update_info = (
                await self._optional(self.client.get_update_info)
                if self.capabilities.updates
                else None
            )
            fan_control = await self._optional(self.client.get_fan_control)
            notifications = (
                await self._optional(self.client.get_notification_summary)
                if self.capabilities.notifications
                else None
            )
            logs = (
                await self._optional(self.client.get_log_summary)
                if self.capabilities.logs
                else None
            )
        except UnasAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except UnasCertificateMismatch as err:
            # Must precede UnasConnectionError, its base class. A certificate that
            # changes while the integration is running is the same event as one
            # that changes before setup, and it has to reach the user the same
            # way: as a repair naming both fingerprints. Left to the branch
            # below it becomes an ordinary UpdateFailed, and the entities simply
            # go unavailable with the reason buried in the log.
            if self.config_entry is not None:
                raise_cert_mismatch(self.hass, self.config_entry, err)
            raise UpdateFailed(str(err)) from err
        except (UnasConnectionError, UnasApiError) as err:
            raise UpdateFailed(str(err)) from err
        return UnasData(
            storage=storage,
            device_info=device_info,
            network_io=network_io,
            user_count=user_count,
            shares=shares,
            update_info=update_info,
            fan_control=fan_control,
            notification_summary=notifications,
            log_summary=logs,
        )
