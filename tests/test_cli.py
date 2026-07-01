"""CLI tests — clients are mocked, so no network is touched."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

from typer.testing import CliRunner

from aiounas import DeviceInfo, Storage
from aiounas.cli import app

runner = CliRunner()
_FX = Path(__file__).parent / "fixtures"
ENV = {"UNAS_HOST": "192.0.2.10", "UNAS_APIKEY": "test-api-key-0123456789"}


def _load(name: str) -> dict:
    return json.loads((_FX / f"{name}.json").read_text(encoding="utf-8"))


def _read_client() -> AsyncMock:
    client = AsyncMock()
    client.get_storage = AsyncMock(return_value=Storage.from_api(_load("storage")))
    client.get_device_info = AsyncMock(return_value=DeviceInfo.from_api(_load("device_info")))
    return client


def test_status_prints_summary() -> None:
    with patch("aiounas.cli.UnasClient", return_value=_read_client()):
        result = runner.invoke(app, ["status"], env=ENV)
    assert result.exit_code == 0, result.output
    assert "UNAS2B" in result.output
    assert "5.1.19" in result.output


def test_reboot_with_yes_calls_action() -> None:
    action = AsyncMock()
    with patch("aiounas.cli.UnasActionClient", return_value=action):
        result = runner.invoke(app, ["reboot", "--yes"], env=ENV)
    assert result.exit_code == 0, result.output
    action.reboot.assert_awaited_once()


def test_reboot_aborts_without_confirmation() -> None:
    action = AsyncMock()
    with patch("aiounas.cli.UnasActionClient", return_value=action):
        result = runner.invoke(app, ["reboot"], input="n\n", env=ENV)
    assert result.exit_code != 0  # aborted, no write
    action.reboot.assert_not_awaited()


def test_missing_host_exits() -> None:
    result = runner.invoke(app, ["status"], env={"UNAS_APIKEY": "k"})
    assert result.exit_code == 2
