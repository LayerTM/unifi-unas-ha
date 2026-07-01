#!/usr/bin/env python3
"""Secret / PII scanner — blocks device data from leaking into the public repo.

Pattern-based (no real device values are hardcoded here), so it protects *any*
contributor's device, not just one. Runs in pre-commit and CI. Exit code 1 on
any finding. Placeholder/example values (e.g. ``<redacted>``, ``AA:BB:CC:...``,
``EXAMPLE``) are allowed so sanitized fixtures and docs pass.

Usage:
    python scripts/secret_scan.py [path]   # default: current directory
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# Snippets that mark a value as an intentional placeholder (allowed).
ALLOW = re.compile(
    r"(?i)(redacted|example|placeholder|synthetic|dummy|sample|<[a-z0-9_.\-]+>|"
    r"aa:bb:cc|aabbcc|00:11:22|de:ad:be|0{6,}|x{4,})"
)

# name -> compiled pattern. Each matches a *real-looking* secret/PII value.
PATTERNS: dict[str, re.Pattern[str]] = {
    "UniFi direct-connect domain": re.compile(r"\b[0-9a-f]{16,}\.[0-9a-z.]*id\.ui\.direct\b"),
    "JWT / bearer token": re.compile(
        r"\beyJ[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{4,}"
    ),
    "MAC address": re.compile(r"\b(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}\b"),
    "GPS coordinate field": re.compile(
        r'"(?:lat|long|latitude|longitude)"\s*:\s*-?\d{1,3}\.\d{3,}'
    ),
    "device serial field": re.compile(r'"serial(?:no|Number)?"\s*:\s*"[^"<\s][^"<]{2,}"'),
    "MAC field value": re.compile(r'"mac(?:Address)?"\s*:\s*"[^"<\s][^"<]{5,}"'),
    "directConnectDomain field": re.compile(r'"directConnectDomain"\s*:\s*"[^"<\s][^"<]+"'),
    "X-API-Key value": re.compile(r'(?i)x-api-key\s*[:=]\s*["\']?[A-Za-z0-9_\-]{16,}'),
    "TOKEN cookie value": re.compile(r"\bTOKEN=[A-Za-z0-9._\-]{16,}"),
    "hardcoded password": re.compile(r'(?i)\bpassword\b\s*[:=]\s*["\'][^"\'{}<\s]{4,}["\']'),
}

SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
    "captures",
    ".secrets",
}
SKIP_SUFFIX = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".ico",
    ".svg",
    ".pdf",
    ".zip",
    ".gz",
    ".mo",
    ".woff",
    ".woff2",
}
# The scanner defines the patterns as literals; don't scan itself for them.
SELF = Path(__file__).name


def iter_files(root: Path):
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        if p.suffix.lower() in SKIP_SUFFIX:
            continue
        if p.name == SELF:
            continue
        yield p


def scan_text(text: str) -> list[tuple[str, str]]:
    hits: list[tuple[str, str]] = []
    for name, rx in PATTERNS.items():
        for m in rx.finditer(text):
            snippet = m.group(0)
            if ALLOW.search(snippet):
                continue
            hits.append((name, snippet[:70]))
    return hits


def main(argv: list[str]) -> int:
    root = Path(argv[1]) if len(argv) > 1 else Path()
    problems: list[tuple[Path, str, str]] = []
    for f in iter_files(root):
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for name, snip in scan_text(text):
            problems.append((f, name, snip))

    if problems:
        print("SECRET-SCAN: potential PII/secret leakage detected:\n", file=sys.stderr)
        for f, name, snip in problems:
            print(f"  {f}: [{name}] {snip}", file=sys.stderr)
        print(
            "\nBlocked. Sanitize the value, add a placeholder, or move it to a "
            "gitignored path (captures/, .secrets/).",
            file=sys.stderr,
        )
        return 1

    print("secret-scan: clean")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
