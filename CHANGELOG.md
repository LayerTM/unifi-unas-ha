# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Fixed

- **One version number.** Three files stated it and they had drifted apart —
  `1.7.5` in the integration manifest, `1.7.4` in the package metadata, `1.7.2` in
  the library, against a released `v1.7.5`. The package version is now read from the
  manifest, the file Home Assistant and HACS actually show and the one a release tag
  is cut from, so a release changes it in one place. The library's `__version__` is
  gone rather than corrected: nothing read it, it was documented nowhere, and the
  package is not published — a copy that only ever drifts.

### Changed

- **The MCP server runs on the current SDK.** Version 2 renamed `FastMCP` to
  `MCPServer` and moved it, so the old import stopped resolving; the dependency was
  capped below 2 rather than following it. The server is ported and the cap is gone —
  the extra now asks for `mcp>=2`, checked against both 2.0.0 and 2.1.1. Tool names,
  arguments and the write-confirmation gate are unchanged.

- **Installation is through the HACS default list.** The integration was accepted into
  it, so no custom repository has to be added first — the badge and the installation
  steps said otherwise and now match. No code change; this ships with the next release.

- **Workflow actions are pinned to a commit, and dependency updates are proposed
  automatically.** `actions/checkout` and `actions/setup-python` now reference the
  commit behind the release rather than a moving tag — `setup-python` was a major
  behind — and a Dependabot configuration proposes updates for both the Python
  dependencies and the actions weekly, with no version held back by rule.

  The `hassfest` and HACS validators stay on their branch on purpose: they check
  against what Home Assistant and HACS require today, so pinning them would freeze
  the check rather than the code it runs.

- **The package declares the Python versions it is actually tested on** — 3.13 and
  3.14 were in the CI matrix but missing from the metadata.

- **The test-suite fails on any deprecated Home Assistant API, not only the one that
  was known about.** Core announces a deprecation through three fixed log sentences
  of its own; the integration suite now watches those sentences for every test,
  rather than asserting the absence of one API's warning in one test. An API core
  deprecates next year turns the suite red the first time the floating test harness
  carries that release, naming the call site in core's own words — with nothing to
  add here in advance. The suite also treats `DeprecationWarning` as an error, which
  covers what the standard library and the runtime dependencies deprecate through
  Python's own channel instead of through logs.

  Verified against Home Assistant 2026.9.1: nothing here is deprecated today, on a
  run exercising 97–100% of every integration module. The guard is checked in both
  directions — it fails when core really does report, and it re-reads core's source
  so that a rewording turns the suite red instead of silently blinding it.

## [1.7.5]

### Changed

- **Sub-devices are attached to the hub by device-registry id, not by identifiers.**
  Home Assistant 2026.8 replaced `DeviceInfo(via_device=…)` with `via_device_id` and
  removes the old key in **2027.8**; until then core logs a warning naming this
  integration every time a device is created that way — 47 of them in one run of the
  integration test-suite (core de-duplicates per call site, so a running Home
  Assistant shows the line rather than the count).
  `async_setup_entry` now registers the hub device before the platforms load, so a
  hub id exists to point at, and every disk / pool / share sub-device carries it.

  **No new minimum Home Assistant version.** Which spelling to send is asked of
  `DeviceInfo` itself rather than of a version number, so the 2025.3 floor is
  unchanged and nothing needs revisiting when the old key is finally removed. The
  hub device definition also lives in one place now, shared by the hub entities and
  by setup, instead of being written twice.
- **The Home Assistant test harness floats instead of being pinned exactly.** The
  `==0.13.340` pin held CI on Home Assistant 2026.6 while users ran 2026.9, so the
  deprecation warnings core logs against this integration could not appear in any
  test run — the warning above reached a user before it reached the build. It is a
  floor now, and the integration suite asserts that no deprecation is reported.

## [1.7.4]

### Fixed

- **The `ha` extra is resolvable again across the declared Python range.** It pulls
  a Home Assistant test harness that requires **Python 3.14.2**, while the library
  itself supports 3.12+, and the dependency carried no marker saying so. `pip` never
  noticed — it resolves for the one interpreter it runs on — but a universal resolver
  (`uv`) correctly reported the whole project as unsatisfiable, so `uv run` failed in
  a checkout. The requirement now carries
  `; python_full_version >= '3.14.2'`, which states that fact once.

### Documentation

- **README, *Data updates*:** "an authentication failure triggers re-authentication"
  no longer describes what the code does. It now says what actually counts as one —
  only a 401 that survives a re-login — and that a booting/updating console is
  treated as unavailable and retried.
- **README, *Troubleshooting*:** an entry for the symptom itself, "it keeps asking to
  re-authenticate but the credential still works", naming the version that fixes it
  and the entry reload that clears the stale repair.
- **docs/API.md:** a new *Responses that are not the API* section recording what the
  console answers while the application behind the proxy is down, and why redirects
  are not followed.
- The **quality-scale badge** now reads *self-reported*. `quality_scale` was dropped
  from the manifest in 1.7.3 precisely because it reads as an official rating; a
  badge claiming the same thing was the same claim in another place.

## [1.7.3]

### Fixed

- **The integration no longer loses authorization on its own.** The transport
  classified two non-authorization conditions as auth failures, and the coordinator
  turns any auth failure into `ConfigEntryAuthFailed` — which Home Assistant treats
  as terminal: polling stops and the entry waits for a manual re-authentication that
  never becomes necessary, because the credential was valid the whole time. This is
  the defect behind a repair notice reading *"Authentication expired"* that reappears
  around firmware updates.
  - A **2xx carrying the console's web UI instead of JSON** was reported as
    "session may have expired". It means the console is not serving the API — it is
    booting, updating or restarting. It is now a retryable `UnasApiError`. A
    session-based login still gets its one re-login attempt first, since the body
    may genuinely be a login shell.
  - **Redirects are no longer followed.** `aiohttp` follows them by default; a
    UniFi OS console can answer an API path with a redirect to its web UI while the
    application behind the proxy is down, and following it produces a
    `200 text/html` indistinguishable from an expired session. Redirects now surface
    as a `UnasApiError` naming the target, so the cause is visible in the log.

### Changed

- **Minimum Home Assistant lowered from 2026.6.0 to 2025.3.0.** The floor was far
  above what the code needs and hid the integration from everyone on an older
  release. 2025.3.0 is the release that introduced `AddConfigEntryEntitiesCallback`,
  the newest core API in use — measured against the Home Assistant sources at each
  tag, with every other imported symbol confirmed present there.
- **`quality_scale` removed from the manifest.** It is a Home Assistant core field,
  is not evaluated for custom integrations, and read as an official rating. Raised
  by a HACS maintainer on the sibling integration; the same applies here.
- **`mcp` extra pinned to `<2`.** mcp 2.x renamed `FastMCP` to `MCPServer`, which
  broke the unpinned install of the optional MCP server.


## [1.7.2] — 2026-07-02

### Changed

- Hardened the CI secret/PII scanner: alongside the existing UniFi-specific
  patterns (MACs, serials, direct-connect domains), it now also catches generic
  credentials and personal data — Anthropic/GitHub/Slack/AWS/Google keys, private
  key blocks, `/Users/` paths, gmail addresses, and private LAN IPs
  (private RFC-1918 ranges). Example hosts in the CLI/smoke docs were switched from
  a real-LAN-looking private-range address to the documentation range `192.0.2.10`.

### Changed

- CI: the HACS validation now runs **without** the `ignore: brands` key. Since Home
  Assistant 2026.3, custom integrations serve their brand icon in-repo
  (`custom_components/unifi_unas_rest/brand/`) via the brands proxy, and the HACS
  action validates it directly — so the ignore is no longer needed. No functional
  change to the integration.

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
