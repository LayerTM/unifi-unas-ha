# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Planned

- Fan-mode select and snapshot controls in Home Assistant.

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
