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
from .tls import (
    TlsMode,
    UnasCertificateMismatch,
    async_probe_fingerprint,
    format_fingerprint,
    parse_fingerprint,
    ssl_from_env,
    ssl_param,
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
    "TlsMode",
    "UnasActionClient",
    "UnasApiError",
    "UnasAuthError",
    "UnasCapabilityError",
    "UnasCertificateMismatch",
    "UnasClient",
    "UnasConnectionError",
    "UnasError",
    "UnasTransport",
    "UpdateInfo",
    "async_probe_fingerprint",
    "format_fingerprint",
    "parse_fingerprint",
    "probe",
    "ssl_from_env",
    "ssl_param",
]
