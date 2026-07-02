"""Per-share snapshot switch tests (opt-in control)."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
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
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

_BASE = {CONF_HOST: "192.0.2.10", CONF_PORT: 443, CONF_VERIFY_SSL: False}
_SHARE1 = "00000000-0000-4000-8000-000000000011"  # snapshot_enabled=True in the fixture


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


def _eid(hass: HomeAssistant) -> str | None:
    return er.async_get(hass).async_get_entity_id(
        "switch", DOMAIN, f"AABBCC000001_share{_SHARE1}_snapshots"
    )


async def test_no_switch_without_controls(hass: HomeAssistant, mock_aiounas: AsyncMock) -> None:
    await _setup(hass, _entry(controls=False, session=True))
    assert _eid(hass) is None


async def test_no_switch_with_api_key_auth(hass: HomeAssistant, mock_aiounas: AsyncMock) -> None:
    await _setup(hass, _entry(controls=True, session=False))
    assert _eid(hass) is None


async def test_switch_reflects_state_and_toggles(
    hass: HomeAssistant, mock_aiounas: AsyncMock
) -> None:
    await _setup(hass, _entry(controls=True, session=True))
    eid = _eid(hass)
    assert eid
    assert hass.states.get(eid).state == "on"  # Share1 has snapshots enabled

    await hass.services.async_call("switch", "turn_off", {ATTR_ENTITY_ID: eid}, blocking=True)
    mock_aiounas.action_mock.set_share_snapshots.assert_awaited_once_with(_SHARE1, False)

    await hass.services.async_call("switch", "turn_on", {ATTR_ENTITY_ID: eid}, blocking=True)
    mock_aiounas.action_mock.set_share_snapshots.assert_awaited_with(_SHARE1, True)


@pytest.mark.parametrize(
    "exc",
    [
        UnasCapabilityError("forbidden"),
        UnasAuthError("bad"),
        UnasConnectionError("down"),
        UnasApiError("boom", status=500),
    ],
)
async def test_switch_error_raises(
    hass: HomeAssistant, mock_aiounas: AsyncMock, exc: Exception
) -> None:
    mock_aiounas.action_mock.set_share_snapshots = AsyncMock(side_effect=exc)
    await _setup(hass, _entry(controls=True, session=True))
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "switch", "turn_off", {ATTR_ENTITY_ID: _eid(hass)}, blocking=True
        )
