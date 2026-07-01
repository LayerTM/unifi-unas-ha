"""Config flow tests."""

from __future__ import annotations

from unittest.mock import AsyncMock

from custom_components.unifi_unas_rest.const import (
    AUTH_API_KEY,
    AUTH_PASSWORD,
    CONF_AUTH_METHOD,
    DOMAIN,
)
from homeassistant.config_entries import SOURCE_REAUTH, SOURCE_USER
from homeassistant.const import (
    CONF_API_KEY,
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
)
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from aiounas import UnasAuthError, UnasConnectionError

_HOST = {CONF_HOST: "192.0.2.10", CONF_PORT: 443, CONF_VERIFY_SSL: False}


async def test_user_flow_api_key(hass: HomeAssistant, mock_aiounas: AsyncMock) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**_HOST, CONF_AUTH_METHOD: AUTH_API_KEY}
    )
    assert result["step_id"] == "api_key"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_KEY: "k123456789"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].unique_id == "AABBCC000001"
    assert result["data"][CONF_HOST] == "192.0.2.10"
    assert result["data"][CONF_AUTH_METHOD] == AUTH_API_KEY


async def test_user_flow_password(hass: HomeAssistant, mock_aiounas: AsyncMock) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**_HOST, CONF_AUTH_METHOD: AUTH_PASSWORD}
    )
    assert result["step_id"] == "password"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_USERNAME: "u", CONF_PASSWORD: "p"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_invalid_auth(hass: HomeAssistant, mock_aiounas: AsyncMock) -> None:
    mock_aiounas.async_prepare = AsyncMock(side_effect=UnasAuthError("bad"))
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**_HOST, CONF_AUTH_METHOD: AUTH_API_KEY}
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_API_KEY: "k"})
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


async def test_cannot_connect(hass: HomeAssistant, mock_aiounas: AsyncMock) -> None:
    mock_aiounas.async_prepare = AsyncMock(side_effect=UnasConnectionError("down"))
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**_HOST, CONF_AUTH_METHOD: AUTH_API_KEY}
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_API_KEY: "k"})
    assert result["errors"] == {"base": "cannot_connect"}


async def test_already_configured(
    hass: HomeAssistant, mock_aiounas: AsyncMock, config_entry: MockConfigEntry
) -> None:
    config_entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**_HOST, CONF_AUTH_METHOD: AUTH_API_KEY}
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_API_KEY: "k"})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauth(
    hass: HomeAssistant, mock_aiounas: AsyncMock, config_entry: MockConfigEntry
) -> None:
    config_entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_REAUTH, "entry_id": config_entry.entry_id},
        data=dict(config_entry.data),
    )
    assert result["step_id"] == "reauth_confirm"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_KEY: "new-key-value"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert config_entry.data[CONF_API_KEY] == "new-key-value"
    # async_update_reload_and_abort schedules a reload; let it finish so no
    # background task lingers past teardown.
    await hass.async_block_till_done()
