"""Launch an independent Ignition Fortress world and an arm-mounted camera robot."""
from pathlib import Path
import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import ExecuteProcess, IncludeLaunchDescription, TimerAction
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch_ros.actions import Node, SetParameter


ROOT = Path("/home/ubuntu/camera_demo")


def generate_launch_description():
    robot_description = (ROOT / "generated/camera_robot.urdf").read_text(encoding="utf-8")
    world = str(Path("/home/ubuntu/multigauge/generated/world.sdf"))
    gazebo_pkg = Path(get_package_share_directory("crane_plus_gazebo"))
    description_pkg = Path(get_package_share_directory("crane_plus_description"))
    environment = {
        "IGN_GAZEBO_SYSTEM_PLUGIN_PATH": os.environ.get("LD_LIBRARY_PATH", ""),
        "IGN_GAZEBO_RESOURCE_PATH": str(description_pkg.parent),
    }
    gazebo = ExecuteProcess(
        cmd=["ign", "gazebo", "-r", world, "--gui-config", "/home/ubuntu/multigauge/generated/gui.config"],
        output="screen", additional_env=environment,
    )
    moveit = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(str(Path(get_package_share_directory(
            "crane_plus_moveit_config")) / "launch/run_move_group.launch.py")),
        launch_arguments={"loaded_description": robot_description}.items(),
    )
    spawn = Node(
        package="ros_gz_sim", executable="create", output="screen",
        arguments=["-topic", "/robot_description", "-name", "crane_plus",
                   "-z", "1.015", "-allow_renaming", "false"],
    )
    spawners = [
        ExecuteProcess(
            cmd=["ros2", "run", "controller_manager", "spawner", controller],
            output="screen",
        )
        for controller in (
            "joint_state_broadcaster",
            "crane_plus_arm_controller",
            "crane_plus_gripper_controller",
        )
    ]
    clock_bridge = Node(
        package="ros_gz_bridge", executable="parameter_bridge", output="screen",
        arguments=["/clock@rosgraph_msgs/msg/Clock[ignition.msgs.Clock"],
    )
    image_bridge = Node(
        package="ros_gz_bridge", executable="parameter_bridge", output="screen",
        arguments=["/inspection_camera/image@sensor_msgs/msg/Image[ignition.msgs.Image"],
    )
    return LaunchDescription([
        SetParameter(name="use_sim_time", value=True),
        gazebo,
        moveit,
        TimerAction(period=5.0, actions=[spawn]),
        TimerAction(period=12.0, actions=spawners),
        clock_bridge,
        image_bridge,
    ])
