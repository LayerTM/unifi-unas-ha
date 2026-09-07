<h1 align="center">UniFi UNAS for Home Assistant (non-invasive)</h1>

<p align="center">
  <em>Agentless monitoring — and opt-in control — for the Ubiquiti UniFi UNAS in Home Assistant.<br>
  Talks to the UniFi OS console over HTTPS only — no SSH, no packages installed on the NAS, no on-device agent.</em>
</p>

<div align="center">

[![release](https://img.shields.io/github/v/release/LayerTM/unifi-unas-ha?sort=semver&color=41BDF5)](https://github.com/LayerTM/unifi-unas-ha/releases)
[![HACS Default](https://img.shields.io/badge/HACS-Default-41BDF5.svg)](https://github.com/hacs/default)
[![quality scale: platinum (self-reported)](https://img.shields.io/badge/quality%20scale-platinum%20(self--reported)-8A2BE2)](custom_components/unifi_unas_rest/quality_scale.yaml)
[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2025.3%2B-41BDF5?logo=home-assistant&logoColor=white)](https://www.home-assistant.io/)
![License: MIT](https://img.shields.io/badge/license-MIT-blue)

[![tests](https://github.com/LayerTM/unifi-unas-ha/actions/workflows/tests.yml/badge.svg)](https://github.com/LayerTM/unifi-unas-ha/actions/workflows/tests.yml)
[![ha-integration](https://github.com/LayerTM/unifi-unas-ha/actions/workflows/ha-integration.yml/badge.svg)](https://github.com/LayerTM/unifi-unas-ha/actions/workflows/ha-integration.yml)
[![hassfest](https://github.com/LayerTM/unifi-unas-ha/actions/workflows/hassfest.yml/badge.svg)](https://github.com/LayerTM/unifi-unas-ha/actions/workflows/hassfest.yml)
[![hacs](https://github.com/LayerTM/unifi-unas-ha/actions/workflows/hacs.yml/badge.svg)](https://github.com/LayerTM/unifi-unas-ha/actions/workflows/hacs.yml)
[![lint](https://github.com/LayerTM/unifi-unas-ha/actions/workflows/lint.yml/badge.svg)](https://github.com/LayerTM/unifi-unas-ha/actions/workflows/lint.yml)
[![secret-scan](https://github.com/LayerTM/unifi-unas-ha/actions/workflows/secret-scan.yml/badge.svg)](https://github.com/LayerTM/unifi-unas-ha/actions/workflows/secret-scan.yml)

</div>

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

Requires **Home Assistant 2025.3+** — the release that introduced
`AddConfigEntryEntitiesCallback`, the newest core API this integration uses.
Development and CI run against the current release. Configuration is through the UI (host, port, TLS, and auth method); re-authentication is supported.

## Installation

This integration is in the HACS default list, so no custom repository is needed:

1. **HACS → Integrations**, search for **UniFi UNAS (non-invasive)** and download it.
2. Restart Home Assistant.
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

Off by default. Enable **Configure → Enable control actions** to add buttons for **reboot, shut down, install UniFi OS update, install Drive-app update**, a **fan-mode selector**, and the **Install** buttons on the update entities. Controls require **username/password** auth — an API key is read-only, and **power/firmware need an owner/admin account**; a refused action reports a clear permissions error.

> Snapshot control is intentionally **not** offered: the UNAS API exposes no writable snapshot endpoint (a live test showed the only candidate write is silently ignored). The read-only *Snapshots* binary sensor reflects each share's scheduled-snapshot flag.

Quality: the integration self-reports against Home Assistant's Integration Quality Scale at the **platinum** tier (see [`quality_scale.yaml`](custom_components/unifi_unas_rest/quality_scale.yaml)) — fully async, injects Home Assistant's shared HTTP session, and enforces `mypy --strict` in CI.

## Supported devices

Any Ubiquiti console running **UniFi OS with the UniFi Drive application** and reachable on your LAN. Verified against a UniFi UNAS console (model `UNAS2B`) on **UniFi OS 5.1.19 / Drive 4.3.6**; other UniFi OS consoles that host the Drive app (including the UNAS Pro) are expected to work but have not been verified. Devices are identified by their MAC, so a single Home Assistant can monitor several consoles.

Not supported: cloud-only access (UniFi Site Manager), and consoles without the Drive app (there is no storage API to read).

## Supported functions

- **Monitoring** (either auth method): storage capacity/usage, pool & RAID status, per-disk SMART health (temperature, power-on hours, health score, bad sectors, read/write rate), CPU/memory, network throughput, UniFi OS & Drive versions, update availability, last boot, and link speed. See [Entities](#entities) for the full list.
- **With a local account**: per-share usage/quota/members/encryption and snapshot/remote-backup status, a privacy-safe account count, and privacy-safe activity aggregates (recent events, last event, log-entry count).
- **Opt-in control** (local account): reboot, shut down, install updates, and fan-mode selection.

## Use cases

- **Health alerting** — automate on the `storage problem` / per-disk `problem` binary sensors, `disks at risk`, or a disk temperature threshold to get notified before data loss.
- **Capacity planning** — track storage usage % and per-share usage over time in the HA history/statistics.
- **Presence-aware power** — shut the NAS down when everyone leaves and no backups are running, then reboot on a schedule.
- **Dashboards** — surface RAID status, temperatures, and throughput on a storage dashboard.

## Data updates

The integration **polls** the console's local REST API (`local_polling`) on a fixed interval — **30 seconds** by default, adjustable per entry under **Configure**. Every entity is served from a single shared coordinator fetch, so the poll cost does not grow with the number of entities. Supplementary reads (shares, users, updates, activity) degrade to *unknown* on a transient permission/API error without taking the core sensors unavailable.

**Only a rejected credential asks you to re-authenticate.** A console that is booting, updating or restarting answers differently — a page of HTML where JSON belongs, or a redirect to its web UI — and that is treated as *unavailable*, so the poll simply retries and recovers on its own. A local-account session still gets one silent re-login first, since such a response can also be a genuine login page. Re-authentication is requested only for a 401 that survives that re-login.

## Known limitations

- **API-key auth is device-scoped**: an API key cannot read shares, the account count, or activity aggregates (those need a local account). It also cannot perform control actions.
- **Snapshots are read-only**: the API exposes only a per-share scheduled-snapshot **flag** (shown as the *Snapshots* binary sensor). There is no snapshot list/create/delete endpoint, and the only candidate write is silently ignored by the device (confirmed by a live test), so no snapshot control is offered.
- **Power/firmware actions require an owner/admin account.** The firmware-install endpoint, auth gating, and its "nothing to update" refusal are verified against live hardware; the actual install-and-reboot path only runs when an update is genuinely available.
- **No cloud**: only local access is supported; the UniFi Site Manager cloud API exposes none of this data.
- **High-churn sensors** (network and per-disk throughput) are **disabled by default** — enable them per entity if you want them.

## Troubleshooting

- **"Failed to connect"** — check the host/port and that the console is reachable over HTTPS on your LAN. TLS verification is off by default because UniFi OS ships a self-signed certificate; leave it off unless you pin a CA.
- **Shares / account count / activity sensors missing** — you are using API-key auth; reconfigure with a local account (**Configure → Reconfigure**) to expose them.
- **It keeps asking to re-authenticate, but the credential still works** — fixed in **v1.7.3**. Earlier versions read a console that was busy restarting (typically during a firmware update) as an expired session, and Home Assistant treats that as final: polling stops until you click through re-authentication. Update, then reload the entry — reloading also clears the stale *"Authentication expired"* repair.
- **Controls don't appear after enabling them** — controls require **username/password** auth; with an API key the option is rejected. Power and firmware actions additionally need an **owner/admin** account.
- **A control returns an error** — the message states the cause (insufficient permissions, auth failed, or the device rejected it). Owner rights are required for reboot/shutdown/firmware.
- **A removed disk/share lingers as a device** — it goes *unavailable*; delete it from the device page (the integration allows removing sub-devices that no longer exist).
- **Diagnostics** — download redacted diagnostics from the device page (serials and credentials are masked) when reporting an issue.

## Examples

Notify when storage has a problem:

```yaml
automation:
  - alias: UNAS storage problem
    triggers:
      - trigger: state
        entity_id: binary_sensor.unas_storage_problem
        to: "on"
    actions:
      - action: notify.mobile_app_phone
        data:
          title: UNAS storage problem
          message: "Check the NAS — a pool is degraded or a disk is at risk."
```

Warn on a hot disk:

```yaml
automation:
  - alias: UNAS disk too hot
    triggers:
      - trigger: numeric_state
        entity_id: sensor.unas_disk_1_temperature
        above: 60
    actions:
      - action: notify.mobile_app_phone
        data:
          message: "UNAS disk 1 is above 60 °C."
```

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
