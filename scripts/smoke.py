#!/usr/bin/env python3
"""Live read-only smoke test against a real UNAS console.

Credentials come from the environment and are never written anywhere. Serials,
MAC, and share names are masked in the output. This is a manual tool, not CI.

    UNAS_HOST=192.0.2.10 UNAS_APIKEY=... python scripts/smoke.py
    UNAS_HOST=192.0.2.10 UNAS_USER=... UNAS_PASS=... python scripts/smoke.py
"""

from __future__ import annotations

import asyncio
import os
import sys

import aiohttp

from aiounas import ApiKeyAuth, SessionAuth, UnasClient, ssl_from_env
from aiounas.auth import AbstractAuth
from aiounas.capabilities import probe


def _mask(value: str) -> str:
    return "****" if len(value) <= 4 else f"{value[:2]}…{value[-2:]}"


async def _run() -> int:
    host = os.environ.get("UNAS_HOST")
    if not host:
        print("set UNAS_HOST (and UNAS_APIKEY or UNAS_USER/UNAS_PASS)", file=sys.stderr)
        return 2

    api_key = os.environ.get("UNAS_APIKEY")
    auth: AbstractAuth
    if api_key:
        auth, method = ApiKeyAuth(api_key), "api-key"
    else:
        auth = SessionAuth(os.environ.get("UNAS_USER", ""), os.environ.get("UNAS_PASS", ""))
        method = "session"

    async with aiohttp.ClientSession() as session:
        client = UnasClient(session, host, auth, ssl=ssl_from_env())
        ident = await client.get_identity()
        info = await client.get_device_info()
        storage = await client.get_storage()
        net = await client.get_network_io()
        caps = await probe(client)

        print(f"auth method    : {method}")
        print(f"device         : {ident.name} [{ident.model_shortname}] mac={_mask(ident.mac)}")
        print(f"firmware/drive : {info.firmware_version} / {info.version}")
        print(
            f"cpu/mem        : {info.cpu_percent}% @ {info.cpu_temperature}C | "
            f"mem {info.memory_percent}%"
        )
        print(f"throughput     : rx {net.rx_kbps:.1f} / tx {net.tx_kbps:.1f} KB/s")
        print(
            f"storage        : {len(storage.pools)} pool(s), {storage.usage_percent}% used, "
            f"{storage.total_available / 1e12:.2f} TB free"
        )
        for pool in storage.pools:
            print(f"  pool {pool.number}: {pool.status} {pool.raid_level} {pool.usage_percent}%")
        print(
            f"disks          : {len(storage.disks)}, avg {storage.average_disk_temperature}C, "
            f"at-risk {storage.at_risk_disk_count}"
        )
        for disk in storage.disks:
            print(
                f"  slot {disk.slot:<2} {disk.state:<9} {disk.temperature}C {disk.power_on_hours}h "
                f"health={disk.health_score} {disk.model} sn={_mask(disk.serial)}"
            )
        print(
            f"capabilities   : storage={caps.storage} device_info={caps.device_info} "
            f"network_io={caps.network_io} shares={caps.shares}"
        )
        print(
            f"  scoped       : updates={caps.updates} users={caps.users} "
            f"notifications={caps.notifications} logs={caps.logs}"
        )
        if caps.shares:
            shares = await client.get_shares()
            print(f"shares         : {len(shares)}")
            for share in shares:
                quota = "unlimited" if share.quota_bytes is None else str(share.quota_bytes)
                print(
                    f"  {_mask(share.name):<16} {share.usage / 1e9:.1f} GB quota={quota} "
                    f"snapshot={share.snapshot_enabled}"
                )
        if caps.updates:
            upd = await client.get_update_info()
            apps = ", ".join(f"{a.name} {a.version}" for a in upd.applications)
            print(f"applications   : {len(upd.applications)} [{apps}]")
        if caps.users:
            print(f"accounts       : {await client.get_user_count()}")
        # Aggregates only — notification/log bodies are PII and never fetched here.
        if caps.notifications:
            ns = await client.get_notification_summary()
            cats = ", ".join(f"{name}:{count}" for name, count in ns.by_category)
            print(f"notifications  : {ns.total} [{cats}] latest={ns.latest}")
        if caps.logs:
            ls = await client.get_log_summary()
            print(f"log entries    : {ls.total} latest={ls.latest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_run()))
