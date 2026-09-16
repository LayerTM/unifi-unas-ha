"""Guard the PII/secret scanner itself — it is the repo's sole PII backstop.

These tests encode the regressions found in the pre-merge review: bare-hex MACs
under any key must be caught, real MACs/serials must not be whitelisted by
placeholder markers, and canonical placeholders must still pass.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("secret_scan", _ROOT / "scripts" / "secret_scan.py")
assert _spec and _spec.loader
secret_scan = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(secret_scan)


def _flagged(text: str) -> bool:
    return bool(secret_scan.scan_text(text))


# Every line this scanner must flag, in one list: the tests below iterate it, and
# `test_hygiene_scan.py` reads it to prove that the hygiene scanner reports none
# of them. A line belongs to exactly one of the two checks.
SHOULD_FLAG: list[str] = [
    # bare-hex MAC under any key, and in prose
    '{"bssid":"F492BF1A2B3C"}',
    "device F492BF1A2B3C rebooted",
    # regression: placeholder markers must not whitelist a real MAC ending in zeros
    '{"mac":"F492BF000000"}',
    "F4:92:BF:12:34:56",
    "a1b2.c3d4.e5f6",
    '{"serial":"WXXXX9K1234567"}',
    "MyConsole12345678.id.ui.direct",  # direct-connect domain, case-insensitive
    # generic credentials and personal data
    "sk-ant-api03-" + "A" * 24,  # Anthropic key
    "token=ghp_" + "b" * 36,  # GitHub classic PAT
    "github_pat_" + "c" * 40,  # GitHub fine-grained PAT
    "xoxb-123456789012-abcdef",  # Slack token
    "AKIAABCDEFGHIJKLMNOP",  # AWS access key id
    "-----BEGIN OPENSSH PRIVATE KEY-----",  # private key block
    "contact me@gmail.com now",  # personal gmail
    "connect to 192.168.1.207",  # private LAN IP
    "host 10.0.0.42",  # private LAN IP
]


@pytest.mark.parametrize("line", SHOULD_FLAG)
def test_flags_secrets_and_pii(line: str) -> None:
    assert _flagged(line)


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
