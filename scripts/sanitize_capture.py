#!/usr/bin/env python3
"""Sanitize a raw UNAS capture into a repo-safe fixture (canonical placeholders).

Best-effort deterministic redaction of device PII (serials, MACs, UUIDs, IPs,
names, direct-connect domains, GPS). ALWAYS re-run ``scripts/secret_scan.py`` on
the output before committing — this tool assists, the scanner enforces.

Usage:
    python scripts/sanitize_capture.py raw.json            # -> stdout
    python scripts/sanitize_capture.py raw.json out.json   # -> file
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
_MAC_COLON = re.compile(r"^[0-9A-Fa-f]{2}(:[0-9A-Fa-f]{2}){5}$")
_MAC_BARE = re.compile(r"^[0-9A-Fa-f]{12}$")
_IPV4 = re.compile(r"^\d{1,3}(\.\d{1,3}){3}$")

# Keys whose values are dropped entirely (highest-risk PII).
DROP_KEYS = {
    "directconnectdomain",
    "publicip",
    "sso_uuid",
    "anonymous_device_id",
    "setup_device_id",
    "location",
}
# Keys whose string values are replaced with a neutral name placeholder.
NAME_KEYS = {
    "name",
    "full_name",
    "fullname",
    "first_name",
    "firstname",
    "last_name",
    "lastname",
    "username",
    "hostname",
}
IP_KEYS = {"ip", "address", "gateway", "netmask", "cidr", "dns", "ipv4", "ipv6"}


@dataclass
class Counters:
    serial: int = 0
    mac: int = 0
    uuid: int = 0
    name: int = 0
    ip: int = 0
    seen_uuids: dict[str, str] = field(default_factory=dict)


def _uuid_placeholder(n: int) -> str:
    return f"00000000-0000-4000-8000-{n:012d}"


def _sanitize_str(value: str, key: str, c: Counters) -> str:
    kl = key.lower()
    if "serial" in kl:
        c.serial += 1
        return f"SN-EXAMPLE-{c.serial:04d}"
    if kl in {"mac", "macaddress"} or _MAC_COLON.match(value) or _MAC_BARE.match(value):
        c.mac += 1
        return f"AA:BB:CC:00:00:{c.mac:02d}" if ":" in value else f"AABBCC0000{c.mac:02d}"
    if _UUID.match(value):
        if value not in c.seen_uuids:
            c.uuid += 1
            c.seen_uuids[value] = _uuid_placeholder(c.uuid)
        return c.seen_uuids[value]
    if value.endswith(".id.ui.direct"):
        return ""
    if kl in IP_KEYS or _IPV4.match(value):
        c.ip += 1
        return f"192.0.2.{c.ip % 250 + 1}"
    if kl in NAME_KEYS:
        c.name += 1
        return f"Name-Example-{c.name}"
    return value


def sanitize(value: Any, key: str, c: Counters) -> Any:
    if isinstance(value, dict):
        return {k: sanitize(v, k, c) for k, v in value.items() if k.lower() not in DROP_KEYS}
    if isinstance(value, list):
        return [sanitize(v, key, c) for v in value]
    if isinstance(value, str):
        return _sanitize_str(value, key, c)
    return value


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__, file=sys.stderr)
        return 2
    raw = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
    clean = sanitize(raw, "", Counters())
    out = json.dumps(clean, indent=2)
    if len(argv) >= 3:
        Path(argv[2]).write_text(out + "\n", encoding="utf-8")
    else:
        print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
