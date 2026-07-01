"""Control-button tests (opt-in)."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from custom_components.unifi_unas_rest.aiounas.exceptions import UnasApiError, UnasCapabilityError
from custom_components.unifi_unas_rest.const import (
    AUTH_API_KEY,
    AUTH_PASSWORD,
    CONF_AUTH_METHOD,
    CONF_ENABLE_CONTROLS,
    DOMAIN,
)
from homeassistant.const import (
    ATTR_ENTITY_ID,
    CONF_API_KEY,
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
)
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

_BASE = {CONF_HOST: "192.0.2.10", CONF_PORT: 443, CONF_VERIFY_SSL: False}


def _entry(controls: bool, *, session: bool = False) -> MockConfigEntry:
    if session:
        data = {
            **_BASE,
            CONF_USERNAME: "user",
            CONF_PASSWORD: "pass",
            CONF_AUTH_METHOD: AUTH_PASSWORD,
        }
    else:
        data = {**_BASE, CONF_API_KEY: "test-api-key-0123456789", CONF_AUTH_METHOD: AUTH_API_KEY}
    return MockConfigEntry(
        domain=DOMAIN,
        unique_id="AABBCC000001",
        data=data,
        options={CONF_ENABLE_CONTROLS: controls},
    )


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


def _reboot_eid(hass: HomeAssistant) -> str | None:
    return er.async_get(hass).async_get_entity_id("button", DOMAIN, "AABBCC000001_reboot")


async def test_no_buttons_when_controls_disabled(
    hass: HomeAssistant, mock_aiounas: AsyncMock
) -> None:
    await _setup(hass, _entry(controls=False, session=True))
    assert _reboot_eid(hass) is None


async def test_no_buttons_with_api_key_auth(hass: HomeAssistant, mock_aiounas: AsyncMock) -> None:
    # Controls enabled but API-key auth: the key cannot write, so no buttons are created.
    await _setup(hass, _entry(controls=True, session=False))
    assert _reboot_eid(hass) is None


async def test_buttons_present_and_press_calls_action(
    hass: HomeAssistant, mock_aiounas: AsyncMock
) -> None:
    await _setup(hass, _entry(controls=True, session=True))
    registry = er.async_get(hass)
    for key in ("reboot", "shutdown", "update_firmware", "update_drive_app"):
        assert registry.async_get_entity_id("button", DOMAIN, f"AABBCC000001_{key}"), key

    await hass.services.async_call(
        "button", "press", {ATTR_ENTITY_ID: _reboot_eid(hass)}, blocking=True
    )
    mock_aiounas.action_mock.reboot.assert_awaited_once()


async def test_press_permission_error_raises_clear_message(
    hass: HomeAssistant, mock_aiounas: AsyncMock
) -> None:
    mock_aiounas.action_mock.reboot = AsyncMock(
        side_effect=UnasCapabilityError("forbidden for /api/system/reboot")
    )
    await _setup(hass, _entry(controls=True, session=True))
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "button", "press", {ATTR_ENTITY_ID: _reboot_eid(hass)}, blocking=True
        )


async def test_press_api_error_raises_clear_message(
    hass: HomeAssistant, mock_aiounas: AsyncMock
) -> None:
    mock_aiounas.action_mock.reboot = AsyncMock(
        side_effect=UnasApiError("unexpected status 500", status=500)
    )
    await _setup(hass, _entry(controls=True, session=True))
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "button", "press", {ATTR_ENTITY_ID: _reboot_eid(hass)}, blocking=True
        )


async def test_options_flow_rejects_controls_with_api_key(
    hass: HomeAssistant, mock_aiounas: AsyncMock
) -> None:
    entry = _entry(controls=False, session=False)  # API-key auth
    await _setup(hass, entry)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_ENABLE_CONTROLS: True}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "controls_need_session"}
    assert entry.options.get(CONF_ENABLE_CONTROLS) is not True


async def test_fan_select_present_and_sets_profile(
    hass: HomeAssistant, mock_aiounas: AsyncMock
) -> None:
    await _setup(hass, _entry(controls=True, session=True))
    registry = er.async_get(hass)
    eid = registry.async_get_entity_id("select", DOMAIN, "AABBCC000001_fan_profile")
    assert eid
    st = hass.states.get(eid)
    assert st.state == "default"
    assert set(st.attributes["options"]) == {"cooling", "default", "quiet"}

    await hass.services.async_call(
        "select", "select_option", {ATTR_ENTITY_ID: eid, "option": "quiet"}, blocking=True
    )
    mock_aiounas.action_mock.set_fan_profile.assert_awaited_once_with("quiet")


async def test_no_fan_select_without_controls(hass: HomeAssistant, mock_aiounas: AsyncMock) -> None:
    await _setup(hass, _entry(controls=False, session=True))
    registry = er.async_get(hass)
    assert registry.async_get_entity_id("select", DOMAIN, "AABBCC000001_fan_profile") is None


async def test_options_flow_toggles_controls(hass: HomeAssistant, mock_aiounas: AsyncMock) -> None:
    entry = _entry(controls=False, session=True)
    await _setup(hass, entry)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["step_id"] == "init"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_ENABLE_CONTROLS: True}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_ENABLE_CONTROLS] is True
    await hass.async_block_till_done()  # options change triggers a reload
