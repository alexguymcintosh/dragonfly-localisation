# GPS Module Test — Step by Step

Goal: confirm the GY-GPSV3 NEO-N9N is alive by flashing the ag-rover firmware to the Pico 2
and watching NMEA sentences print over USB serial.

---

## WIRING (do this before anything else)

Disconnect GPS from Pixhawk first.

| Pico 2 Pin | Label | → GPS Module |
|---|---|---|
| Pin 36 | 3V3 OUT | VCC |
| Pin 38 | GND | GND |
| Pin 2 | GP1 (UART0 RX) | TX |

Leave GPS RX unconnected — not needed for this test.

---

## STEP 1 — Disconnect Pixhawk from USB

Unplug the Pixhawk USB cable from your laptop.

---

## STEP 2 — Put Pico into bootloader mode

1. Hold down the **BOOTSEL** button on the Pico 2
2. While holding it, plug the Pico USB into your laptop
3. Release BOOTSEL

---

## STEP 3 — Confirm the Pico drive appeared

Run this:

```bash
ls /media/mantis/
```

You should see a drive called **RP2350**. If you see nothing, repeat Step 2.

---

## STEP 4 — Flash the firmware

```bash
cp /home/mantis/ag-rover-prototype/pico_firmware/build/imu.uf2 /media/mantis/RP2350/
```

The drive will disappear automatically — that means it worked and the Pico rebooted.

---

## STEP 5 — Confirm Pico serial port appeared

```bash
ls /dev/ttyACM*
```

You should now see `/dev/ttyACM0` (just the Pico, Pixhawk is unplugged).

---

## STEP 6 — Open serial monitor

```bash
screen /dev/ttyACM0 115200
```

---

## STEP 7 — Hold GPS near a window

The firmware will print:

```
Trying 9600 baud...
Trying 38400 baud...
...
GPS: locked baud 57600. Streaming.
GPS: $GNRMC,...
GPS: $GNGGA,...
```

Wait up to 60 seconds for baud detection + first NMEA sentences.

**If you see `GPS: $GN...` lines → GPS module is alive and working.**

**If you see `GPS: no NMEA '$' at any candidate rate. Retrying...` forever → GPS is dead (likely from reversed polarity).**

---

## STEP 8 — Exit screen

Press `Ctrl+A` then `K` then `Y`.

---

## Notes

- IMU will print a wake failed message — ignore it, the MPU-6050 is not connected
- You do not need a GPS fix to confirm the module is alive — just seeing NMEA sentences is enough
- To get a fix (sats > 4), hold GPS near an open window or take outside
