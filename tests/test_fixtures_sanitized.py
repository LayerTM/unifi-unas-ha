"""Fixtures load and contain no PII (the secret scanner must pass on them)."""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

FIXTURE_NAMES = ["storage", "device_info", "network_io", "system_short", "drives"]


@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_fixture_loads(fixture: Callable[[str], dict[str, Any]], name: str) -> None:
    assert isinstance(fixture(name), dict)


def test_secret_scan_clean_on_fixtures() -> None:
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "scripts/secret_scan.py", "tests/fixtures"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
