"""Update platform: UniFi OS firmware and Drive-app updates.

Update entities appear when the full ``/api/system`` payload is available (session
auth). They surface installed/latest versions read-only; the Install button is
enabled only when control actions are opted in (an owner account is required to
actually install — the same gate as the control buttons).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.update import (
    UpdateDeviceClass,
    UpdateEntity,
    UpdateEntityDescription,
    UpdateEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import UnasConfigEntry
from .aiounas import UnasActionClient, UpdateInfo
from .aiounas.exceptions import (
    UnasAuthError,
    UnasCapabilityError,
    UnasConnectionError,
    UnasError,
)
from .coordinator import UnasDataUpdateCoordinator
from .entity import UnasEntity


@dataclass(frozen=True, kw_only=True)
class UnasUpdateDescription(UpdateEntityDescription):
    installed_fn: Callable[[UpdateInfo], str | None]
    latest_fn: Callable[[UpdateInfo], str | None]
    install_fn: Callable[[UnasActionClient], Awaitable[None]]


UPDATES: tuple[UnasUpdateDescription, ...] = (
    UnasUpdateDescription(
        key="unifi_os_update",
        translation_key="unifi_os_update",
        device_class=UpdateDeviceClass.FIRMWARE,
        installed_fn=lambda u: u.unifi_os_installed or None,
        latest_fn=lambda u: u.unifi_os_latest or u.unifi_os_installed or None,
        install_fn=lambda client: client.update_firmware(),
    ),
    UnasUpdateDescription(
        key="drive_update",
        translation_key="drive_update",
        device_class=UpdateDeviceClass.FIRMWARE,
        installed_fn=lambda u: u.drive_installed or None,
        latest_fn=lambda u: u.drive_latest or u.drive_installed or None,
        install_fn=lambda client: client.update_drive_app(),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: UnasConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create update entities only when the full /api/system is available (session)."""
    runtime = entry.runtime_data
    if not runtime.coordinator.capabilities.updates:
        return
    async_add_entities(
        UnasUpdate(runtime.coordinator, description, runtime.action_client)
        for description in UPDATES
    )


class UnasUpdate(UnasEntity, UpdateEntity):
    entity_description: UnasUpdateDescription

    def __init__(
        self,
        coordinator: UnasDataUpdateCoordinator,
        description: UnasUpdateDescription,
        action_client: UnasActionClient | None,
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description
        self._action_client = action_client
        if action_client is not None:
            self._attr_supported_features = UpdateEntityFeature.INSTALL

    @property
    def _info(self) -> UpdateInfo | None:
        return self.coordinator.data.update_info

    @property
    def installed_version(self) -> str | None:
        info = self._info
        return self.entity_description.installed_fn(info) if info is not None else None

    @property
    def latest_version(self) -> str | None:
        info = self._info
        return self.entity_description.latest_fn(info) if info is not None else None

    async def async_install(self, version: str | None, backup: bool, **kwargs: Any) -> None:
        if self._action_client is None:
            raise HomeAssistantError(
                "Enable control actions (with an owner account) to install updates."
            )
        try:
            await self.entity_description.install_fn(self._action_client)
        except UnasCapabilityError as err:
            raise HomeAssistantError(
                "The UNAS account is not permitted to install updates (owner account required)."
            ) from err
        except UnasAuthError as err:
            raise HomeAssistantError("Authentication with the UNAS failed.") from err
        except UnasConnectionError as err:
            raise HomeAssistantError(f"Could not reach the UNAS: {err}") from err
        except UnasError as err:
            status = getattr(err, "status", None)
            detail = f" (HTTP {status})" if status else ""
            raise HomeAssistantError(f"The UNAS could not install the update{detail}.") from err
        await self.coordinator.async_request_refresh()
