# UniFi UNAS local REST API — reverse-engineered reference

> Unofficial, community-documented. Verified against a real **UNAS-2** running
> **UniFi OS 5.1.19 / UniFi Drive app 4.3.6**. All example values below are
> **sanitized** (synthetic serials, MACs, UUIDs). Ubiquiti does not publish or
> support this API; endpoints may change between firmware versions.

## Overview

The UNAS runs UniFi OS. Its storage application ("UniFi Drive", internal name
`drive`) exposes a local REST API behind the console's reverse proxy at
`https://<host>/proxy/drive/api/...`. A small number of device-wide endpoints
live under `https://<host>/api/...`.

- **Transport:** HTTPS on port **443** (self-signed certificate — clients must
  either skip verification or pin the console CA).
- **Read-only use:** everything documented here is retrieved with `GET`. This
  reference intentionally does not document state-changing calls.
- The application is served under `/proxy/drive/`; confirm it is present via
  `GET /api/system` → `apps.controllers[].name == "drive"`.

## Authentication

Two independent methods work. Both are validated live.

### 1. Local account (session)

```
1. GET  https://<host>/                     # priming request; read CSRF from
                                            #   response header X-CSRF-Token
2. POST https://<host>/api/auth/login
        Content-Type: application/json
        X-CSRF-Token: <token from step 1>
        {"username": "...", "password": "...", "rememberMe": true, "remember": true}
   → 200, Set-Cookie: TOKEN=<jwt>; ...
        response header X-Updated-CSRF-Token: <new token>
   → 401/403 on bad credentials
3. Subsequent requests:
        Cookie: TOKEN=<jwt>
        X-CSRF-Token: <latest token>
```

The `TOKEN` cookie should be captured from `Set-Cookie` and sent explicitly —
a shared client backed by an **IP** host will not persist it in a standard
cookie jar (aiohttp's default jar ignores cookies for IP hosts). On `401`,
repeat the login and retry once.

### 2. API key

Create a key in the UniFi OS UI (only name / description / expiry are
configurable — the key's scope is fixed by UniFi OS). Then send it on every
request; no login or CSRF is needed:

```
X-API-Key: <key>
```

### Auth capability matrix (verified)

An API key is **device-scoped and user-agnostic**: it authorizes device-global
telemetry but is denied anything needing a user context. A key created from the
**owner** account is still denied on shares/users — the limit is intrinsic to
the key, not the account role.

| Endpoint | API key | Session |
|---|:--:|:--:|
| `GET /proxy/drive/api/v2/storage` | ✅ 200 | ✅ 200 |
| `GET /proxy/drive/api/v2/systems/device-info` | ✅ 200 | ✅ 200 |
| `GET /proxy/drive/api/v2/systems/network-io` | ✅ 200 | ✅ 200 |
| `GET /proxy/drive/api/v2/systems/fan-control` | ✅ 200 | ✅ 200 |
| `GET /proxy/drive/api/v2/drives` (shares) | ❌ 500 | ✅ 200 |
| `GET /proxy/drive/api/v1/users` | ❌ 403 | ✅ 200 |
| `GET /proxy/drive/api/v1/systems/snapshot` | ❌ 403 | ✅ 200 |
| `GET /api/system` | ⚠️ short public payload only | ✅ full payload |

### Error contract

Non-2xx responses return JSON:

```json
{ "error": { "code": 401, "message": "Unauthorized" } }
```

## Endpoints

### `GET /api/system` (device identity)

Unauthenticated / API-key returns a short public payload; a session returns a
much larger one. The short payload is enough to identify the device (and derive
a stable unique id from the MAC):

```json
{
  "hardware": { "shortname": "UNAS2B" },
  "name": "My UNAS",
  "mac": "AABBCC000001",
  "deviceState": "setup",
  "cloudConnected": true,
  "isSsoEnabled": true
}
```

### `GET /proxy/drive/api/v2/storage`

The primary telemetry payload: pools (RAID), physical disks (with SMART-derived
fields), and cache slots. Per-disk health/temperature/power-on-hours **are**
available here over pure REST.

```json
{
  "pools": [
    {
      "number": 1,
      "id": "00000000-0000-4000-8000-000000000001",
      "preferLevel": "raid1",
      "type": "lvm",
      "status": "fullyOperational",
      "capacity": 23991544709120,
      "usage": 8894504435712,
      "raidGroups": [
        {
          "number": 1,
          "currentLevel": "raid1",
          "configLevel": "raid1",
          "currentProtection": 1,
          "expectedProtection": 1,
          "isSSDCache": false,
          "progress": 0
        }
      ],
      "initializingStatus": "successful",
      "dataScrubbing": { "status": "idle", "schedule": { "enabled": false } }
    }
  ],
  "disks": [
    {
      "slotId": "1",
      "poolId": "00000000-0000-4000-8000-000000000001",
      "raidGroupId": "00000000:00000000:00000000:00000001",
      "type": "HDD",
      "state": "optimal",
      "rpm": 7200,
      "model": "WDC WUH722424ALE6L4",
      "size": 24000277250048,
      "firmware": "LVGNWHA2",
      "sectorFormat": "512E",
      "serial": "SN-EXAMPLE-0001",
      "temperature": 47,
      "powerOnHours": 3357,
      "badSectorCount": 0,
      "uncorrectableSectorCount": 0,
      "readErrorRate": 0,
      "smartReadErrorCount": 0,
      "readKBPS": 0,
      "writeKBPS": 0,
      "smartTestSupported": true,
      "healthScore": 5
    }
  ],
  "cacheSlots": [],
  "expansions": null
}
```

**Field notes**

| Path | Type | Unit / meaning |
|---|---|---|
| `pools[].capacity`, `pools[].usage` | int | **bytes** (decimal) |
| `pools[].status` | str | observed: `fullyOperational` (degraded states not yet captured) |
| `pools[].raidGroups[0].currentLevel` | str | e.g. `raid1` |
| `pools[].raidGroups[0].currentProtection` | int | redundancy count |
| `pools[].dataScrubbing.status` | str | e.g. `idle` |
| `disks[].state` | str | `optimal` when healthy |
| `disks[].temperature` | int | °C |
| `disks[].powerOnHours` | int | hours |
| `disks[].size` | int | **bytes** (decimal) |
| `disks[].healthScore` | int | observed `5` = healthy |
| `disks[].badSectorCount`, `uncorrectableSectorCount`, `readErrorRate` | int | SMART counters |
| `disks[].smartTestSupported` | bool | |

### `GET /proxy/drive/api/v2/systems/device-info`

CPU load/temperature, memory, model, firmware, and NIC link — the cleanest
system-telemetry source (and far less PII than the full `/api/system`).

```json
{
  "name": "My UNAS",
  "model": "UNAS2B",
  "version": "4.3.6",
  "firmwareVersion": "5.1.19",
  "status": "STATE_RUNNING",
  "cpu": { "currentload": 0.098, "temperature": 66.3 },
  "memory": { "free": 446720, "total": 3970688, "available": 2406848 },
  "networkInterfaces": [
    { "interfaceName": "eth0", "connected": true, "maxSpeed": "2.5 GbE", "linkSpeed": "2.5 GbE" }
  ],
  "usbs": [{ "portId": "1", "connected": false }],
  "sfpAggregation": false
}
```

| Path | Unit / meaning |
|---|---|
| `cpu.currentload` | fraction 0..1 (× 100 for %) |
| `cpu.temperature` | °C |
| `memory.total`, `memory.free`, `memory.available` | **KiB** (from `/proc/meminfo`) |
| `firmwareVersion` | UniFi OS version |
| `version` | Drive app version |

### `GET /proxy/drive/api/v2/systems/network-io`

```json
{ "receiveKBPS": 3.62, "transmitKBPS": 15.30, "timestamp": "2026-07-01T10:26:32+02:00" }
```

### `GET /proxy/drive/api/v2/systems/fan-control`

```json
{ "availableProfiles": ["quiet", "balance", "cooling"], "currentProfile": "balance" }
```

Fan is exposed as a **profile only** — no RPM. (The exact `availableProfiles`
values are firmware-dependent; the endpoint is undocumented by Ubiquiti.)

### `GET /proxy/drive/api/v2/drives` (shared drives / SMB-NFS shares) — session only

```json
{
  "drives": [
    {
      "id": "00000000-0000-4000-8000-000000000011",
      "type": "shared",
      "name": "Share1",
      "status": "active",
      "storagePoolId": "00000000-0000-4000-8000-000000000001",
      "quota": -1,
      "usage": 2670956052480,
      "memberCount": 4,
      "protections": {
        "encryptionStatus": "unencrypted",
        "snapshotEnabled": true,
        "remoteBackupEnabled": false
      }
    }
  ]
}
```

`quota == -1` means unlimited. `usage` is in bytes. An API key receives `500`
here.

### `GET /proxy/drive/api/v1/systems/snapshot` (session only)

Returns per-share snapshot settings under `data.personal[]` and `data.shared[]`
(schedule, counts, last/next snapshot time). Documented at a high level here;
capture your own device for the full shape before relying on it.

## What is NOT available over this REST API

- **Fan RPM** — only the profile is exposed.
- **Per-process / detailed CPU breakdown** — only aggregate `cpu.currentload`.
- **Real SMART attribute tables** beyond the summarized counters in
  `/v2/storage` (bad/uncorrectable/read-error counts, health score).

## Channels that do NOT work (verified)

- **UniFi Site Manager cloud API** and the **local Network Integration API**
  expose no storage/NAS/SMART data.
- **SNMP** exposes only generic CPU/RAM/NIC counters (no SMART, temperatures,
  pools, or shares).
- SSH (22) and the internal Drive API port (16080) are not reachable off-box on
  a default UNAS.

---

_This document is maintained alongside the `aiounas` client; field names map
directly to `aiounas.models`. Contributions of captures from other UNAS models
and firmware versions are welcome._
