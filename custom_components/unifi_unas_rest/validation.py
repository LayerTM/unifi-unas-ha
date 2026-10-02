"""The schema library Home Assistant validates flow forms with.

Home Assistant 2026.10 moved from voluptuous to probatio, which mirrors the
voluptuous API; a form schema must be a probatio schema there and a voluptuous
schema on the releases before it.
"""

from __future__ import annotations

try:
    import probatio as vol
except ImportError:  # Home Assistant before 2026.10
    import voluptuous as vol  # type: ignore[no-redef]

__all__ = ["vol"]
