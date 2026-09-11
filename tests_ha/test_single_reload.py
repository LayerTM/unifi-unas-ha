"""Every path that changes a loaded entry sets it up exactly once.

The entry used to keep an update listener that reloaded it. A reconfigure or a
re-authentication ends in `async_update_reload_and_abort`, which updates the
entry — firing that listener, reload one — and then schedules a reload of its
own — reload two. The core reports that combination as breaking in 2026.12, but
the first reload removed the listener before the core looked, so the report
never appeared. None of this is visible unless the entry is loaded first, which
is why every test here sets it up before touching it.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from unittest.mock import AsyncMock, patch

import custom_components.unifi_unas_rest as integration
import homeassistant.config_entries as config_entries
from custom_components.unifi_unas_rest.aiounas import TlsMode
from custom_components.unifi_unas_rest.const import (
    AUTH_API_KEY,
    CONF_AUTH_METHOD,
    CONF_ENABLE_CONTROLS,
    CONF_TLS_MODE,
    DOMAIN,
    ISSUE_TLS_INSECURE,
)
from custom_components.unifi_unas_rest.repairs import async_create_fix_flow
from homeassistant.config_entries import SOURCE_REAUTH
from homeassistant.const import CONF_API_KEY, CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry


class _Watch:
    def __init__(self) -> None:
        self.setups = 0
        self.reports: list[str] = []


@contextmanager
def _watch() -> Iterator[_Watch]:
    """Count setups of the entry and any report the core makes about reloading."""
    watch = _Watch()
    real_setup = integration.async_setup_entry
    real_report = config_entries.report_usage

    async def counting_setup(hass: HomeAssistant, entry: MockConfigEntry) -> bool:
        watch.setups += 1
        return await real_setup(hass, entry)

    def recording_report(what: str, *args: Any, **kwargs: Any) -> None:
        watch.reports.append(what)
        real_report(what, *args, **kwargs)

    with (
        patch.object(integration, "async_setup_entry", counting_setup),
        patch.object(config_entries, "report_usage", recording_report),
    ):
        yield watch


async def _loaded(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_a_loaded_entry_keeps_no_update_listener(
    hass: HomeAssistant, mock_aiounas: AsyncMock, config_entry: MockConfigEntry
) -> None:
    """The options flow reloads the entry itself; a listener would double it."""
    await _loaded(hass, config_entry)
    assert config_entry.update_listeners == []


async def test_reconfiguring_a_loaded_entry_sets_it_up_once(
    hass: HomeAssistant, mock_aiounas: AsyncMock, config_entry: MockConfigEntry
) -> None:
    await _loaded(hass, config_entry)
    with _watch() as watch:
        result = await config_entry.start_reconfigure_flow(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_HOST: "192.0.2.55",
                CONF_PORT: 443,
                CONF_TLS_MODE: TlsMode.INSECURE,
                CONF_AUTH_METHOD: AUTH_API_KEY,
            },
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_API_KEY: "new-key-000"}
        )
        await hass.async_block_till_done()

    assert result["reason"] == "reconfigure_successful"
    assert watch.setups == 1
    assert watch.reports == []


async def test_reauthenticating_a_loaded_entry_sets_it_up_once(
    hass: HomeAssistant, mock_aiounas: AsyncMock, config_entry: MockConfigEntry
) -> None:
    await _loaded(hass, config_entry)
    with _watch() as watch:
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": SOURCE_REAUTH, "entry_id": config_entry.entry_id},
            data=dict(config_entry.data),
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_API_KEY: "new-key-value"}
        )
        await hass.async_block_till_done()

    assert result["reason"] == "reauth_successful"
    assert watch.setups == 1
    assert watch.reports == []


async def test_changing_options_on_a_loaded_entry_sets_it_up_once(
    hass: HomeAssistant, mock_aiounas: AsyncMock, config_entry: MockConfigEntry
) -> None:
    await _loaded(hass, config_entry)
    with _watch() as watch:
        result = await hass.config_entries.options.async_init(config_entry.entry_id)
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {CONF_ENABLE_CONTROLS: False}
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert watch.setups == 1


async def test_saving_unchanged_options_does_not_reload(
    hass: HomeAssistant, mock_aiounas: AsyncMock, config_entry: MockConfigEntry
) -> None:
    """The other branch: a reload that nothing asked for is not free either."""
    config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(config_entry, options={CONF_ENABLE_CONTROLS: False})
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    with _watch() as watch:
        result = await hass.config_entries.options.async_init(config_entry.entry_id)
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {CONF_ENABLE_CONTROLS: False}
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert watch.setups == 0


async def test_pinning_a_certificate_on_a_loaded_entry_sets_it_up_once(
    hass: HomeAssistant, mock_aiounas: AsyncMock, config_entry: MockConfigEntry
) -> None:
    """The repair reloads the entry itself; the listener used to add a second one."""
    fingerprint = "ab:" * 31 + "ab"
    await _loaded(hass, config_entry)
    flow = await async_create_fix_flow(
        hass, f"{ISSUE_TLS_INSECURE}_{config_entry.entry_id}", {"entry_id": config_entry.entry_id}
    )
    flow.hass = hass
    with (
        _watch() as watch,
        patch(
            "custom_components.unifi_unas_rest.repairs.async_probe_fingerprint",
            AsyncMock(return_value=fingerprint),
        ),
    ):
        await flow.async_step_init()
        await flow.async_step_confirm({})
        await hass.async_block_till_done()

    assert watch.setups == 1
