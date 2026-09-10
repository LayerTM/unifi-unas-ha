"""Constants for the UniFi UNAS (non-invasive) integration."""

from __future__ import annotations

from typing import Final

from homeassistant.const import Platform

from .aiounas import TlsMode

DOMAIN: Final = "unifi_unas_rest"

PLATFORMS: Final = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.UPDATE,
]

# config-entry option keys (host/port/username/password/api_key/verify_ssl reuse HA consts)
CONF_AUTH_METHOD: Final = "auth_method"
AUTH_API_KEY: Final = "api_key"
AUTH_PASSWORD: Final = "password"

# Opt-in control (write) operations. Off by default — v1 is read-only.
CONF_ENABLE_CONTROLS: Final = "enable_controls"
DEFAULT_ENABLE_CONTROLS: Final = False

DEFAULT_PORT: Final = 443

# TLS trust. The console's certificate is self-signed, so the choice is between
# pinning it and not checking at all; pinning is the default. CONF_VERIFY_SSL is
# still read once, to migrate entries created before this existed.
CONF_TLS_MODE: Final = "tls_mode"
CONF_CERT_FINGERPRINT: Final = "cert_fingerprint"
DEFAULT_TLS_MODE: Final = TlsMode.FINGERPRINT
ISSUE_CERT_MISMATCH: Final = "cert_mismatch"
ISSUE_TLS_INSECURE: Final = "tls_insecure"

DEFAULT_VERIFY_SSL: Final = False
DEFAULT_SCAN_INTERVAL: Final = 30
MIN_SCAN_INTERVAL: Final = 15
MAX_SCAN_INTERVAL: Final = 3600

MANUFACTURER: Final = "Ubiquiti"
