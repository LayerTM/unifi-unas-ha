"""A NAS that is not fully populated: an empty bay is not a disk at risk."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock

from custom_components.unifi_unas_rest.aiounas import Storage
from custom_components.unifi_unas_rest.const import DOMAIN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

_FX = Path(__file__).resolve().parents[1] / "tests" / "fixtures"


def _partial() -> Storage:
    return Storage.from_api(json.loads((_FX / "storage_partial.json").read_text()))


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


def _state(hass: HomeAssistant, domain: str, key: str) -> str:
    eid = er.async_get(hass).async_get_entity_id(domain, DOMAIN, f"AABBCC000001_{key}")
    assert eid, f"no {domain} for {key}"
    return hass.states.get(eid).state


async def test_an_empty_bay_raises_no_alarm(
    hass: HomeAssistant, mock_aiounas: AsyncMock, config_entry: MockConfigEntry
) -> None:
    """Reported on a 4-bay console with 3 drives: every at-risk signal fired.

    The empty bay made the hub count one disk at risk, switched the hub's
    storage-problem sensor on, and marked the bay's own problem sensor on.
    """
    mock_aiounas.get_storage = AsyncMock(return_value=_partial())
    await _setup(hass, config_entry)

    assert _state(hass, "sensor", "disks_at_risk") == "0"
    assert _state(hass, "binary_sensor", "storage_problem") == "off"
    assert _state(hass, "binary_sensor", "disk3_problem") == "off"
    # The bay is still shown, with the state the console gives it.
    assert _state(hass, "sensor", "disk3_state").lower() == "empty"


async def test_a_failing_drive_next_to_an_empty_bay_still_raises_the_alarm(
    hass: HomeAssistant, mock_aiounas: AsyncMock, config_entry: MockConfigEntry
) -> None:
    """The other branch: skipping the empty bay must not silence a real fault."""
    storage = _partial()
    failing = replace(storage.disks[0], state="degraded")
    mock_aiounas.get_storage = AsyncMock(
        return_value=replace(storage, disks=(failing, *storage.disks[1:]))
    )
    await _setup(hass, config_entry)

    assert _state(hass, "sensor", "disks_at_risk") == "1"
    assert _state(hass, "binary_sensor", "storage_problem") == "on"
    assert _state(hass, "binary_sensor", "disk1_problem") == "on"
    assert _state(hass, "binary_sensor", "disk3_problem") == "off"
