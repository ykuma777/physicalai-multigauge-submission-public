#!/usr/bin/env bash
set -eo pipefail
source /opt/ros/humble/setup.bash
source /home/ubuntu/airobot_ws/install/setup.bash
cd /home/ubuntu/final_ws
colcon build --symlink-install --packages-select inspection_task
source /home/ubuntu/final_ws/install/setup.bash
cd /home/ubuntu/camera_demo/ros2_ws
colcon build --symlink-install --packages-select camera_inspection
source /home/ubuntu/camera_demo/ros2_ws/install/setup.bash
set -u
ros2 pkg executables camera_inspection
