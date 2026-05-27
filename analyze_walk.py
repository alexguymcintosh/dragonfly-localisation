#!/usr/bin/env python3
"""Analyse the recorded /mavros/local_position/pose trajectory and check
whether it traces a square. Saves a PNG of the path next to the input file."""
import re
import sys
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

raw = Path("/home/mantis/loc/walk_raw.yaml").read_text()
xs = [float(v) for v in re.findall(r"x:\s*(-?\d+\.\d+)", raw)]
ys = [float(v) for v in re.findall(r"y:\s*(-?\d+\.\d+)", raw)]
assert len(xs) == len(ys), f"x/y count mismatch: {len(xs)} vs {len(ys)}"
x = np.array(xs)
y = np.array(ys)
n = len(x)

# Path length
seg = np.hypot(np.diff(x), np.diff(y))
path_len = seg.sum()

# Bounding box
bbox_w = x.max() - x.min()
bbox_h = y.max() - y.min()

# Loop closure error
closure = np.hypot(x[-1] - x[0], y[-1] - y[0])

# Furthest-from-start distance, to gauge walk extent
d_from_start = np.hypot(x - x[0], y - y[0])
furthest = d_from_start.max()

# Estimate corner indices by finding where the heading changes most.
# Smooth heading using a moving window.
dx = np.diff(x); dy = np.diff(y)
heading = np.degrees(np.arctan2(dy, dx))
# Unwrap to a continuous signal
heading_u = np.unwrap(np.radians(heading))
heading_u_deg = np.degrees(heading_u)
total_turn = heading_u_deg[-1] - heading_u_deg[0]

# Find 3 sharpest cumulative turn points -> approx corners
# Use cumulative heading change, look for steepest sections.
win = 8
if len(heading_u_deg) > 2 * win:
    smoothed = np.convolve(heading_u_deg, np.ones(win)/win, mode="valid")
    dh = np.abs(np.diff(smoothed))
    # find local maxima
    corners = []
    last_idx = -1e9
    for i in np.argsort(dh)[::-1]:
        if abs(i - last_idx) < n / 8:
            continue
        corners.append(i + win // 2)  # back-shift for the smoothing window
        last_idx = i
        if len(corners) == 3:
            break
    corners.sort()
else:
    corners = []

print(f"samples: {n}")
print(f"path length: {path_len:.1f} m")
print(f"bbox (E×N): {bbox_w:.1f} × {bbox_h:.1f} m")
print(f"start: ({x[0]:+.2f}, {y[0]:+.2f})  end: ({x[-1]:+.2f}, {y[-1]:+.2f})")
print(f"loop closure error: {closure:.2f} m  ({100*closure/path_len:.1f}% of path)")
print(f"furthest from start: {furthest:.1f} m")
print(f"net heading change: {total_turn:+.0f} deg  (expect ~+/-360 for a closed loop)")

if corners:
    print(f"estimated corner indices (along {n} samples): {corners}")
    for ci in corners:
        print(f"  corner @ idx {ci}: ({x[ci]:+.2f}, {y[ci]:+.2f})")

# --- plot ---
fig, ax = plt.subplots(figsize=(8, 8))
ax.plot(x, y, "-", lw=1.2, color="tab:blue", label="path")
ax.plot(x[0], y[0], "o", color="green", markersize=10, label="start")
ax.plot(x[-1], y[-1], "s", color="red", markersize=10, label="end")
if corners:
    for ci in corners:
        ax.plot(x[ci], y[ci], "x", color="orange", markersize=12, mew=2)
ax.set_xlabel("East (m)")
ax.set_ylabel("North (m)")
ax.set_title(f"Walk: {n} samples, {path_len:.0f} m path, closure {closure:.1f} m")
ax.set_aspect("equal")
ax.grid(True, alpha=0.3)
ax.legend()
fig.tight_layout()
out = Path("/home/mantis/loc/walk_plot.png")
fig.savefig(out, dpi=110)
print(f"\nplot saved: {out}")
