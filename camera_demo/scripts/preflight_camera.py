#!/usr/bin/env python3
"""Fail-closed health check for the isolated camera/robot session."""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import rclpy
import yaml
from control_msgs.msg import JointTrajectoryControllerState
from rosgraph_msgs.msg import Clock
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import Image, JointState


ROOT = Path(__file__).resolve().parents[1]
REQUIRED = (
    "crane_plus_arm_controller",
    "crane_plus_gripper_controller",
    "joint_state_broadcaster",
)


def run(argv: list[str], timeout: int = 12) -> str:
    result = subprocess.run(argv, text=True, capture_output=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError(f"{' '.join(argv)}: {result.stdout} {result.stderr}")
    return result.stdout


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-pose", choices=["home", "observe", "normal_response", "abnormal_response"])
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    cfg = yaml.safe_load((ROOT / "configs/runtime.yaml").read_text(encoding="utf-8"))
    pose_cfg = yaml.safe_load((ROOT / "configs/poses.yaml").read_text(encoding="utf-8"))
    output = {"checked_at_utc": datetime.now(timezone.utc).isoformat(), "ros_domain_id": os.environ.get("ROS_DOMAIN_ID"),
              "checks": {}, "expected_pose": args.expected_pose, "result": "FAIL"}
    node = None
    try:
        if os.environ.get("ROS_DOMAIN_ID") != str(cfg["ros_domain_id"]):
            raise RuntimeError(f"ROS_DOMAIN_ID must be {cfg['ros_domain_id']}")
        controllers = re.sub(r"\x1b\[[0-9;]*m", "", run(["ros2", "control", "list_controllers"], 10))
        output["controllers"] = controllers
        for name in REQUIRED:
            row = next((line for line in controllers.splitlines() if line.startswith(name + " ")), None)
            if row is None or "active" not in row:
                raise RuntimeError(f"controller not active: {name}")
        output["checks"]["controllers"] = "PASS"
        poses_by_name = {}
        poses = run(["ign", "topic", "-e", "-t", f"/world/{cfg['world']}/pose/info",
                     "-n", "1", "--json-output"], 12)
        # ign topic can append another complete JSON message even with -n 1.
        first_pose_message, end = json.JSONDecoder().raw_decode(poses.lstrip())
        output["extra_pose_payload_bytes_ignored"] = len(poses.lstrip()[end:].strip())
        for item in first_pose_message.get("pose", []):
            point = item.get("position", {})
            poses_by_name[item.get("name", "")] = [float(point.get(k, 0.0)) for k in ("x", "y", "z")]
        if "crane_plus" not in poses_by_name or cfg["target_entity"] not in poses_by_name:
            raise RuntimeError("robot or gauge entity absent in camera world")
        expected = [float(x) for x in cfg["target_bottom_world"]]
        actual = poses_by_name[cfg["target_entity"]]
        if max(abs(a-b) for a,b in zip(actual,expected)) > 0.002:
            raise RuntimeError(f"gauge world pose mismatch: {actual} vs {expected}")
        output["target_world_bottom"] = actual
        output["checks"]["world_entities"] = "PASS"
        topic = run(["ros2", "topic", "info", cfg["camera_topic"], "--verbose"], 10)
        if "Publisher count: 0" in topic or "Publisher count: 1" not in topic:
            raise RuntimeError("camera ROS topic has no publisher")
        output["checks"]["camera_publisher"] = "PASS"

        rclpy.init(args=[])
        node = rclpy.create_node("camera_demo_preflight")
        state = {"clocks": [], "joints": None, "controller_state": False, "image": False}

        def clock_callback(msg):
            stamp = (msg.clock.sec, msg.clock.nanosec)
            if not state["clocks"] or state["clocks"][-1] != stamp:
                state["clocks"].append(stamp)

        def joints_callback(msg):
            state["joints"] = {n: float(p) for n,p in zip(msg.name,msg.position)}

        node.create_subscription(Clock, "/clock", clock_callback, qos_profile_sensor_data)
        node.create_subscription(JointState, "/joint_states", joints_callback, qos_profile_sensor_data)
        node.create_subscription(JointTrajectoryControllerState,
                                 "/crane_plus_arm_controller/controller_state",
                                 lambda _: state.__setitem__("controller_state", True), qos_profile_sensor_data)
        node.create_subscription(Image, cfg["camera_topic"],
                                 lambda msg: state.__setitem__("image", msg.width > 0 and msg.height > 0),
                                 qos_profile_sensor_data)
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            rclpy.spin_once(node, timeout_sec=0.2)
            if len(state["clocks"]) >= 2 and state["joints"] and state["controller_state"] and state["image"]:
                break
        if len(state["clocks"]) < 2 or state["clocks"][-1] <= state["clocks"][0]:
            raise RuntimeError("/clock did not progress")
        if not state["joints"] or not state["controller_state"] or not state["image"]:
            raise RuntimeError("joint state, controller state, or camera image missing")
        output["checks"]["clock_joint_controller_image"] = "PASS"
        output["joint_positions"] = state["joints"]
        if args.expected_pose:
            targets = pose_cfg["poses"][args.expected_pose]["positions"]
            names = pose_cfg["joint_names"]
            errors = [abs(state["joints"][name]-target) for name,target in zip(names,targets)]
            output["expected_pose_errors_rad"] = errors
            if max(errors) > 0.06:
                raise RuntimeError(f"robot is not near {args.expected_pose}: {errors}")
            output["checks"]["expected_pose"] = "PASS"
        output["result"] = "PASS"
        return 0
    except Exception as exc:
        output["error"] = f"{type(exc).__name__}: {exc}"
        return 1
    finally:
        if node is not None:
            node.destroy_node()
            rclpy.shutdown()
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(output, indent=2))


if __name__ == "__main__":
    raise SystemExit(main())
