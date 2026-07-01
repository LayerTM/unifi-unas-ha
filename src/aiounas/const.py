"""Constants: endpoint paths, defaults, header names."""

from __future__ import annotations

from typing import Final

DEFAULT_PORT: Final = 443
DEFAULT_TIMEOUT: Final = 15
DEFAULT_VERIFY_SSL: Final = False

# UniFi OS core
PATH_LOGIN: Final = "/api/auth/login"
PATH_SYSTEM: Final = "/api/system"  # short (public/key) or full (session)

# Drive app (reverse-proxied)
PATH_STORAGE: Final = "/proxy/drive/api/v2/storage"
PATH_DEVICE_INFO: Final = "/proxy/drive/api/v2/systems/device-info"
PATH_NETWORK_IO: Final = "/proxy/drive/api/v2/systems/network-io"
PATH_FAN_CONTROL: Final = "/proxy/drive/api/v2/systems/fan-control"
PATH_SHARES: Final = "/proxy/drive/api/v2/drives"  # session-only

HEADER_API_KEY: Final = "X-API-Key"
HEADER_CSRF: Final = "X-CSRF-Token"
HEADER_CSRF_UPDATED: Final = "X-Updated-CSRF-Token"
COOKIE_TOKEN: Final = "TOKEN"
