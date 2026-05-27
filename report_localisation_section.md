# Localisation Node — Pixhawk EKF3 + MAVROS

The sensor acquisition and low-level state estimation are migrated to a Holybro Pixhawk 6C flight controller running ArduPilot ArduCopter 4.6.3. The Pixhawk integrates two redundant IMUs (ICM-42688-P, BMI088), an IST8310 magnetometer, and an MS5611 barometer on a single STM32H743 host MCU. A u-blox NEO-M9N multi-constellation GNSS receiver is connected to the GPS1 port (Serial3) at 230,400 baud and auto-configured by the firmware on startup. The three custom ROS2 sensor nodes from the previous prototype are subsumed by a single firmware-level filter: the ArduPilot Extended Kalman Filter (EKF3) runs on the flight controller at 50 Hz, fusing the IMUs, magnetometer, barometric height and GPS internally, and exposes the fused global state over USB CDC as MAVLink for ingestion by the host machine. EKF3 is configured for a GPS-aided ground vehicle: EK3_SRC1_POSXY = 3 (GPS), EK3_SRC1_VELXY = 3 (GPS), EK3_SRC1_POSZ = 1 (barometric), EK3_SRC1_YAW = 1 (compass), with AHRS_EKF_TYPE = 3 and AHRS_GPS_USE = 1. The filter outputs a continuously available global pose at 10 Hz once a position fix is acquired.

## MAVROS Bridge

The Pixhawk exposes two USB-CDC endpoints; the secondary endpoint (SERIAL7, mapped to /dev/ttyACM3 on the host) is used for the ROS2 bridge so that QGroundControl can run concurrently on the primary endpoint for parameter editing and diagnostics. The mavros_node is launched with the ArduPilot configuration profile (apm.launch). The SR3_* stream-rate parameters were persisted to the flight controller's flash (POSITION = 10 Hz, RAW_SENS = 10 Hz, EXTRA1 = 10 Hz, EXTRA2 = 10 Hz) so that the secondary endpoint streams telemetry at usable rates without runtime configuration on each connection. The GeographicLib geoid and magnetic datasets (egm96-5, emm2015) were installed on the host to enable accurate altitude and declination handling. After bring-up MAVROS publishes the fused state on standard ROS2 topics: /mavros/global_position/global (sensor_msgs/NavSatFix) at 10 Hz, /mavros/global_position/compass_hdg (std_msgs/Float64) at 10 Hz, /mavros/local_position/pose (geometry_msgs/PoseStamped) at 10 Hz, and /mavros/imu/data_raw at 50 Hz. No additional sensor-parsing, calibration, or GPS-to-odometry nodes are required on the host side; the equivalent of the previous prototype's gps_node, imu_node, mag_node and gps_to_odom_node is reduced to a single bridge subscription.

## Waypoint Navigator

A custom rclpy node, walk_to_waypoints, loads a list of lat/lon waypoints from waypoints.yaml, subscribes to the live MAVROS GPS and compass topics, and computes the haversine distance and great-circle bearing to the active waypoint each control tick (3.3 Hz). The relative bearing — bearing-to-target minus current heading, wrapped to [-180°, +180°] — is rendered in a terminal UI as a turn magnitude and direction, with the colour grading from green (straight) through yellow to red (hard turn) for at-a-glance interpretation while walking. On entering a 5 m arrival radius for three consecutive position readings (a hysteresis chosen to suppress GPS-jitter false triggers), the node displays the cardinal bearing of the next waypoint (N/NE/E/...) and auto-advances after a 4 s dwell. The node also publishes /walking_test/status as a JSON string at the same rate; this is captured to the rosbag alongside the MAVROS topics, providing a time-aligned mission-state record for post-walk analysis. A companion script, visualize_walk.py, re-reads the bag through rosbag2_py, projects the trajectory into a local east-north frame centred on the waypoints, and renders the figure used below.

## Initial Results

A four-corner waypoint mission was executed around a residential block to validate end-to-end pipeline performance. The planned route consisted of two long edges (~105 m, along the street) and two short edges (~16 m, crossing the road), for a planned perimeter of approximately 243 m. Corner coordinates were taken from Google Maps and entered as decimal degrees in waypoints.yaml. The mission was completed in a single take with no operator intervention required between waypoints. The summary metrics are presented in Table 1, and the walked trajectory is shown in Figure 1.

Table 1 Walking-test summary — 4-corner block route, Melbourne, 27/05/2026.

| Metric | Value | Notes |
|---|---|---|
| Waypoints reached | 4 / 4 | All within 5 m arrival radius |
| Closest approach (per waypoint) | 2.28 – 2.84 m | P1 2.54, P2 2.28, P3 2.77, P4 2.84 |
| Total GPS path length | 231.3 m | EKF-fused output |
| Planned perimeter | 243 m | 95 % path-to-plan ratio |
| Mission duration | 181.9 s (3.0 min) | Includes three 4 s arrival dwells |
| Average speed | 1.27 m/s (4.6 km/h) | Normal walking pace |
| GPS satellites | avg 20.6, min 16, max 24 | Multi-constellation, outdoor |
| Time per long edge | 65.4 – 70.5 s | P1→P2 east, P3→P4 west |
| Time per short edge | 9.9 s | P2→P3 cross-road |

The trajectory passes through all four arrival circles in sequence, with closest approach to each corner falling well within the 5 m arrival threshold. The endpoint of the walk lies adjacent to the starting position, confirming gross loop closure. The trace is smooth at the resolution of normal walking and shows no inter-correction oscillation: the sawtooth pattern that dominated the Prototype 1 EKF output between 1 Hz GPS updates is absent. This is attributable to two architectural differences. First, the magnetometer is fused inside the FC firmware against the IMU at 50 Hz with full hard- and soft-iron compensation from the ArduPilot compass-calibration routine, rather than at the heading-only level used previously. Second, the EKF propagates at 50 Hz against the IMU and is corrected by GPS at 10 Hz rather than 1 Hz, so the open-loop drift window between corrections is reduced by an order of magnitude. The total walked path length (231.3 m) matches the planned perimeter (243 m) to 95 %, with no over-counting; in the previous prototype the equivalent ratio was 2.4× due to heading noise integrating into the position channel.

The number of visible GPS satellites (avg 20.6, max 24) is substantially higher than the satellite counts observed during indoor pipeline bring-up (11–14) and is consistent with the M9N's published multi-constellation performance under open-sky conditions. The EKF3 GPS-quality checks (EK3_GPS_CHECK = 31, the default strict mask) additionally reject fixes that fail any of the configured horizontal-accuracy, velocity-consistency, or speed-accuracy sub-tests, providing a clean front-end gate to the filter and explaining the absence of GPS-jump artefacts in the trace.

The pipeline is operationally complete for the waypoint-following test case. The next stage ports the same MAVROS topics to a Raspberry Pi 4 carried by the target rover platform, replacing the walking navigator's terminal output with /cmd_vel publication into the rover's motor driver for autonomous traversal of a fixed survey grid.

Figure 1: Walking-test trajectory. Walked path coloured by elapsed time (dark purple at t = 0 → yellow at t = 182 s). Planned waypoints (red dots) with 5 m arrival circles (dotted), arrival events (gold stars), start (green triangle) and end (black square). Trajectory passes through all four arrival circles in sequence and closes adjacent to the start.
