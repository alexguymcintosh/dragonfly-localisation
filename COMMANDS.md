# Walking-Test Mission Commands

End-to-end runbook for the GPS waypoint walking test. Defined waypoints walk
the 4 corners of your block (configured in `waypoints.yaml`). The mission flow:
the laptop tells you bearing+distance to the current corner, you walk there,
on arrival it tells you which compass direction to face for the next corner,
auto-advance, repeat.

All commands assume working directory `/home/mantis/loc`.

---

## 0. Once-per-session setup

```bash
cd /home/mantis/loc
source /opt/ros/jazzy/setup.bash
```

Plug the Pixhawk USB into the laptop. Two `/dev/ttyACM*` devices should appear
(same Pixhawk exposes two USB-CDC endpoints). Confirm:

```bash
ls /dev/ttyACM*
udevadm info --name=/dev/ttyACM3 --query=property | grep Pixhawk
```

You should see `ID_MODEL=Pixhawk6C` on at least one of them. We use the
**second** endpoint (`/dev/ttyACM3` on this machine — SERIAL7 in ArduPilot)
so QGroundControl on `/dev/ttyACM0` (SERIAL0) can run concurrently. If your
laptop reorders the ACM numbering after a reboot, verify with `udevadm` and
substitute below.

---

## 1. Terminal A — start mavros (and leave it running)

**First, make sure no other mavros is already running** — if there is, you'll
get a `Device or resource busy` retry loop and the second instance's logs
will spam wherever you launch it:

```bash
pgrep -af mavros_node    # should print nothing
# if it prints a PID, kill it:  kill <PID>
```

Then launch one fresh instance. Two equally good options:

**(a) Foreground in this terminal (recommended — easy to Ctrl+C, easy to read logs):**
```bash
source /opt/ros/jazzy/setup.bash
ros2 launch mavros apm.launch fcu_url:=/dev/ttyACM3:115200
```

**(b) Background with log to file (so terminal stays free):**
```bash
setsid bash -c 'source /opt/ros/jazzy/setup.bash && \
  exec ros2 launch mavros apm.launch fcu_url:=/dev/ttyACM3:115200 \
  > /tmp/mavros.log 2>&1' < /dev/null > /dev/null 2>&1 &
disown
# follow:  tail -f /tmp/mavros.log
```
Use `setsid` (not plain `nohup &`) — `ros2 launch` touches the controlling
terminal during startup and will SIGTTOU itself if backgrounded with `nohup`.

**One-shot reset (kill any running mavros and start fresh):**
```bash
pkill -f mavros_node ; sleep 2
setsid bash -c 'source /opt/ros/jazzy/setup.bash && \
  exec ros2 launch mavros apm.launch fcu_url:=/dev/ttyACM3:115200 \
  > /tmp/mavros.log 2>&1' < /dev/null > /dev/null 2>&1 &
disown
sleep 6 && grep -E "Got HEARTBEAT|ERROR" /tmp/mavros.log | tail -3
```

Either way, wait for `CON: Got HEARTBEAT, connected. FCU: ArduPilot` (~2 s)
before continuing. **Do not start mavros twice — they'll fight for the port.**

**Stream rates** are already persisted in the FC (params `SR3_*` written to
flash), so no extra runtime setup is needed.

---

## 2. Terminal B — verify the bridge is actually streaming (~30 s)

In a new terminal:

```bash
cd /home/mantis/loc
source /opt/ros/jazzy/setup.bash

# 1) FC connection good?
ros2 topic echo --once /mavros/state | grep -E "connected|mode"

# 2) GPS fix and sat count (need a fix before walking)
ros2 topic echo --once --qos-reliability best_effort /mavros/global_position/raw/satellites
ros2 topic echo --once --qos-reliability best_effort /mavros/global_position/raw/fix \
  | grep -E "status:|latitude|longitude"

# 3) EKF-fused position and heading should both be live
ros2 topic hz --window 8 /mavros/global_position/global       # expect ~10 Hz
ros2 topic hz --window 8 /mavros/global_position/compass_hdg  # expect ~10 Hz
```

You want: `status: 0` (FIX), sats ≥ 6 (preferably ≥ 10), and both `hz` checks
showing ~10 Hz. **If you don't have a fix yet, take the Pixhawk outside for
30–60 s and re-check.** Indoors near a window usually works too — you saw
17 sats earlier.

---

## 3. Terminal C — start the walking UI

In a third terminal:

```bash
cd /home/mantis/loc
source /opt/ros/jazzy/setup.bash
python3 walk_to_waypoints.py
```

The screen shows:

- Top: which waypoint (e.g. `WAYPOINT 1 / 4: P1 SW corner`)
- Big: `DISTANCE: 47.3 m` and `BEARING: NNW (347.5° true)`
- Highlighted: `>>> Turn RIGHT 30° <<<` (color-coded — green if straight, red if hard turn)
- Bottom: current heading, sat count, elapsed time

On arrival (within `arrival_radius_m` = 5 m, for 3 consecutive readings):

```
*** ARRIVED at P1 SW corner ***
  Turn to face: NE  (45.0° true)
  Next waypoint: P2 SE corner
  Distance:      106.1 m
  Advancing in 4...
```

After the `arrival_dwell_seconds` countdown (4 s) it switches to the next
waypoint automatically. After the last waypoint: `*** MISSION COMPLETE ***`.

To edit the route, distances, or behaviour, open `waypoints.yaml`. You can
flip `loop: true` to keep cycling the 4 corners.

---

## 4. Terminal D — start the rosbag (do this just before you walk)

In a fourth terminal (keep the walking UI visible elsewhere):

```bash
cd /home/mantis/loc/bags
source /opt/ros/jazzy/setup.bash

ros2 bag record -o walk_$(date +%Y%m%d_%H%M%S) \
  /mavros/state \
  /mavros/global_position/global \
  /mavros/global_position/raw/fix \
  /mavros/global_position/raw/satellites \
  /mavros/global_position/compass_hdg \
  /mavros/local_position/pose \
  /mavros/local_position/odom \
  /mavros/imu/data \
  /walking_test/status \
  /tf /tf_static
```

`-o walk_<timestamp>` creates a directory like `walk_20260527_143012/`
containing `walk_20260527_143012_0.mcap` + `metadata.yaml`.

Expect ~5–10 MB per minute of walking.

---

## 5. Do the walk

1. Stand somewhere with sky view; carry the laptop (backpack) and the
   Pixhawk (in your hand or on top of the bag — keep it un-occluded).
2. Glance at the walking-UI screen periodically. Walk in the indicated
   direction.
3. On `ARRIVED`, turn to the indicated compass direction and start walking.
4. Repeat for all 4 corners. The UI will show `MISSION COMPLETE` when done.

---

## 6. Stop and analyse

Order doesn't strictly matter but suggested:

1. **Terminal C (walking UI):** `Ctrl+C` — it'll print `Stopped.`
2. **Terminal D (rosbag):** `Ctrl+C` — bag is flushed and closed
3. **Terminal A (mavros):** leave running OR `Ctrl+C` if done

Then visualise the bag:

```bash
cd /home/mantis/loc
python3 visualize_walk.py /home/mantis/loc/bags/walk_<timestamp>
```

Output:
- Console: walk summary (duration, path length, avg speed, sats summary,
  per-waypoint time-to-arrive and closest approach).
- PNG: `/home/mantis/loc/bags/walk_<timestamp>.png` — your walked path
  (coloured by elapsed time) overlaid on the planned route, with
  arrival markers and arrival circles around each waypoint.

To open the PNG: `xdg-open /home/mantis/loc/bags/walk_<timestamp>.png`

---

## Troubleshooting

**"Waiting for GPS fix" never goes away**
- Take the Pixhawk outside or near a clear-sky window for 60 s.
- `ros2 topic echo --once --qos-reliability best_effort /mavros/global_position/raw/fix`
  — if `status: -1`, the FC isn't reporting a fix yet.
- `ros2 topic echo --once --qos-reliability best_effort /mavros/global_position/raw/satellites`
  — need ≥ 6.

**"Waiting for compass heading"**
- This topic depends on `MESSAGE_ID 33` (GLOBAL_POSITION_INT). If silent,
  re-run the `ros2 topic hz /mavros/global_position/compass_hdg` check.
- Worst case, re-send the message intervals manually:
  ```bash
  ros2 service call /mavros/set_message_interval mavros_msgs/srv/MessageInterval \
    "{message_id: 33, message_rate: 10}"
  ```

**Direction feels 180° wrong**
- Check `AHRS_ORIENTATION` in ArduPilot (should be `0` for default mounting).
- The `compass_hdg` is true north + magnetic declination handled by ArduPilot.
  If you suspect the compass is rotated, redo compass calibration in QGC.

**Walking UI shows no `>>> Turn ... <<<` line**
- Your heading is within 1° of bearing — it's showing `WALK STRAIGHT AHEAD`.

**Waypoint auto-advances when you're not there**
- GPS jumped. The arrival hysteresis is only 3 consecutive in-radius
  readings (~0.3 s at 10 Hz). Increase to require longer settling, or shrink
  `arrival_radius_m`. Edit `walk_to_waypoints.py` line with
  `if self.in_radius_count >= 3:` if you want more hysteresis.

**Bag is empty / `No GPS fixes in bag`**
- Recorder wasn't subscribed when MAVROS first emitted. Restart the
  recorder, then echo `/mavros/global_position/global` once to confirm
  publishers are alive before walking.

---

## Files (all in /home/mantis/loc)

| File | What |
|---|---|
| `waypoints.yaml` | 4 corners, arrival radius, dwell, loop flag |
| `walk_to_waypoints.py` | The walking-UI node — reads GPS+compass, prints directions, publishes `/walking_test/status` |
| `visualize_walk.py` | Post-walk bag → PNG + console stats |
| `bags/` | `ros2 bag record` output goes here |
| `COMMANDS.md` | This file |
| `mav.parm` | Snapshot of FC params (reference) |
