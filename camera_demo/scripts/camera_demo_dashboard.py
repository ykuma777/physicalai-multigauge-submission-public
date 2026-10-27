#!/usr/bin/env python3
"""Show the exact run image and model result beside the live Gazebo window.

This process reads only coordinator display snapshots. It never reads the gauge
setup, expected label, needle angle, or dataset configuration.
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np
import yaml


WIDTH, HEIGHT = 950, 970
WINDOW = 'Camera AI demo - current run'
RUNTIME = yaml.safe_load((Path('/home/ubuntu/camera_demo') / 'configs/runtime.yaml').read_text(encoding='utf-8'))
ROI_X, ROI_Y = map(int, RUNTIME['roi_center_xy'])
ROI_HALF = int(RUNTIME['roi_size_px']) // 2


def utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')


def atomic_json(path: Path, value: dict) -> None:
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    os.replace(temporary, path)


def move_gazebo_right() -> str:
    """Arrange the existing GUI; this does not alter the simulation or its camera."""
    tree = subprocess.check_output(['xwininfo', '-root', '-tree'], text=True)
    matches = re.findall(r'(0x[0-9a-f]+) "Gazebo": \("ign-gazebo-gui" "Gazebo GUI"\)', tree)
    if len(matches) != 1:
        raise RuntimeError(f'exactly one Gazebo GUI is required; found {len(matches)}')
    lib = ctypes.CDLL('libX11.so.6')
    lib.XOpenDisplay.restype = ctypes.c_void_p
    lib.XOpenDisplay.argtypes = [ctypes.c_char_p]
    display = lib.XOpenDisplay(os.environ.get('DISPLAY', ':0').encode())
    if not display:
        raise RuntimeError('cannot open X display')
    lib.XMoveResizeWindow.argtypes = [ctypes.c_void_p, ctypes.c_ulong,
                                      ctypes.c_int, ctypes.c_int, ctypes.c_uint, ctypes.c_uint]
    lib.XMoveResizeWindow(display, int(matches[0], 16), 960, 48, 950, 960)
    geometry = subprocess.check_output(['xwininfo', '-id', matches[0], '-tree'], text=True)
    parent_match = re.search(r'Parent window id: (0x[0-9a-f]+)', geometry)
    if not parent_match:
        raise RuntimeError('Gazebo window-manager frame not found')
    lib.XRaiseWindow.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    lib.XRaiseWindow(display, int(parent_match.group(1), 16))
    lib.XFlush.argtypes = [ctypes.c_void_p]
    lib.XFlush(display)
    lib.XCloseDisplay.argtypes = [ctypes.c_void_p]
    lib.XCloseDisplay(display)
    # Ask the window manager to activate the Gazebo frame above RViz as well.
    subprocess.run(['python3', '/home/ubuntu/camera_demo/scripts/raise_gazebo.py'],
                   check=True, capture_output=True, text=True, timeout=8)
    return matches[0]


def gazebo_above_rviz(gazebo_window: str) -> bool:
    raw = subprocess.check_output(['xprop', '-root', '_NET_CLIENT_LIST_STACKING'], text=True)
    stack = re.findall(r'0x[0-9a-f]+', raw)
    rviz = []
    for candidate in stack:
        kind = subprocess.check_output(['xprop', '-id', candidate, 'WM_CLASS'], text=True)
        if '"rviz2"' in kind:
            rviz.append(candidate)
    return gazebo_window in stack and (not rviz or all(stack.index(gazebo_window) > stack.index(item) for item in rviz))


def text(canvas: np.ndarray, value: str, x: int, y: int, *, scale: float = .61,
         color: tuple[int, int, int] = (235, 235, 235), thick: int = 1) -> None:
    cv2.putText(canvas, value, (x, y), cv2.FONT_HERSHEY_SIMPLEX, scale,
                color, thick, cv2.LINE_AA)


def draw(state: dict, image: np.ndarray | None, error: str | None) -> np.ndarray:
    canvas = np.full((HEIGHT, WIDTH, 3), (28, 24, 21), dtype=np.uint8)
    cv2.rectangle(canvas, (0, 0), (WIDTH, 84), (49, 37, 29), -1)
    text(canvas, 'CAMERA OBSERVATION  >  AI  >  ROBOT', 18, 39,
         scale=.92, color=(255, 240, 213), thick=2)
    text(canvas, f"RUN  {state['run_id']}", 18, 70, scale=.48)
    cv2.line(canvas, (666, 90), (666, 953), (80, 78, 75), 2)
    text(canvas, 'ROS CAMERA IMAGE - THIS RUN', 18, 111, scale=.66,
         color=(158, 216, 255), thick=2)
    if image is not None:
        if image.shape != (480, 640, 3):
            raise ValueError(f'unexpected camera image shape: {image.shape}')
        canvas[129:609, 15:655] = image
        cv2.rectangle(canvas, (15 + ROI_X - ROI_HALF, 129 + ROI_Y - ROI_HALF),
                      (15 + ROI_X + ROI_HALF, 129 + ROI_Y + ROI_HALF), (0, 216, 255), 2)
        roi = image[ROI_Y - ROI_HALF:ROI_Y + ROI_HALF,
                    ROI_X - ROI_HALF:ROI_X + ROI_HALF]
        enlarged = cv2.resize(roi, (302, 302), interpolation=cv2.INTER_NEAREST)
        canvas[642:944, 183:485] = enlarged
        cv2.rectangle(canvas, (182, 641), (485, 944), (0, 216, 255), 2)
        text(canvas, 'NEEDLE: enlarged crop of SAME image', 15, 634, scale=.58)
    else:
        cv2.rectangle(canvas, (15, 129), (655, 609), (47, 46, 45), -1)
        text(canvas, 'Waiting for post-arrival ROS image', 61, 367, scale=.72)
    x = 690
    text(canvas, 'PROCESS / MODEL', x, 118, scale=.65, color=(158, 216, 255), thick=2)
    stage = state.get('stage', 'WAITING')
    stage_lines = {
        'STARTING': ['New run', 'Previous result cleared'],
        'MOVING_TO_OBSERVE': ['Moving to', 'OBSERVE'],
        'ARRIVED_OBSERVE': ['OBSERVE arrival', 'JointState PASS'],
        'CAMERA_IMAGE_CAPTURED': ['New ROS image', 'CAPTURED'],
        'AI_INFERENCE_RUNNING': ['AI INFERENCE', 'RUNNING...'],
        'AI_RESULT': ['HOG + linear SVM', 'RESULT BELOW'],
        'MOVING_TO_NORMAL_RESPONSE': ['Moving to', 'LEFT response'],
        'MOVING_TO_ABNORMAL_RESPONSE': ['Moving to', 'RIGHT response'],
        'ARRIVED_NORMAL_RESPONSE': ['LEFT response', 'JointState PASS'],
        'ARRIVED_ABNORMAL_RESPONSE': ['RIGHT response', 'JointState PASS'],
        'HOLDING_RESPONSE': ['Response pose', 'HOLD 3 seconds'],
        'MOVING_TO_HOME': ['Returning', 'HOME'],
        'ARRIVED_HOME': ['HOME arrival', 'JointState PASS'],
        'COMPLETE_HOME': ['RUN COMPLETE', 'HOME PASS'],
        'ERROR': ['RUN ABORTED', 'NO DEFAULT LABEL'],
    }.get(stage, [stage[:21], ''])
    cv2.rectangle(canvas, (681, 139), (936, 273), (54, 48, 42), -1)
    text(canvas, stage_lines[0], x, 192, scale=.77, thick=2)
    text(canvas, stage_lines[1], x, 231, scale=.72, color=(121, 226, 251), thick=2)
    inference = state.get('inference')
    if inference:
        label = inference['label'].upper()
        color = (100, 226, 113) if label == 'NORMAL' else (111, 133, 255)
        cv2.rectangle(canvas, (681, 302), (936, 388), (54, 48, 42), -1)
        text(canvas, 'IMAGE AI SAYS', x, 330, scale=.56)
        text(canvas, label, x, 370, scale=1.08, color=color, thick=2)
        text(canvas, f"SVM margin {inference['svm_raw_margin']:+.3f}", x, 421, scale=.57)
    else:
        text(canvas, 'AI result: pending', x, 343, scale=.63)
    cv2.line(canvas, (681, 451), (936, 451), (80, 78, 75), 1)
    text(canvas, 'ROBOT RESPONSE', x, 485, scale=.63, color=(158, 216, 255), thick=2)
    text(canvas, 'NORMAL  -> LEFT', x, 528, scale=.66)
    text(canvas, 'joint1 = -0.5 rad', x, 555, scale=.52)
    text(canvas, 'ABNORMAL -> RIGHT', x, 596, scale=.65)
    text(canvas, 'joint1 = +0.5 rad', x, 623, scale=.52)
    text(canvas, 'Left/right in the', x, 677, scale=.54)
    text(canvas, 'fixed Gazebo view.', x, 703, scale=.54)
    selected = state.get('response_pose')
    if selected:
        text(canvas, 'Selected:', x, 763, scale=.59)
        text(canvas, selected.replace('_', ' '), x, 790, scale=.58,
             color=(121, 226, 251), thick=2)
    info = state.get('image')
    if info:
        text(canvas, 'ROS image UTC:', x, 843, scale=.51)
        text(canvas, str(info['received_at_utc'])[11:23], x, 867, scale=.55)
        text(canvas, 'SHA256 ' + info['image_sha256'][:14], x, 898, scale=.49)
    if error or state.get('error'):
        cv2.rectangle(canvas, (680, 908), (938, 953), (52, 52, 180), -1)
        text(canvas, 'ERROR: ' + str(error or state['error'])[:28], x, 936, scale=.44)
    return canvas


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', type=Path, required=True)
    parser.add_argument('--review-only', action='store_true',
                        help='Show a saved result without adding acknowledgements to its audit')
    args = parser.parse_args()
    run_dir = args.run_dir
    if not run_dir.is_dir() or not run_dir.name.startswith('camera_'):
        parser.error('run directory must be pre-created with a camera_ run ID')
    os.environ.setdefault('DISPLAY', ':0')
    os.environ.setdefault('XAUTHORITY', '/home/ubuntu/.Xauthority')
    gazebo_window = move_gazebo_right()
    cv2.namedWindow(WINDOW, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(WINDOW, WIDTH, HEIGHT)
    cv2.moveWindow(WINDOW, 4, 48)
    state = {'run_id': run_dir.name, 'revision': 0, 'stage': 'WAITING',
             'image': None, 'inference': None}
    cv2.imshow(WINDOW, draw(state, None, None))
    cv2.waitKey(100)
    if not gazebo_above_rviz(gazebo_window):
        raise RuntimeError('Gazebo remains behind RViz; refusing to record/move')
    if not args.review_only:
        atomic_json(run_dir / 'display_ready.json', {'run_id': run_dir.name, 'at_utc': utc(),
                                                      'gazebo_window': gazebo_window,
                                                      'dashboard_size': [WIDTH, HEIGHT],
                                                      'gazebo_above_rviz': True})
    previous_revision = 0
    cached_image_path = None
    cached_image = None
    while True:
        snapshot = run_dir / 'display_state.json'
        if snapshot.exists():
            try:
                incoming = json.loads(snapshot.read_text(encoding='utf-8'))
            except (OSError, json.JSONDecodeError):
                incoming = None
            if incoming and incoming.get('run_id') == run_dir.name and incoming.get('revision', 0) > previous_revision:
                state = incoming
                error = None
                info = state.get('image')
                image_sha = None
                label = (state.get('inference') or {}).get('label')
                try:
                    if info:
                        path = Path(info['image_path'])
                        if path != cached_image_path:
                            image_sha = hashlib.sha256(path.read_bytes()).hexdigest()
                            if image_sha != info['image_sha256']:
                                raise ValueError('camera image SHA-256 mismatch')
                            cached_image = cv2.imread(str(path), cv2.IMREAD_COLOR)
                            if cached_image is None:
                                raise ValueError('camera image could not be decoded')
                            cached_image_path = path
                        else:
                            image_sha = hashlib.sha256(path.read_bytes()).hexdigest()
                            if image_sha != info['image_sha256']:
                                raise ValueError('camera image changed after capture')
                    if state.get('inference') and state['inference'].get('image_sha256') != image_sha:
                        raise ValueError('display image differs from model input image')
                    frame = draw(state, cached_image if info else None, None)
                except Exception as exc:
                    error = f'{type(exc).__name__}: {exc}'
                    frame = draw(state, None, error)
                cv2.imshow(WINDOW, frame)
                cv2.waitKey(80)
                ack = {'run_id': run_dir.name, 'revision': state['revision'],
                       'at_utc': utc(), 'stage': state['stage'],
                       'result': 'FAIL' if error else 'PASS', 'error': error,
                       'image_sha256': image_sha, 'label': label,
                       'response_pose': state.get('response_pose')}
                if not args.review_only:
                    atomic_json(run_dir / 'display_ack.json', ack)
                    with (run_dir / 'display_audit.jsonl').open('a', encoding='utf-8') as handle:
                        handle.write(json.dumps(ack, ensure_ascii=False) + '\n')
                previous_revision = state['revision']
        if cv2.waitKey(40) == 27:
            break
        time.sleep(.04)
    cv2.destroyAllWindows()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
