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
    Application,
    DeviceInfo,
    Disk,
    FanControl,
    LogSummary,
    NetworkIO,
    NotificationSummary,
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
    "Application",
    "Capabilities",
    "DeviceInfo",
    "Disk",
    "FanControl",
    "LogSummary",
    "NetworkIO",
    "NotificationSummary",
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
__version__ = "1.4.0"
