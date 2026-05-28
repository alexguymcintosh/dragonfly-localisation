# Pico MAVLink Bridge — Setup & Run Commands

End-to-end runbook for the localisation-module bridge:
**Pixhawk TELEM1 (UART) → Pico (USB-CDC) → host (mavros)**.

All commands assume working directory `/home/mantis/loc/pico_mavlink_bridge`.

---

## 0. Once-only — build the firmware

> **Board:** this project is built for the **Raspberry Pi Pico 2 (RP2350)**.
> If you ever swap to an original Pico (RP2040), change `-DPICO_BOARD=pico2`
> to `-DPICO_BOARD=pico` and wipe the build directory (the toolchain target
> differs between Cortex-M33 and Cortex-M0+).

```bash
cd /home/mantis/loc/pico_mavlink_bridge
rm -rf build && mkdir build && cd build
PICO_SDK_PATH=/home/mantis/pico-sdk cmake -DPICO_BOARD=pico2 ..
make -j$(nproc)
```

Artefact: `build/pico_mavlink_bridge.uf2` (~57 KB).

You should not need to rebuild unless `main.c` or `CMakeLists.txt` change.

---

## 1. Flash the Pico (BOOTSEL)

### 1a. Put the Pico into BOOTSEL mode

1. Unplug the Pico USB cable from the laptop.
2. **Hold the BOOTSEL button** on the Pico (the white button on top).
3. Plug the USB cable back in **while still holding BOOTSEL**.
4. Release BOOTSEL ~1 s after the cable is seated.

### 1b. Validate BOOTSEL mode BEFORE attempting to copy

The Pico in BOOTSEL mode looks completely different from the Pico
running firmware — different USB IDs, different `/dev` entries.

| Board | BOOTSEL VID:PID | BOOTSEL drive label | Normal-fw VID:PID |
|---|---|---|---|
| Pico 2 (RP2350) — **this build** | `2e8a:000f` Raspberry Pi RP2350 Boot | `RP2350` → `/media/$USER/RP2350` | `2e8a:0009` (set by our CDC firmware) |
| original Pico (RP2040) | `2e8a:0003` Raspberry Pi RP2 Boot | `RPI-RP2` → `/media/$USER/RPI-RP2` | `2e8a:0009` |

Run all three checks to confirm BOOTSEL is live (paths shown for RP2350
— substitute `RPI-RP2` if you ever use an RP2040 board):

```bash
# (i) USB IDs — BOOTSEL is 2e8a:000f on Pico 2 / 2e8a:0003 on Pico
lsusb | grep 2e8a
# expected on Pico 2 BOOTSEL:  ID 2e8a:000f Raspberry Pi RP2350 Boot

# (ii) Block device — BOOTSEL appears as a ~128 MB USB drive
lsblk -o NAME,SIZE,LABEL,MOUNTPOINT | grep -iE "RP2350|RPI-RP2|sd[a-z]"
# expected:  sdX1   128M  RP2350   /media/mantis/RP2350

# (iii) Mount point exists and is a DIRECTORY (this is what the cp wants)
ls -ld /media/$USER/RP2350/
# expected:  drwx------ ... /media/mantis/RP2350/
# if you see "No such file or directory" or "Not a directory",
# the Pico is NOT in BOOTSEL — re-do step 1a.
```

If `lsusb` shows `2e8a:0009` instead of the boot VID, the Pico booted
into its existing firmware — you didn't hold BOOTSEL long enough or
released it too soon. Unplug and retry.

If `lsusb` shows the boot VID but the mount directory doesn't exist,
Ubuntu didn't auto-mount it. Mount it manually:

```bash
# Find the device node (e.g. /dev/sda1) and mount it:
sudo mkdir -p /media/$USER/RP2350
sudo mount -o uid=$(id -u),gid=$(id -g) \
  $(lsblk -lnp -o NAME,LABEL | awk '$2=="RP2350"{print $1}') \
  /media/$USER/RP2350
ls /media/$USER/RP2350/
# expected:  INDEX.HTM  INFO_UF2.TXT
```

### 1c. Copy the UF2

Only run this once the validation above shows a mounted directory:

```bash
cp /home/mantis/loc/pico_mavlink_bridge/build/pico_mavlink_bridge.uf2 \
   /media/$USER/RP2350/
sync
```

The Pico will reboot automatically the instant the UF2 finishes writing
— the `RPI-RP2` drive will vanish from `lsblk` and a new `ttyACM*`
device will appear within a couple of seconds. That's expected; the
`cp` may print a benign "Input/output error" *after* a successful copy
because the device disappeared under it. As long as the new ttyACM
shows up, the flash succeeded.

### 1d. Confirm the new firmware is running

```bash
# LED check — physically look at the Pico, onboard LED should blink at
# 1 Hz (500 ms on, 500 ms off).

# USB ID is back to the CDC variant
lsusb | grep 2e8a
# expected:  ID 2e8a:0009 Raspberry Pi Pico
# (the firmware reports itself as "Pico" via the TinyUSB descriptor
#  even on RP2350 hardware — that is normal, the board is still a Pico 2)

# CDC serial device re-enumerated
ls -l /dev/serial/by-id/usb-Raspberry_Pi_Pico_*
# expected:
#   ...usb-Raspberry_Pi_Pico_D453CDB057D9D414-if00 -> ../../ttyACMx
```

If the LED is solid or dark, or no `Raspberry_Pi_Pico` link appears,
the flash didn't take — go back to 1a and retry.

The `/dev/serial/by-id/...` link is stable across reboots; the
`ttyACMx` number is not. Use the by-id link in every command below.

---

## 2. Wiring check (Pixhawk TELEM1 → Pico)

Three wires only — both 3.3 V logic, no level shifter.

| TELEM1 pin (DF13/JST-GH 6-pin) | Signal | Pico physical pin |
|---|---|---|
| **1** | VCC 5 V | leave open (Pico is USB-powered) |
| **2** | TX (FC → Pico) | **pin 2** — GP1 / UART0 RX |
| **3** | RX (Pico → FC) | **pin 1** — GP0 / UART0 TX |
| **4** | CTS | leave open |
| **5** | RTS | leave open |
| **6** | GND | **pin 3** (or **38**) — any GND pin |

If you ever see no data flowing in section 5 below, the first thing to
swap is GP0 ↔ GP1 — the cross-over rule (FC TX → Pico RX) is the most
common wiring mistake.

---

## 3. Pixhawk parameters (one-time, persist in flash)

Plug the Pixhawk's primary USB cable into the laptop (separate from the
Pico — QGC connects to that USB endpoint, not via the Pico).

Open QGroundControl → connect → **Vehicle Setup → Parameters**. Search
for each name, type the new value, **Force Save**. After the last one
choose **Tools → Reboot Vehicle** (or pull power + USB) so they take
effect.

| Param | Current | Set to | Why |
|---|---|---|---|
| `SERIAL1_PROTOCOL` | 2 | **2** | MAVLink2 — already correct, just verify |
| `SERIAL1_BAUD` | 57 | **115** | 115200 baud (Pico bridge runs 115200) |
| `BRD_SER1_RTSCTS` | 2 | **0** | no flow control — Pico only has TX/RX/GND |
| `SR1_POSITION` | 0 | **10** | GLOBAL_POSITION_INT @ 10 Hz |
| `SR1_EXTRA1` | 0 | **10** | ATTITUDE @ 10 Hz |
| `SR1_EXTRA2` | 0 | **10** | VFR_HUD @ 10 Hz |
| `SR1_RAW_SENS` | 0 | **10** | IMU samples @ 10 Hz |

Optional extras:
- `SR1_EXT_STAT = 4` if you want `/mavros/global_position/raw/fix`
  and sat counts (4 Hz is plenty).

After the FC reboots, the new SERIAL1 settings are live. From this point
on, the SiK radio cannot share TELEM1 — TELEM1 is the Pico's port.

---

## 4. Verify the Pixhawk ↔ Pico link is alive

Both USB cables (Pixhawk SERIAL0 + Pico) should be plugged into the
laptop. Three independent USB devices should be visible:

```bash
ls -l /dev/serial/by-id/
# expected:
#   usb-Holybro_Pixhawk6C_46002D000351333531373234-if00 -> ../../ttyACMx   (QGC)
#   usb-Holybro_Pixhawk6C_46002D000351333531373234-if02 -> ../../ttyACMy   (SERIAL7, unused now)
#   usb-Raspberry_Pi_Pico_D453CDB057D9D414-if00         -> ../../ttyACMz   (bridge)
```

Quick byte-level sanity check — you should see MAVLink v2 framing bytes
(`0xFD` is the v2 start-of-frame) streaming out of the Pico's USB:

```bash
# Read 256 bytes off the Pico's CDC, hexdump them.
timeout 3 cat /dev/serial/by-id/usb-Raspberry_Pi_Pico_D453CDB057D9D414-if00 \
  | head -c 256 | xxd | head -8
```

Expect: lots of `fd` bytes, no `IMU: read failed` strings (that's the old
firmware — if you see it, the flash didn't take, redo section 1).

---

## 5. Launch mavros against the Pico endpoint

```bash
source /opt/ros/jazzy/setup.bash
ros2 launch mavros apm.launch \
  fcu_url:=/dev/serial/by-id/usb-Raspberry_Pi_Pico_D453CDB057D9D414-if00:115200
```

Wait ~2 s. You want to see `CON: Got HEARTBEAT, connected. FCU: ArduPilot`
in the mavros logs. If you don't get HEARTBEAT within ~10 s, jump to
**Troubleshooting** below.

**Then, in a second terminal, bump the message rates to 10 Hz:**

```bash
/home/mantis/loc/pico_mavlink_bridge/set_rates.sh
```

The FC's `SR1_*` stream-rate params don't reliably persist on this build,
so we use mavros's runtime `set_message_interval` instead. Run this once
each time you launch mavros (it's idempotent and fast).

In a second terminal verify the topics are streaming at the expected
rates (same checks as the previous setup — `walk_to_waypoints.py` and
the rosbag scripts work unchanged):

```bash
source /opt/ros/jazzy/setup.bash

# FC connection good?
ros2 topic echo --once /mavros/state | grep -E "connected|mode"

# Position + heading at 10 Hz
ros2 topic hz --window 20 /mavros/global_position/global       # expect ~10 Hz
ros2 topic hz --window 20 /mavros/global_position/compass_hdg  # expect ~10 Hz
```

---

## 6. Run the walking test (unchanged)

The bridge is transparent to mavros — every downstream command from
`/home/mantis/loc/COMMANDS.md` works as-is. Short version:

```bash
# Terminal B — start bag (in /home/mantis/loc/bags)
ros2 bag record -o walk_$(date +%Y%m%d_%H%M%S) \
  /mavros/state \
  /mavros/global_position/global \
  /mavros/global_position/raw/fix \
  /mavros/global_position/compass_hdg \
  /mavros/local_position/pose \
  /mavros/imu/data \
  /walking_test/status

# Terminal C — start UI
cd /home/mantis/loc && python3 walk_to_waypoints.py
```

---

## Troubleshooting

**Pico LED solid / dark, not blinking**
- Firmware didn't take. Re-do section 1 (BOOTSEL re-flash). Confirm the
  copy completed with `sync` before unplugging.

**`ls /dev/serial/by-id/` doesn't show the Pico**
- Pico is in BOOTSEL/mass-storage mode, not CDC mode. Press the RUN
  button (if your Pico board has one) or replug without holding BOOTSEL.

**mavros never prints `Got HEARTBEAT`**
- Wiring: swap GP0 ↔ GP1. The cross-over rule (FC TX → Pico RX) is the
  most common mistake.
- Baud: confirm `SERIAL1_BAUD = 115` in QGC. If it's still 57 the Pico
  is decoding gibberish.
- Protocol: confirm `SERIAL1_PROTOCOL = 2`. If anything else (especially
  23 = RCIN, the TELEM2 default), nothing MAVLink-shaped will arrive.
- Flow control: confirm `BRD_SER1_RTSCTS = 0`. With it at 2 and no CTS
  wired, the FC may stall waiting for CTS to assert.
- Reboot the FC after any param change — `Force Save` only writes flash,
  it doesn't apply the new serial config until reboot.

**`ros2 topic hz` shows 0 Hz on `/mavros/global_position/global`**
- The stream-rate params didn't take. Re-check `SR1_POSITION = 10` and
  `SR1_EXTRA1 = 10`, then reboot FC.
- Workaround (runtime, doesn't persist):
  ```bash
  ros2 service call /mavros/set_message_interval \
    mavros_msgs/srv/MessageInterval "{message_id: 33, message_rate: 10}"
  ```

**Garbled / partial bytes on the Pico CDC**
- Baud mismatch between Pico firmware (115200, hardcoded in `main.c`)
  and FC SERIAL1_BAUD. Both must be 115200.
- If you really want to run faster (e.g. 921600 for higher IMU rates),
  change `UART_BAUD` in `main.c`, rebuild + reflash, and set
  `SERIAL1_BAUD = 921` to match. 115200 is plenty for 10 Hz position +
  10 Hz attitude + IMU; only bump it if you want the full 50 Hz
  attitude stream.

**Pico CDC shows old `IMU: read failed` lines**
- Old firmware is still on it. Re-do section 1.

**QGC and mavros conflict**
- They can run concurrently on different USB endpoints. QGC on the
  Pixhawk's primary USB (`usb-Holybro_Pixhawk6C_..._-if00`), mavros on
  the Pico's USB. If QGC tries to grab the Pico's port, point it
  explicitly at the Pixhawk endpoint in QGC's *Application Settings →
  Comm Links*.

---

## Files in this directory

| File | What |
|---|---|
| `main.c` | Bridge firmware — UART0 ⇄ USB-CDC byte pump, 1 Hz LED blink |
| `CMakeLists.txt` | pico-sdk build config; disables stdio_uart so UART0 is payload-only |
| `pico_sdk_import.cmake` | Points the build at `/home/mantis/pico-sdk` |
| `build/pico_mavlink_bridge.uf2` | Flash image — drag onto `RPI-RP2` |
| `README.md` | Architecture overview, info-flow table, wiring |
| `COMMANDS.md` | This file — step-by-step runbook |
