# UniFi UNAS for Home Assistant (non-invasive)

> Agentless monitoring — and opt-in control — for the Ubiquiti UniFi UNAS in Home Assistant.
> Talks to the UniFi OS console over HTTPS only — no SSH, no packages installed on the NAS, no on-device agent.

[![tests](https://github.com/LayerTM/unifi-unas-ha/actions/workflows/tests.yml/badge.svg)](https://github.com/LayerTM/unifi-unas-ha/actions/workflows/tests.yml)
[![ha-integration](https://github.com/LayerTM/unifi-unas-ha/actions/workflows/ha-integration.yml/badge.svg)](https://github.com/LayerTM/unifi-unas-ha/actions/workflows/ha-integration.yml)
[![secret-scan](https://github.com/LayerTM/unifi-unas-ha/actions/workflows/secret-scan.yml/badge.svg)](https://github.com/LayerTM/unifi-unas-ha/actions/workflows/secret-scan.yml)
![Status: stable](https://img.shields.io/badge/status-stable-brightgreen)
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

Everything is grouped under one hub device (the UNAS), with a sub-device per disk, per pool and (with local-account auth) per share.

- **Storage** — used / total / free, usage %, RAID level, storage status, pool count.
- **System** — CPU usage %, CPU temperature, memory usage %, network throughput, link speed, last boot, UniFi OS and Drive app versions.
- **Health** — disks-at-risk count, average disk temperature, a `storage problem` binary sensor, and a connectivity (`online`) binary sensor.
- **Per disk** — temperature, read/write rate, power-on hours, health score, bad sectors, state, and a per-disk `problem` binary sensor.
- **Per pool** — RAID level, status, usage %, capacity, used space, data-scrubbing status.
- **Per share** *(local-account auth)* — usage, quota, member count, encryption, and snapshot / remote-backup binary sensors. A privacy-safe **account count** is also exposed (only the number of accounts — never the accounts themselves).
- **Updates** *(local-account auth)* — UniFi OS and Drive-app update entities (install requires opt-in controls with an owner account). An **Applications** sensor lists installed apps/integrations and their versions.
- **Activity** *(local-account auth)* — recent-event count (with a per-category breakdown), latest-event time, and recent-log-entry count. Only counts, categories and timestamps are read — notification and log **bodies are personal data and are never retained**.

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

## Removal

1. **Settings → Devices & Services → UniFi UNAS**, open the ⋮ menu on the integration entry and choose **Delete**. This removes the config entry and all its devices and entities; the stored credential is discarded.
2. Optional — to remove the integration itself, delete it in **HACS → UniFi UNAS (non-invasive) → Remove**, then restart Home Assistant.

Nothing is written to or left on the NAS, so no cleanup is needed on the device side.

## Security & privacy

- Read-only by default; control actions are opt-in and off by default, and need username/password auth (an owner account for power/firmware) — never an API key.
- User accounts are never exposed as entities (they are personal data).
- Credentials live only in the Home Assistant config entry; nothing is sent to third parties.
- A secret/PII scanner (`scripts/secret_scan.py`) runs in pre-commit and CI, and diagnostics are redacted.

## Control actions (opt-in)

Off by default. Enable **Configure → Enable control actions** to add buttons for **reboot, shut down, install UniFi OS update, install Drive-app update**, a **fan-mode selector**, per-share **scheduled-snapshots switches**, and the **Install** buttons on the update entities. Controls require **username/password** auth — an API key is read-only, and **power/firmware need an owner/admin account**; a refused action reports a clear permissions error.

> The scheduled-snapshots switch toggles each share's `snapshotEnabled` flag. The UNAS API exposes no snapshot list/create endpoint (only this flag), and the write path is inferred from the share resource and **not yet verified on live hardware** — treat it as experimental.

Quality: the integration self-reports against Home Assistant's Integration Quality Scale at the **silver** tier (see [`quality_scale.yaml`](custom_components/unifi_unas_rest/quality_scale.yaml)).

## Beyond Home Assistant: CLI & MCP

The same client also powers a command-line tool and an MCP server for scripts, agents and LLMs. Credentials come from the environment (`UNAS_HOST` + `UNAS_APIKEY`, or `UNAS_USER`/`UNAS_PASS`).

```bash
pip install "aiounas[cli]"        # CLI
unifi-unas status                 # storage, disks, system summary
unifi-unas status --json          # machine-readable output
unifi-unas fan                    # show the fan profile
unifi-unas fan quiet              # set it (write — asks for confirmation, or --yes)
unifi-unas reboot                 # write — asks for confirmation (or --yes)

pip install "aiounas[mcp]"        # MCP server for LLMs/agents
unifi-unas-mcp                    # read tools only; set UNAS_MCP_ALLOW_WRITES to expose gated writes
```

**Safety model:** reads are always open; writes require explicit confirmation — the CLI prompts (or `--yes`), and MCP write tools appear only with `UNAS_MCP_ALLOW_WRITES` set **and** each call must pass `confirm=true`.

## License

[MIT](LICENSE) © LayerTM
