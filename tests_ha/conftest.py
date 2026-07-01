"""Fixtures for the UniFi UNAS integration tests.

pytest-homeassistant-custom-component auto-loads (entry point), so its fixtures
(hass, enable_custom_integrations, ...) are available without pytest_plugins.
The aiounas client is mocked with models built from the sanitized library
fixtures, so no network is touched.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from custom_components.unifi_unas_rest.aiounas import (
    Capabilities,
    DeviceInfo,
    NetworkIO,
    Share,
    Storage,
    SystemIdentity,
)
from custom_components.unifi_unas_rest.const import AUTH_API_KEY, CONF_AUTH_METHOD, DOMAIN
from homeassistant.const import (
    CONF_API_KEY,
    CONF_HOST,
    CONF_PORT,
    CONF_VERIFY_SSL,
)
from pytest_homeassistant_custom_component.common import MockConfigEntry

_FX = Path(__file__).resolve().parents[1] / "tests" / "fixtures"


def _load(name: str) -> dict:
    return json.loads((_FX / f"{name}.json").read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def _enable_custom(enable_custom_integrations: object) -> None:
    """Allow HA to load the custom integration."""
    return None


@pytest.fixture
def unas_client() -> AsyncMock:
    client = AsyncMock()
    client.async_prepare = AsyncMock(return_value=None)
    client.get_identity = AsyncMock(return_value=SystemIdentity.from_api(_load("system_short")))
    client.get_storage = AsyncMock(return_value=Storage.from_api(_load("storage")))
    client.get_device_info = AsyncMock(return_value=DeviceInfo.from_api(_load("device_info")))
    client.get_network_io = AsyncMock(return_value=NetworkIO.from_api(_load("network_io")))
    client.get_shares = AsyncMock(
        return_value=[Share.from_api(x) for x in _load("drives")["drives"]]
    )
    return client


@pytest.fixture
def mock_aiounas(unas_client: AsyncMock) -> Iterator[AsyncMock]:
    caps = Capabilities(storage=True, device_info=True, network_io=True, shares=True)
    action = AsyncMock()
    unas_client.action_mock = action  # exposed for control tests
    with (
        patch("custom_components.unifi_unas_rest.UnasClient", return_value=unas_client),
        patch("custom_components.unifi_unas_rest.probe", AsyncMock(return_value=caps)),
        patch("custom_components.unifi_unas_rest.UnasActionClient", return_value=action),
        patch(
            "custom_components.unifi_unas_rest.config_flow.UnasClient",
            return_value=unas_client,
        ),
    ):
        yield unas_client


@pytest.fixture
def config_entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        unique_id="AABBCC000001",
        title="Name-Example (192.0.2.10)",
        data={
            CONF_HOST: "192.0.2.10",
            CONF_PORT: 443,
            CONF_VERIFY_SSL: False,
            CONF_API_KEY: "test-api-key-0123456789",
            CONF_AUTH_METHOD: AUTH_API_KEY,
        },
    )
