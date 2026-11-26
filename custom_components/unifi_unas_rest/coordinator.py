"""Data update coordinator for the UniFi UNAS integration."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .aiounas import (
    Capabilities,
    ConsoleBackup,
    DeviceInfo,
    FanControl,
    LogSummary,
    NetworkIO,
    NotificationSummary,
    Share,
    Storage,
    StorageIO,
    UnasApiError,
    UnasAuthError,
    UnasCapabilityError,
    UnasCertificateMismatch,
    UnasClient,
    UnasConnectionError,
    UpdateInfo,
)
from .const import DOMAIN
from .issues import clear_cert_mismatch, raise_cert_mismatch, sync_storage_issues

_LOGGER = logging.getLogger(__name__)

MAX_RETRY_DELAY = 15.0
"""Longest wait, in seconds, before a failed read of a poll is sent once more;
a short scan interval caps it at half the interval."""


class Read(StrEnum):
    """A read whose failure affects only the entities that depend on it.

    Storage and device info are not listed: they prove the console answers this
    credential and describe the hub and its drives, so their failure fails the
    whole update. The value names the read in the log.
    """

    NETWORK_IO = "network throughput"
    SHARES = "shared drives"
    USERS = "user count"
    SYSTEM = "firmware and console backup settings"
    FAN_CONTROL = "fan control"
    NOTIFICATIONS = "notifications"
    LOGS = "logs"
    STORAGE_IO = "storage throughput"
    BACKUP_TASKS = "backup tasks"


@dataclass(slots=True)
class UnasData:
    """Snapshot of everything the coordinator fetches each cycle."""

    storage: Storage
    device_info: DeviceInfo
    network_io: NetworkIO | None
    shares: list[Share] | None
    user_count: int | None
    update_info: UpdateInfo | None
    fan_control: FanControl | None
    notification_summary: NotificationSummary | None
    log_summary: LogSummary | None
    storage_io: StorageIO | None
    backup_task_count: int | None = None
    console_backup: ConsoleBackup | None = None
    failed_reads: frozenset[Read] = frozenset()
    """Reads that did not answer this cycle; their entities are unavailable."""


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
        self._retry_delay = min(MAX_RETRY_DELAY, scan_interval / 2)
        # An unload or a reload ends a wait through `async_shutdown`; stopping
        # Home Assistant does not call that for a config entry's coordinator.
        entry.async_on_unload(hass.bus.async_listen(EVENT_HOMEASSISTANT_STOP, self._async_stopping))
        self.capabilities = capabilities
        self.hub_device_id: str | None = None
        """Device-registry id of the hub, set by `async_setup_entry` before the
        platforms load. Sub-devices point at it (see `entity.link_to_hub`)."""
        self._storage_io: StorageIO | None = None
        self._failing: set[Read] = set()
        """Reads that failed the last time they were asked, to log each outage once."""
        self._served = set(Read) - {Read.FAN_CONTROL}
        """Reads this console is known to serve, so losing one is worth a warning.
        The setup probe checks each of them except fan control, which joins once
        it has answered."""

    @callback
    def _async_stopping(self, _: Event) -> None:
        self.client.cancel_retry()

    async def async_shutdown(self) -> None:
        self.client.cancel_retry()
        await super().async_shutdown()

    async def _read[T](
        self, read: Read, call: Callable[[], Awaitable[T]], failed: set[Read]
    ) -> T | None:
        """Run a read that only its own entities depend on.

        Any failure to answer (a server error, a timeout, a dropped connection,
        a refusal) adds *read* to *failed* instead of failing the whole update,
        and the next cycle asks again. A 401 counts as a refusal here too: the
        two anchor reads of this same cycle have already answered, so the
        credential is good and the 401 is the console refusing this auth method
        on a session-only read. Which status it picks is firmware-dependent
        (403 and 500 on UniFi OS 5.1.19 / Drive 4.3.6, 401 on 5.1.33 / Drive
        4.4.9), so the kind of refusal cannot be read off the status. Raising
        ConfigEntryAuthFailed for it would tear down a working entry and send
        the user into a re-auth loop over a credential that is not the problem.

        A changed certificate is the exception: it propagates, so the user is
        told. The first failure of a read the console serves is logged as a
        warning, the ones that follow at debug level, and the recovery once. A
        read it has never served is logged at debug level only.

        Only safe after the anchor reads have succeeded in this cycle; see
        :meth:`_async_update_data`, which awaits them first.
        """
        try:
            value = await call()
        except UnasCertificateMismatch:
            # Must precede UnasConnectionError, its base class.
            raise
        except (UnasCapabilityError, UnasApiError, UnasAuthError, UnasConnectionError) as err:
            first = read in self._served and read not in self._failing
            level = logging.WARNING if first else logging.DEBUG
            _LOGGER.log(level, "Could not read %s: %s", read, err)
            if read in self._served:
                self._failing.add(read)
            failed.add(read)
            return None
        self._served.add(read)
        if read in self._failing:
            self._failing.discard(read)
            _LOGGER.info("Reading %s works again", read)
        return value

    async def _storage_io_reading(self, failed: set[Read]) -> StorageIO | None:
        """The latest storage throughput, fetched only once a newer bucket exists.

        The console averages throughput over fixed buckets and reports completed
        ones only, so asking again before the next bucket ends returns the same
        numbers. Polling at the entry's interval would repeat the request ten
        times per bucket at the default 30 s for nothing.
        """
        last = self._storage_io
        if (
            last is not None
            and last.window_end is not None
            and last.interval is not None
            and time.time() < last.window_end + last.interval
        ):
            return last
        self._storage_io = await self._read(Read.STORAGE_IO, self.client.get_storage_io, failed)
        return self._storage_io

    async def _async_update_data(self) -> UnasData:
        failed: set[Read] = set()
        caps = self.capabilities
        # Not for the first poll: it is part of setup, which Home Assistant
        # retries by itself and which an unload waits for instead of ending.
        if self.data is not None:
            self.client.allow_one_retry(self._retry_delay)
        try:
            # The anchors run first and on their own: a 401 here IS a credential
            # failure, and it is what licenses _read to absorb a 401 below.
            storage, device_info = await asyncio.gather(
                self.client.get_storage(),
                self.client.get_device_info(),
            )
            network_io = (
                await self._read(Read.NETWORK_IO, self.client.get_network_io, failed)
                if caps.network_io
                else None
            )
            shares = (
                await self._read(Read.SHARES, self.client.get_shares, failed)
                if caps.shares
                else None
            )
            user_count = (
                await self._read(Read.USERS, self.client.get_user_count, failed)
                if caps.users
                else None
            )
            # One /api/system read serves every reading derived from it.
            system = (
                await self._read(Read.SYSTEM, self.client.get_system_readings, failed)
                if caps.updates or caps.console_backup
                else None
            )
            update_info = system.update_info if system and caps.updates else None
            fan_control = await self._read(Read.FAN_CONTROL, self.client.get_fan_control, failed)
            notifications = (
                await self._read(Read.NOTIFICATIONS, self.client.get_notification_summary, failed)
                if caps.notifications
                else None
            )
            logs = (
                await self._read(Read.LOGS, self.client.get_log_summary, failed)
                if caps.logs
                else None
            )
            storage_io = await self._storage_io_reading(failed) if caps.storage_io else None
            backup_task_count = (
                await self._read(Read.BACKUP_TASKS, self.client.get_backup_task_count, failed)
                if caps.backup_tasks
                else None
            )
            console_backup = system.console_backup if system and caps.console_backup else None
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
        # Symmetric with raising it above. Without this the repair outlives the
        # condition: the console recovers, the entities come back, and a scary
        # notification stays on a healthy system — offering to pin a certificate
        # that is no longer served.
        if self.config_entry is not None:
            clear_cert_mismatch(self.hass, self.config_entry)
            sync_storage_issues(
                self.hass,
                self.config_entry,
                device_info.name or "UNAS",
                storage,
            )
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
            storage_io=storage_io,
            backup_task_count=backup_task_count,
            console_backup=console_backup,
            failed_reads=frozenset(failed),
        )
