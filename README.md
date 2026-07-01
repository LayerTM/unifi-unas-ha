# UniFi UNAS → Home Assistant (non-invasive)

> **Agentless, read-only monitoring for Ubiquiti UniFi UNAS in Home Assistant.**
> Talks to the UniFi OS console **only over HTTPS** — no SSH, no packages installed on the NAS, no on-device agent, **zero footprint**.

[![Secret scan](https://github.com/LayerTM/unifi-unas-ha/actions/workflows/secret-scan.yml/badge.svg)](https://github.com/LayerTM/unifi-unas-ha/actions/workflows/secret-scan.yml)
![Status: in development](https://img.shields.io/badge/status-in%20development-orange)
![License: MIT](https://img.shields.io/badge/license-MIT-blue)

---

## Why this exists

| | This project | `cardouken/homeassistant-unifi-unas` | `memphi2/ha-unifi-drive` |
|---|:--:|:--:|:--:|
| No SSH / no packages installed on NAS | ✅ | ❌ (root SSH + `apt`/`pip` + on-NAS agent) | ✅ |
| Read-only by default | ✅ (v1) | ❌ | partial |
| **API-key auth** (no password stored) | ✅ | ❌ | plumbed, unverified |
| **Verified** disk SMART / CPU / memory model | ✅ (from real capture) | via SSH | heuristic guessing |
| First-class reverse-engineered **API docs** | ✅ (`docs/API.md`) | ❌ | ❌ |

We read the same rich data as SSH-based tools — disk health, temperatures, RAID/pool status, capacity, CPU, memory, throughput — but **entirely through the console's local REST API**, leaving the NAS untouched.

## How it works

The UniFi UNAS runs UniFi OS. Its "Drive" application exposes a local REST API behind the console reverse proxy (`https://<host>/proxy/drive/api/...`). This integration authenticates locally — with either a **UniFi OS API key** or a **local account** — and polls that API. See [`docs/API.md`](docs/API.md) for the full, reverse-engineered reference.

**Two authentication methods (your choice):**
- **API key** *(recommended for read-only)* — created in the UniFi OS UI. Authorizes core NAS + disk-health + system telemetry, and **cannot** read user/share PII (a security feature).
- **Local account (username + password)** — adds shares, snapshots and backup visibility.

## Status & roadmap

This project is under active development.

- **v1 (in progress):** read-only monitoring — disks (SMART/temperature/health), pools/RAID, capacity, CPU, memory, throughput, versions, uptime. HACS-installable.
- **v2 (planned):** opt-in control (power, fan mode, snapshots, firmware) **and** a CLI + MCP server so tools/LLMs can query and act — behind a unified safety model.

## Security & privacy

- **Read-only** in v1; least-privilege (works with a restricted account or scoped API key).
- Credentials live only in the Home Assistant config entry; nothing is sent to third parties.
- The repository is guarded by an automated **secret/PII scanner** (`scripts/secret_scan.py`) in pre-commit and CI, and diagnostics are redacted.

## Installation

_HACS custom-repository instructions will be added with the first release (`v0.1.0`)._

## License

[MIT](LICENSE) © LayerTM
