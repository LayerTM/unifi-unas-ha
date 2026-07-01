"""Shared test helpers: sanitized-fixture loader."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

_FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict[str, Any]:
    """Load a sanitized JSON fixture by base name (no extension)."""
    return json.loads((_FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


@pytest.fixture
def fixture() -> Callable[[str], dict[str, Any]]:
    """Return the fixture loader as a pytest fixture."""
    return load_fixture
