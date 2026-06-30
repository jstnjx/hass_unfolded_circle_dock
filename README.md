# Unfolded Circle Dock — Home Assistant Integration

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![Validate](https://github.com/jstnjx/hass_unfolded_circle_dock/actions/workflows/validate.yml/badge.svg)](https://github.com/jstnjx/hass_unfolded_circle_dock/actions/workflows/validate.yml)

A custom [Home Assistant](https://www.home-assistant.io/) integration for the
**Unfolded Circle Dock 3** and **Dock Two**. It talks to the dock over its
native WebSocket JSON API, authenticates automatically, exposes dock status as
entities, and surfaces dock actions (IR, serial, identify, volume, …) as Home
Assistant services.

- **Integration domain:** `hass_unfolded_circle_dock` (service calls and event
  types use this prefix).
- **IoT class:** `local_push` — the dock pushes serial/log/IR events to HA in real time.
- **Connection:** WebSocket, local network only. No cloud dependency.
- **Tested against:** Dock 3 firmware WebSocket API (`type: "dock"` envelope).

---

## Features

| Capability | How it's exposed |
| --- | --- |
| System info (name, version, serial, model, uptime, …) | Sensors (diagnostic) |
| Ethernet / Wi-Fi connectivity, IR-learning active | Binary sensors |
| Volume, SSID, free heap | Sensors |
| Per-port mode (RS232 / TRIGGER_5V / …) | One sensor per external port |
| Identify, Stop IR, Refresh | Buttons |
| Serial-TCP bridge, IR-learning | Switches |
| Send IR, stop IR, identify, set volume/brightness, send serial, set port mode, (un)subscribe serial events, refresh | Services |
| Incoming serial data, log lines, IR-receive, port-mode changes | Home Assistant bus events |

---

## Installation

### Option A — HACS (recommended)

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=jstnjx&repository=hass_unfolded_circle_dock&category=integration)

This integration is installed as a **HACS custom repository**:

1. Open **HACS → Integrations**, click the ⋮ menu (top-right) → **Custom
   repositories**.
2. Add `https://github.com/jstnjx/hass_unfolded_circle_dock` and choose category
   **Integration**.
3. Search for **Unfolded Circle Dock** in HACS and click **Download**.
4. **Restart Home Assistant.**
5. Add the integration via **Settings → Devices & Services → Add Integration**.

> Once this repository is accepted into the HACS default store, steps 1–2 are no
> longer needed — it will appear in HACS search directly.

### Option B — Manual

1. Copy the `custom_components/hass_unfolded_circle_dock` folder into your Home
   Assistant configuration directory so you end up with:

   ```text
   <config>/custom_components/hass_unfolded_circle_dock/
   ```

2. Restart Home Assistant.

---

## Configuration

Add the integration from the UI:

**Settings → Devices & Services → Add Integration → "Unfolded Circle Dock"**

You'll first pick your **dock model** — *Dock 3* or *Dock Two* — which pre-fills
the right connection defaults. Then enter:

| Field | Dock 3 default | Dock Two default | Notes |
| --- | --- | --- | --- |
| **Host / IP** | — | — | The dock's IP address or hostname. |
| **Port** | `80` | `946` | Dock 3 serves on port 80; Dock Two on 946. |
| **WebSocket path** | `/ws` | `/` | Dock 3 is `ws://<ip>/ws`; Dock Two is `ws://<ip>:946/`. |
| **Token** | `0000` | `0000` | The dock PIN/token; `0000` if never changed. |
| **Use TLS** | off | off | Enable only if your dock serves `wss://`. |
| **Name** | optional | optional | Friendly name override. |

During setup the integration opens the WebSocket, sends the auth token, and
calls `get_sysinfo` (the one command both docks allow before authentication).
The dock **serial number** becomes the unique ID, so the same dock can't be
added twice. A wrong token gives *Invalid authentication*; an unreachable host
gives *Cannot connect*.

> **Finding the token:** it's the PIN shown in the Unfolded Circle remote/web
> configurator for the dock. A factory-fresh dock with no custom PIN uses `0000`.

### Dock Two vs Dock 3

Dock Two and Dock 3 share the same core API, but a few features are **Dock 3
only**: speaker **volume**, the external **ports** (RS232 / 5 V trigger), and
serial streaming. On a Dock Two those entities simply won't appear and the
corresponding services return an error if called. IR, identify, LED brightness,
Wi-Fi/Ethernet status and reboot/reset work on both.

---

## Entities

After setup you get a single device with, among others:

- **Sensors:** Name, Hostname, Version, Serial, Model, Revision, Uptime, SSID,
  Volume, Free heap *(disabled by default)*, and one **Port mode** sensor per
  external port (attributes include `supported_modes` and the active UART config).
- **Binary sensors:** Ethernet, Wi-Fi (connectivity), IR learning (running).
- **Buttons:** Identify, Stop IR, Refresh.
- **Switches:** Serial TCP, IR learning.

Most informational sensors are categorised as *diagnostic*.

---

## Services & usage examples

All services accept an optional `device_id`. If you only have **one** dock
configured, you can omit it.

### Send an IR command — `hass_unfolded_circle_dock.send_ir`

```yaml
service: hass_unfolded_circle_dock.send_ir
data:
  code: "0000 006D 0022 0002 0155 00AA 0015 0015 ..."  # PRONTO hex
  format: pronto
  repeat: 0
  hold: 0
  int_side: true     # internal side blaster
  int_top: false     # internal top blaster
  ext1: false        # external IR port 1
  ext2: false        # external IR port 2
```

If no emitter is selected, the internal side blaster is used by default.

> **Note on repeats:** when `repeat` > 1 (or the dock advertises the async-IR
> feature) the firmware sends IR **without** a synchronous WebSocket reply. The
> integration treats that as success (`202 Accepted`) rather than waiting and
> timing out.

### Stop IR — `hass_unfolded_circle_dock.stop_ir`

```yaml
service: hass_unfolded_circle_dock.stop_ir
```

### Identify the dock — `hass_unfolded_circle_dock.identify`

```yaml
service: hass_unfolded_circle_dock.identify
```

(Or just press the **Identify** button entity.)

### Set volume — `hass_unfolded_circle_dock.set_volume`

```yaml
service: hass_unfolded_circle_dock.set_volume
data:
  volume: 50   # 0-100
```

### Set LED brightness — `hass_unfolded_circle_dock.set_brightness`

```yaml
service: hass_unfolded_circle_dock.set_brightness
data:
  status_led: 150   # 0-255
  eth_led: 100      # 0-255
```

### Send serial data — `hass_unfolded_circle_dock.send_serial`

The target port must already be in **RS232** mode (otherwise the dock returns
`409 Conflict`). Use `set_port_mode` first if needed.

```yaml
service: hass_unfolded_circle_dock.send_serial
data:
  port: 1
  data: "POWER ON\r"
```

### Set port mode — `hass_unfolded_circle_dock.set_port_mode`

```yaml
service: hass_unfolded_circle_dock.set_port_mode
data:
  port: 1
  mode: RS232
  baud_rate: 115200      # optional, RS232 only — 300..115200, defaults to 9600
  data_bits: 8           # optional — 5/6/7/8, defaults to 8
  parity: none           # optional — none/even/odd, defaults to none
  stop_bits: "1"         # optional — 1/1.5/2, defaults to 1
```

When switching a port to RS232 you can set the **baud rate** (and, if needed,
data bits, parity and stop bits). Anything you omit falls back to the dock's
documented defaults — `9600 8N1` — so for the common case you only need `port`,
`mode`, and `baud_rate`. These line settings are ignored for non-RS232 modes,
and the whole `set_port_mode` service is Dock 3 only.

### Subscribe to serial events — `hass_unfolded_circle_dock.enable_serial_events`

```yaml
service: hass_unfolded_circle_dock.enable_serial_events
data:
  port: 1
  enable: true
```

### Force a refresh — `hass_unfolded_circle_dock.refresh`

```yaml
service: hass_unfolded_circle_dock.refresh
```

---

## Receiving serial data (and other events)

Incoming data from the dock is published on the Home Assistant **event bus**.
Subscribe to it from an automation.

Event types:

| Event | Fired when | Data |
| --- | --- | --- |
| `hass_unfolded_circle_dock_serial_data` | RS232 data arrives | `serial`, `port`, `data` |
| `hass_unfolded_circle_dock_log` | Dock log streaming enabled | `serial`, `level`, `tag`, `log`, `ts` |
| `hass_unfolded_circle_dock_ir_learn` | IR receive on/off / learned code | `serial`, `state`, `raw` |
| `hass_unfolded_circle_dock_port_mode` | A port mode changes | `serial`, port fields |

Example automation reacting to serial data:

```yaml
automation:
  - alias: "Log dock serial data"
    trigger:
      - platform: event
        event_type: hass_unfolded_circle_dock_serial_data
    action:
      - service: persistent_notification.create
        data:
          title: "Dock serial (port {{ trigger.event.data.port }})"
          message: "{{ trigger.event.data.data }}"
```

Remember to enable the stream first (once) with
`hass_unfolded_circle_dock.enable_serial_events` for the relevant port, and make
sure the port is in RS232 mode.

See [`example_configuration.yaml`](./example_configuration.yaml) for more
ready-to-paste service calls and automations.

---

## Reconnection behaviour

- The WebSocket is supervised by a background task. On disconnect the client
  reconnects with **exponential backoff** (1 s → up to 60 s) and re-authenticates.
- Serial-event subscriptions are **re-applied** automatically after a reconnect.
- Pending requests are cancelled cleanly on disconnect so HA never blocks.
- Entities report **unavailable** while the socket is down and recover on reconnect.

---

## Troubleshooting

- **"Cannot connect"** — verify the IP, that port `80`/path `/ws` are correct,
  and that nothing else holds the dock's single API slot. Unauthenticated
  sockets are dropped by the dock after ~30 s.
- **"Invalid authentication"** — wrong token/PIN. Default is `0000`.
- **`409` when sending serial** — the port isn't in RS232 mode; call
  `set_port_mode` first.
- **No IR reply / IR "timeout"** — expected for repeated/async IR; the
  integration reports success anyway. Check the blaster selection flags.
- **Diagnostics** — download via the device page; the token, serial and SSID are
  redacted.

---

## Notes on design

- The API client (`api.py`) has **no Home Assistant imports**, so it can be unit
  tested in isolation.
- Boolean states (Ethernet/Wi-Fi/IR-learning) are implemented as **binary
  sensors**, which is the idiomatic Home Assistant pattern, in addition to the
  sensors requested in the original spec.
- Request/response correlation uses the JSON `id` ⇄ `req_id` fields, matching the
  dock firmware.

---

## Development & validation

This repo ships a GitHub Actions workflow
([`.github/workflows/validate.yml`](./.github/workflows/validate.yml)) that runs
the official **HACS Action** and Home Assistant **hassfest** checks on every
push and pull request.

To get the integration into the HACS *default* store, submit it to
[hacs/default](https://github.com/hacs/default) per the HACS publishing docs.
Make sure the GitHub repo is **public** and has a **description** and at least
one **topic** — both are required by HACS.

## License

Released under the [MIT License](./LICENSE).
The dock firmware is © Unfolded Circle ApS.