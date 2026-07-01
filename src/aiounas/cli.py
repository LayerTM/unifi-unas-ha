"""Command-line interface for aiounas.

Read commands are always available; write commands are safety-gated (they refuse
to run without ``--yes`` / an interactive confirmation). Credentials come from
the environment:

    UNAS_HOST=192.168.1.x  UNAS_APIKEY=...            # API key (read-only scope)
    UNAS_HOST=192.168.1.x  UNAS_USER=...  UNAS_PASS=...  # local account

Install with the ``cli`` extra: ``pip install aiounas[cli]``.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable, Callable

import aiohttp
import typer
from rich.console import Console
from rich.table import Table

from .actions import UnasActionClient
from .auth import AbstractAuth, ApiKeyAuth, SessionAuth
from .client import UnasClient
from .exceptions import UnasError

app = typer.Typer(
    help="Query and control a UniFi UNAS over its local REST API.",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()
err_console = Console(stderr=True)


def _auth() -> AbstractAuth:
    key = os.environ.get("UNAS_APIKEY")
    if key:
        return ApiKeyAuth(key)
    user, password = os.environ.get("UNAS_USER"), os.environ.get("UNAS_PASS")
    if not user or not password:
        err_console.print("[red]Set UNAS_APIKEY, or UNAS_USER and UNAS_PASS.[/]")
        raise typer.Exit(2)
    return SessionAuth(user, password)


def _host() -> str:
    host = os.environ.get("UNAS_HOST")
    if not host:
        err_console.print("[red]Set UNAS_HOST to the UNAS console IP/hostname.[/]")
        raise typer.Exit(2)
    return host


def _run[T](func: Callable[[UnasClient], Awaitable[T]]) -> T:
    async def runner() -> T:
        async with aiohttp.ClientSession() as session:
            return await func(UnasClient(session, _host(), _auth(), verify_ssl=False))

    try:
        return asyncio.run(runner())
    except UnasError as err:
        err_console.print(f"[red]{err}[/]")
        raise typer.Exit(1) from err


def _run_action(func: Callable[[UnasActionClient], Awaitable[None]]) -> None:
    async def runner() -> None:
        async with aiohttp.ClientSession() as session:
            await func(UnasActionClient(session, _host(), _auth(), verify_ssl=False))

    try:
        asyncio.run(runner())
    except UnasError as err:
        err_console.print(f"[red]{err}[/]")
        raise typer.Exit(1) from err


def _confirm(action: str, yes: bool) -> None:
    if yes:
        return
    if not typer.confirm(f"Really {action} the UNAS?"):
        raise typer.Abort


@app.command()
def status() -> None:
    """Show a summary of storage, disks and system telemetry."""

    async def _fetch(client: UnasClient) -> None:
        storage = await client.get_storage()
        info = await client.get_device_info()
        console.print(
            f"[bold]{info.name or 'UNAS'}[/] ({info.model})  UniFi OS {info.firmware_version} / "
            f"Drive {info.version}"
        )
        console.print(
            f"CPU {info.cpu_percent}% @ {info.cpu_temperature}C  |  memory {info.memory_percent}%  "
            f"|  storage {storage.usage_percent}% used"
        )
        table = Table("Slot", "State", "Temp", "Power-on", "Health", "Model")
        for disk in storage.disks:
            table.add_row(
                disk.slot,
                disk.state,
                f"{disk.temperature}C",
                f"{disk.power_on_hours}h",
                str(disk.health_score),
                disk.model,
            )
        console.print(table)

    _run(_fetch)


@app.command()
def reboot(yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation.")) -> None:
    """Reboot the console (write)."""
    _confirm("reboot", yes)
    _run_action(lambda client: client.reboot())
    console.print("reboot requested")


@app.command()
def shutdown(yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation.")) -> None:
    """Power the console off (write)."""
    _confirm("shut down", yes)
    _run_action(lambda client: client.shutdown())
    console.print("shutdown requested")


@app.command("update-firmware")
def update_firmware(
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
) -> None:
    """Install the available UniFi OS firmware update (write)."""
    _confirm("install a firmware update on", yes)
    _run_action(lambda client: client.update_firmware())
    console.print("firmware update requested")


if __name__ == "__main__":
    app()
