"""Sub-devices carry the console's name, so their entities do too."""

from __future__ import annotations

from dataclasses import replace
from unittest.mock import AsyncMock, patch

from custom_components.unifi_unas_rest.aiounas import Capabilities
from custom_components.unifi_unas_rest.const import DOMAIN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


def _device_name(hass: HomeAssistant, domain: str, unique_id: str) -> str:
    ereg, dreg = er.async_get(hass), dr.async_get(hass)
    eid = ereg.async_get_entity_id(domain, DOMAIN, unique_id)
    assert eid, unique_id
    device = dreg.async_get(ereg.async_get(eid).device_id)
    assert device is not None and device.name
    return device.name


async def test_every_kind_of_sub_device_starts_with_the_console_name(
    hass: HomeAssistant, mock_aiounas: AsyncMock, config_entry: MockConfigEntry
) -> None:
    """Disks, pools and shares; the hub carried the name all along."""
    await _setup(hass, config_entry)
    console = _device_name(hass, "sensor", "AABBCC000001_cpu_temperature")
    assert console == "Name-Example"

    assert _device_name(hass, "sensor", "AABBCC000001_disk1_temperature") == f"{console} Disk 1"
    # A new installation gets the console's name in the entity ID as well.
    assert (
        er.async_get(hass).async_get_entity_id("sensor", DOMAIN, "AABBCC000001_disk1_temperature")
        == "sensor.name_example_disk_1_temperature"
    )
    pool = _device_name(hass, "sensor", "AABBCC000001_pool" + _pool_key(hass) + "_capacity")
    assert pool.startswith(f"{console} Pool ")
    share = _device_name(hass, "sensor", "AABBCC000001_share" + _share_key(hass) + "_usage")
    assert share.startswith(f"{console} ")
    assert share != console


def _pool_key(hass: HomeAssistant) -> str:
    for e in er.async_get(hass).entities.values():
        if e.platform == DOMAIN and "_pool" in e.unique_id and e.unique_id.endswith("_capacity"):
            return e.unique_id.split("_pool", 1)[1].rsplit("_capacity", 1)[0]
    raise AssertionError("fixture creates no pool")


def _share_key(hass: HomeAssistant) -> str:
    for e in er.async_get(hass).entities.values():
        if e.platform == DOMAIN and "_share" in e.unique_id and e.unique_id.endswith("_usage"):
            return e.unique_id.split("_share", 1)[1].rsplit("_usage", 1)[0]
    raise AssertionError("fixture creates no share")


async def test_two_consoles_give_their_disks_different_names(
    hass: HomeAssistant, unas_client: AsyncMock, config_entry: MockConfigEntry
) -> None:
    """Before, both consoles' first disk read "Disk 1 Temperature"."""
    first_info = await unas_client.get_device_info()
    second_client = AsyncMock()
    for name in dir(unas_client):
        if name.startswith("get_") or name == "async_prepare":
            setattr(second_client, name, getattr(unas_client, name))
    second_client.get_device_info = AsyncMock(return_value=replace(first_info, name="Other-NAS"))

    second = MockConfigEntry(
        domain=DOMAIN,
        unique_id="AABBCC000002",
        title="Other-NAS (192.0.2.11)",
        data={**config_entry.data, "host": "192.0.2.11"},
    )
    clients = {config_entry.data["host"]: unas_client, "192.0.2.11": second_client}

    def build(session: object, host: str, *args: object, **kwargs: object) -> AsyncMock:
        return clients[host]

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
    with (
        patch("custom_components.unifi_unas_rest.UnasClient", side_effect=build),
        patch("custom_components.unifi_unas_rest.probe", AsyncMock(return_value=caps)),
        patch("custom_components.unifi_unas_rest.UnasActionClient", return_value=AsyncMock()),
    ):
        await _setup(hass, config_entry)
        await _setup(hass, second)

    ereg = er.async_get(hass)
    names = []
    for uid in ("AABBCC000001_disk1_temperature", "AABBCC000002_disk1_temperature"):
        eid = ereg.async_get_entity_id("sensor", DOMAIN, uid)
        assert eid
        names.append(hass.states.get(eid).name)
    assert names == ["Name-Example Disk 1 Temperature", "Other-NAS Disk 1 Temperature"]
    # And a second console no longer needs a `_2` suffix to get its own entity IDs.
    ids = [
        ereg.async_get_entity_id("sensor", DOMAIN, u)
        for u in ("AABBCC000001_disk1_temperature", "AABBCC000002_disk1_temperature")
    ]
    assert not any(i.endswith("_2") for i in ids if i)


async def test_an_existing_installation_keeps_its_entity_ids(
    hass: HomeAssistant, mock_aiounas: AsyncMock, config_entry: MockConfigEntry
) -> None:
    """Upgrading must not rename an entity ID an automation already uses.

    Modelled on an entity registered before this change: its ID was made from the
    old sub-device name, and the renamed sub-device must leave it alone while the
    friendly name picks up the console's name.
    """
    config_entry.add_to_hass(hass)
    ereg = er.async_get(hass)
    old = ereg.async_get_or_create(
        "sensor",
        DOMAIN,
        "AABBCC000001_disk1_temperature",
        suggested_object_id="disk_1_temperature",
        config_entry=config_entry,
    )
    assert old.entity_id == "sensor.disk_1_temperature"

    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    eid = ereg.async_get_entity_id("sensor", DOMAIN, "AABBCC000001_disk1_temperature")
    assert eid == "sensor.disk_1_temperature"
    assert hass.states.get(eid).name == "Name-Example Disk 1 Temperature"


async def test_a_name_the_user_gave_the_sub_device_wins(
    hass: HomeAssistant, mock_aiounas: AsyncMock, config_entry: MockConfigEntry
) -> None:
    await _setup(hass, config_entry)
    ereg, dreg = er.async_get(hass), dr.async_get(hass)
    eid = ereg.async_get_entity_id("sensor", DOMAIN, "AABBCC000001_disk1_temperature")
    assert eid
    dreg.async_update_device(ereg.async_get(eid).device_id, name_by_user="Bay one")
    await hass.config_entries.async_reload(config_entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(eid).name == "Bay one Temperature"
