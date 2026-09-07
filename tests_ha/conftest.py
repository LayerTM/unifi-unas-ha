"""Fixtures for the UniFi UNAS integration tests.

pytest-homeassistant-custom-component auto-loads (entry point), so its fixtures
(hass, enable_custom_integrations, ...) are available without pytest_plugins.
The aiounas client is mocked with models built from the sanitized library
fixtures, so no network is touched.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from custom_components.unifi_unas_rest.aiounas import (
    Capabilities,
    DeviceInfo,
    FanControl,
    LogSummary,
    NetworkIO,
    NotificationSummary,
    Share,
    Storage,
    SystemIdentity,
    UpdateInfo,
)
from custom_components.unifi_unas_rest.const import AUTH_API_KEY, CONF_AUTH_METHOD, DOMAIN
from homeassistant.const import (
    CONF_API_KEY,
    CONF_HOST,
    CONF_PORT,
    CONF_VERIFY_SSL,
)
from homeassistant.helpers import frame
from pytest_homeassistant_custom_component.common import MockConfigEntry

_FX = Path(__file__).resolve().parents[1] / "tests" / "fixtures"


def _load(name: str) -> dict:
    return json.loads((_FX / f"{name}.json").read_text(encoding="utf-8"))


# Home Assistant announces every deprecated API it catches an integration using
# through one of three log channels, each with a fixed sentence of core's own:
#
#   helpers.frame.report_usage        "Detected that custom integration '<domain>' ..."
#   helpers.deprecation               "The deprecated <thing> was <used> from <domain> ..."
#   helpers.deprecation (substitute)  "'<old>' is deprecated. Please rename ..."
#
# Watching the channels instead of the APIs is what makes this general: an API
# that core deprecates next year turns the suite red the first time the floating
# harness carries that release, with core's own wording naming the call site —
# no test has to be taught the name of the API in advance.
_DEPRECATION_SENTENCES = (
    "Detected that custom integration",
    "The deprecated ",
    "is deprecated. Please rename",
)

_OUR_PACKAGE = "custom_components.unifi_unas_rest"


def ha_deprecation_reports(records: list[logging.LogRecord]) -> list[str]:
    """Return core's deprecation notices about this integration, in its own words."""
    found = []
    for record in records:
        if record.levelno < logging.WARNING:
            continue
        message = record.getMessage()
        if not any(sentence in message for sentence in _DEPRECATION_SENTENCES):
            continue
        # The frame and deprecation channels name the domain in the message; the
        # substitute channel logs under the reporting module instead.
        if DOMAIN in message or record.name.startswith(_OUR_PACKAGE):
            found.append(f"{record.name}: {message}")
    return found


class _RecordCollector(logging.Handler):
    """Keep every record of one test, whichever phase logged it."""

    def __init__(self, records: list[logging.LogRecord]) -> None:
        super().__init__(level=logging.NOTSET)
        self.records = records

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@pytest.fixture(autouse=True)
def ha_deprecation_log() -> Iterator[list[logging.LogRecord]]:
    """Fail any test in which Home Assistant reports a deprecated API used here.

    A handler of its own rather than `caplog`, whose `records` are scoped to the
    phase asking for them: read from a teardown, it answers with the teardown's
    records and stays empty however loudly the test body was warned.

    Core keeps a process-wide set of notices already emitted so a running
    instance is not flooded; cleared here so each test reports independently and
    a failure names every call site rather than only the run's first.
    """
    records: list[logging.LogRecord] = []
    handler = _RecordCollector(records)
    root = logging.getLogger()
    root.addHandler(handler)
    frame._REPORTED_INTEGRATIONS.clear()
    try:
        yield records
    finally:
        root.removeHandler(handler)
    reported = ha_deprecation_reports(records)
    assert not reported, "Home Assistant reports deprecated API usage:\n" + "\n".join(reported)


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
    client.get_user_count = AsyncMock(return_value=6)
    client.get_update_info = AsyncMock(return_value=UpdateInfo.from_api(_load("system_full")))
    client.get_fan_control = AsyncMock(return_value=FanControl.from_api(_load("fan_control")))
    client.get_notification_summary = AsyncMock(
        return_value=NotificationSummary.from_api(_load("notifications"))
    )
    client.get_log_summary = AsyncMock(return_value=LogSummary.from_api(_load("logs")))
    return client


@pytest.fixture
def mock_aiounas(unas_client: AsyncMock) -> Iterator[AsyncMock]:
    caps = Capabilities(
        storage=True,
        device_info=True,
        network_io=True,
        shares=True,
        users=True,
        updates=True,
        notifications=True,
        logs=True,
    )
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
