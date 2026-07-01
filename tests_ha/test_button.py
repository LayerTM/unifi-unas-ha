"""Control-button tests (opt-in)."""

from __future__ import annotations

from unittest.mock import AsyncMock

from custom_components.unifi_unas_rest.const import (
    AUTH_API_KEY,
    CONF_AUTH_METHOD,
    CONF_ENABLE_CONTROLS,
    DOMAIN,
)
from homeassistant.const import (
    ATTR_ENTITY_ID,
    CONF_API_KEY,
    CONF_HOST,
    CONF_PORT,
    CONF_VERIFY_SSL,
)
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry


def _entry(controls: bool) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        unique_id="AABBCC000001",
        data={
            CONF_HOST: "192.0.2.10",
            CONF_PORT: 443,
            CONF_VERIFY_SSL: False,
            CONF_API_KEY: "test-api-key-0123456789",
            CONF_AUTH_METHOD: AUTH_API_KEY,
        },
        options={CONF_ENABLE_CONTROLS: controls},
    )


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_no_buttons_when_controls_disabled(
    hass: HomeAssistant, mock_aiounas: AsyncMock
) -> None:
    await _setup(hass, _entry(controls=False))
    registry = er.async_get(hass)
    assert registry.async_get_entity_id("button", DOMAIN, "AABBCC000001_reboot") is None


async def test_buttons_present_and_press_calls_action(
    hass: HomeAssistant, mock_aiounas: AsyncMock
) -> None:
    await _setup(hass, _entry(controls=True))
    registry = er.async_get(hass)
    for key in ("reboot", "shutdown", "update_firmware", "update_drive_app"):
        assert registry.async_get_entity_id("button", DOMAIN, f"AABBCC000001_{key}"), key

    reboot_eid = registry.async_get_entity_id("button", DOMAIN, "AABBCC000001_reboot")
    await hass.services.async_call("button", "press", {ATTR_ENTITY_ID: reboot_eid}, blocking=True)
    mock_aiounas.action_mock.reboot.assert_awaited_once()


async def test_options_flow_toggles_controls(hass: HomeAssistant, mock_aiounas: AsyncMock) -> None:
    entry = _entry(controls=False)
    await _setup(hass, entry)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["step_id"] == "init"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_ENABLE_CONTROLS: True}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_ENABLE_CONTROLS] is True
    await hass.async_block_till_done()  # options change triggers a reload
