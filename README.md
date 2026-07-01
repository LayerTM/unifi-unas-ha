# UniFi UNAS → Home Assistant (non-invasive)

> **Agentless, read-only monitoring for Ubiquiti UniFi UNAS in Home Assistant.**
> Talks to the UniFi OS console **only over HTTPS** — no SSH, no packages installed on the NAS, no on-device agent, **zero footprint**.

[![tests](https://github.com/LayerTM/unifi-unas-ha/actions/workflows/tests.yml/badge.svg)](https://github.com/LayerTM/unifi-unas-ha/actions/workflows/tests.yml)
[![ha-integration](https://github.com/LayerTM/unifi-unas-ha/actions/workflows/ha-integration.yml/badge.svg)](https://github.com/LayerTM/unifi-unas-ha/actions/workflows/ha-integration.yml)
[![secret-scan](https://github.com/LayerTM/unifi-unas-ha/actions/workflows/secret-scan.yml/badge.svg)](https://github.com/LayerTM/unifi-unas-ha/actions/workflows/secret-scan.yml)
![Status: alpha](https://img.shields.io/badge/status-alpha-yellow)
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

## Entities

Grouped as one **hub device** (the UNAS) with a **sub-device per disk**:

- **Storage:** used / total / free, usage %, RAID level, storage status, pool count.
- **System:** CPU usage %, CPU temperature, memory usage %, network receive/transmit, UniFi OS & Drive app versions.
- **Health:** disks-at-risk count, average disk temperature; a `storage problem` binary sensor and a connectivity (`online`) binary sensor.
- **Per disk:** temperature, power-on hours, health score, bad sectors, state, and a per-disk `problem` binary sensor.
- **Shares** *(local-account auth only)* are visible to the coordinator and used for health.

Requires **Home Assistant 2026.6+** (Python 3.14). Config is via the UI (host, port, TLS, and your chosen auth method); re-authentication is supported.

## Status & roadmap

- **v1 (current):** read-only monitoring — implemented and tested against real hardware.
- **v2 (planned):** opt-in control (power, fan mode, snapshots, firmware) **and** a CLI + MCP server so tools/LLMs can query and act — behind a unified safety model.

## Security & privacy

- **Read-only** in v1; least-privilege (works with a restricted account or scoped API key).
- Credentials live only in the Home Assistant config entry; nothing is sent to third parties.
- The repository is guarded by an automated **secret/PII scanner** (`scripts/secret_scan.py`) in pre-commit and CI, and diagnostics are redacted.

## Installation

**Via HACS (custom repository):**

1. HACS → ⋮ → *Custom repositories* → add `https://github.com/LayerTM/unifi-unas-ha` (category: *Integration*).
2. Install **UniFi UNAS (non-invasive)**, then restart Home Assistant.
3. *Settings → Devices & Services → Add Integration → UniFi UNAS* and follow the flow:
   - **Host / Port** of the UNAS console, and whether to verify TLS (off by default — UniFi OS uses a self-signed cert).
   - **Authentication:** an **API key** (create one in the UniFi OS UI — recommended, read-only) or a **local account**.

**Creating a least-privilege credential** is recommended — an API key, or a dedicated limited local admin — rather than your owner account.

> The `aiounas` client is **bundled inside the integration** — there are no external dependencies (Home Assistant already ships `aiohttp`/`yarl`), so HACS installs everything. `src/aiounas/` is the development source of the client; `scripts/vendor_aiounas.py` syncs the bundled copy and CI fails if they drift. See [`docs/API.md`](docs/API.md) for the API and [`docs/design/`](docs/design) / [`docs/plans/`](docs/plans) for the design.

## Beyond Home Assistant: CLI & MCP (v2, in progress)

The same client also powers a command-line tool and an MCP server for scripts, agents and LLMs. Credentials come from the environment (`UNAS_HOST` + `UNAS_APIKEY`, or `UNAS_USER`/`UNAS_PASS`).

```bash
pip install "aiounas[cli]"        # CLI
unifi-unas status                 # storage, disks, system summary
unifi-unas reboot                 # write — asks for confirmation (or --yes)

pip install "aiounas[mcp]"        # MCP server for LLMs/agents
unifi-unas-mcp                    # read tools only; set UNAS_MCP_ALLOW_WRITES to expose gated writes
```

**Safety model:** reads are always open; writes require explicit confirmation — the CLI prompts (or `--yes`), and MCP write tools appear only with `UNAS_MCP_ALLOW_WRITES` set **and** each call must pass `confirm=true`.

## License

[MIT](LICENSE) © LayerTM
