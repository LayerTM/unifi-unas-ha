"""The schema library Home Assistant validates flow forms with.

Home Assistant 2026.10 moved from voluptuous to probatio, which mirrors the
voluptuous API, and registers probatio under the ``voluptuous`` name at startup.
Importing ``voluptuous`` therefore always yields the library the running Home
Assistant validates with: real voluptuous before 2026.10, probatio from then on.
Type checking runs against the newest Home Assistant, whose flow helpers are
typed with probatio.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import probatio as vol
else:
    import voluptuous as vol

__all__ = ["vol"]
