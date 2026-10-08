"""Update rows name the console software they install, not this integration."""

from __future__ import annotations

from unittest.mock import AsyncMock

from custom_components.unifi_unas_rest.const import DOMAIN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

CONSOLE = "AABBCC000001"


async def test_update_rows_name_the_console_software(
    hass: HomeAssistant, mock_aiounas: AsyncMock, config_entry: MockConfigEntry
) -> None:
    """Settings > Updates groups rows under the integration's name and shows each
    row as "<area> - <title> <latest version>", so the title must say what updates."""
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    registry = er.async_get(hass)
    expected = {
        "unifi_os_update": ("UniFi OS firmware", "5.2.0"),
        "drive_update": ("UniFi Drive app", "4.4.0"),
    }
    for key, (title, latest) in expected.items():
        eid = registry.async_get_entity_id("update", DOMAIN, f"{CONSOLE}_{key}")
        assert eid, key
        state = hass.states.get(eid)
        assert state is not None
        assert state.attributes["title"] == title
        assert state.attributes["friendly_name"].endswith(title)
        assert state.attributes["latest_version"] == latest
        assert state.attributes["release_summary"] == "Release channel: release"
