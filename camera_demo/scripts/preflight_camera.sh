#!/usr/bin/env bash
set -eo pipefail
source /opt/ros/humble/setup.bash
source /home/ubuntu/airobot_ws/install/setup.bash
source /home/ubuntu/final_ws/install/setup.bash
source /home/ubuntu/camera_demo/ros2_ws/install/setup.bash
exec python3 /home/ubuntu/camera_demo/scripts/preflight_camera.py "$@"
