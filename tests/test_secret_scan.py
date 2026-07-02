"""Guard the PII/secret scanner itself — it is the repo's sole PII backstop.

These tests encode the regressions found in the pre-merge review: bare-hex MACs
under any key must be caught, real MACs/serials must not be whitelisted by
placeholder markers, and canonical placeholders must still pass.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("secret_scan", _ROOT / "scripts" / "secret_scan.py")
assert _spec and _spec.loader
secret_scan = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(secret_scan)


def _flagged(text: str) -> bool:
    return bool(secret_scan.scan_text(text))


def test_flags_bare_hex_mac_under_any_key() -> None:
    assert _flagged('{"bssid":"F492BF1A2B3C"}')
    assert _flagged("device F492BF1A2B3C rebooted")


def test_flags_real_mac_with_zero_run() -> None:
    # regression: placeholder markers must not whitelist a real MAC ending in zeros
    assert _flagged('{"mac":"F492BF000000"}')


def test_flags_separated_and_dotted_macs() -> None:
    assert _flagged("F4:92:BF:12:34:56")
    assert _flagged("a1b2.c3d4.e5f6")


def test_flags_serial_with_x_run() -> None:
    assert _flagged('{"serial":"WXXXX9K1234567"}')


def test_flags_direct_connect_domain_case_insensitive() -> None:
    assert _flagged("MyConsole12345678.id.ui.direct")


def test_flags_generic_secrets_and_pii() -> None:
    # Adopted from the ClaudeInHA scanner: generic credentials + personal data.
    assert _flagged("sk-ant-api03-" + "A" * 24)  # Anthropic key
    assert _flagged("token=ghp_" + "b" * 36)  # GitHub classic PAT
    assert _flagged("github_pat_" + "c" * 40)  # GitHub fine-grained PAT
    assert _flagged("xoxb-123456789012-abcdef")  # Slack token
    assert _flagged("AKIAABCDEFGHIJKLMNOP")  # AWS access key id
    assert _flagged("-----BEGIN OPENSSH PRIVATE KEY-----")  # private key block
    assert _flagged("path /Users/someone/project")  # personal macOS path
    assert _flagged("contact me@gmail.com now")  # personal gmail
    assert _flagged("connect to 192.168.1.207")  # private LAN IP
    assert _flagged("host 10.0.0.42")  # private LAN IP


def test_allows_canonical_placeholders() -> None:
    assert not _flagged('"id":"00000000-0000-4000-8000-000000000001"')
    assert not _flagged('"id":"00000000:00000000:00000000:00000001"')
    assert not _flagged('"mac":"AABBCC000001"')
    assert not _flagged('"serial":"SN-EXAMPLE-0001"')
    assert not _flagged("<redacted:mac len=12>")
    assert not _flagged('"mac":"AA:BB:CC:00:00:01"')
    # documentation-range IP + placeholder tokens must pass
    assert not _flagged("UNAS_HOST=192.0.2.10")
    assert not _flagged("api_key: your-token-here")
    assert not _flagged("key: sk-ant-...")
