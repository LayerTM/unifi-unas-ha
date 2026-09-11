"""What the entry's current authentication can produce, said once.

An entry's authentication decides which readings the console will serve it, and
that can change under a live entry: reconfiguring from a local account to an API
key narrows it, and the reverse widens it again. Three things have to agree
about that set — the platforms, which create entities for it; the entity
registry, which must not keep what the platforms no longer create; and
diagnostics, which reports it. They agree because they read this one list.

Without the registry half, a narrowed entry keeps every entity the wider
authentication had created, permanently `unavailable`: a row that reads as a
fault when it is only a setting. That is the same defect that was fixed for the
control entities, one layer over, and it is fixed here for both at once.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Final

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .aiounas import Capabilities
from .const import CONTROL_PLATFORMS


@dataclass(frozen=True, slots=True)
class Reading:
    """A supplementary reading, and the entities that exist only because of it."""

    name: str
    """How the reading is named to a person, in the log and in diagnostics."""

    capability: str
    """The attribute on :class:`Capabilities` that says whether it is in scope."""

    keys: tuple[str, ...] = ()
    """Entity keys owned by this reading, as they appear in a unique id."""

    share_entities: bool = field(default=False)
    """Whether this reading owns every per-share entity (one per share, per key)."""


OPTIONAL_READINGS: Final = (
    Reading("shares", "shares", share_entities=True),
    Reading("accounts", "users", ("user_count",)),
    Reading("firmware updates", "updates", ("applications", "unifi_os_update", "drive_update")),
    Reading("notifications", "notifications", ("recent_events", "last_event")),
    Reading("logs", "logs", ("log_entries",)),
)
"""Readings a local account can reach and an API key cannot.

The core readings — storage, device info, network I/O — are not here: an entry
that cannot reach those has nothing to degrade to and fails setup instead.
"""


def readings_out_of_scope(capabilities: Capabilities) -> list[str]:
    """Name the supplementary readings this authentication cannot reach."""
    return [
        reading.name
        for reading in OPTIONAL_READINGS
        if not getattr(capabilities, reading.capability)
    ]


def _is_customized(registry: er.EntityRegistry, entity: er.RegistryEntry) -> bool:
    """Whether the user has put their own work into this registry row.

    Removing a row removes everything the user set on it, so a row carrying any
    of it is kept — it goes `unavailable` instead, which loses nothing and is the
    user's own choice to clean up. Only fields a person sets count:

    - a name, an icon, labels, categories, or an area chosen for the entity
      itself (a device's area lives on the device and survives regardless);
    - hidden or disabled by the user — not by the integration, which is how
      this one ships its high-churn sensors;
    - a voice alias: aliases hold the computed-name placeholder by default, so
      only an actual string counts, never "the list is not empty";
    - a hand-edited entity ID, when Home Assistant can say what the generated
      one would have been. That question has an answer only from 2026.2 on;
      on older releases an edited ID alone is not recognised.

    `options` is deliberately not read. Home Assistant writes into it on its
    own at setup — suggested display precision and unit conversion, 17 of this
    integration's 61 entities on a plain run — so a non-empty `options` cannot
    separate a user's choice from the core's bookkeeping, and counting it would
    keep exactly the rows this pruning exists to remove.
    """
    if entity.name or entity.icon or entity.labels or entity.categories or entity.area_id:
        return True
    if entity.hidden_by is er.RegistryEntryHider.USER:
        return True
    if entity.disabled_by is er.RegistryEntryDisabler.USER:
        return True
    if any(isinstance(alias, str) for alias in entity.aliases):
        return True
    regenerate = getattr(registry, "async_regenerate_entity_id", None)
    return regenerate is not None and entity.entity_id != regenerate(entity)


def _orphaned(unique_id: str, prefix: str, readings: Iterable[Reading]) -> bool:
    """Whether *unique_id* belongs to a reading that is out of scope."""
    for reading in readings:
        if reading.share_entities and unique_id.startswith(f"{prefix}share"):
            return True
        if any(unique_id == f"{prefix}{key}" for key in reading.keys):
            return True
    return False


def prune_registry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    capabilities: Capabilities,
    *,
    writes_available: bool,
) -> list[str]:
    """Drop registry entities this entry's authentication can no longer produce.

    Returns the entity ids removed, so a caller can report what it did.

    Runs at setup, before the platforms load, and is keyed on exactly the
    conditions the platforms themselves use — so the registry cannot end up
    claiming something the platforms decline to create. An entry that never
    narrows its authentication removes nothing, which is the common case.

    A row the user customised is never removed, whatever its scope; see
    :func:`_is_customized`.
    """
    registry = er.async_get(hass)
    prefix = f"{entry.unique_id}_"
    out_of_scope = [
        reading for reading in OPTIONAL_READINGS if not getattr(capabilities, reading.capability)
    ]
    removed: list[str] = []
    for entity in er.async_entries_for_config_entry(registry, entry.entry_id):
        stale_control = not writes_available and entity.domain in CONTROL_PLATFORMS
        out_of_reach = stale_control or _orphaned(entity.unique_id, prefix, out_of_scope)
        if out_of_reach and not _is_customized(registry, entity):
            registry.async_remove(entity.entity_id)
            removed.append(entity.entity_id)
    return removed
