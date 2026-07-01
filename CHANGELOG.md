# Changelog

All notable changes are documented here. This project adheres to
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added (v2, in progress)
- **Write/action layer** (`UnasActionClient`): reboot, shutdown, install UniFi OS
  update, install Drive-app update, set fan profile — kept separate from the
  read-only client. Fan payload is unverified pending a live check.
- **Home Assistant control buttons** (reboot / shutdown / updates) behind an
  opt-in `enable_controls` option (default off; v1 stays read-only).
- **`unifi-unas` CLI** and **`unifi-unas-mcp` MCP server** over the shared client,
  with a unified safety model: reads are open, writes require explicit
  confirmation (CLI `--yes`/prompt; MCP opt-in env **and** `confirm=true`).

### Planned
- Fan-mode select and snapshot controls in Home Assistant.
- Zeroconf discovery; per-pool sensors.

## [0.1.0] — v1 (read-only)

First release. Non-invasive, read-only monitoring of Ubiquiti UniFi UNAS over the
local UniFi OS / Drive REST API — no SSH, nothing installed on the NAS.

### Added
- **`aiounas`** — async client library: dual auth (API key + local-account
  session), GET-only transport with reauth and typed error mapping, typed models
  (disks/SMART, pools/RAID, CPU/memory, network, shares, identity), and a
  capability probe. Verified live against real UNAS-2 hardware. 47 tests,
  `mypy --strict`.
- **`unifi_unas_rest`** — Home Assistant integration: UI config flow offering a
  choice of API key or local account, with re-authentication; a
  `DataUpdateCoordinator` (local polling); sensors for
  storage / RAID / CPU / memory / network / versions and per-disk SMART
  sub-devices; connectivity and problem binary sensors; redacted diagnostics.
  Tested against Home Assistant 2026.6 on Python 3.14.
- **`docs/API.md`** — a reverse-engineered reference for the UNAS local REST API.
- Repository PII/secret guard (pre-commit + CI); CI across Python 3.12–3.14 for
  the library and Python 3.14 + real Home Assistant for the integration.

### Security
- Read-only. Least-privilege friendly (a scoped API key, or a restricted local
  account). Credentials stay in the Home Assistant config entry; diagnostics
  redact serials and credentials.
