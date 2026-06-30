# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.4.0] - 2026-06-30

Exposes more of the dock's capabilities that were previously unreachable.

### Added
- **5 V trigger control (Dock 3).** Each external port that supports
  `TRIGGER_5V` gets a switch entity, plus a `set_port_trigger` service with an
  optional `duration` for timed pulses. Previously the trigger could be selected
  as a port mode but never actually fired.
- **Reboot** button (restart device class) and `reboot` service.
- **Number entities** for volume and Status/Ethernet LED brightness, so they can
  be set straight from the dashboard (created only when the dock reports them).
- **Diagnostic sensors**: Status/Ethernet LED brightness, reset reason, PoE
  mode, and an NTP binary sensor (handles both the `ntp` and `sntp` fields).

## [1.3.0] - 2026-06-30

Makes setup dramatically easier with automatic discovery and model detection.

### Added
- **Automatic discovery** over mDNS/zeroconf (`_uc-dock._tcp`) and DHCP
  (hostnames `UC-Dock-*` and `UCD3*`). Docks now appear in Home Assistant
  ready to add — usually you only confirm the token.
- **Automatic model detection.** Manual setup no longer asks whether you have a
  Dock 3 or Dock Two; entering a host and token is enough — the integration
  probes both known endpoints and picks the right one.

### Changed
- Manual setup is now a single host + token form (port and path are optional
  advanced overrides instead of required fields). The previous Dock 3 / Dock Two
  model picker has been removed in favour of auto-detection.

### Notes
- Discovery reads the unauthenticated `get_sysinfo` to identify the dock by
  serial, so discovered and manually-added docks de-duplicate correctly.

## [1.2.0] - 2026-06-30

Adds support for the Unfolded Circle **Dock Two** and corrects several values to
match the official Dock-API specification.

### Added
- **Dock Two support.** Setup now starts with a dock-model picker (Dock 3 /
  Dock Two) that pre-fills the correct connection defaults — Dock 3: port 80,
  path `/ws`; Dock Two: port 946, path `/`.
- Port mode is now a dropdown of the documented modes (`AUTO`, `NONE`,
  `IR_BLASTER`, `IR_EMITTER_MONO_PLUG`, `IR_EMITTER_STEREO_PLUG`, `TRIGGER_5V`,
  `RS232`) with a custom-value fallback.

### Changed
- ⚠️ **`set_port_mode` default baud rate changed from 115200 to 9600.** RS232
  calls that don't pass an explicit `baud_rate` now negotiate at 9600. Specify
  `baud_rate: 115200` to keep the previous behavior.

### Fixed
- **LED brightness range is 0–255**, not 0–100. `set_brightness` and its sliders
  previously capped well below the dock's real maximum.
- **Baud rate** now uses the spec's documented default of 9600 and is
  constrained to the valid 300–115200 range (the previous list included an
  out-of-range value).

### Notes
- Volume, the external ports (RS232 / 5 V trigger) and serial streaming are
  **Dock 3 only**. On a Dock Two those entities don't appear and the related
  services return an error if called. IR, identify, LED brightness,
  Wi-Fi/Ethernet status and reboot/reset work on both.

## [1.1.0] - 2026-06-30

> Not published as a standalone GitHub release; the changes below shipped to
> users as part of 1.2.0.

### Added
- `set_port_mode` accepts RS232 line settings: **`baud_rate`** plus optional
  `data_bits`, `parity`, and `stop_bits`. Omitted values fall back to defaults
  (115200 8N1 in this release; changed to 9600 8N1 in 1.2.0). The service
  exposes a baud-rate dropdown with a custom-value option.

### Fixed
- The device target ("Dock") dropdown was empty for every service — the
  `integration:` filter in `services.yaml` still referenced the pre-rename
  domain. All service targets now resolve correctly.

## [1.0.0] - 2026-06-30

Initial release of the Unfolded Circle Dock integration for Home Assistant.
Connects to the Unfolded Circle Dock 3 over its local WebSocket API.

### Added
- Local-push WebSocket connection with automatic authentication and reconnect
  (exponential backoff, serial subscriptions restored on reconnect).
- Config flow UI setup; the dock serial number is used as the unique ID.
  Reconfigure supported.
- Entities:
  - Sensors for name, hostname, version, serial, model, revision, uptime, SSID,
    volume, free heap, and a per-port mode sensor for each external port.
  - Binary sensors for Ethernet, Wi-Fi, and IR-learning state.
  - Buttons: Identify, Stop IR, Refresh.
  - Switches: Serial-TCP bridge, IR learning.
- Services: `send_ir`, `stop_ir`, `identify`, `set_volume`, `set_brightness`,
  `send_serial`, `set_port_mode`, `enable_serial_events`, `refresh`.
- Home Assistant bus events for incoming serial data, dock logs, IR-receive,
  and port-mode changes (`hass_unfolded_circle_dock_*`).
- Diagnostics download with token, serial, and SSID redacted.

[Unreleased]: https://github.com/jstnjx/hass_unfolded_circle_dock/compare/v1.4.0...HEAD
[1.4.0]: https://github.com/jstnjx/hass_unfolded_circle_dock/compare/v1.3.0...v1.4.0
[1.3.0]: https://github.com/jstnjx/hass_unfolded_circle_dock/compare/v1.2.0...v1.3.0
[1.2.0]: https://github.com/jstnjx/hass_unfolded_circle_dock/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/jstnjx/hass_unfolded_circle_dock/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/jstnjx/hass_unfolded_circle_dock/releases/tag/v1.0.0