# UniFi UNAS local REST API reference

Unofficial, community-documented reference for the local REST API on a Ubiquiti
UniFi UNAS running UniFi OS with the UniFi Drive app. Ubiquiti does not publish
or support this API; paths and payloads may change between firmware versions.
Example values are sanitized (synthetic serials, MACs, UUIDs); replace `<host>`
with your console address.

## Overview

The UNAS runs UniFi OS. The Drive storage app (internal name `drive`) is exposed
behind the console reverse proxy at `https://<host>/proxy/drive/api/...`; a few
device-wide endpoints live under `https://<host>/api/...`.

| Property | Value |
|---|---|
| Transport | HTTPS, port `443` |
| TLS | Self-signed console certificate — skip verification or pin the console CA |
| Methods used | `GET` only (this reference covers read access) |

## Authentication

Two independent methods work: a **local-account session** (CSRF token + `TOKEN`
cookie) and a **device API key** (`X-API-Key`). Use an API key for read-only
telemetry; use a session only if you need shares. Their differing scope is in the
[capability matrix](#auth-scope-capability-matrix).

### Session (local account)

```
1. GET  https://<host>/
        → read CSRF from response header  X-CSRF-Token

2. POST https://<host>/api/auth/login
        Content-Type: application/json
        X-CSRF-Token: <token from step 1>
        {"username": "...", "password": "...", "rememberMe": true, "remember": true}

        → 200      Set-Cookie: TOKEN=<jwt>; ...
                   response header  X-Updated-CSRF-Token: <new token>
        → 401/403  invalid credentials

3. Every subsequent request:
        Cookie: TOKEN=<jwt>
        X-CSRF-Token: <latest token>
```

Capture `TOKEN` from `Set-Cookie` and send it explicitly: aiohttp's default
cookie jar drops cookies for IP hosts, so it will not persist automatically. On a
`401`, re-run the login once and retry the request.

### API key

Create a key in the UniFi OS UI (name / description / expiry only — scope is
fixed by UniFi OS), then send it on every request. No login or CSRF handshake:

```
X-API-Key: <key>
```

### Auth-scope capability matrix

An API key is **device-scoped and user-agnostic**: it authorizes device-global
telemetry but is denied anything requiring a user context, even when created from
the owner account. The rows below are the scope differences encoded in the test
suite.

| Request | API key | Session |
|---|:--:|:--:|
| `GET /api/system` | short public payload | full payload |
| `GET /proxy/drive/api/v2/storage` | 200 | 200 |
| `GET /proxy/drive/api/v2/systems/device-info` | 200 | 200 |
| `GET /proxy/drive/api/v2/systems/network-io` | 200 | 200 |
| `GET /proxy/drive/api/v2/drives` (shares) | 500 | 200 |
| `GET /proxy/drive/api/v1/users` | 403 | 200 |

`/v1/users` is not consumed by this client; it is listed only as the proof that
an API key is user-agnostic (a key from the owner account is still denied there).

### Error contract

Non-2xx responses return JSON:

```json
{ "error": { "code": 401, "message": "Unauthorized" } }
```

## Endpoints

The client reads these five endpoints:

| Method | Path | Returns |
|---|---|---|
| GET | `/api/system` | Device identity (short payload for key, full for session) |
| GET | `/proxy/drive/api/v2/storage` | Pools, disks (SMART-derived fields), cache slots |
| GET | `/proxy/drive/api/v2/systems/device-info` | CPU, memory, model, firmware, NIC link |
| GET | `/proxy/drive/api/v2/systems/network-io` | Instantaneous throughput |
| GET | `/proxy/drive/api/v2/drives` | Shared drives — **session only** |

`GET /proxy/drive/api/v2/systems/fan-control` returns the active fan **profile**
(no RPM): `{"availableProfiles": ["cooling", "default", "quiet"], "currentProfile": "<name>"}`.
Set it with `PUT` and the body `{"profile": "<name>"}` — the write field is
`profile`, **not** the `currentProfile` seen in the GET response (verified against
hardware). Reading accepts an API key; **writing requires session auth** (an API
key returns `500`).

### `GET /api/system`

The short payload (returned to an API key or unauthenticated request) identifies
the device; a MAC-derived value is used as its stable unique id.

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

The **full** payload (session auth) additionally carries firmware and app data
used for update detection:

- `hardware.firmwareVersion` — the **installed** UniFi OS version (e.g. `5.1.19`).
  Note the top-level `firmwareVersion` is empty on real hardware; use this field.
- `firmware.latest.version` — the **latest** UniFi OS version, often formatted
  with a leading `v` and a `+build` suffix (e.g. `v5.1.19+3fbc1da`). Normalize
  both sides (strip `v` and `+build`) before comparing, or an up-to-date device
  reads as having an update.
- `apps.controllers[]` — installed apps; the entry with `name == "drive"` gives
  the Drive app `version` and its `updateAvailable` (a version string, or null).
- `uptime` — seconds since boot.

### `GET /proxy/drive/api/v2/storage`

Pools (RAID), physical disks with SMART-derived fields, and cache slots. Per-disk
temperature, power-on-hours and health are available here.

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
      "type": "HDD",
      "state": "optimal",
      "rpm": 7200,
      "model": "WDC WUH722424ALE6L4",
      "size": 24000277250048,
      "firmware": "LVGNWHA2",
      "serial": "SN-EXAMPLE-0001",
      "temperature": 47,
      "powerOnHours": 3357,
      "badSectorCount": 0,
      "uncorrectableSectorCount": 0,
      "readErrorRate": 0,
      "smartTestSupported": true,
      "healthScore": 5
    }
  ],
  "cacheSlots": [],
  "expansions": null
}
```

| Path | Type | Meaning |
|---|---|---|
| `pools[].capacity`, `pools[].usage` | int | bytes (decimal) |
| `pools[].status` | str | `fullyOperational` when healthy |
| `pools[].raidGroups[0].currentLevel` | str | active RAID level, e.g. `raid1` |
| `pools[].raidGroups[0].currentProtection` | int | redundancy count |
| `pools[].dataScrubbing.status` | str | e.g. `idle` |
| `disks[].slotId` | str | drive bay id |
| `disks[].state` | str | `optimal` when healthy |
| `disks[].temperature` | int | °C |
| `disks[].powerOnHours` | int | hours |
| `disks[].size` | int | bytes (decimal) |
| `disks[].healthScore` | int | `5` = healthy |
| `disks[].badSectorCount`, `uncorrectableSectorCount`, `readErrorRate` | int | SMART counters |

### `GET /proxy/drive/api/v2/systems/device-info`

CPU load/temperature, memory, model, firmware and NIC link.

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

| Path | Meaning |
|---|---|
| `cpu.currentload` | CPU load as a fraction 0..1 (× 100 for %) |
| `cpu.temperature` | °C |
| `memory.total`, `memory.free`, `memory.available` | KiB |
| `firmwareVersion` | UniFi OS version |
| `version` | Drive app version |

Memory-used percentage is derived from `total − available`.

### `GET /proxy/drive/api/v2/systems/network-io`

Instantaneous throughput in KB/s.

```json
{ "receiveKBPS": 3.62, "transmitKBPS": 15.30, "timestamp": "2026-07-01T10:26:32+02:00" }
```

### `GET /proxy/drive/api/v2/drives` — session only

Shared SMB/NFS drives. An API key is denied here (`500`); use session auth.

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

| Path | Meaning |
|---|---|
| `drives[].quota` | quota in bytes; `-1` = unlimited |
| `drives[].usage` | bytes |
| `drives[].memberCount` | share members |
| `drives[].protections.snapshotEnabled` | bool |
| `drives[].protections.encryptionStatus` | e.g. `unencrypted` |

## Not available over this REST API

- **Fan RPM** — only the profile is exposed (`fan-control`).
- **Per-process CPU breakdown** — only aggregate `cpu.currentload`.
- **Full SMART attribute tables** — only the summarized counters and health score
  in `/v2/storage`.
- **Storage/NAS/SMART data via other channels** — the UniFi Site Manager cloud
  API and the local Network Integration API expose none of it; SNMP exposes only
  generic CPU/RAM/NIC counters. SSH (22) and the internal Drive port (16080) are
  not reachable off-box on a default UNAS.

Field names map directly to `aiounas.models`.
