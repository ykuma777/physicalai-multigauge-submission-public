#!/usr/bin/env bash
set -eo pipefail
export DISPLAY=:0 XAUTHORITY=/home/ubuntu/.Xauthority
export ROS_DOMAIN_ID=46 IGN_PARTITION=physicalai_multigauge_46 GZ_PARTITION=physicalai_multigauge_46
source /opt/ros/humble/setup.bash
source /home/ubuntu/airobot_ws/install/setup.bash
source /home/ubuntu/final_ws/install/setup.bash
source /home/ubuntu/camera_demo/ros2_ws/install/setup.bash
python3 /home/ubuntu/multigauge/build_robot.py
cd /home/ubuntu/multigauge
exec ros2 launch ./launch.py
