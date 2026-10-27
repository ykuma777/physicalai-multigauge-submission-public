#!/usr/bin/env python3
"""Read-only MoveIt/FK and point-to-AABB check for a camera-demo joint path."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
LINKS = ["crane_plus_link_endtip", "crane_plus_link_hand", "inspection_camera_link"]


def distance_aabb(point, center, size):
    return math.dist([max(abs(p-c)-s/2, 0.0) for p,c,s in zip(point, center, size)], [0, 0, 0])


def rotate_x(quaternion):
    x, y, z, w = quaternion
    return [1 - 2 * (y*y+z*z), 2 * (x*y+w*z), 2 * (x*z-w*y)]


def call(node, client, request, timeout=5.0):
    future = client.call_async(request)
    import rclpy
    rclpy.spin_until_future_complete(node, future, timeout_sec=timeout)
    if not future.done() or future.result() is None:
        raise TimeoutError(f"service timeout: {client.srv_name}")
    return future.result()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--from-pose", required=True)
    parser.add_argument("--to-pose", required=True)
    parser.add_argument("--samples", type=int, default=101)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    if args.samples < 51:
        parser.error("at least 51 samples required")
    cfg = yaml.safe_load((ROOT / "configs/runtime.yaml").read_text(encoding="utf-8"))
    poses = yaml.safe_load((ROOT / "configs/poses.yaml").read_text(encoding="utf-8"))
    names = list(poses["joint_names"])
    start = [float(x) for x in poses["poses"][args.from_pose]["positions"]]
    goal = [float(x) for x in poses["poses"][args.to_pose]["positions"]]
    if len(names) != 4 or len(start) != 4 or len(goal) != 4:
        raise ValueError("expected four ordered arm joints")
    report_path = args.report or ROOT / "results" / f"path_{args.from_pose}_to_{args.to_pose}.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    result = {
        "from_pose": args.from_pose, "to_pose": args.to_pose,
        "samples": args.samples, "start": start, "goal": goal,
        "verdict": "FAIL_DO_NOT_MOVE",
    }
    import rclpy
    from moveit_msgs.srv import GetPlanningScene, GetPositionFK, GetStateValidity
    from sensor_msgs.msg import JointState

    rclpy.init(args=[])
    node = rclpy.create_node("camera_demo_path_preflight")
    try:
        fk = node.create_client(GetPositionFK, "/compute_fk")
        valid = node.create_client(GetStateValidity, "/check_state_validity")
        scene = node.create_client(GetPlanningScene, "/get_planning_scene")
        for client in (fk, valid, scene):
            if not client.wait_for_service(timeout_sec=5):
                raise TimeoutError(f"service unavailable: {client.srv_name}")
        scene_req = GetPlanningScene.Request()
        scene_req.components.components = 8 | 16
        planning_scene = call(node, scene, scene_req)
        result["moveit_world_objects"] = [x.id for x in planning_scene.scene.world.collision_objects]
        target_bottom = [float(x) for x in cfg["target_bottom_world"]]
        size = [float(x) for x in cfg["target_body_dimensions"]]
        target_center = [target_bottom[0], target_bottom[1], target_bottom[2] + size[2]/2]
        target_face = [target_bottom[0] - size[0]/2 - 0.005,
                       target_bottom[1], target_bottom[2] + 0.077]
        min_target = {"distance_m": float("inf")}
        min_table = {"distance_m": float("inf")}
        invalid = []
        limits_failed = []
        max_step = 0.0
        final_pose = None
        for index in range(args.samples):
            fraction = index / (args.samples - 1)
            joints = [a + fraction*(b-a) for a,b in zip(start,goal)]
            if not all(math.isfinite(v) for v in joints):
                raise ValueError(f"non-finite joint at sample {index}")
            if index:
                max_step = max(max_step, max(abs(b-a)/(args.samples-1) for a,b in zip(start,goal)))
            if not all(cfg["joint_limits"][n][0] <= q <= cfg["joint_limits"][n][1]
                       for n,q in zip(names,joints)):
                limits_failed.append(index)
            js = JointState()
            js.name = names + ["crane_plus_joint_hand"]
            js.position = joints + [0.0]
            fk_req = GetPositionFK.Request()
            fk_req.header.frame_id = "crane_plus_base"
            fk_req.fk_link_names = LINKS
            fk_req.robot_state.joint_state = js
            fk_res = call(node, fk, fk_req)
            if fk_res.error_code.val != 1 or len(fk_res.pose_stamped) != len(LINKS):
                raise RuntimeError(f"FK error at sample {index}: {fk_res.error_code.val}")
            valid_req = GetStateValidity.Request()
            valid_req.group_name = str(cfg["moveit_group"])
            valid_req.robot_state.joint_state = js
            valid_res = call(node, valid, valid_req)
            if not valid_res.valid or valid_res.contacts:
                invalid.append(index)
            for link, stamped in zip(LINKS, fk_res.pose_stamped):
                p = stamped.pose.position
                world = [p.x + cfg["robot_base_world"][0],
                         p.y + cfg["robot_base_world"][1],
                         p.z + cfg["robot_base_world"][2]]
                d = distance_aabb(world, target_center, size)
                if d < min_target["distance_m"]:
                    min_target = {"distance_m": d, "sample": index, "link": link,
                                  "joint_positions": joints, "point_world": world}
                xmin,xmax,ymin,ymax = cfg["table_bounds_xy"]
                dx = max(xmin-world[0],0,world[0]-xmax)
                dy = max(ymin-world[1],0,world[1]-ymax)
                dz = max(world[2]-cfg["table_surface_z"],0)
                table_d = math.sqrt(dx*dx+dy*dy+dz*dz)
                if world[2] < cfg["table_surface_z"] and dx == 0 and dy == 0:
                    table_d = 0.0
                if table_d < min_table["distance_m"]:
                    min_table = {"distance_m": table_d, "sample": index, "link": link,
                                 "joint_positions": joints, "point_world": world}
                if index == args.samples-1 and link == "inspection_camera_link":
                    q = stamped.pose.orientation
                    ray = rotate_x((q.x,q.y,q.z,q.w))
                    vector = [t-p for t,p in zip(target_face,world)]
                    cosine = sum(a*b for a,b in zip(ray,vector))/(math.dist(ray,[0,0,0])*math.dist(vector,[0,0,0]))
                    angle = math.degrees(math.acos(max(-1.0,min(1.0,cosine))))
                    final_pose = {"camera_world": world, "camera_forward_world": ray,
                                  "target_face_world": target_face,
                                  "distance_m": math.dist(vector,[0,0,0]),
                                  "angle_error_deg": angle}
        duration = float(cfg["motion_duration_sec"])
        speed = max(abs(b-a)/duration for a,b in zip(start,goal))
        result.update({
            "joint_limit_failed_samples": limits_failed,
            "state_invalid_samples": invalid,
            "minimum_target_basepoint_clearance": min_target,
            "minimum_table_basepoint_clearance": min_table,
            "maximum_sample_joint_delta_rad": max_step,
            "maximum_average_joint_speed_rad_s": speed,
            "endpoint_camera_geometry": final_pose,
            "limitation": "MoveIt checks its planning scene; the Gazebo target and table are not registered there. Distances cover endtip, hand and camera frame origins, not complete link surfaces or swept geometry.",
        })
        clearance = float(cfg["minimum_basepoint_clearance_m"])
        good = not limits_failed and not invalid and min_target["distance_m"] >= clearance and min_table["distance_m"] >= clearance
        if args.to_pose == "observe":
            good &= final_pose is not None and final_pose["angle_error_deg"] <= cfg["maximum_camera_target_angle_deg"] and final_pose["distance_m"] <= cfg["maximum_camera_target_distance_m"]
        result["verdict"] = "PARTIAL_PASS_SUPERVISED_GAZEBO" if good else "FAIL_DO_NOT_MOVE"
        print(json.dumps(result, indent=2, allow_nan=False))
        return 0 if good else 1
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        print(json.dumps(result, indent=2))
        return 1
    finally:
        report_path.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
