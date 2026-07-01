"""aiounas — async client for the UniFi UNAS (UniFi Drive) local REST API."""

from __future__ import annotations

from .exceptions import (
    UnasApiError,
    UnasAuthError,
    UnasCapabilityError,
    UnasConnectionError,
    UnasError,
)

__all__ = [
    "UnasApiError",
    "UnasAuthError",
    "UnasCapabilityError",
    "UnasConnectionError",
    "UnasError",
]
__version__ = "0.1.0"
