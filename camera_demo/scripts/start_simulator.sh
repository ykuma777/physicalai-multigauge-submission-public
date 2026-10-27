#!/usr/bin/env bash
set -eo pipefail
export DISPLAY=:0
export XAUTHORITY=/home/ubuntu/.Xauthority
export ROS_DOMAIN_ID=44
export IGN_PARTITION=physicalai_camera_submission_44
source ~/.bashrc || true
source /opt/ros/humble/setup.bash
source /home/ubuntu/airobot_ws/install/setup.bash
source /home/ubuntu/final_ws/install/setup.bash
source /home/ubuntu/camera_demo/ros2_ws/install/setup.bash
set -u
python3 /home/ubuntu/camera_demo/scripts/build_camera_robot.py
ign sdf -k /home/ubuntu/camera_demo/worlds/camera_table.sdf
exec ros2 launch camera_inspection camera_world.launch.py
