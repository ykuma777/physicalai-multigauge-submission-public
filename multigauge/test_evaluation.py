"""Meaningful regression: failed/unfinished setup attempts remain in denominators."""
import json
import argparse
import tempfile
from pathlib import Path
import evaluate


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='multigauge_scoring_') as tmp:
        root = Path(tmp)
        (root / 'truth').mkdir()
        (root / 'runs/runtime_failed').mkdir(parents=True)
        for key, status in [('setup_failed', 'FAIL'), ('runtime_failed', 'PREPARED')]:
            value = {'run_id': key, 'result': status, 'campaign': 'test_fixture',
                     'started_at_utc': '2026-10-27T00:00:00Z',
                     'finished_at_utc': '2026-10-27T00:00:01Z',
                     'targets': {target: {'truth_label': 'normal'} for target in evaluate.IDS}}
            (root / 'truth' / (key + '.json')).write_text(json.dumps(value))
        manifest = {'run_id': 'runtime_failed', 'result': 'FAIL',
                    'started_at_utc': '2026-10-27T00:00:01Z',
                    'finished_at_utc': '2026-10-27T00:00:02Z',
                    'selected_targets': [], 'pointed_targets': [], 'motions': [],
                    'abort_reason': 'fixture: image acquisition failed'}
        (root / 'runs/runtime_failed/run_manifest.json').write_text(json.dumps(manifest))
        report = evaluate.evaluate(root)
        checks = {'two_attempts_retained': report['metrics']['trial_count'] == 2,
                  'all_six_labels_in_denominator': report['metrics']['classification_total'] == 6,
                  'zero_success_rate': report['metrics']['task_success_rate'] == 0,
                  'missing_predictions_not_correct_normal_selections': report['metrics']['selection_correct_trials'] == 0,
                  'no_home_claim': report['metrics']['home_return_pass'] == 0,
                  'no_fake_motion_success': report['metrics']['all_motion_arrivals_trials'] == 0,
                  'coverage_not_fabricated': report['coverage']['missing'] != []}
        synthetic = root / 'runs/header_fixture'
        synthetic.mkdir()
        image = synthetic / 'image.png'
        image.write_bytes(b'synthetic scoring fixture; not a camera image')
        image_hash = evaluate.sha256(image)
        target = {'image': {'image_path': str(image), 'image_sha256': image_hash,
                           'subscription_started_at_utc': '2026-10-27T00:00:01.100Z',
                           'received_at_utc': '2026-10-27T00:00:01.200Z',
                           'header_stamp': {'sec': 10, 'nanosec': 2}},
                  'inference': {'label': 'normal', 'image_sha256': image_hash},
                  'arrival': {'result': 'PASS', 'at_utc': '2026-10-27T00:00:01Z',
                              'joint_state_header': {'stamp': {'sec': 10, 'nanosec': 1}}}}
        manifest['run_id'] = 'runtime_failed'
        manifest['targets'] = {key: target for key in evaluate.IDS}
        manifest_path = synthetic / 'run_manifest.json'
        manifest_path.write_text(json.dumps(manifest))
        fresh = evaluate.score('runtime_failed', manifest_path, root / 'truth/runtime_failed.json')
        checks['newer_simulation_frame_accepted'] = all(not any('simulation' in issue for issue in row['issues']) for row in fresh['image_audit'].values())
        target['image']['header_stamp']['nanosec'] = 1
        manifest_path.write_text(json.dumps(manifest))
        stale = evaluate.score('runtime_failed', manifest_path, root / 'truth/runtime_failed.json')
        checks['equal_simulation_frame_rejected'] = all(any('simulation timestamp was not newer' in issue for issue in row['issues']) for row in stale['image_audit'].values())
        result = {'result': 'PASS' if all(checks.values()) else 'FAIL',
                  'checks': checks, 'fixture_metrics': report['metrics'],
                  'scope': 'Synthetic failure accounting only; excluded from Gazebo experiment results.'}
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
        print(json.dumps(result, indent=2))
        return 0 if result['result'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())