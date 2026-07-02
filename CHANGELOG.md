# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [1.7.0] — 2026-07-02

Live write-verification against real hardware.

### Removed

- **Scheduled-snapshots switch** (added in 1.3.0). A live test showed the only
  candidate write — `PATCH /drives/{id}` with `protections.snapshotEnabled` —
  returns `2xx` but is **silently ignored** by the device (the value never
  changes, confirmed with a delayed read on a fresh session). Rather than ship a
  control that does nothing, it is removed; the read-only *Snapshots* binary
  sensor remains. `aiounas.UnasActionClient.set_share_snapshots()` is removed too.

### Verified

- **Firmware install** is confirmed against live hardware: the endpoint is
  reachable, owner-account auth is accepted, and it safely refuses with `409` when
  no update is available (no install/reboot is triggered).

## [1.6.0] — 2026-07-02

Quality scale raised to **platinum** — the top tier.

### Changed

- `quality_scale`: **gold → platinum**. All platinum rules are met: the client is
  fully async (`async-dependency`), the integration injects Home Assistant's shared
  aiohttp session (`inject-websession`), and CI enforces `mypy --strict` on both the
  library and the integration (`strict-typing`). No code behaviour change.

## [1.5.0] — 2026-07-02

Quality scale raised to **gold**.

### Added

- **Reconfigure flow**: change host, port, TLS or credentials for an existing
  entry without deleting it (the device MAC must still match).
- **Dynamic devices**: disks, pools and shares that appear at runtime get their
  entities without a reload; sub-devices that vanish can be deleted from the
  device page (`async_remove_config_entry_device`).
- **Documentation**: supported devices, supported functions, use cases, data-update
  behaviour, known limitations, troubleshooting, and automation examples.

### Changed

- **Translated error messages** for every control action (shared `errors.py`
  helper + an `exceptions` block in the translations).
- High-churn sensors (network and per-disk throughput) are now **disabled by
  default**; enable them per entity if wanted.
- `quality_scale`: **silver → gold**.

## [1.4.0] — 2026-07-02

Quality scale raised to **silver**.

### Added

- Error-path tests for every write platform (button, select, switch, update) and
  the config-flow and coordinator error branches, bringing every integration
  module to ≥95% line coverage (the vendored `aiounas` client keeps its own 90%+
  suite).

### Changed

- `quality_scale` is now **silver** (all silver rules done or exempt): the
  `test-coverage` rule is satisfied and `parallel-updates` was already in place.

## [1.3.0] — 2026-07-02

Snapshot control and a published quality self-assessment.

### Added

- **Scheduled-snapshots switch** per share (opt-in control, session auth): toggles
  the share's `snapshotEnabled` flag. The UNAS local REST API exposes no snapshot
  list/create endpoint — an extensive read-only probe found only this per-share
  flag — so scheduling is the sole snapshot control surface. The write path is
  inferred from the confirmed share resource and is **not yet verified against live
  hardware**; it is off unless control actions are enabled.
- **`quality_scale.yaml`** and a `quality_scale: bronze` manifest declaration
  documenting the integration against Home Assistant's Integration Quality Scale.
- `PARALLEL_UPDATES` declared on every platform (0 for the read-only coordinator
  platforms, 1 for the write platforms).
- `aiounas`: `UnasActionClient.set_share_snapshots()`.

## [1.2.0] — 2026-07-02

Privacy-safe activity insight. Three additional session-only endpoints are read
strictly as aggregates — counts, categories and timestamps — so no notification
or log content is ever parsed, returned, stored or logged.

### Added

- **Applications sensor** (session-only): the number of installed UniFi OS
  apps/integrations, with a name→version map as attributes (from the full
  `/api/system` payload).
- **Recent events sensor** (session-only): a count of recent notifications with a
  per-category breakdown (e.g. `admins`, `backups`, `updates`) as attributes, and
  a **Last event** timestamp sensor — derived from `/api/notifications`. The
  notification bodies (`event_data`, `cef_log`, titles) are personal data and are
  never parsed or retained.
- **Log entries sensor** (session-only): a count of recent activity-log entries
  from `/proxy/drive/api/v2/systems/logs`; the log payloads are never retained.
- `aiounas`: `Application`, `NotificationSummary` and `LogSummary` models;
  `UnasClient.get_notification_summary()` / `get_log_summary()`; `notifications`
  and `logs` capability probes.

### Security

- The new endpoints are session-scoped; an API key is denied (`403`/`500`) and the
  sensors are simply absent. Each summary discards every content field at parse
  time, so PII cannot reach entity state, attributes, diagnostics or logs.

## [1.1.0] — 2026-07-01

Richer monitoring plus update entities and a fan-mode selector. All new read
paths were verified against real hardware.

### Added

- **Sensors**: per-disk read/write rate; pool data-scrubbing status; last-boot
  (timestamp) and network link speed; a privacy-safe **account count**
  (session-only — read from the `total` field; the account list, which is PII,
  is never parsed, returned, stored, or logged).
- **Per-share sub-devices** (session-only): usage, quota, member count and
  encryption sensors, plus snapshot-enabled and remote-backup binary sensors.
- **Update entities** for UniFi OS and the Drive app (session-only): installed
  and latest versions, with an Install button when control actions are opted in
  (an owner account is required to install). Versions are normalized so the same
  release in a different format does not read as an available update.
- **Fan-mode selector** (opt-in control) using the hardware-verified
  `{"profile": …}` payload.
- **CLI/MCP**: a `fan` command, `status --json`, and an `update-drive-app`
  command; MCP gains confirmation-gated `set_fan_profile` and `update_drive_app`
  write tools and a `get_fan_profile` read tool.

### Security

- The account-count feature reads only the count; individual user accounts are
  never exposed. Session-only entities are created only under username/password
  auth; API-key configs are unaffected.

## [1.0.0] — 2026-07-01

First stable release. Builds on the read-only foundation (0.1.0) with opt-in
control, a CLI and MCP server, per-pool sensors, and integration branding.

### Added

- **Opt-in control (write) layer** (`UnasActionClient`, kept separate from the
  read-only client): reboot, shutdown, UniFi OS firmware update, Drive-app
  update, and fan profile. The fan write payload is verified against hardware
  (`PUT {"profile": <cooling|default|quiet>}`).
- **Home Assistant control buttons** (reboot / shutdown / updates) behind an
  `enable_controls` option (default off). Created only for username/password
  auth — an API key is read-only; power and firmware need an owner account.
  Refusals surface a clear "insufficient permissions" message.
- **`unifi-unas` CLI** and **`unifi-unas-mcp` MCP server** over the shared
  client, behind a unified safety model: reads are open; writes require explicit
  confirmation (CLI `--yes` or prompt; MCP an opt-in env var plus `confirm=true`).
- **Per-pool sub-devices**: RAID level, status, usage, capacity and used space
  per storage pool.
- **Branding**: an in-repo brand icon (shown in Home Assistant) and MDI entity
  icons via `icons.json`.
- **Richer device page**: the UNAS is a `hub` with a MAC connection, a
  "Visit device" link to the console, and per-disk serial numbers.
- **CI**: hassfest and HACS validation.

### Security

- Control actions are opt-in and off by default; they need session auth (an
  owner account for power/firmware), never an API key.
- No user/account entities are exposed (accounts are personal data).
- Credentials stay in the Home Assistant config entry; diagnostics redact
  serials and credentials.

## [0.1.0]

First release. Non-invasive, read-only monitoring of the Ubiquiti UniFi UNAS
over the local UniFi OS / Drive REST API — no SSH, nothing installed on the NAS.

### Added

- `aiounas` async client library:
  - Dual auth: API key or local-account session, with automatic reauth.
  - GET-only transport with typed error mapping.
  - Typed models for disks/SMART, pools/RAID, CPU/memory, network, shares, and identity.
  - Capability probe that reports which endpoints the current credential can read.
- `unifi_unas_rest` Home Assistant integration:
  - UI config flow offering API key or local account, with reauthentication.
  - `DataUpdateCoordinator` local polling.
  - Sensors for storage, RAID, CPU, memory, network, and versions, plus per-disk
    SMART sub-devices.
  - Connectivity and problem binary sensors.
  - Redacted diagnostics.
- `docs/API.md`: reverse-engineered reference for the UNAS local REST API.
- Repository PII/secret guard (pre-commit + CI). CI runs the library on
  Python 3.12–3.14 and the integration on Python 3.14 against a real Home
  Assistant install.

### Security

- Read-only; no write endpoints are called.
- Least-privilege friendly: use a scoped API key or a restricted local account.
- Credentials stay in the Home Assistant config entry; diagnostics redact serials
  and credentials.
