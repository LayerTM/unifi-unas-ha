"""Related readings share a leading word, so they sort next to each other."""

from __future__ import annotations

from unittest.mock import AsyncMock

from custom_components.unifi_unas_rest.const import DOMAIN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

CONSOLE = "AABBCC000001"
DISK = f"{CONSOLE}_disk1"
POOL = f"{CONSOLE}_pool00000000-0000-4000-8000-000000000001"
SHARE = f"{CONSOLE}_share00000000-0000-4000-8000-000000000011"

# The readings that describe one quantity from several sides.
GROUPS = (
    ("Transfer", (f"{DISK}_read_rate", f"{DISK}_write_rate")),
    ("Storage", (f"{POOL}_capacity", f"{POOL}_used", f"{POOL}_usage")),
    ("Storage", (f"{SHARE}_usage", f"{SHARE}_quota")),
)


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


def _name(hass: HomeAssistant, unique_id: str) -> str:
    registry = er.async_get(hass)
    eid = registry.async_get_entity_id("sensor", DOMAIN, unique_id)
    assert eid, unique_id
    name = registry.async_get(eid).original_name
    assert name, unique_id
    return name


async def test_each_group_starts_with_one_word(
    hass: HomeAssistant, mock_aiounas: AsyncMock, config_entry: MockConfigEntry
) -> None:
    """Checked in the registry, so the disabled-by-default disk rates count too."""
    await _setup(hass, config_entry)
    for prefix, unique_ids in GROUPS:
        names = [_name(hass, uid) for uid in unique_ids]
        assert all(n.startswith(f"{prefix} ") for n in names), names
        assert len(set(names)) == len(names), names


async def test_pools_and_shares_use_the_consoles_storage_words(
    hass: HomeAssistant, mock_aiounas: AsyncMock, config_entry: MockConfigEntry
) -> None:
    """One word for one meaning: bytes used and percent used read alike everywhere."""
    await _setup(hass, config_entry)
    used, usage, total = (_name(hass, f"{CONSOLE}_storage_{k}") for k in ("used", "usage", "total"))
    assert _name(hass, f"{POOL}_used") == used
    assert _name(hass, f"{POOL}_usage") == usage
    assert _name(hass, f"{POOL}_capacity") == total
    assert _name(hass, f"{SHARE}_usage") == used


async def test_a_new_installation_gets_the_new_words_in_its_entity_ids(
    hass: HomeAssistant, mock_aiounas: AsyncMock, config_entry: MockConfigEntry
) -> None:
    await _setup(hass, config_entry)
    registry = er.async_get(hass)
    assert (
        registry.async_get_entity_id("sensor", DOMAIN, f"{DISK}_read_rate")
        == "sensor.name_example_disk_1_transfer_read_rate"
    )
    assert (
        registry.async_get_entity_id("sensor", DOMAIN, f"{POOL}_capacity")
        == "sensor.name_example_pool_1_storage_total"
    )


async def test_an_existing_installation_keeps_its_entity_ids(
    hass: HomeAssistant, mock_aiounas: AsyncMock, config_entry: MockConfigEntry
) -> None:
    """Only the displayed name changes; automations keep pointing at the same IDs."""
    config_entry.add_to_hass(hass)
    registry = er.async_get(hass)
    earlier = {
        f"{DISK}_read_rate": "sensor.disk_1_read_rate",
        f"{DISK}_write_rate": "sensor.disk_1_write_rate",
        f"{POOL}_capacity": "sensor.pool_1_capacity",
        f"{POOL}_used": "sensor.pool_1_used",
        f"{POOL}_usage": "sensor.pool_1_usage",
        f"{SHARE}_usage": "sensor.share1_usage",
        f"{SHARE}_quota": "sensor.share1_quota",
    }
    for unique_id, entity_id in earlier.items():
        registry.async_get_or_create(
            "sensor",
            DOMAIN,
            unique_id,
            suggested_object_id=entity_id.split(".", 1)[1],
            config_entry=config_entry,
        )
        assert registry.async_get_entity_id("sensor", DOMAIN, unique_id) == entity_id

    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    for unique_id, entity_id in earlier.items():
        assert registry.async_get_entity_id("sensor", DOMAIN, unique_id) == entity_id
    assert registry.async_get("sensor.disk_1_read_rate").original_name == "Transfer read rate"
    state = hass.states.get("sensor.pool_1_capacity")
    assert state is not None
    assert state.attributes["friendly_name"].endswith("Pool 1 Storage total")
