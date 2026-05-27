#!/usr/bin/env python3
"""Walking-test waypoint navigator.

Reads `waypoints.yaml` (lat/lon corners), subscribes to live MAVROS GPS +
compass, and prints turn-by-turn walking directions in a clear terminal UI.
Auto-advances to the next waypoint when within `arrival_radius_m`. Publishes
`/walking_test/status` (JSON string) so a rosbag captures the mission state
in step with the raw sensor topics.
"""

import json
import math
import sys
import time
from pathlib import Path

import yaml
import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import NavSatFix
from std_msgs.msg import Float64, String, UInt32


CLEAR = "\x1b[2J\x1b[H"
BOLD = "\x1b[1m"
DIM = "\x1b[2m"
RED = "\x1b[31m"
GREEN = "\x1b[32m"
YELLOW = "\x1b[33m"
CYAN = "\x1b[36m"
WHITE = "\x1b[97m"
RESET = "\x1b[0m"

COMPASS_16 = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
              "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]


def compass_label(bearing_deg: float) -> str:
    return COMPASS_16[int((bearing_deg + 11.25) / 22.5) % 16]


def haversine_distance(lat1, lon1, lat2, lon2) -> float:
    R = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlam / 2) ** 2
    return 2.0 * R * math.asin(math.sqrt(a))


def initial_bearing(lat1, lon1, lat2, lon2) -> float:
    """Forward azimuth from (lat1, lon1) to (lat2, lon2), compass deg (0=N, 90=E)."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlam = math.radians(lon2 - lon1)
    y = math.sin(dlam) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dlam)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


class WalkingNavigator(Node):
    def __init__(self, config: dict):
        super().__init__("walking_test")

        self.waypoints = config["waypoints"]
        self.arrival_radius = float(config.get("arrival_radius_m", 5.0))
        self.dwell_seconds = float(config.get("arrival_dwell_seconds", 4.0))
        self.loop = bool(config.get("loop", False))

        self.wp_idx = 0
        self.last_fix = None        # (lat, lon, alt, walltime)
        self.heading = None
        self.sats = None
        self.in_radius_count = 0
        self.state = "navigating"   # navigating | arrived | complete
        self.arrived_until = None
        self.start_walltime = time.time()

        sensor_qos = qos_profile_sensor_data
        self.create_subscription(NavSatFix, "/mavros/global_position/global",
                                 self._on_fix, sensor_qos)
        self.create_subscription(Float64, "/mavros/global_position/compass_hdg",
                                 self._on_hdg, sensor_qos)
        self.create_subscription(UInt32, "/mavros/global_position/raw/satellites",
                                 self._on_sats, sensor_qos)

        self.status_pub = self.create_publisher(String, "/walking_test/status", 10)
        self.create_timer(0.3, self._tick)

        # Banner the planned route once at startup (goes above the live UI).
        print(CLEAR + BOLD + CYAN + "Planned route:" + RESET)
        for i, wp in enumerate(self.waypoints):
            print(f"  {i+1}. {wp['name']:<20}  ({wp['lat']:.6f}, {wp['lon']:.6f})")
        print(DIM + f"arrival_radius_m = {self.arrival_radius}    "
                    f"dwell = {self.dwell_seconds}s    loop = {self.loop}" + RESET)
        time.sleep(2.0)

    # callbacks --------------------------------------------------------------
    def _on_fix(self, msg: NavSatFix):
        if msg.status.status < 0:
            return
        self.last_fix = (msg.latitude, msg.longitude, msg.altitude, time.time())

    def _on_hdg(self, msg: Float64):
        self.heading = float(msg.data)

    def _on_sats(self, msg: UInt32):
        self.sats = int(msg.data)

    # main tick --------------------------------------------------------------
    def _tick(self):
        if self.state == "complete":
            self._draw_complete()
            return

        if self.last_fix is None:
            self._draw_waiting("Waiting for GPS fix on /mavros/global_position/global ...")
            return
        if self.heading is None:
            self._draw_waiting("Waiting for compass heading on /mavros/global_position/compass_hdg ...")
            return

        lat, lon, _, fix_t = self.last_fix
        if time.time() - fix_t > 3.0:
            self._draw_waiting(f"GPS stale ({time.time()-fix_t:.1f}s since last fix)")
            return

        wp = self.waypoints[self.wp_idx]
        dist = haversine_distance(lat, lon, wp["lat"], wp["lon"])
        bearing = initial_bearing(lat, lon, wp["lat"], wp["lon"])
        relative = ((bearing - self.heading + 540.0) % 360.0) - 180.0

        if self.state == "navigating":
            if dist <= self.arrival_radius:
                self.in_radius_count += 1
            else:
                self.in_radius_count = 0

            if self.in_radius_count >= 3:
                self.state = "arrived"
                self.arrived_until = time.time() + self.dwell_seconds

            self._draw_nav(dist, bearing, relative)
            self._publish_status("navigating", dist, bearing, relative)
            return

        if self.state == "arrived":
            next_idx = ((self.wp_idx + 1) % len(self.waypoints)
                        if self.loop else self.wp_idx + 1)
            self._draw_arrived(next_idx)
            self._publish_status("arrived", dist, bearing, relative)
            if time.time() >= self.arrived_until:
                if next_idx >= len(self.waypoints) and not self.loop:
                    self.state = "complete"
                else:
                    self.wp_idx = next_idx
                    self.in_radius_count = 0
                    self.state = "navigating"

    # status publishing ------------------------------------------------------
    def _publish_status(self, state, dist, bearing, relative):
        wp = self.waypoints[self.wp_idx]
        lat, lon, _, _ = self.last_fix
        msg = String()
        msg.data = json.dumps({
            "wp_idx": self.wp_idx,
            "wp_name": wp["name"],
            "wp_lat": wp["lat"],
            "wp_lon": wp["lon"],
            "cur_lat": lat,
            "cur_lon": lon,
            "heading_deg": self.heading,
            "distance_m": round(dist, 2),
            "bearing_deg": round(bearing, 1),
            "relative_deg": round(relative, 1),
            "sats": self.sats,
            "state": state,
            "elapsed_s": round(time.time() - self.start_walltime, 2),
        })
        self.status_pub.publish(msg)

    # rendering --------------------------------------------------------------
    def _draw_waiting(self, msg):
        out = [CLEAR,
               BOLD + "=" * 64 + RESET,
               BOLD + "  WALKING TEST" + RESET,
               BOLD + "=" * 64 + RESET,
               "",
               YELLOW + "  " + msg + RESET,
               ""]
        print("\n".join(out), flush=True)

    def _draw_nav(self, dist, bearing, relative):
        wp = self.waypoints[self.wp_idx]
        if abs(relative) < 1:
            direction, mag = "STRAIGHT", 0.0
        elif relative > 0:
            direction, mag = "RIGHT", relative
        else:
            direction, mag = "LEFT", -relative
        dir_color = GREEN if mag < 15 else YELLOW if mag < 60 else RED
        elapsed = int(time.time() - self.start_walltime)
        m, s = divmod(elapsed, 60)

        out = [CLEAR,
               BOLD + CYAN + "=" * 64 + RESET,
               BOLD + CYAN + f"  WAYPOINT {self.wp_idx+1} / {len(self.waypoints)}: {wp['name']}" + RESET,
               BOLD + CYAN + "=" * 64 + RESET,
               "",
               BOLD + WHITE + f"  DISTANCE:  {dist:6.1f} m" + RESET,
               BOLD + WHITE + f"  BEARING:   {compass_label(bearing):<4} ({bearing:5.1f}° true)" + RESET,
               ""]
        if direction == "STRAIGHT":
            out.append(BOLD + GREEN + f"  >>>  WALK STRAIGHT AHEAD  <<<" + RESET)
        else:
            out.append(BOLD + dir_color + f"  >>>  Turn {direction} {mag:4.0f}°  <<<" + RESET)
        out.append(DIM + f"       (your heading: {self.heading:5.1f}°, "
                          f"arrive within {self.arrival_radius:.1f} m)" + RESET)
        out.append("")
        sats_str = f"{self.sats}" if self.sats is not None else "?"
        out.append(f"  GPS sats: {sats_str}     Elapsed: {m:02d}:{s:02d}     "
                   "Press Ctrl+C to stop")
        out.append(BOLD + CYAN + "=" * 64 + RESET)
        print("\n".join(out), flush=True)

    def _draw_arrived(self, next_idx):
        wp = self.waypoints[self.wp_idx]
        countdown = max(0, int(math.ceil(self.arrived_until - time.time())))
        out = [CLEAR,
               BOLD + GREEN + "=" * 64 + RESET,
               BOLD + GREEN + f"  *** ARRIVED at {wp['name']} ***" + RESET,
               BOLD + GREEN + "=" * 64 + RESET,
               ""]
        if next_idx < len(self.waypoints):
            nxt = self.waypoints[next_idx]
            lat, lon, _, _ = self.last_fix
            nb = initial_bearing(lat, lon, nxt["lat"], nxt["lon"])
            nd = haversine_distance(lat, lon, nxt["lat"], nxt["lon"])
            out += [BOLD + WHITE + f"  Turn to face: {compass_label(nb)}  ({nb:5.1f}° true)" + RESET,
                    "",
                    f"  Next waypoint: {nxt['name']}",
                    f"  Distance:      {nd:.1f} m",
                    "",
                    YELLOW + f"  Advancing in {countdown}..." + RESET]
        else:
            out.append(BOLD + GREEN + "  All waypoints reached - completing mission." + RESET)
        out.append(BOLD + GREEN + "=" * 64 + RESET)
        print("\n".join(out), flush=True)

    def _draw_complete(self):
        elapsed = int(time.time() - self.start_walltime)
        m, s = divmod(elapsed, 60)
        out = [CLEAR,
               BOLD + GREEN + "=" * 64 + RESET,
               BOLD + GREEN + "  *** MISSION COMPLETE ***" + RESET,
               BOLD + GREEN + "=" * 64 + RESET,
               "",
               f"  Waypoints reached: {len(self.waypoints)} / {len(self.waypoints)}",
               f"  Total time:        {m:02d}:{s:02d}",
               "",
               DIM + "  Stop the rosbag (Ctrl+C in that terminal), then run:" + RESET,
               DIM + "    python3 /home/mantis/loc/visualize_walk.py <bag-dir>" + RESET,
               "",
               YELLOW + "  Press Ctrl+C to exit." + RESET,
               BOLD + GREEN + "=" * 64 + RESET]
        print("\n".join(out), flush=True)
        msg = String()
        msg.data = json.dumps({"state": "complete", "elapsed_s": elapsed})
        self.status_pub.publish(msg)


def main():
    cfg_path = Path(__file__).resolve().parent / "waypoints.yaml"
    if len(sys.argv) > 1:
        cfg_path = Path(sys.argv[1])
    if not cfg_path.exists():
        print(f"ERROR: waypoints file not found: {cfg_path}", file=sys.stderr)
        sys.exit(1)
    cfg = yaml.safe_load(cfg_path.read_text())
    if not cfg.get("waypoints"):
        print("ERROR: waypoints.yaml has no 'waypoints' list", file=sys.stderr)
        sys.exit(1)

    rclpy.init()
    node = WalkingNavigator(cfg)
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        print(RESET + "\nStopped.\n", flush=True)
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
