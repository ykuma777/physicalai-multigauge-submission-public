#!/usr/bin/env python3
"""One supervised, recorded camera trial with a live, verified dashboard."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import signal
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import yaml


ROOT = Path('/home/ubuntu/camera_demo')
RUNS = ROOT / 'results/runs'
TRIALS = ROOT / 'results/displayed_trials'
ACTIVE_DASHBOARD = TRIALS / 'active_dashboard.json'


def utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')


def command(argv: list[str], timeout: int) -> subprocess.CompletedProcess:
    result = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError(f'command failed {argv}: {result.stderr[-700:]} {result.stdout[-700:]}')
    return result


def frame(path: Path, env: dict) -> None:
    result = subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-f', 'x11grab',
                             '-video_size', '1920x1080', '-i', ':0', '-frames:v', '1', str(path)],
                            capture_output=True, text=True, timeout=15, env=env)
    if result.returncode:
        raise RuntimeError(f'screen frame capture failed: {result.stderr[-500:]}')


def stop_process(process: subprocess.Popen | None, *, interrupt: bool = False) -> None:
    if process is None or process.poll() is not None:
        return
    if interrupt:
        process.send_signal(signal.SIGINT)
    else:
        process.terminate()
    try:
        process.wait(timeout=20)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def close_previous_dashboard() -> None:
    """Close only the previous task-owned dashboard when a new trial starts."""
    if not ACTIVE_DASHBOARD.exists():
        return
    previous = json.loads(ACTIVE_DASHBOARD.read_text(encoding='utf-8'))
    pid = int(previous['pid'])
    command_line = Path(f'/proc/{pid}/cmdline')
    if not command_line.exists():
        return
    argv = command_line.read_bytes().replace(b'\0', b' ').decode('utf-8', errors='replace')
    if 'camera_demo_dashboard.py' not in argv or previous['run_id'] not in argv:
        raise RuntimeError('previous dashboard PID now belongs to a different process')
    os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + 5
    while command_line.exists() and time.monotonic() < deadline:
        time.sleep(.05)
    if command_line.exists():
        raise TimeoutError('previous task dashboard did not exit')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', choices=['normal', 'abnormal'], required=True,
                        help='Gauge setup truth; never passed to the coordinator or dashboard')
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--confirm-motion', action='store_true')
    args = parser.parse_args()
    if not (args.execute and args.confirm_motion):
        parser.error('both --execute and --confirm-motion are required for one real trial')
    cfg = yaml.safe_load((ROOT / 'configs/runtime.yaml').read_text(encoding='utf-8'))
    if os.environ.get('ROS_DOMAIN_ID') != str(cfg['ros_domain_id']):
        parser.error(f"ROS_DOMAIN_ID must be {cfg['ros_domain_id']}")
    TRIALS.mkdir(parents=True, exist_ok=True)
    close_previous_dashboard()
    run_id = 'camera_display_' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ_') + uuid.uuid4().hex[:6]
    run_dir = RUNS / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    video = TRIALS / (run_id + '_screen.mp4')
    summary_path = TRIALS / (run_id + '_trial.json')
    summary = {'run_id': run_id, 'started_at_utc': utc(), 'truth_for_post_run_validation': args.state,
               'status': 'RUNNING', 'recording': str(video), 'coordinator_exit_code': None}
    save(summary_path, summary)
    dashboard = None
    recorder = None
    video_log = None
    env = dict(os.environ, DISPLAY=':0', XAUTHORITY='/home/ubuntu/.Xauthority')
    try:
        # Stop before changing the gauge if the controller/robot session is unhealthy.
        previous = json.loads(command(['python3', str(ROOT / 'scripts/preflight_camera.py'),
                                       '--expected-pose', 'home'], 55).stdout)
        if previous['result'] != 'PASS':
            raise RuntimeError('initial camera preflight was not PASS')
        setup = json.loads(command(['python3', str(ROOT / 'scripts/set_target_state.py'),
                                    '--state', args.state], 45).stdout)
        save(TRIALS / (run_id + '_target_setup.json'), setup)
        current = json.loads(command(['python3', str(ROOT / 'scripts/preflight_camera.py'),
                                      '--expected-pose', 'home'], 55).stdout)
        if current['result'] != 'PASS':
            raise RuntimeError('preflight after target setup was not PASS')
        save(TRIALS / (run_id + '_preflight.json'), current)
        # The VNC image must stay unobscured during the trial. This affects only
        # the desktop decoration in the isolated camera container.
        saver = subprocess.run(['pkill', '-TERM', '-x', 'mate-screensaver'],
                               capture_output=True, text=True)
        summary['screensaver_exit_code'] = saver.returncode
        subprocess.run(['xset', 's', 'off'], env=env, capture_output=True, timeout=5)
        subprocess.run(['xdg-screensaver', 'reset'], env=env, capture_output=True, timeout=5)
        dashboard_log = (TRIALS / (run_id + '_dashboard.log')).open('w', encoding='utf-8')
        dashboard = subprocess.Popen(['python3', str(ROOT / 'scripts/camera_demo_dashboard.py'),
                                      '--run-dir', str(run_dir)], env=env,
                                     stdout=dashboard_log, stderr=subprocess.STDOUT)
        ready = run_dir / 'display_ready.json'
        deadline = time.monotonic() + 15
        while not ready.exists() and time.monotonic() < deadline:
            if dashboard.poll() is not None:
                raise RuntimeError('dashboard exited before becoming ready')
            time.sleep(.1)
        if not ready.exists():
            raise TimeoutError('dashboard was not ready')
        time.sleep(.5)
        frame(TRIALS / (run_id + '_before.png'), env)
        video_log = (TRIALS / (run_id + '_ffmpeg.log')).open('w', encoding='utf-8')
        recorder = subprocess.Popen(['ffmpeg', '-hide_banner', '-loglevel', 'error',
                                     '-f', 'x11grab', '-framerate', '6',
                                     '-video_size', '1920x1080', '-i', ':0', '-t', '220',
                                     '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '27',
                                     '-pix_fmt', 'yuv420p', str(video)], env=env,
                                    stdout=video_log, stderr=subprocess.STDOUT)
        summary['recording_started_at_utc'] = utc()
        time.sleep(1)
        if recorder.poll() is not None:
            raise RuntimeError('screen recording exited before the coordinator started')
        argv = ['ros2', 'run', 'camera_inspection', 'camera_coordinator',
                '--execute', '--confirm-motion', '--require-display', '--run-id', run_id]
        summary['coordinator_command'] = argv
        print(f'START {run_id}; state prepared, screen recording active', flush=True)
        with (TRIALS / (run_id + '_coordinator_console.log')).open('w', encoding='utf-8') as log:
            result = subprocess.run(argv, stdout=log, stderr=subprocess.STDOUT, timeout=240, env=env)
        summary['coordinator_exit_code'] = result.returncode
        # Preserve the final prediction on-screen through the home return and ending frame.
        time.sleep(3)
        frame(TRIALS / (run_id + '_after.png'), env)
        manifest_path = run_dir / 'run_manifest.json'
        if not manifest_path.exists():
            raise RuntimeError('coordinator did not write a run manifest')
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        audit_path = run_dir / 'display_audit.jsonl'
        display_rows = [json.loads(line) for line in audit_path.read_text(encoding='utf-8').splitlines()]
        image = manifest.get('image') or {}
        inference = manifest.get('inference') or {}
        motions = manifest.get('motions') or []
        required_stages = ['STARTING', 'ARRIVED_OBSERVE', 'CAMERA_IMAGE_CAPTURED',
                           'AI_INFERENCE_RUNNING', 'AI_RESULT', 'HOLDING_RESPONSE',
                           'COMPLETE_HOME']
        stages = [row['stage'] for row in display_rows]
        missing_stages = [stage for stage in required_stages if stage not in stages]
        image_path = Path(image['image_path']) if image.get('image_path') else None
        checks = {
            'coordinator_pass': result.returncode == 0 and manifest.get('result') == 'PASS',
            'display_stages_complete': not missing_stages,
            'display_ack_all_pass': bool(display_rows) and all(row['result'] == 'PASS' for row in display_rows),
            'exact_inference_image': bool(image_path) and sha(image_path) == image.get('image_sha256') == inference.get('image_sha256'),
            'displayed_image_hash_matches': bool(image) and all(
                row['image_sha256'] == image['image_sha256'] for row in display_rows if row.get('image_sha256')),
            'displayed_label_matches': bool(inference) and all(
                row['label'] == inference['label'] for row in display_rows if row.get('label')),
            'motion_from_prediction': bool(inference) and manifest.get('selected_response_pose') ==
                {'normal': 'normal_response', 'abnormal': 'abnormal_response'}.get(inference.get('label')),
            'three_one_time_arrivals': len(motions) == 3 and all(
                m.get('published_commands') == 1 and (m.get('verification') or {}).get('verification_result') == 'PASS'
                for m in motions),
            'home_reached': (manifest.get('final_preflight') or {}).get('result') == 'PASS',
            'hold_at_least_3_sec': (manifest.get('hold') or {}).get('duration_sec', 0) >= 3,
        }
        summary.update({'expected_label': args.state, 'predicted_label': inference.get('label'),
                        'image_classification': 'PASS' if inference.get('label') == args.state else 'FAIL',
                        'selected_response_pose': manifest.get('selected_response_pose'),
                        'image_received_at_utc': image.get('received_at_utc'),
                        'image_sha256': image.get('image_sha256'),
                        'image_path': str(image_path) if image_path else None,
                        'display_stages': stages, 'missing_stages': missing_stages,
                        'checks': checks, 'motion_command_ids': [
                            (m.get('command') or {}).get('command_id') for m in motions],
                        'trajectory_publish_count': sum(m.get('published_commands', 0) for m in motions),
                        'status': 'PASS' if all(checks.values()) else 'FAIL'})
        if not all(checks.values()):
            raise RuntimeError(f'integrated display checks failed: {checks}')
        return 0
    except Exception as exc:
        summary['status'] = 'FAIL'
        summary['error'] = f'{type(exc).__name__}: {exc}'
        print(summary['error'], file=sys.stderr, flush=True)
        return 1
    finally:
        summary['finished_at_utc'] = utc()
        stop_process(recorder, interrupt=True)
        if video_log:
            video_log.close()
        if video.exists() and video.stat().st_size > 0:
            summary['recording_sha256'] = sha(video)
            summary['recording_bytes'] = video.stat().st_size
        if dashboard is not None and dashboard.poll() is None:
            save(ACTIVE_DASHBOARD, {'pid': dashboard.pid, 'run_id': run_id,
                                    'left_open_at_utc': utc()})
            summary['dashboard_left_open_for_review'] = True
        else:
            summary['dashboard_left_open_for_review'] = False
        if dashboard is not None:
            dashboard_log.close()
        save(summary_path, summary)
        print(f"RESULT {summary['status']} {run_id} {summary_path}", flush=True)


if __name__ == '__main__':
    raise SystemExit(main())
