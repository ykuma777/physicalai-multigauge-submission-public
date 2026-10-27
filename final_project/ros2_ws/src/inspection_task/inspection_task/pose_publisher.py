"""Validate, audit, and optionally publish one configured CRANE+ arm pose."""

import json
import math
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import rclpy
import yaml
from builtin_interfaces.msg import Duration
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import JointState
from trajectory_msgs.msg import JointTrajectory, JointTrajectoryPoint


JOINT_NAMES = [
    "crane_plus_joint1",
    "crane_plus_joint2",
    "crane_plus_joint3",
    "crane_plus_joint4",
]
TRAJECTORY_TOPIC = "/crane_plus_arm_controller/joint_trajectory"
JOINT_STATE_TOPIC = "/joint_states"
AUDIT_LOG = Path("/home/ubuntu/final_project/results/trajectory_commands.jsonl")

# Limits are derived from crane_plus_description's URDF/Xacro defaults.
# The gripper joint is intentionally excluded.
SERVO_HOME_RAD = math.radians(150.0)
JOINT_LIMITS_RAD = [
    (math.radians(0.0) - SERVO_HOME_RAD, math.radians(300.0) - SERVO_HOME_RAD),
    (math.radians(45.45) - SERVO_HOME_RAD, math.radians(252.20) - SERVO_HOME_RAD),
    (math.radians(3.52) - SERVO_HOME_RAD, math.radians(290.62) - SERVO_HOME_RAD),
    (math.radians(44.57) - SERVO_HOME_RAD, math.radians(251.32) - SERVO_HOME_RAD),
]
DEFAULT_CONFIG = Path("/home/ubuntu/final_project/configs/poses.yaml")


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _append_jsonl(record: dict[str, Any]) -> None:
    """Append one durable audit event without replacing previous records."""
    AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
    with AUDIT_LOG.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


class PosePublisher(Node):
    """Run one dry-run or one explicitly confirmed trajectory publication."""

    def __init__(self) -> None:
        super().__init__("pose_publisher")
        self.declare_parameter("pose_name", "home")
        self.declare_parameter("dry_run", True)
        self.declare_parameter("confirm_motion", False)
        self.declare_parameter("duration_sec", 3.0)
        self.declare_parameter("config_path", str(DEFAULT_CONFIG))
        self.declare_parameter("verify_joint_states", True)
        self.declare_parameter("tolerance_rad", 0.03)
        self.declare_parameter("verification_timeout_sec", 12.0)

        self.publisher = self.create_publisher(JointTrajectory, TRAJECTORY_TOPIC, 10)
        self._joint_state_generation = 0
        self._latest_joint_positions: dict[str, float | None] = {}
        self.joint_state_subscription = self.create_subscription(
            JointState,
            JOINT_STATE_TOPIC,
            self._on_joint_state,
            qos_profile_sensor_data,
        )

    def _on_joint_state(self, message: JointState) -> None:
        if len(message.name) != len(message.position):
            self.get_logger().warning(
                "Ignoring malformed JointState: name and position lengths differ."
            )
            return

        positions: dict[str, float | None] = {}
        for name, raw_value in zip(message.name, message.position):
            value = float(raw_value)
            positions[name] = value if math.isfinite(value) else None
        self._latest_joint_positions = positions
        self._joint_state_generation += 1

    def _load_pose(
        self,
    ) -> tuple[str, list[float], str, float, bool, bool, bool, float, float, str]:
        pose_name = str(self.get_parameter("pose_name").value)
        dry_run = bool(self.get_parameter("dry_run").value)
        confirm_motion = bool(self.get_parameter("confirm_motion").value)
        duration_sec = float(self.get_parameter("duration_sec").value)
        verify_joint_states = bool(self.get_parameter("verify_joint_states").value)
        tolerance_rad = float(self.get_parameter("tolerance_rad").value)
        verification_timeout_sec = float(
            self.get_parameter("verification_timeout_sec").value
        )
        config_path = Path(str(self.get_parameter("config_path").value)).expanduser().resolve()

        if not math.isfinite(duration_sec) or duration_sec <= 0.0:
            raise ValueError("duration_sec must be a finite value greater than zero")
        if not math.isfinite(tolerance_rad) or tolerance_rad < 0.0:
            raise ValueError("tolerance_rad must be finite and non-negative")
        if (
            not math.isfinite(verification_timeout_sec)
            or verification_timeout_sec <= 0.0
        ):
            raise ValueError(
                "verification_timeout_sec must be finite and greater than zero"
            )

        try:
            with config_path.open("r", encoding="utf-8") as stream:
                config: Any = yaml.safe_load(stream)
        except (OSError, yaml.YAMLError) as exc:
            raise ValueError(f"could not read pose config {config_path}: {exc}") from exc

        if not isinstance(config, dict):
            raise ValueError("pose config must contain a YAML mapping")

        joint_names = config.get("joint_names")
        if not isinstance(joint_names, list) or len(joint_names) != 4:
            raise ValueError("joint_names must contain exactly four arm joints")
        if joint_names != JOINT_NAMES:
            raise ValueError(f"joint_names must use the required order: {JOINT_NAMES}")

        pose_limits = JOINT_LIMITS_RAD
        poses = config.get("poses")
        if isinstance(poses, dict):
            available = sorted(poses.keys())
            if pose_name not in poses:
                raise ValueError(f"unknown pose_name {pose_name!r}; available poses: {available}")
            pose = poses[pose_name]
            if not isinstance(pose, dict):
                raise ValueError(f"pose {pose_name!r} must be a YAML mapping")
            status = pose.get("status")
            positions = pose.get("positions")
        elif isinstance(config.get("equipment"), list) and "pointing_link" in config:
            pointing_poses = {
                f"point_{str(item.get('id', '')).lower()}": item
                for item in config["equipment"]
                if isinstance(item, dict) and item.get("id") in {"A", "B", "C"}
            }
            available = sorted(pointing_poses)
            if pose_name not in pointing_poses:
                raise ValueError(f"unknown pose_name {pose_name!r}; available poses: {available}")
            pose = pointing_poses[pose_name]
            status = pose.get("status")
            positions = pose.get("candidate_positions")
            configured_limits = config.get("joint_limits")
            if not isinstance(configured_limits, dict):
                raise ValueError("pointing config joint_limits must be a mapping")
            pose_limits = []
            for joint_name in JOINT_NAMES:
                limits = configured_limits.get(joint_name)
                if not isinstance(limits, list) or len(limits) != 2:
                    raise ValueError(f"pointing config is missing a two-value joint limit for {joint_name}")
                lower, upper = (float(value) for value in limits)
                if not math.isfinite(lower) or not math.isfinite(upper) or lower >= upper:
                    raise ValueError(f"pointing config has invalid joint limits for {joint_name}")
                pose_limits.append((lower, upper))
        else:
            raise ValueError("config must be poses.yaml or pointing.yaml with the expected schema")

        if not isinstance(positions, list) or len(positions) != 4:
            raise ValueError(f"pose {pose_name!r} positions must contain exactly four values")
        if not isinstance(status, str) or not status:
            raise ValueError(f"pose {pose_name!r} must define a non-empty status")

        checked_positions: list[float] = []
        for index, raw_value in enumerate(positions):
            if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
                raise ValueError(f"position {index} must be a numeric radian value")
            value = float(raw_value)
            if not math.isfinite(value):
                raise ValueError(f"position {index} must be finite (NaN and infinity are invalid)")
            lower, upper = pose_limits[index]
            if not lower <= value <= upper:
                raise ValueError(
                    f"position {index}={value} rad is outside URDF range [{lower}, {upper}] rad"
                )
            checked_positions.append(value)

        return (
            pose_name,
            checked_positions,
            str(status),
            duration_sec,
            dry_run,
            confirm_motion,
            verify_joint_states,
            tolerance_rad,
            verification_timeout_sec,
            str(config_path),
        )

    def _audit_base(
        self,
        *,
        command_id: str,
        timestamp: str,
        pose_name: str,
        positions: list[float],
        duration_sec: float,
        dry_run: bool,
        confirm_motion: bool,
        subscriber_count: int,
        publish_count: int,
        verify_joint_states: bool,
        tolerance_rad: float,
        verification_timeout_sec: float,
    ) -> dict[str, Any]:
        return {
            "event": "pose_command",
            "command_id": command_id,
            "timestamp": timestamp,
            "pose_name": pose_name,
            "status": getattr(self, "_active_pose_status", "unknown"),
            "config_path": getattr(self, "_active_config_path", "unknown"),
            "joint_names": JOINT_NAMES,
            "positions": positions,
            "duration_sec": duration_sec,
            "dry_run": dry_run,
            "confirm_motion": confirm_motion,
            "subscriber_count": subscriber_count,
            "publish_count": publish_count,
            "verify_joint_states": verify_joint_states,
            "tolerance_rad": tolerance_rad,
            "verification_timeout_sec": verification_timeout_sec,
        }

    def _write_audit(self, record: dict[str, Any]) -> bool:
        try:
            _append_jsonl(record)
            return True
        except (OSError, TypeError, ValueError) as exc:
            self.get_logger().error(f"Could not append trajectory audit JSONL: {exc}")
            return False

    def _verify_joint_state(
        self,
        *,
        positions: list[float],
        tolerance_rad: float,
        timeout_sec: float,
        generation_before_publish: int,
    ) -> tuple[str, list[float | None] | None, list[float | None] | None]:
        deadline = time.monotonic() + timeout_sec
        last_measured: list[float | None] | None = None
        last_errors: list[float | None] | None = None
        last_generation = generation_before_publish

        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            rclpy.spin_once(self, timeout_sec=min(0.1, max(0.0, remaining)))
            if self._joint_state_generation <= last_generation:
                continue
            last_generation = self._joint_state_generation

            measured = [self._latest_joint_positions.get(name) for name in JOINT_NAMES]
            errors = [
                (actual - target) if actual is not None else None
                for actual, target in zip(measured, positions)
            ]
            last_measured = measured
            last_errors = errors
            if all(error is not None and abs(error) <= tolerance_rad for error in errors):
                return "PASS", last_measured, last_errors

        return "FAIL", last_measured, last_errors

    def run_once(self) -> bool:
        try:
            (
                pose_name,
                positions,
                status,
                duration_sec,
                dry_run,
                confirm_motion,
                verify_joint_states,
                tolerance_rad,
                verification_timeout_sec,
                config_path,
            ) = self._load_pose()
        except ValueError as exc:
            self.get_logger().error(str(exc))
            return False

        self._active_pose_status = status
        self._active_config_path = config_path

        self.get_logger().info(
            f"config_path={config_path}, pose_name={pose_name}, status={status}, joint_names={JOINT_NAMES}, "
            f"positions_rad={positions}, topic={TRAJECTORY_TOPIC}, "
            f"duration_sec={duration_sec}, dry_run={dry_run}, "
            f"confirm_motion={confirm_motion}, "
            f"verify_joint_states={verify_joint_states}, "
            f"tolerance_rad={tolerance_rad}, "
            f"verification_timeout_sec={verification_timeout_sec}"
        )

        command_id = str(uuid.uuid4())
        timestamp = _utc_timestamp()
        subscriber_count = self.publisher.get_subscription_count()
        if dry_run:
            record = self._audit_base(
                command_id=command_id,
                timestamp=timestamp,
                pose_name=pose_name,
                positions=positions,
                duration_sec=duration_sec,
                dry_run=True,
                confirm_motion=confirm_motion,
                subscriber_count=subscriber_count,
                publish_count=0,
                verify_joint_states=verify_joint_states,
                tolerance_rad=tolerance_rad,
                verification_timeout_sec=verification_timeout_sec,
            )
            record.update(event="dry_run", verification_result="NOT_RUN_DRY_RUN")
            if not self._write_audit(record):
                return False
            self.get_logger().info("DRY RUN: no JointTrajectory was published.")
            return True

        if not confirm_motion:
            record = self._audit_base(
                command_id=command_id,
                timestamp=timestamp,
                pose_name=pose_name,
                positions=positions,
                duration_sec=duration_sec,
                dry_run=False,
                confirm_motion=False,
                subscriber_count=subscriber_count,
                publish_count=0,
                verify_joint_states=verify_joint_states,
                tolerance_rad=tolerance_rad,
                verification_timeout_sec=verification_timeout_sec,
            )
            record.update(event="publish_skipped", verification_result="NOT_RUN_NOT_CONFIRMED")
            if not self._write_audit(record):
                return False
            if status == "candidate":
                self.get_logger().error(
                    f"Candidate pose {pose_name!r} requires explicit confirm_motion:=true; "
                    "no JointTrajectory was published."
                )
                return False
            self.get_logger().warning(
                "Motion is not confirmed: no JointTrajectory was published."
            )
            return True

        # Avoid a one-shot command before the controller has discovered the publisher.
        deadline = time.monotonic() + 5.0
        while self.publisher.get_subscription_count() == 0 and time.monotonic() < deadline:
            rclpy.spin_once(self, timeout_sec=0.1)
        subscriber_count = self.publisher.get_subscription_count()
        if subscriber_count == 0:
            record = self._audit_base(
                command_id=command_id,
                timestamp=timestamp,
                pose_name=pose_name,
                positions=positions,
                duration_sec=duration_sec,
                dry_run=False,
                confirm_motion=True,
                subscriber_count=0,
                publish_count=0,
                verify_joint_states=verify_joint_states,
                tolerance_rad=tolerance_rad,
                verification_timeout_sec=verification_timeout_sec,
            )
            record.update(event="publish_skipped", verification_result="NOT_RUN_NO_SUBSCRIBER")
            self._write_audit(record)
            self.get_logger().error(
                f"No subscriber found on {TRAJECTORY_TOPIC}; no trajectory was published."
            )
            return False

        if verify_joint_states:
            # rclpy Subscription has no get_publisher_count() in ROS 2 Humble.
            # Confirm an actual JointState sample instead of calling a missing API.
            joint_state_deadline = time.monotonic() + 5.0
            generation_before_check = self._joint_state_generation
            while (
                self._joint_state_generation == generation_before_check
                and time.monotonic() < joint_state_deadline
            ):
                rclpy.spin_once(self, timeout_sec=0.1)

        if verify_joint_states and self._joint_state_generation == 0:
            record = self._audit_base(
                command_id=command_id,
                timestamp=timestamp,
                pose_name=pose_name,
                positions=positions,
                duration_sec=duration_sec,
                dry_run=False,
                confirm_motion=True,
                subscriber_count=subscriber_count,
                publish_count=0,
                verify_joint_states=True,
                tolerance_rad=tolerance_rad,
                verification_timeout_sec=verification_timeout_sec,
            )
            record.update(event="publish_skipped", verification_result="NOT_RUN_NO_JOINT_STATES")
            self._write_audit(record)
            self.get_logger().error(
                f"No JointState sample received from {JOINT_STATE_TOPIC}; "
                "no trajectory was published."
            )
            return False

        intent = self._audit_base(
            command_id=command_id,
            timestamp=timestamp,
            pose_name=pose_name,
            positions=positions,
            duration_sec=duration_sec,
            dry_run=False,
            confirm_motion=True,
            subscriber_count=subscriber_count,
            publish_count=0,
            verify_joint_states=verify_joint_states,
            tolerance_rad=tolerance_rad,
            verification_timeout_sec=verification_timeout_sec,
        )
        intent.update(event="publish_intent", verification_result="PENDING")
        if not self._write_audit(intent):
            self.get_logger().error("Aborting motion because the audit intent could not be saved.")
            return False

        generation_before_publish = self._joint_state_generation
        message = JointTrajectory()
        message.joint_names = JOINT_NAMES
        point = JointTrajectoryPoint()
        point.positions = positions
        whole_seconds = int(duration_sec)
        nanoseconds = int(round((duration_sec - whole_seconds) * 1_000_000_000))
        if nanoseconds >= 1_000_000_000:
            whole_seconds += 1
            nanoseconds -= 1_000_000_000
        point.time_from_start = Duration(sec=whole_seconds, nanosec=nanoseconds)
        message.points.append(point)

        try:
            self.publisher.publish(message)
        except Exception as exc:  # Keep a durable failure event for an attempted send.
            failed = self._audit_base(
                command_id=command_id,
                timestamp=timestamp,
                pose_name=pose_name,
                positions=positions,
                duration_sec=duration_sec,
                dry_run=False,
                confirm_motion=True,
                subscriber_count=subscriber_count,
                publish_count=0,
                verify_joint_states=verify_joint_states,
                tolerance_rad=tolerance_rad,
                verification_timeout_sec=verification_timeout_sec,
            )
            failed.update(event="publish_failed", verification_result="NOT_RUN_PUBLISH_ERROR")
            self._write_audit(failed)
            self.get_logger().error(f"JointTrajectory publish failed: {exc}")
            return False

        command_record = self._audit_base(
            command_id=command_id,
            timestamp=timestamp,
            pose_name=pose_name,
            positions=positions,
            duration_sec=duration_sec,
            dry_run=False,
            confirm_motion=True,
            subscriber_count=subscriber_count,
            publish_count=1,
            verify_joint_states=verify_joint_states,
            tolerance_rad=tolerance_rad,
            verification_timeout_sec=verification_timeout_sec,
        )
        command_record.update(
            event="trajectory_command",
            topic=TRAJECTORY_TOPIC,
            verification_result="PENDING" if verify_joint_states else "DISABLED",
        )
        audit_ok = self._write_audit(command_record)
        self.get_logger().info(
            f"Published exactly one pose {pose_name!r} to {TRAJECTORY_TOPIC}; "
            f"subscriber_count={subscriber_count}."
        )

        if not verify_joint_states:
            return audit_ok

        result, measured, errors = self._verify_joint_state(
            positions=positions,
            tolerance_rad=tolerance_rad,
            timeout_sec=verification_timeout_sec,
            generation_before_publish=generation_before_publish,
        )
        verification = self._audit_base(
            command_id=command_id,
            timestamp=_utc_timestamp(),
            pose_name=pose_name,
            positions=positions,
            duration_sec=duration_sec,
            dry_run=False,
            confirm_motion=True,
            subscriber_count=subscriber_count,
            publish_count=1,
            verify_joint_states=True,
            tolerance_rad=tolerance_rad,
            verification_timeout_sec=verification_timeout_sec,
        )
        verification.update(
            event="joint_state_verification",
            command_timestamp=timestamp,
            topic=JOINT_STATE_TOPIC,
            verification_result=result,
            measured_positions=measured,
            errors_rad=errors,
        )
        audit_ok = self._write_audit(verification) and audit_ok
        if result == "PASS":
            self.get_logger().info(
                f"JointState verification PASS: measured_positions={measured}, "
                f"errors_rad={errors}, tolerance_rad={tolerance_rad}."
            )
        else:
            self.get_logger().error(
                f"JointState verification FAIL after {verification_timeout_sec}s: "
                f"measured_positions={measured}, errors_rad={errors}, "
                f"tolerance_rad={tolerance_rad}."
            )
        return result == "PASS" and audit_ok


def main(args: list[str] | None = None) -> None:
    rclpy.init(args=args)
    node = PosePublisher()
    success = False
    try:
        success = node.run_once()
    finally:
        node.destroy_node()
        rclpy.shutdown()
    if not success:
        raise SystemExit(2)
