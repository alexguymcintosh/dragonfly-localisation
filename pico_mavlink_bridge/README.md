# Pico MAVLink Bridge — Localisation Module

Transparent UART ↔ USB-CDC byte bridge running on a Raspberry Pi **Pico 2 (RP2350)**. Sits
between the Pixhawk 6C (TELEM2) and the host computer running mavros, so the
Pico + Pixhawk + battery form a self-contained localisation module that
exposes a single USB port to whatever mother computer plugs in.

```
   ┌───────────────────────────────────────┐         ┌──────────────┐
   │  LOCALISATION MODULE                  │  USB    │ MOTHER COMP  │
   │                                       │         │ (Ubuntu+ROS2)│
   │  ┌─────────┐  UART   ┌──────────┐     │ /ttyACM*│              │
   │  │ Pixhawk │ ◄─────► │  Pico    │ ────┼────────►│  mavros      │
   │  │  +GPS   │ MAVLink │ (bridge) │     │ MAVLink │  apm.launch  │
   │  │  +IMU   │ TELEM2  └──────────┘     │ stream  └──────────────┘
   │  │  +mag   │           115200 8N1     │
   │  │  EKF3   │                          │
   │  └─────────┘                          │
   │      ↑                                │
   │  [4S 1500 mAh battery via PM02 V3]    │
   └───────────────────────────────────────┘
```

The Pico does **no parsing** — it shovels raw bytes both ways. From mavros'
point of view, the Pico-USB endpoint is indistinguishable from the previous
Pixhawk-SERIAL7-USB endpoint, so `apm.launch` and every downstream topic
stay the same.

## Information flow

| Link | Direction | Content | Rate |
|---|---|---|---|
| Pixhawk TELEM2 → Pico → host | FC → host | MAVLink2: `HEARTBEAT`, `GLOBAL_POSITION_INT` (lat/lon/alt + hdg), `ATTITUDE` (roll/pitch/yaw), `GPS_RAW_INT`, `SYS_STATUS`, params on request | 10 Hz pos, 50 Hz attitude/IMU, others lower |
| host → Pico → Pixhawk TELEM2 | host → FC | MAVLink2: `HEARTBEAT` (mavros), `PARAM_REQUEST_LIST` on connect, `COMMAND_LONG` (`set_message_interval`) as needed | low |

Pure localisation: the only payload topics the host needs are
`/mavros/global_position/global` (NavSatFix, **position**) and
`/mavros/global_position/compass_hdg` (Float64, **direction**). Everything
else in the stream is overhead — heartbeats to keep the link alive and
params so mavros knows the FC capabilities.

## Wiring — Pixhawk TELEM2 → Pico

Pixhawk 6C TELEM2 is the DF13/JST-GH 6-pin port labelled TELEM2.

| TELEM2 pin | Signal | → | Pico physical pin | Pico signal |
|---|---|---|---|---|
| 1 | VCC 5 V | — | (open) | leave disconnected — Pico runs from USB |
| 2 | TX (FC → Pico) | → | **pin 2** | GP1 / UART0 RX |
| 3 | RX (Pico → FC) | ← | **pin 1** | GP0 / UART0 TX |
| 4 | CTS | — | (open) | unused |
| 5 | RTS | — | (open) | unused |
| 6 | GND | → | **pin 3** (or 38) | GND |

Both sides are 3.3 V logic — no level shifter.

**Cross-over rule:** FC TX → Pico RX, FC RX → Pico TX. If you see no
data flow, swap GP0/GP1 first.

### Pico physical pin reference

The Pico has 40 pins. Relevant ones for this build:

| Pico physical pin | Function used |
|---|---|
| 1 | GP0 / UART0 TX → TELEM2 pin 3 |
| 2 | GP1 / UART0 RX ← TELEM2 pin 2 |
| 3 | GND → TELEM2 pin 6 |
| 40 | VBUS (5 V from USB) — not used here |

## Pixhawk parameter changes

Your current `mav.parm` has TELEM2 set up for RC input with inverted RX.
Override in QGroundControl → Vehicle Setup → Parameters (search by name,
write each, then reboot the FC once at the end):

| Parameter | Current | Set to | Why |
|---|---|---|---|
| `SERIAL2_PROTOCOL` | 23 (RCIN) | **2** | MAVLink2 |
| `SERIAL2_BAUD` | 115 | **115** | 115200 — already correct |
| `SERIAL2_OPTIONS` | 128 (INVERT_RX) | **0** | standard non-inverted UART |
| `BRD_SER2_RTSCTS` | 2 (auto) | **0** | no flow control (only TX/RX/GND wired) |
| `SR2_POSITION` | 4 | **10** | GLOBAL_POSITION_INT at 10 Hz (matches mavros expectation) |
| `SR2_EXTRA1` | 4 | **10** | ATTITUDE at 10 Hz |
| `SR2_EXTRA2` | 4 | **10** | VFR_HUD at 10 Hz |
| `SR2_EXT_STAT` | 4 | **4** | GPS_RAW_INT / SYS_STATUS — 4 Hz is fine |
| `SR2_RAW_SENS` | 4 | **10** | IMU samples — bump to match the previous USB2 setup |

Reboot the FC after writing (Vehicle Setup → Parameters → Tools → Reboot
Vehicle, or pull battery + USB). Stream-rate params persist in flash once
written so this is a one-time setup.

## Flashing the Pico

1. Unplug the Pico USB.
2. Hold the **BOOTSEL** button on the Pico.
3. Plug the USB cable back in while still holding BOOTSEL.
4. Release BOOTSEL — the Pico mounts as a USB mass-storage device named
   `RPI-RP2`.
5. Copy the UF2 onto it (Pico 2's drive label is `RP2350`, original Pico is `RPI-RP2`):
   ```bash
   cp /home/mantis/loc/pico_mavlink_bridge/build/pico_mavlink_bridge.uf2 \
      /media/$USER/RP2350/
   ```
6. The Pico auto-reboots into the new firmware. The onboard LED should
   blink at 1 Hz (500 ms on, 500 ms off).
7. Confirm the Pico re-enumerates as a USB CDC device:
   ```bash
   ls -l /dev/serial/by-id/usb-Raspberry_Pi_Pico_*
   ```

If the BOOTSEL button is hard to reach behind the wiring, hold it before
the next replug and the firmware is overwritten in seconds — there is no
risk of bricking.

## Building the firmware

```bash
cd /home/mantis/loc/pico_mavlink_bridge
mkdir -p build && cd build
PICO_SDK_PATH=/home/mantis/pico-sdk cmake -DPICO_BOARD=pico2 ..
make -j$(nproc)
# UF2 produced at: build/pico_mavlink_bridge.uf2
```

## Running mavros against the Pico endpoint

Once the Pico is flashed and wired, the Pico's USB-CDC enumerates at a
stable by-id link. Replace the previous `/dev/ttyACM3` line in the runbook
with this:

```bash
source /opt/ros/jazzy/setup.bash
ros2 launch mavros apm.launch \
  fcu_url:=/dev/serial/by-id/usb-Raspberry_Pi_Pico_D453CDB057D9D414-if00:115200
```

(Using `/dev/serial/by-id/...` instead of `/dev/ttyACM0` makes the launch
survive reboots and Pixhawk replug — the ACM numbering is order-dependent,
the by-id link is not.)

Everything downstream — `walk_to_waypoints.py`, the rosbag, the analysis
scripts — is unchanged because the MAVROS topics are unchanged.

## What changes from the previous setup

| Thing | Before | After |
|---|---|---|
| Pixhawk USB cable | plugged into laptop | optional (QGC only) |
| MAVROS endpoint | `/dev/ttyACM3` (Pixhawk SERIAL7) | `/dev/serial/by-id/usb-Raspberry_Pi_Pico_...-if00` |
| MAVLink-carrying serial port on FC | SERIAL7 (USB2) | SERIAL2 (TELEM2 wires) |
| Stream-rate params used | `SR3_*` | `SR2_*` |
| ROS topics, QoS, rates | — | unchanged |

QGroundControl on the Pixhawk's primary USB endpoint (SERIAL0) still works
exactly as before and can run concurrently with mavros.
