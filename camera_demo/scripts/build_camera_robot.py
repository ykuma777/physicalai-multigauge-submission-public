#!/usr/bin/env python3
"""Expand the lecture CRANE+ xacro and attach a Gazebo camera to its endtip."""
from __future__ import annotations

import argparse
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import yaml
from ament_index_python.packages import get_package_share_directory


ROOT = Path(__file__).resolve().parents[1]


def add(parent: ET.Element, tag: str, text: str | None = None, **attrs: str) -> ET.Element:
    child = ET.SubElement(parent, tag, attrs)
    if text is not None:
        child.text = text
    return child


def build(config: dict) -> ET.Element:
    xacro_file = Path(get_package_share_directory("crane_plus_description")) / "urdf/crane_plus.urdf.xacro"
    command = [
        "xacro", str(xacro_file),
        "use_gazebo:=true",
        "use_ignition:=true",
        "use_camera:=false",
        "gz_control_config_package:=crane_plus_control",
        "gz_control_config_file_path:=config/crane_plus_controllers.yaml",
    ]
    expanded = subprocess.run(command, check=True, text=True, capture_output=True).stdout
    robot = ET.fromstring(expanded)
    link_name = str(config["camera_link"])
    parent_link = str(config["camera_parent_link"])
    existing = {link.get("name") for link in robot.findall("link")}
    if link_name in existing or parent_link not in existing:
        raise ValueError(f"camera link collision or missing parent: {link_name}, {parent_link}")

    link = add(robot, "link", name=link_name)
    inertial = add(link, "inertial")
    add(inertial, "origin", xyz="0 0 0", rpy="0 0 0")
    add(inertial, "mass", value="0.02")
    add(inertial, "inertia", ixx="0.000001", iyy="0.000001", izz="0.000001",
        ixy="0", ixz="0", iyz="0")
    visual = add(link, "visual")
    geometry = add(visual, "geometry")
    add(geometry, "box", size="0.02 0.02 0.02")
    joint = add(robot, "joint", name="inspection_camera_joint", type="fixed")
    add(joint, "parent", link=parent_link)
    add(joint, "child", link=link_name)
    add(joint, "origin",
        xyz=" ".join(str(x) for x in config["camera_joint_xyz"]),
        rpy=" ".join(str(x) for x in config["camera_joint_rpy"]))

    gazebo = add(robot, "gazebo", reference=link_name)
    sensor = add(gazebo, "sensor", name="inspection_camera", type="camera")
    add(sensor, "always_on", "true")
    add(sensor, "update_rate", str(config["image_update_hz"]))
    add(sensor, "topic", str(config["camera_topic"]))
    camera = add(sensor, "camera")
    add(camera, "horizontal_fov", str(config["horizontal_fov_rad"]))
    image = add(camera, "image")
    add(image, "width", str(config["image_width"]))
    add(image, "height", str(config["image_height"]))
    add(image, "format", "R8G8B8")
    clip = add(camera, "clip")
    add(clip, "near", "0.025")
    add(clip, "far", "2.0")
    return robot


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "generated/camera_robot.urdf")
    args = parser.parse_args()
    config = yaml.safe_load((ROOT / "configs/runtime.yaml").read_text(encoding="utf-8"))
    robot = build(config)
    ET.indent(robot, space="  ")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(robot).write(args.output, encoding="unicode", xml_declaration=True)
    print(args.output)


if __name__ == "__main__":
    main()
