#!/usr/bin/env python3
"""Post-run audit only; expected labels never enter the runtime coordinator."""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path


def timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


def check(run_dir: Path, expected: str) -> dict:
    run = json.loads((run_dir / 'run_manifest.json').read_text(encoding='utf-8'))
    image = run['image']
    motions = run['motions']
    issues = []
    if run['result'] != 'PASS':
        issues.append('runtime result is not PASS')
    if len(motions) != 3:
        issues.append('expected exactly 3 trajectory sends')
    else:
        if [m['to'] for m in motions] != ['observe', f'{expected}_response', 'home']:
            issues.append('motion sequence differs from expected image-selected branch')
        for m in motions:
            if m['published_commands'] != 1 or m['command']['publish_count'] != 1:
                issues.append(f'not exactly one publish for {m["to"]}')
            if m['verification']['verification_result'] != 'PASS':
                issues.append(f'arrival failed for {m["to"]}')
    if run['inference']['label'] != expected:
        issues.append('inference differs from separate configured ground truth')
    if run['selected_response_pose'] != f'{expected}_response':
        issues.append('selected response does not match image inference')
    arrival = timestamp(motions[0]['verification']['timestamp'])
    image_received = timestamp(image['received_at_utc'])
    if image_received <= arrival or timestamp(image['subscription_started_at_utc']) <= arrival:
        issues.append('image was not newly subscribed and received after arrival')
    if run['inference']['image_sha256'] != image['image_sha256']:
        issues.append('inference image hash differs from saved camera image')
    hold = run.get('hold') or {}
    if hold.get('duration_sec', 0) < 3:
        issues.append('response hold shorter than 3 seconds')
    if run['final_preflight']['result'] != 'PASS':
        issues.append('final preflight did not confirm home')
    return {'run_id': run['run_id'], 'configured_ground_truth': expected,
            'ground_truth_source': 'set_target_state.py --state argument, separate from coordinator',
            'result': 'PASS' if not issues else 'FAIL', 'issues': issues,
            'observation_arrival_utc': motions[0]['verification']['timestamp'],
            'image_received_utc': image['received_at_utc'],
            'image_sha256': image['image_sha256'], 'predicted_label': run['inference']['label'],
            'response_pose': run['selected_response_pose'],
            'motion_command_ids': [m['command']['command_id'] for m in motions],
            'published_trajectories': sum(m['published_commands'] for m in motions),
            'hold_sec': hold.get('duration_sec'), 'home_preflight': run['final_preflight']['result']}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--normal-run', type=Path, required=True)
    parser.add_argument('--abnormal-run', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    rows = [check(args.normal_run, 'normal'), check(args.abnormal_run, 'abnormal')]
    result = {'runs': rows, 'result': 'PASS' if all(row['result'] == 'PASS' for row in rows) else 'FAIL',
              'limitation': 'Gazebo target/table are not MoveIt world collision objects; contact sensor and real hardware were not tested.'}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, indent=2))
    return 0 if result['result'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
