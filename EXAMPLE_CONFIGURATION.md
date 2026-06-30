# Examples & configuration reference

This integration is set up entirely through the UI — there's **no YAML to add to
`configuration.yaml`** to install or connect it. This document is a reference for
the **entities**, **services**, and **events** it provides, with copy-paste
examples for automations and dashboards.

For the connection/setup steps (discovery, manual host + token), see the
[README](./README.md). A plain `.yaml` version of the service snippets below is
in [`example_configuration.yaml`](./example_configuration.yaml).

> **Model note:** a few features are **Dock 3 only** — `set_volume`,
> `set_port_mode`, `send_serial`, `enable_serial_events`, `set_port_trigger`, and
> the volume / external-port entities. Everything else works on both Dock 3 and
> Dock Two.

---

## Entities

| Platform | Entities |
| --- | --- |
| **Sensor** | Name, Hostname, Version, Serial, Model, Revision, Uptime, SSID, Volume, Free heap, Status/Ethernet LED brightness, Reset reason, PoE mode, and one **Port mode** sensor per external port |
| **Binary sensor** | Ethernet, Wi-Fi, IR learning, NTP |
| **Number** | Volume, Status LED brightness, Ethernet LED brightness *(only when reported)* |
| **Button** | Identify, Stop IR, Refresh, Reboot |
| **Switch** | Serial TCP, IR learning, and a **5 V trigger** per trigger-capable port |

Some sensors are diagnostic and/or disabled by default; enable them from the
device page if you want them.

---

## Services

Every service accepts an optional **`device_id`**. Omit it when you have a single
dock; otherwise target a specific dock with its device id.

### `send_ir` — send an infrared code

```yaml
service: hass_unfolded_circle_dock.send_ir
data:
  code: "0000 006D 0022 0002 0155 00AA ..."   # PRONTO hex, or Unfolded Circle hex
  format: pronto       # pronto | hex
  repeat: 0            # >0 repeats the code; the dock may answer asynchronously
  hold: 0              # ms to hold (firmware permitting)
  int_side: true       # internal side blaster (used by default if none selected)
  int_top: false       # internal top blaster
  ext1: false          # external IR port 1
  ext2: false          # external IR port 2
```

Only `code` and `format` are required. Repeated/asynchronous sends are reported
as success even when the firmware returns no acknowledgement.

### `stop_ir` — stop a repeating transmission

```yaml
service: hass_unfolded_circle_dock.stop_ir
```

### `identify` — flash the dock LEDs

```yaml
service: hass_unfolded_circle_dock.identify
```

### `set_volume` — set speaker volume *(Dock 3)*

```yaml
service: hass_unfolded_circle_dock.set_volume
data:
  volume: 50           # 0-100
```

You can also use the **Volume** number entity.

### `set_brightness` — set LED brightness

```yaml
service: hass_unfolded_circle_dock.set_brightness
data:
  status_led: 150      # 0-255, optional
  eth_led: 100         # 0-255, optional
```

At least one of `status_led` / `eth_led` is required. The **Status/Ethernet LED
brightness** number entities do the same.

### `set_port_mode` — configure an external port *(Dock 3)*

```yaml
service: hass_unfolded_circle_dock.set_port_mode
data:
  port: 1
  mode: RS232          # AUTO | NONE | IR_BLASTER | IR_EMITTER_MONO_PLUG |
                       # IR_EMITTER_STEREO_PLUG | TRIGGER_5V | RS232
  baud_rate: 115200    # RS232 only, 300-115200, default 9600
  data_bits: 8         # RS232 only, default 8
  parity: none         # RS232 only, default none
  stop_bits: "1"       # RS232 only, default 1
```

The RS232 line settings are optional and ignored for non-RS232 modes.

### `send_serial` — write to an RS232 port *(Dock 3)*

```yaml
service: hass_unfolded_circle_dock.send_serial
data:
  port: 1
  data: "POWER ON\r"
```

The port must already be in RS232 mode (otherwise the dock returns `409`).

### `enable_serial_events` — stream incoming serial data *(Dock 3)*

```yaml
service: hass_unfolded_circle_dock.enable_serial_events
data:
  port: 1
  enable: true
```

Incoming data is then delivered on the event bus (see **Events** below).

### `set_port_trigger` — control a 5 V trigger *(Dock 3)*

The port must be in `TRIGGER_5V` mode. Omit `duration` to latch; set it to pulse
and auto-release.

```yaml
# Latch on
service: hass_unfolded_circle_dock.set_port_trigger
data:
  port: 1
  trigger: true

# Pulse for 300 ms
service: hass_unfolded_circle_dock.set_port_trigger
data:
  port: 1
  trigger: true
  duration: 300
```

Each trigger-capable port also has a **switch** entity for simple on/off.

### `reboot` — restart the dock

```yaml
service: hass_unfolded_circle_dock.reboot
```

The dock drops the connection on reboot; the integration reconnects
automatically. There's also a **Reboot** button entity.

### `refresh` — re-poll system info

```yaml
service: hass_unfolded_circle_dock.refresh
```

---

## Events

The dock pushes events onto the Home Assistant **event bus**. Each event's data
includes the dock `serial`.

| Event type | Fired when | Data fields |
| --- | --- | --- |
| `hass_unfolded_circle_dock_serial_data` | RS232 data arrives | `serial`, `port`, `data` |
| `hass_unfolded_circle_dock_log` | Dock log streaming is enabled | `serial`, `level`, `tag`, `log`, `ts` |
| `hass_unfolded_circle_dock_ir_learn` | IR receive on/off or a learned code | `serial`, `state`, `raw` |
| `hass_unfolded_circle_dock_port_mode` | A port's mode changes | `serial`, port fields |

---

## Automations

### Notify on incoming serial data

```yaml
automation:
  - alias: "Dock: notify on serial data"
    trigger:
      - platform: event
        event_type: hass_unfolded_circle_dock_serial_data
    action:
      - service: persistent_notification.create
        data:
          title: "Dock serial (port {{ trigger.event.data.port }})"
          message: "{{ trigger.event.data.data }}"
```

### Turn a TV on at sunset via IR

```yaml
automation:
  - alias: "Dock: TV on at sunset"
    trigger:
      - platform: sun
        event: sunset
    action:
      - service: hass_unfolded_circle_dock.send_ir
        data:
          code: "0000 006D 0022 0002 0155 00AA ..."
          format: pronto
          repeat: 1
          int_side: true
```

### Drive an amplifier's trigger from a media player

The port must be configured as `TRIGGER_5V`.

```yaml
automation:
  - alias: "Dock: amp trigger follows media player"
    trigger:
      - platform: state
        entity_id: media_player.living_room
        to: "playing"
        id: "on"
      - platform: state
        entity_id: media_player.living_room
        to: "off"
        id: "off"
    action:
      - service: hass_unfolded_circle_dock.set_port_trigger
        data:
          port: 1
          trigger: "{{ trigger.id == 'on' }}"
```

### Quiet hours (lower volume at night)

```yaml
automation:
  - alias: "Dock: quiet hours"
    trigger:
      - platform: time
        at: "22:00:00"
    action:
      - service: hass_unfolded_circle_dock.set_volume
        data:
          volume: 10
```

---

## Dashboard card

A simple entities card grouping the controls:

```yaml
type: entities
title: Dock
entities:
  - entity: number.dock_volume
  - entity: number.dock_status_led_brightness
  - entity: switch.dock_port_1_5v_trigger
  - entity: button.dock_identify
  - entity: button.dock_reboot
  - entity: binary_sensor.dock_ethernet
  - entity: binary_sensor.dock_wifi
```

Entity IDs depend on your dock's name — adjust the `dock_` prefix to match what
Home Assistant assigned.

---

## Tips

- **Targeting a specific dock:** add `device_id: <id>` to any service call. With
  one dock you can leave it out.
- **RS232 ordering:** set the port to RS232 with `set_port_mode` *before*
  `send_serial` or `enable_serial_events`, or the dock replies `409`.
- **5 V triggers:** the trigger switch/service only works while the port is in
  `TRIGGER_5V` mode; the switch shows unavailable otherwise.
- **Dock Two:** volume, serial, and the external ports don't exist on Dock Two —
  those services return an error and the related entities won't appear.