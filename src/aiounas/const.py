"""Constants: endpoint paths, defaults, header names."""

from __future__ import annotations

from typing import Final

DEFAULT_PORT: Final = 443
DEFAULT_TIMEOUT: Final = 15
# TLS trust lives in .tls: a console's self-signed certificate is pinned by
# SHA-256 on first use rather than waved through. There is deliberately no
# "verification off" default here any more — see TlsMode.

# UniFi OS core
PATH_LOGIN: Final = "/api/auth/login"
PATH_SYSTEM: Final = "/api/system"  # short (public/key) or full (session)

# Drive app (reverse-proxied)
PATH_STORAGE: Final = "/proxy/drive/api/v2/storage"
PATH_DEVICE_INFO: Final = "/proxy/drive/api/v2/systems/device-info"
PATH_NETWORK_IO: Final = "/proxy/drive/api/v2/systems/network-io"
PATH_FAN_CONTROL: Final = "/proxy/drive/api/v2/systems/fan-control"
PATH_SHARES: Final = "/proxy/drive/api/v2/drives"  # session-only
PATH_USERS: Final = "/proxy/drive/api/v1/users"  # session-only; count only (list is PII)
PATH_NOTIFICATIONS: Final = "/api/notifications"  # session-only; counts only (bodies are PII)
PATH_LOGS: Final = "/proxy/drive/api/v2/systems/logs"  # session-only; counts only (data is PII)

# Write / action endpoints (v2). Power and update paths are well-established;
# the fan-control payload shape is UNVERIFIED against live hardware.
PATH_REBOOT: Final = "/api/system/reboot"
PATH_POWEROFF: Final = "/api/system/poweroff"
PATH_FIRMWARE_UPDATE: Final = "/api/firmware/update"
PATH_DRIVE_UPDATE: Final = "/api/applications/drive/update"

HEADER_API_KEY: Final = "X-API-Key"
HEADER_CSRF: Final = "X-CSRF-Token"
HEADER_CSRF_UPDATED: Final = "X-Updated-CSRF-Token"
COOKIE_TOKEN: Final = "TOKEN"
