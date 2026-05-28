# Session Log — 2026-05-28

End-to-end record of the session that built the Pico-bridged localisation
module and probed the GPS module directly. Read this if you want to know
*what was done*, *what currently works*, and *what's still open*.

## What was built this session

The localisation sub-system is now packaged as a self-contained module:

```
   ┌───────────────────────────────────────┐         ┌──────────────┐
   │  LOCALISATION MODULE                  │  USB    │ MOTHER COMP  │
   │                                       │         │ (laptop)     │
   │  ┌─────────┐  UART   ┌──────────┐     │ /ttyACM0│              │
   │  │ Pixhawk │ ◄─────► │  Pico 2  │ ────┼────────►│  mavros      │
   │  │  +GPS   │ TELEM1  │ (bridge) │     │ MAVLink │  apm.launch  │
   │  │  +IMU   │115200   │ RP2350   │     │ stream  └──────────────┘
   │  │  +mag   │         └──────────┘     │
   │  │  EKF3   │                          │
   │  └─────────┘                          │
   │      ↑                                │
   │  [4S 1500 mAh battery via PM02 V3]    │
   └───────────────────────────────────────┘
```

The Pico is a **dumb byte-pump** — it shovels MAVLink2 bytes between the
Pixhawk's TELEM1 UART and its own USB CDC. From mavros' perspective the
Pico's USB endpoint is indistinguishable from the previous Pixhawk-USB2
endpoint, so all downstream ROS2 topics, the `walk_to_waypoints.py`
navigator, the rosbag recorder and the visualiser scripts work
unchanged.

## Pixhawk-side (firmware) state

| Param | Final value | Note |
|---|---|---|
| `SERIAL1_PROTOCOL` | 2 | MAVLink2 — was already correct |
| `SERIAL1_BAUD` | 115 | bridge firmware is hardcoded to 115200 |
| `BRD_SER1_RTSCTS` | 0 | no flow control — only TX/RX/GND wired |
| `SR1_*` (POSITION / EXTRA1 / EXTRA2 / RAW_SENS) | (see below) | DO NOT trust — they didn't reliably persist this session, use `set_rates.sh` instead |

## Pico-side (firmware) state

- **Board: Raspberry Pi Pico 2 (RP2350)** — *not* the original RP2040.
  Build target is `PICO_BOARD=pico2`, BOOTSEL VID:PID is `2e8a:000f`,
  BOOTSEL drive label is `RP2350` (not the RP2040's `RPI-RP2`).
- Firmware: 60-line transparent UART⇄USB byte bridge in `main.c`.
  UART0 on GP0 (TX) / GP1 (RX) @ 115200 8N1, no flow control. Onboard
  LED blinks at 1 Hz on the alive heartbeat.
- USB CDC by-id link (stable across reboots):
  `/dev/serial/by-id/usb-Raspberry_Pi_Pico_D453CDB057D9D414-if00`

## Wiring (final, working)

| Pixhawk 6C TELEM1 (DF13 6-pin) | → | Pico 2 physical pin | Pico signal |
|---|---|---|---|
| Pin 1 (VCC 5 V) | — | (open) | Pico is USB-powered, do not connect |
| Pin 2 (TX from FC) | → | pin 2 | GP1 / UART0 RX |
| Pin 3 (RX into FC) | ← | pin 1 | GP0 / UART0 TX |
| Pin 6 (GND) | → | pin 3 (or 38) | GND |
| Pins 4, 5 (CTS, RTS) | — | (open) | unused |

Both sides are 3.3 V logic — no level shifter required.

## What works (verified live)

- Pico 2 enumerates as a CDC serial device → `/dev/serial/by-id/...`
- MAVLink2 bytes flow from Pixhawk → Pico → laptop (verified with `xxd`,
  the `0xfd` start-of-frame markers are present, and the byte-level
  decode of the first few packets pulled valid `GLOBAL_POSITION_INT`,
  `ATTITUDE`, `VFR_HUD` and `SCALED_IMU2` message IDs)
- mavros connects: `CON: Got HEARTBEAT, connected. FCU: ArduPilot`
- `/mavros/global_position/global` publishes at **10.0 Hz** (verified)
- `/mavros/global_position/compass_hdg` publishes at **10.0 Hz** (verified)
- `/mavros/state` shows `connected: true, mode: STABILIZE`
- All downstream ROS2 tooling from the previous walk-test session
  (`walk_to_waypoints.py`, rosbag recorder, visualiser) is wired to the
  same topic names, so it should work unchanged

## What doesn't work yet

### `SR1_*` stream-rate params don't persist

The original plan was to write `SR1_POSITION=10`, `SR1_EXTRA1=10`, etc.
in QGroundControl and have the FC stream at 10 Hz automatically. The
observed behaviour after writing the params and rebooting was instead
**2.5 Hz** on `/mavros/global_position/global` — exactly 1/4 of the
requested rate.

Workaround: `set_rates.sh` calls `/mavros/set_message_interval` at
runtime to force 10 Hz for the four MAVLink messages we care about
(33 = `GLOBAL_POSITION_INT`, 30 = `ATTITUDE`, 74 = `VFR_HUD`,
26 = `SCALED_IMU2`). The runtime override sticks for the current mavros
session only — re-run the script every time you launch mavros from
scratch.

To investigate next session (low priority while the workaround works):
the previous session's memory says SERIAL7 → `SR3_*` (an unusual
mapping). It's possible SERIAL1 maps to a different `SR#_*` group than
the obvious `SR1_*` on this firmware. Read back the actual SERIAL→SR
mapping via QGC's MAVLink Inspector to confirm.

### GPS — module is healthy, sees 0 satellites

The GPS module's *electronics are fine* — confirmed by bypassing the
Pixhawk entirely and reading the GPS's UART directly via an FTDI FT232R
USB adapter. At **230400 baud** the module outputs a clean UBX binary
stream (`0xb5 0x62` sync header, valid `NAV-PVT` packets every 0.1 s).
The wiring to the GPS is therefore confirmed correct end-to-end.

The decoded first `NAV-PVT` packet reports:

| Field | Value | Meaning |
|---|---|---|
| fixType | 0 | NO FIX |
| numSV | 0 | zero satellites visible |
| hAcc | `0xFFFFFFFF` | no position estimate |
| year | 2020 | not synced to GPS time |
| lat/lon | 0 / 0 | placeholder |

This rules out the Pixhawk, the wiring, the power rail, and the GPS
module's electronics. **What's left is RF — antenna or sky exposure.**
Three things to physically check next time:

1. **u.FL connector** on the side of the GY-GPSV3 module. If the module
   has been previously configured for external antenna and the external
   pigtail is now loose/missing, you get exactly this symptom. Either
   re-attach an external antenna, or reconfigure the module via u-center
   to use the internal patch.
2. **Ceramic patch antenna** on top of the module. Must be unobstructed,
   face-up, and not pressed against metal (battery / Pixhawk case).
3. **Cold-start time + sky view.** After a long power-off, the M9N can
   need 3+ minutes with full sky view (outdoors or in a clear window) to
   re-acquire the almanac.

### Pixhawk pre-arm errors (not blocking localisation)

mavros logs three pre-arm errors that are expected and unrelated to the
localisation pipeline:

- `RC not found` — no RC receiver plugged in yet (RP3 not bound)
- `Hardware safety switch` — safety switch not pressed
- `Battery 1 unhealthy` — battery monitor calibration / PM02 reading

These are blockers for arming the motors but have no effect on GPS, EKF,
or MAVROS topic publication. They are inherited from the previous build
state, not introduced this session.

## How to bring the localisation module up from cold

```bash
# Terminal A — start mavros via the Pico bridge
source /opt/ros/jazzy/setup.bash
ros2 launch mavros apm.launch \
  fcu_url:=/dev/serial/by-id/usb-Raspberry_Pi_Pico_D453CDB057D9D414-if00:115200

# (in the mavros log you should see within ~2 s:
#   "CON: Got HEARTBEAT, connected. FCU: ArduPilot")

# Terminal B — bump message rates to 10 Hz
/home/mantis/loc/pico_mavlink_bridge/set_rates.sh

# Sanity check (expect ~10 Hz on both)
ros2 topic hz --window 20 /mavros/global_position/global
ros2 topic hz --window 20 /mavros/global_position/compass_hdg
```

From here the existing `/home/mantis/loc/COMMANDS.md` walk-test flow
works unchanged — `walk_to_waypoints.py`, the rosbag recorder, the
visualiser — none of them know about the Pico, they only see MAVROS
topics.

## Files added / modified this session

```
pico_mavlink_bridge/
├── main.c                       Pico bridge firmware — UART⇄USB byte pump
├── CMakeLists.txt               pico-sdk build config, stdio_uart disabled
├── pico_sdk_import.cmake        points at /home/mantis/pico-sdk
├── README.md                    architecture, info-flow tables, wiring
├── COMMANDS.md                  step-by-step runbook (build, flash, params, launch, troubleshoot)
├── set_rates.sh                 runtime rate-bump helper (the SR1_* workaround)
├── SESSION_LOG.md               this file
└── .gitignore                   excludes build/ and binary artefacts
```

Not in this directory but worth knowing:

- `/home/mantis/.claude/projects/-home-mantis-loc/memory/project_loc_module.md`
  — assistant's persistent memory record of this work; survives across
  sessions

## Diagnostic commands used (kept here for next time)

```bash
# Verify Pico CDC is enumerating
ls -l /dev/serial/by-id/usb-Raspberry_Pi_Pico_*

# Confirm MAVLink frames flow through the bridge
timeout 3 cat /dev/serial/by-id/usb-Raspberry_Pi_Pico_*-if00 \
  | head -c 256 | xxd | head -8
# expect: lots of 'fd' bytes (MAVLink v2 SOF)

# Read GPS UBX directly (bypassing Pixhawk) via an FTDI adapter
stty -F /dev/ttyUSB0 raw -echo cs8 -parenb -cstopb 230400
timeout 2 head -c 512 /dev/ttyUSB0 | xxd | head -10
# expect: 'b5 62 01 07 5c 00 ...' (UBX-NAV-PVT)

# Read GPS fix status via mavros
ros2 topic echo --once --qos-reliability best_effort \
  /mavros/global_position/raw/fix          # status: 0 = fix, -1 = none
ros2 topic echo --once --qos-reliability best_effort \
  /mavros/global_position/raw/satellites    # data: N satellites

# Common gotcha: QGC's AutoConnect grabs any serial port
fuser -v /dev/ttyUSB0    # shows which process is holding it
```
