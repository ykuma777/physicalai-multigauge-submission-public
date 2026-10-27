#!/usr/bin/env bash
set -eo pipefail
export ROS_DOMAIN_ID=44
export IGN_PARTITION=physicalai_camera_submission_44
export DISPLAY=:0
export XAUTHORITY=/home/ubuntu/.Xauthority
source /opt/ros/humble/setup.bash
source /home/ubuntu/airobot_ws/install/setup.bash
source /home/ubuntu/final_ws/install/setup.bash
source /home/ubuntu/camera_demo/ros2_ws/install/setup.bash
set -u
exec python3 /home/ubuntu/camera_demo/scripts/run_displayed_trial.py "$@"
