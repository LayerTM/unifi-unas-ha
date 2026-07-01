"""aiounas — async client for the UniFi UNAS (UniFi Drive) local REST API."""

from __future__ import annotations

from .actions import UnasActionClient
from .auth import AbstractAuth, ApiKeyAuth, SessionAuth
from .capabilities import Capabilities, probe
from .client import UnasClient
from .exceptions import (
    UnasApiError,
    UnasAuthError,
    UnasCapabilityError,
    UnasConnectionError,
    UnasError,
)
from .models import (
    DeviceInfo,
    Disk,
    NetworkIO,
    Pool,
    RaidGroup,
    Share,
    Storage,
    SystemIdentity,
    UpdateInfo,
)
from .transport import UnasTransport

__all__ = [
    "AbstractAuth",
    "ApiKeyAuth",
    "Capabilities",
    "DeviceInfo",
    "Disk",
    "NetworkIO",
    "Pool",
    "RaidGroup",
    "SessionAuth",
    "Share",
    "Storage",
    "SystemIdentity",
    "UnasActionClient",
    "UnasApiError",
    "UnasAuthError",
    "UnasCapabilityError",
    "UnasClient",
    "UnasConnectionError",
    "UnasError",
    "UnasTransport",
    "UpdateInfo",
    "probe",
]
__version__ = "0.1.0"
