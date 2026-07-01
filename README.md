# UniFi UNAS for Home Assistant (non-invasive)

> Agentless, read-only monitoring for the Ubiquiti UniFi UNAS in Home Assistant.
> Talks to the UniFi OS console over HTTPS only — no SSH, no packages installed on the NAS, no on-device agent.

[![tests](https://github.com/LayerTM/unifi-unas-ha/actions/workflows/tests.yml/badge.svg)](https://github.com/LayerTM/unifi-unas-ha/actions/workflows/tests.yml)
[![ha-integration](https://github.com/LayerTM/unifi-unas-ha/actions/workflows/ha-integration.yml/badge.svg)](https://github.com/LayerTM/unifi-unas-ha/actions/workflows/ha-integration.yml)
[![secret-scan](https://github.com/LayerTM/unifi-unas-ha/actions/workflows/secret-scan.yml/badge.svg)](https://github.com/LayerTM/unifi-unas-ha/actions/workflows/secret-scan.yml)
![Status: alpha](https://img.shields.io/badge/status-alpha-yellow)
![License: MIT](https://img.shields.io/badge/license-MIT-blue)

---

## Why this integration

It reads disk health, temperatures, RAID/pool status, capacity, CPU, memory, and throughput — the same data SSH-based tools expose — but entirely through the console's local REST API, so the NAS is left untouched.

| | This project | `cardouken/homeassistant-unifi-unas` | `memphi2/ha-unifi-drive` |
|---|:--:|:--:|:--:|
| No SSH or packages on the NAS | ✅ | ❌ | ✅ |
| Read-only by default | ✅ | ❌ | partial |
| API-key auth (no password stored) | ✅ | ❌ | partial |
| Disk SMART / CPU / memory sensors | ✅ | via SSH | partial |

## How it works

The UniFi UNAS runs UniFi OS, whose Drive application exposes a local REST API behind the console reverse proxy (`https://<host>/proxy/drive/api/...`). The integration authenticates locally and polls that API. See [`docs/API.md`](docs/API.md) for the exact endpoints.

Two authentication methods are supported; pick one during setup:

- **API key** (recommended) — created in the UniFi OS UI. Authorizes core NAS, disk-health, and system telemetry, and cannot read user or share PII.
- **Local account** (username + password) — everything the API key can read, plus shares, snapshots, and backup visibility.

## Entities

Everything is grouped under one hub device (the UNAS), with a sub-device per disk.

- **Storage** — used / total / free, usage %, RAID level, storage status, pool count.
- **System** — CPU usage %, CPU temperature, memory usage %, network receive/transmit, UniFi OS and Drive app versions.
- **Health** — disks-at-risk count, average disk temperature, a `storage problem` binary sensor, and a connectivity (`online`) binary sensor.
- **Per disk** — temperature, power-on hours, health score, bad sectors, state, and a per-disk `problem` binary sensor.

With local-account auth, shares are also read and factored into health (they are not exposed as their own entities).

Requires **Home Assistant 2026.6+** (Python 3.14). Configuration is through the UI (host, port, TLS, and auth method); re-authentication is supported.

## Installation

Via HACS (custom repository):

1. HACS → ⋮ → **Custom repositories** → add `https://github.com/LayerTM/unifi-unas-ha` (category: **Integration**).
2. Install **UniFi UNAS (non-invasive)**, then restart Home Assistant.
3. **Settings → Devices & Services → Add Integration → UniFi UNAS**, then complete the flow:
   - **Host / Port** of the UNAS console, and whether to verify TLS (off by default — UniFi OS ships a self-signed certificate).
   - **Authentication** — an API key (recommended, read-only) or a local account.

Use a least-privilege credential — an API key or a dedicated limited local admin — rather than your owner account.

The `aiounas` client is bundled inside the integration and has no external dependencies (Home Assistant already ships `aiohttp` and `yarl`), so HACS installs everything. See [`docs/API.md`](docs/API.md) for the API reference.

## Security & privacy

- Read-only in v1; works with a restricted account or a scoped API key.
- Credentials live only in the Home Assistant config entry; nothing is sent to third parties.
- A secret/PII scanner (`scripts/secret_scan.py`) runs in pre-commit and CI, and diagnostics are redacted.

## Roadmap

**v2 (planned):** opt-in control (power, fan mode, snapshots, firmware) plus a CLI and MCP server, behind a unified safety model.

## License

[MIT](LICENSE) © LayerTM
