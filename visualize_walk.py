#!/usr/bin/env python3
"""Visualize a walking-test rosbag.

Reads `/mavros/global_position/global` (fused EKF lat/lon), the per-tick
`/walking_test/status` JSON events, and `/mavros/global_position/raw/satellites`
from the given bag directory. Plots the walked path overlaid on the planned
waypoints (with arrival circles), and prints per-waypoint timing/closest-
approach stats.

Usage:
  python3 visualize_walk.py <bag_directory>
  python3 visualize_walk.py <bag_directory> <waypoints.yaml>
"""

import json
import math
import sys
from pathlib import Path

import numpy as np
import yaml
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Circle

import rosbag2_py
from rclpy.serialization import deserialize_message
from rosidl_runtime_py.utilities import get_message


def open_bag(bag_dir: Path):
    meta_path = bag_dir / "metadata.yaml"
    if not meta_path.exists():
        sys.exit(f"ERROR: no metadata.yaml in {bag_dir} (not a rosbag2 directory).")
    meta = yaml.safe_load(meta_path.read_text())
    info = meta["rosbag2_bagfile_information"]
    storage_id = info.get("storage_identifier", "mcap")
    reader = rosbag2_py.SequentialReader()
    reader.open(
        rosbag2_py.StorageOptions(uri=str(bag_dir), storage_id=storage_id),
        rosbag2_py.ConverterOptions("cdr", "cdr"),
    )
    return reader


def read_topics(bag_dir: Path, wanted: set):
    reader = open_bag(bag_dir)
    type_map = {t.name: t.type for t in reader.get_all_topics_and_types()}
    out = {t: [] for t in wanted if t in type_map}
    while reader.has_next():
        topic, data, t_ns = reader.read_next()
        if topic not in out:
            continue
        msg = deserialize_message(data, get_message(type_map[topic]))
        out[topic].append((t_ns, msg))
    return out, type_map


def haversine(lat1, lon1, lat2, lon2):
    R = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dlam/2)**2
    return 2.0 * R * math.asin(math.sqrt(a))


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    bag_dir = Path(sys.argv[1]).resolve()
    wp_yaml = Path(sys.argv[2]) if len(sys.argv) >= 3 else Path("/home/mantis/loc/waypoints.yaml")

    cfg = yaml.safe_load(wp_yaml.read_text())
    waypoints = cfg["waypoints"]
    arrival_r = float(cfg.get("arrival_radius_m", 5.0))
    loop = bool(cfg.get("loop", False))

    wanted = {
        "/mavros/global_position/global",
        "/mavros/global_position/raw/fix",
        "/mavros/global_position/raw/satellites",
        "/walking_test/status",
    }
    msgs, type_map = read_topics(bag_dir, wanted)

    fixes = []  # (t_s, lat, lon)
    for t, m in msgs.get("/mavros/global_position/global", []):
        fixes.append((t * 1e-9, m.latitude, m.longitude))
    if not fixes:  # fall back to raw GPS
        for t, m in msgs.get("/mavros/global_position/raw/fix", []):
            if m.status.status >= 0:
                fixes.append((t * 1e-9, m.latitude, m.longitude))
    if not fixes:
        sys.exit("ERROR: no GPS fixes in bag.")

    fixes_arr = np.array(fixes, dtype=float)
    t0 = fixes_arr[0, 0]
    fixes_arr[:, 0] -= t0
    total_time = fixes_arr[-1, 0]

    seg = [haversine(fixes_arr[i-1, 1], fixes_arr[i-1, 2],
                     fixes_arr[i, 1], fixes_arr[i, 2])
           for i in range(1, len(fixes_arr))]
    total_path_m = sum(seg)
    avg_speed_mps = total_path_m / total_time if total_time > 0 else 0.0

    sats_list = [int(m.data) for _, m in msgs.get("/mavros/global_position/raw/satellites", [])]
    sat_summary = (f"avg {np.mean(sats_list):.1f}, min {min(sats_list)}, max {max(sats_list)}"
                   if sats_list else "no sat counts in bag")

    status_events = []
    for t, m in msgs.get("/walking_test/status", []):
        try:
            d = json.loads(m.data)
            d["_t"] = t * 1e-9
            status_events.append(d)
        except Exception:
            pass

    closest = {}
    arrived_at = {}
    started_nav = {}
    for ev in status_events:
        idx = ev.get("wp_idx")
        if idx is None:
            continue
        d = ev.get("distance_m")
        if d is not None and d < closest.get(idx, float("inf")):
            closest[idx] = d
        if idx not in started_nav and ev.get("state") == "navigating":
            started_nav[idx] = ev["_t"]
        if ev.get("state") == "arrived" and idx not in arrived_at:
            arrived_at[idx] = ev["_t"]

    print(f"\n=== WALK SUMMARY ===")
    print(f"Bag:           {bag_dir}")
    print(f"GPS fixes:     {len(fixes_arr)}")
    print(f"Duration:      {total_time:.1f} s   ({total_time/60:.1f} min)")
    print(f"Path length:   {total_path_m:.1f} m")
    print(f"Avg speed:     {avg_speed_mps:.2f} m/s   ({avg_speed_mps*3.6:.1f} km/h)")
    print(f"GPS sats:      {sat_summary}")
    print()
    print(f"=== PER-WAYPOINT ===")
    print(f"{'#':<3} {'name':<16} {'arrived':<8} {'time_to_arrive':<16} {'closest_approach':<18}")
    print(f"{'-'*3:<3} {'-'*16:<16} {'-'*8:<8} {'-'*16:<16} {'-'*18:<18}")
    for i, wp in enumerate(waypoints):
        was_arrived = i in arrived_at
        tta = (arrived_at[i] - started_nav.get(i, arrived_at[i])) if was_arrived else None
        cmin = closest.get(i, float("nan"))
        print(f"{i+1:<3} {wp['name']:<16} {'YES' if was_arrived else 'no':<8} "
              f"{(f'{tta:5.1f} s' if tta is not None else '-'):<16} "
              f"{cmin:5.2f} m{' (within radius)' if cmin <= arrival_r else ''}")

    # ---- plot in local flat projection ----
    cen_lat = float(np.mean([w["lat"] for w in waypoints]))
    cen_lon = float(np.mean([w["lon"] for w in waypoints]))
    m_per_deg_lat = 111_132.0
    m_per_deg_lon = 111_132.0 * math.cos(math.radians(cen_lat))

    def to_xy(lat, lon):
        return ((lon - cen_lon) * m_per_deg_lon, (lat - cen_lat) * m_per_deg_lat)

    fig, ax = plt.subplots(figsize=(12, 10))

    xs = (fixes_arr[:, 2] - cen_lon) * m_per_deg_lon
    ys = (fixes_arr[:, 1] - cen_lat) * m_per_deg_lat
    ts = fixes_arr[:, 0]
    sc = ax.scatter(xs, ys, c=ts, cmap="viridis", s=4, alpha=0.7, zorder=2,
                    label=f"walked path ({len(xs)} fixes)")
    cb = plt.colorbar(sc, ax=ax, fraction=0.035, pad=0.02)
    cb.set_label("time since bag start (s)")

    # planned route (dashed)
    pxs = [to_xy(w["lat"], w["lon"])[0] for w in waypoints]
    pys = [to_xy(w["lat"], w["lon"])[1] for w in waypoints]
    rxs = pxs + ([pxs[0]] if loop else [])
    rys = pys + ([pys[0]] if loop else [])
    ax.plot(rxs, rys, "--", color="crimson", alpha=0.7, lw=1.6, zorder=1,
            label="planned route")

    # waypoints + arrival circles
    for i, wp in enumerate(waypoints):
        wx, wy = to_xy(wp["lat"], wp["lon"])
        ax.plot(wx, wy, "o", color="crimson", markersize=11, zorder=4)
        ax.add_patch(Circle((wx, wy), arrival_r, fill=False,
                            edgecolor="crimson", linestyle=":", alpha=0.7, zorder=3))
        ax.annotate(f"{i+1}: {wp['name']}", (wx, wy),
                    textcoords="offset points", xytext=(10, 10),
                    fontsize=10, color="crimson", fontweight="bold")

    # arrival markers from status events
    for i, t in arrived_at.items():
        rel = t - t0
        if rel < ts[0] or rel > ts[-1]:
            continue
        idx = int(np.argmin(np.abs(ts - rel)))
        ax.plot(xs[idx], ys[idx], "*", color="gold", markersize=20,
                markeredgecolor="black", markeredgewidth=1, zorder=6,
                label="arrival event" if i == min(arrived_at) else None)

    # start/end
    ax.plot(xs[0], ys[0], "^", color="green", markersize=14, zorder=5, label="start")
    ax.plot(xs[-1], ys[-1], "s", color="black", markersize=12, zorder=5, label="end")

    ax.set_xlabel("East (m, local flat projection)")
    ax.set_ylabel("North (m, local flat projection)")
    ax.set_aspect("equal")
    ax.grid(True, alpha=0.3)
    ax.legend(loc="best")
    n_arrived = len(arrived_at)
    ax.set_title(f"Walk: {len(fixes_arr)} fixes  |  {total_path_m:.0f} m  |  "
                 f"{total_time/60:.1f} min  |  {n_arrived}/{len(waypoints)} waypoints reached")
    fig.tight_layout()
    out = bag_dir.parent / f"{bag_dir.name}.png"
    fig.savefig(out, dpi=110)
    print(f"\nPlot saved: {out}")


if __name__ == "__main__":
    main()
