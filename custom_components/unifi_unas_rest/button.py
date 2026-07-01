"""Button platform (opt-in control actions) for the UniFi UNAS integration."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from homeassistant.components.button import (
    ButtonDeviceClass,
    ButtonEntity,
    ButtonEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import UnasConfigEntry
from .aiounas import UnasActionClient
from .coordinator import UnasDataUpdateCoordinator
from .entity import UnasEntity


@dataclass(frozen=True, kw_only=True)
class UnasButtonDescription(ButtonEntityDescription):
    press_fn: Callable[[UnasActionClient], Awaitable[None]]


BUTTONS: tuple[UnasButtonDescription, ...] = (
    UnasButtonDescription(
        key="reboot",
        translation_key="reboot",
        device_class=ButtonDeviceClass.RESTART,
        entity_category=EntityCategory.CONFIG,
        press_fn=lambda client: client.reboot(),
    ),
    UnasButtonDescription(
        key="shutdown",
        translation_key="shutdown",
        entity_category=EntityCategory.CONFIG,
        press_fn=lambda client: client.shutdown(),
    ),
    UnasButtonDescription(
        key="update_firmware",
        translation_key="update_firmware",
        entity_category=EntityCategory.CONFIG,
        press_fn=lambda client: client.update_firmware(),
    ),
    UnasButtonDescription(
        key="update_drive_app",
        translation_key="update_drive_app",
        entity_category=EntityCategory.CONFIG,
        press_fn=lambda client: client.update_drive_app(),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: UnasConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up control buttons only when the user has opted in to controls."""
    runtime = entry.runtime_data
    if runtime.action_client is None:
        return
    async_add_entities(
        UnasButton(runtime.coordinator, runtime.action_client, description)
        for description in BUTTONS
    )


class UnasButton(UnasEntity, ButtonEntity):
    entity_description: UnasButtonDescription

    def __init__(
        self,
        coordinator: UnasDataUpdateCoordinator,
        action_client: UnasActionClient,
        description: UnasButtonDescription,
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description
        self._action_client = action_client

    async def async_press(self) -> None:
        await self.entity_description.press_fn(self._action_client)
