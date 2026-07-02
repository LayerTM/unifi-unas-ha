"""Map aiounas write failures to translated Home Assistant errors.

Keeps the control platforms (button/select/switch/update) DRY and gives every
user-facing action failure a translation key (see the ``exceptions`` block in
``strings.json``).
"""

from __future__ import annotations

from homeassistant.exceptions import HomeAssistantError

from .aiounas.exceptions import (
    UnasAuthError,
    UnasCapabilityError,
    UnasConnectionError,
    UnasError,
)
from .const import DOMAIN


def action_error(err: UnasError) -> HomeAssistantError:
    """Translate an aiounas write error into a user-facing HomeAssistantError."""
    if isinstance(err, UnasCapabilityError):
        return HomeAssistantError(translation_domain=DOMAIN, translation_key="not_permitted")
    if isinstance(err, UnasAuthError):
        return HomeAssistantError(translation_domain=DOMAIN, translation_key="auth_failed")
    if isinstance(err, UnasConnectionError):
        return HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="cannot_connect",
            translation_placeholders={"error": str(err)},
        )
    status = getattr(err, "status", None)
    return HomeAssistantError(
        translation_domain=DOMAIN,
        translation_key="action_failed",
        translation_placeholders={"detail": f" (HTTP {status})" if status else ""},
    )
