"""One-target camera demo. Ground truth is deliberately absent from this process."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import yaml

from .vision_model import classify


ROOT = Path('/home/ubuntu/camera_demo')
AUDIT = Path('/home/ubuntu/final_project/results/trajectory_commands.jsonl')
POSES = ROOT / 'configs/poses.yaml'
RUNTIME = ROOT / 'configs/runtime.yaml'


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')


def write_atomic(path: Path, value: object) -> None:
    """Publish a complete display snapshot so the GUI never reads half a JSON file."""
    temporary = path.with_name(path.name + '.tmp')
    write(temporary, value)
    os.replace(temporary, path)


def command(argv: list[str], timeout: float, log_path: Path) -> subprocess.CompletedProcess:
    result = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    with log_path.open('a', encoding='utf-8') as handle:
        handle.write(json.dumps({'at_utc': now(), 'argv': argv, 'returncode': result.returncode,
                                 'stdout': result.stdout, 'stderr': result.stderr}, ensure_ascii=False) + '\n')
    if result.returncode:
        raise RuntimeError(f"command failed ({result.returncode}): {' '.join(argv)}; {result.stderr[-500:]}")
    return result


def audit_rows() -> list[dict]:
    if not AUDIT.exists():
        return []
    return [json.loads(line) for line in AUDIT.read_text(encoding='utf-8').splitlines() if line.strip()]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--confirm-motion', action='store_true')
    parser.add_argument('--run-id')
    parser.add_argument('--require-display', action='store_true',
                        help='Wait for the on-screen dashboard to acknowledge each visible state')
    args = parser.parse_args()
    cfg = yaml.safe_load(RUNTIME.read_text(encoding='utf-8'))
    poses = yaml.safe_load(POSES.read_text(encoding='utf-8'))
    run_id = args.run_id or 'camera_' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ_') + uuid.uuid4().hex[:8]
    if '/' in run_id or '\\' in run_id or run_id in ('.', '..'):
        parser.error('invalid run ID')
    run_dir = ROOT / 'results/runs' / run_id
    if args.require_display and run_dir.is_dir():
        # The runner starts the screen first. Only its ready marker may exist.
        if {path.name for path in run_dir.iterdir()} != {'display_ready.json'}:
            raise RuntimeError(f'display run directory is not fresh: {run_dir}')
    else:
        run_dir.mkdir(parents=True, exist_ok=False)
    events = run_dir / 'execution_log.jsonl'
    motion_file = run_dir / 'motions.jsonl'
    display_file = run_dir / 'display_state.json'
    display_ack = run_dir / 'display_ack.json'
    display_revision = 0
    manifest = {'run_id': run_id, 'started_at_utc': now(), 'finished_at_utc': None,
                'mode': 'execute' if args.execute else 'dry_run', 'result': 'RUNNING',
                'runtime_config_sha256': digest(RUNTIME), 'poses_sha256': digest(POSES),
                'model_sha256': digest(Path(cfg['model_path'])),
                'target_entity': cfg['target_entity'], 'camera_topic': cfg['camera_topic'],
                'motions': [], 'image': None, 'inference': None,
                'selected_response_pose': None, 'abort_reason': None}
    write(run_dir / 'run_manifest.json', manifest)

    def display(stage: str, *, image: dict | None = None, inference: dict | None = None,
                response_pose: str | None = None, arrival: str | None = None,
                error: str | None = None) -> None:
        nonlocal display_revision
        display_revision += 1
        value = {'run_id': run_id, 'revision': display_revision, 'at_utc': now(),
                 'stage': stage, 'image': image, 'inference': inference,
                 'response_pose': response_pose, 'joint_arrival': arrival,
                 'error': error}
        write_atomic(display_file, value)
        with (run_dir / 'display_trace.jsonl').open('a', encoding='utf-8') as handle:
            handle.write(json.dumps(value, ensure_ascii=False) + '\n')
        if not args.require_display:
            return
        deadline = time.monotonic() + 8.0
        while time.monotonic() < deadline:
            if display_ack.exists():
                try:
                    ack = json.loads(display_ack.read_text(encoding='utf-8'))
                except (OSError, json.JSONDecodeError):
                    time.sleep(0.05)
                    continue
                if ack.get('run_id') == run_id and ack.get('revision') == display_revision:
                    if ack.get('result') != 'PASS':
                        raise RuntimeError(f'dashboard could not display {stage}: {ack.get("error")}')
                    if image and ack.get('image_sha256') != image.get('image_sha256'):
                        raise RuntimeError('dashboard displayed image hash differs from inference image')
                    if inference and ack.get('label') != inference.get('label'):
                        raise RuntimeError('dashboard label differs from model prediction')
                    return
            time.sleep(0.05)
        raise TimeoutError(f'dashboard did not acknowledge {stage}')


    def event(name: str, **values) -> None:
        row = {'at_utc': now(), 'event': name, **values}
        with events.open('a', encoding='utf-8') as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + '\n')
        print(json.dumps(row, ensure_ascii=False), flush=True)

    def preflight(expected: str) -> dict:
        report = run_dir / f'preflight_{expected}_{len(manifest["motions"])}.json'
        command(['python3', str(ROOT / 'scripts/preflight_camera.py'),
                 '--expected-pose', expected, '--report', str(report)], 45, events)
        state = json.loads(report.read_text(encoding='utf-8'))
        if state['result'] != 'PASS':
            raise RuntimeError(f'preflight failed at {expected}')
        return state

    def move(source: str, target: str) -> None:
        display('MOVING_TO_' + target.upper(), image=manifest['image'],
                inference=manifest['inference'], response_pose=manifest['selected_response_pose'])
        preflight(source)
        path_report = run_dir / f'path_{source}_to_{target}.json'
        command(['python3', str(ROOT / 'scripts/check_motion_path.py'), '--from-pose', source,
                 '--to-pose', target, '--report', str(path_report)], 240, events)
        path = json.loads(path_report.read_text(encoding='utf-8'))
        if path['verdict'] != 'PARTIAL_PASS_SUPERVISED_GAZEBO':
            raise RuntimeError(f'path preflight rejected {source} to {target}')
        previous = audit_rows()
        previous_ids = {row['command_id'] for row in previous if row.get('event') == 'trajectory_command'}
        argv = ['ros2', 'run', 'inspection_task', 'pose_publisher', '--ros-args',
                '-p', f'config_path:={POSES}', '-p', f'pose_name:={target}',
                '-p', 'dry_run:=false', '-p', 'confirm_motion:=true',
                '-p', f'duration_sec:={float(cfg["motion_duration_sec"])}',
                '-p', 'verify_joint_states:=true', '-p',
                f'tolerance_rad:={float(cfg["observation_tolerance_rad"])}', '-p',
                f'verification_timeout_sec:={float(cfg["verification_timeout_sec"])}']
        # Do not retry this call, even if it returns an error or times out.
        try:
            command(argv, float(cfg['motion_duration_sec']) + float(cfg['verification_timeout_sec']) + 25, events)
        finally:
            rows = audit_rows()
            sent = [row for row in rows if row.get('event') == 'trajectory_command'
                    and row.get('command_id') not in previous_ids]
            checks = [row for row in rows if row.get('event') == 'joint_state_verification'
                      and sent and row.get('command_id') == sent[0].get('command_id')]
            entry = {'from': source, 'to': target, 'published_commands': len(sent),
                     'command': sent[0] if len(sent) == 1 else None,
                     'verification': checks[-1] if checks else None}
            with motion_file.open('a', encoding='utf-8') as handle:
                handle.write(json.dumps(entry, ensure_ascii=False) + '\n')
            manifest['motions'].append(entry)
            write(run_dir / 'run_manifest.json', manifest)
        if len(sent) != 1 or sent[0].get('publish_count') != 1 or len(checks) != 1 or checks[0].get('verification_result') != 'PASS':
            raise RuntimeError(f'motion audit or joint arrival failed for {target}')
        event('motion_arrived', pose=target, command_id=sent[0]['command_id'])
        display('ARRIVED_' + target.upper(), image=manifest['image'],
                inference=manifest['inference'], response_pose=manifest['selected_response_pose'],
                arrival=checks[0]['verification_result'])

    try:
        # A new run clears the previous image and decision before any robot movement.
        display('STARTING')
        if os.environ.get('ROS_DOMAIN_ID') != str(cfg['ros_domain_id']):
            raise RuntimeError('wrong ROS domain')
        if args.execute != args.confirm_motion:
            raise RuntimeError('execution requires both --execute and --confirm-motion')
        if not args.execute:
            manifest['plan'] = ['home -> observe', 'capture a fresh ROS camera image after arrival',
                                'classify image', 'observe -> normal_response OR abnormal_response',
                                'hold', 'response -> home']
            manifest['result'] = 'DRY_RUN_PASS_NO_PUBLISH'
            event('dry_run_plan', plan=manifest['plan'], publish_count=0)
            return 0
        preflight('home')
        move('home', 'observe')
        observation = run_dir / 'observation.png'
        command(['ros2', 'run', 'camera_inspection', 'capture_image',
                 '--topic', cfg['camera_topic'], '--output', str(observation),
                 '--timeout-sec', str(cfg['image_timeout_sec']),
                 '--minimum-image-std', str(cfg['minimum_image_std'])], 35, events)
        image_data = json.loads(observation.with_suffix('.json').read_text(encoding='utf-8'))
        arrival = manifest['motions'][-1]['verification']['timestamp']
        if image_data['subscription_started_at_utc'] <= arrival or image_data['received_at_utc'] <= arrival:
            raise RuntimeError('camera image was not acquired after observation arrival')
        manifest['image'] = image_data
        write(run_dir / 'run_manifest.json', manifest)
        event('camera_image_acquired_after_arrival', image_sha256=image_data['image_sha256'])
        display('CAMERA_IMAGE_CAPTURED', image=image_data, arrival='PASS')
        time.sleep(0.5)
        display('AI_INFERENCE_RUNNING', image=image_data, arrival='PASS')
        time.sleep(0.8)
        inference = classify(observation)
        if inference.get('image_sha256') != image_data['image_sha256']:
            raise RuntimeError('model input image hash differs from captured ROS image')
        manifest['inference'] = inference
        write(run_dir / 'inference.json', inference)
        event('image_inference', label=inference['label'], margin=inference['svm_raw_margin'])
        selected = {'normal': 'normal_response', 'abnormal': 'abnormal_response'}.get(inference['label'])
        if selected not in poses['poses']:
            raise RuntimeError('model returned an unsupported response')
        manifest['selected_response_pose'] = selected
        display('AI_RESULT', image=image_data, inference=inference,
                response_pose=selected, arrival='PASS')
        move('observe', selected)
        display('HOLDING_RESPONSE', image=image_data, inference=inference,
                response_pose=selected, arrival='PASS')
        hold_started = now()
        time.sleep(max(3.0, float(cfg['hold_sec'])))
        manifest['hold'] = {'started_at_utc': hold_started, 'finished_at_utc': now(),
                            'duration_sec': max(3.0, float(cfg['hold_sec']))}
        event('response_held', pose=selected, duration_sec=manifest['hold']['duration_sec'])
        move(selected, 'home')
        manifest['final_preflight'] = preflight('home')
        manifest['result'] = 'PASS'
        display('COMPLETE_HOME', image=image_data, inference=inference,
                response_pose=selected, arrival='PASS')
        event('run_complete', result='PASS')
        return 0
    except Exception as exc:
        manifest['result'] = 'FAIL'
        manifest['abort_reason'] = f'{type(exc).__name__}: {exc}'
        try:
            display('ERROR', image=manifest['image'], inference=manifest['inference'],
                    response_pose=manifest['selected_response_pose'], error=manifest['abort_reason'])
        except Exception as display_exc:
            event('display_error', reason=str(display_exc))
        event('run_aborted', reason=manifest['abort_reason'])
        return 1
    finally:
        manifest['finished_at_utc'] = now()
        write(run_dir / 'run_manifest.json', manifest)


if __name__ == '__main__':
    sys.exit(main())
