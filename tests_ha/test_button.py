"""Control-button tests (opt-in)."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from custom_components.unifi_unas_rest.aiounas import TlsMode
from custom_components.unifi_unas_rest.aiounas.exceptions import (
    UnasApiError,
    UnasAuthError,
    UnasCapabilityError,
    UnasConnectionError,
)
from custom_components.unifi_unas_rest.const import (
    AUTH_API_KEY,
    AUTH_PASSWORD,
    CONF_AUTH_METHOD,
    CONF_ENABLE_CONTROLS,
    CONF_TLS_MODE,
    DOMAIN,
)
from homeassistant.const import (
    ATTR_ENTITY_ID,
    CONF_API_KEY,
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_USERNAME,
)
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

_BASE = {CONF_HOST: "192.0.2.10", CONF_PORT: 443, CONF_TLS_MODE: TlsMode.INSECURE}
_ERRORS = [
    UnasCapabilityError("forbidden"),
    UnasAuthError("bad"),
    UnasConnectionError("down"),
    UnasApiError("boom", status=500),
]


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


@pytest.mark.parametrize("exc", _ERRORS)
async def test_press_error_raises_clear_message(
    hass: HomeAssistant, mock_aiounas: AsyncMock, exc: Exception
) -> None:
    mock_aiounas.action_mock.reboot = AsyncMock(side_effect=exc)
    await _setup(hass, _entry(controls=True, session=True))
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "button", "press", {ATTR_ENTITY_ID: _reboot_eid(hass)}, blocking=True
        )


@pytest.mark.parametrize("exc", _ERRORS)
async def test_fan_select_error_raises_clear_message(
    hass: HomeAssistant, mock_aiounas: AsyncMock, exc: Exception
) -> None:
    mock_aiounas.action_mock.set_fan_profile = AsyncMock(side_effect=exc)
    await _setup(hass, _entry(controls=True, session=True))
    eid = er.async_get(hass).async_get_entity_id("select", DOMAIN, "AABBCC000001_fan_profile")
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "select", "select_option", {ATTR_ENTITY_ID: eid, "option": "quiet"}, blocking=True
        )


def _update_eid(hass: HomeAssistant) -> str | None:
    return er.async_get(hass).async_get_entity_id("update", DOMAIN, "AABBCC000001_unifi_os_update")


async def test_update_install_calls_action(hass: HomeAssistant, mock_aiounas: AsyncMock) -> None:
    await _setup(hass, _entry(controls=True, session=True))
    await hass.services.async_call(
        "update", "install", {ATTR_ENTITY_ID: _update_eid(hass)}, blocking=True
    )
    mock_aiounas.action_mock.update_firmware.assert_awaited_once()


@pytest.mark.parametrize("exc", _ERRORS)
async def test_update_install_error_raises_clear_message(
    hass: HomeAssistant, mock_aiounas: AsyncMock, exc: Exception
) -> None:
    mock_aiounas.action_mock.update_firmware = AsyncMock(side_effect=exc)
    await _setup(hass, _entry(controls=True, session=True))
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "update", "install", {ATTR_ENTITY_ID: _update_eid(hass)}, blocking=True
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


async def test_control_entities_are_removed_when_controls_are_turned_off(
    hass: HomeAssistant, mock_aiounas: AsyncMock
) -> None:
    """Opting out must clear the rows, not leave them `unavailable` forever.

    The platforms create nothing without a write client, so anything registered
    on an earlier run would otherwise sit in the UI permanently, reading as a
    fault rather than as a setting the user chose.
    """
    entry = _entry(True, session=True)
    await _setup(hass, entry)
    registry = er.async_get(hass)

    def control_entities() -> list[str]:
        return sorted(
            e.entity_id
            for e in er.async_entries_for_config_entry(registry, entry.entry_id)
            if e.domain in ("button", "select")
        )

    assert control_entities(), "the fixture must actually create control entities"

    hass.config_entries.async_update_entry(entry, options={CONF_ENABLE_CONTROLS: False})
    await hass.async_block_till_done()

    assert control_entities() == []


async def test_control_entities_survive_while_controls_are_on(
    hass: HomeAssistant, mock_aiounas: AsyncMock
) -> None:
    """The other direction: a reload with controls on must not clear them."""
    entry = _entry(True, session=True)
    await _setup(hass, entry)
    registry = er.async_get(hass)
    before = sorted(
        e.entity_id
        for e in er.async_entries_for_config_entry(registry, entry.entry_id)
        if e.domain in ("button", "select")
    )

    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    after = sorted(
        e.entity_id
        for e in er.async_entries_for_config_entry(registry, entry.entry_id)
        if e.domain in ("button", "select")
    )
    assert after == before


async def test_an_api_key_entry_keeps_no_control_rows(
    hass: HomeAssistant, mock_aiounas: AsyncMock
) -> None:
    """An API key cannot write, so controls-on must still leave no rows behind."""
    entry = _entry(True)  # API-key auth
    await _setup(hass, entry)
    registry = er.async_get(hass)
    assert [
        e.entity_id
        for e in er.async_entries_for_config_entry(registry, entry.entry_id)
        if e.domain in ("button", "select")
    ] == []
