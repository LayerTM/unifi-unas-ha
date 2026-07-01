"""Select platform: fan-mode profile (opt-in control).

The fan-profile selector appears only when control actions are opted in (a session
is required to write the profile) and the device reports fan-control. Reading the
current profile works with either auth; changing it needs session auth.
"""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import UnasConfigEntry
from .aiounas import UnasActionClient
from .aiounas.exceptions import (
    UnasAuthError,
    UnasCapabilityError,
    UnasConnectionError,
    UnasError,
)
from .coordinator import UnasDataUpdateCoordinator
from .entity import UnasEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: UnasConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create the fan-mode selector when controls are opted in and fan-control exists."""
    runtime = entry.runtime_data
    if runtime.action_client is None or runtime.coordinator.data.fan_control is None:
        return
    async_add_entities([UnasFanSelect(runtime.coordinator, runtime.action_client)])


class UnasFanSelect(UnasEntity, SelectEntity):
    _attr_translation_key = "fan_profile"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self, coordinator: UnasDataUpdateCoordinator, action_client: UnasActionClient
    ) -> None:
        super().__init__(coordinator, "fan_profile")
        self._action_client = action_client

    @property
    def options(self) -> list[str]:
        fan = self.coordinator.data.fan_control
        return list(fan.available_profiles) if fan is not None else []

    @property
    def current_option(self) -> str | None:
        fan = self.coordinator.data.fan_control
        return (fan.current_profile or None) if fan is not None else None

    async def async_select_option(self, option: str) -> None:
        try:
            await self._action_client.set_fan_profile(option)
        except UnasCapabilityError as err:
            raise HomeAssistantError(
                "The UNAS account is not permitted to change the fan profile."
            ) from err
        except UnasAuthError as err:
            raise HomeAssistantError("Authentication with the UNAS failed.") from err
        except UnasConnectionError as err:
            raise HomeAssistantError(f"Could not reach the UNAS: {err}") from err
        except UnasError as err:
            status = getattr(err, "status", None)
            detail = f" (HTTP {status})" if status else ""
            raise HomeAssistantError(f"The UNAS rejected the fan profile{detail}.") from err
        await self.coordinator.async_request_refresh()
