#!/usr/bin/env bash
# Run once after mavros connects. Bumps the 4 MAVLink messages we need for
# localisation to 10 Hz. These rates do NOT persist across FC reboots, so
# re-run this script every time you launch mavros from scratch.
#
# Messages bumped:
#   33 GLOBAL_POSITION_INT  -> /mavros/global_position/global + compass_hdg
#   30 ATTITUDE             -> roll/pitch/yaw (direction)
#   74 VFR_HUD              -> heading + ground-speed convenience topic
#   26 SCALED_IMU2          -> /mavros/imu/data_raw

set -e
source /opt/ros/jazzy/setup.bash

echo "Bumping localisation message rates to 10 Hz via /mavros/set_message_interval"
for msgid in 33 30 74 26; do
  result=$(ros2 service call /mavros/set_message_interval \
    mavros_msgs/srv/MessageInterval \
    "{message_id: $msgid, message_rate: 10.0}" 2>&1 | grep -oE "success=[A-Za-z]+")
  printf "  msgid %-3d %s\n" "$msgid" "$result"
done
echo "Done. Verify with:"
echo "  ros2 topic hz --window 20 /mavros/global_position/global"
