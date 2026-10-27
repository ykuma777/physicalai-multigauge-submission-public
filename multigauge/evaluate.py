"""Offline scoring; truth is read only after a runtime attempt has finished.

Union of preparation records and runtime attempts defines the denominator. No
failed or incomplete attempt is dropped. Unknown labels count as incorrect in
3-per-trial accuracy; observed-only accuracy is reported separately.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import itertools
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
IDS = ('A', 'B', 'C')
LABELS = {'normal', 'abnormal'}
COMBINATIONS = [''.join(x) for x in itertools.product('NA', repeat=3)]


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def stamp(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00')) if value else None


def read_lines(path):
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]


def score(run_id, run_path, truth_path):
    issues = []
    run = read(run_path) if run_path and run_path.exists() else {}
    truth = read(truth_path) if truth_path and truth_path.exists() else {}
    if not run:
        issues.append('runtime manifest missing: preparation attempt retained')
    if not truth:
        issues.append('separate preparation/truth record missing')
    if run.get('run_id', run_id) != run_id or truth.get('run_id', run_id) != run_id:
        issues.append('run ID mismatch')
    if run.get('result') != 'PASS':
        issues.append('runtime did not complete with PASS')
    if truth.get('result') != 'PREPARED':
        issues.append('target preparation did not complete with PREPARED')
    if run and not run.get('finished_at_utc'):
        issues.append('runtime is unfinished; scoring snapshot is incomplete')
    truth_labels = {key: (truth.get('targets', {}).get(key) or {}).get('truth_label') for key in IDS}
    if any(value not in LABELS for value in truth_labels.values()):
        issues.append('one or more configured truth labels unavailable')
    combination = ''.join('N' if truth_labels[key] == 'normal' else 'A' if truth_labels[key] == 'abnormal' else '?' for key in IDS)
    predictions, image_correct, image_audit = {}, {}, {}
    for key in IDS:
        target = (run.get('targets', {}).get(key) or {})
        inference = target.get('inference') or {}
        image = target.get('image') or {}
        arrival = target.get('arrival') or {}
        prediction = inference.get('label')
        predictions[key] = prediction
        image_correct[key] = prediction in LABELS and prediction == truth_labels[key]
        errors = []
        if not image or not inference:
            errors.append('image or inference missing: indeterminate')
        if prediction not in LABELS:
            errors.append('prediction unavailable or invalid')
        if image.get('image_sha256') != inference.get('image_sha256') or not image.get('image_sha256'):
            errors.append('capture and inference hashes differ or unavailable')
        if image.get('image_path'):
            image_path = Path(image['image_path'])
            if not image_path.exists():
                errors.append('captured image missing on evaluator filesystem')
            elif sha256(image_path) != image.get('image_sha256'):
                errors.append('captured image SHA-256 changed')
        arrival_time = arrival.get('at_utc') or arrival.get('timestamp')
        if arrival.get('result', arrival.get('verification_result')) != 'PASS':
            errors.append('observation arrival not confirmed')
        try:
            if not arrival_time or not image.get('subscription_started_at_utc') or not image.get('received_at_utc'):
                errors.append('fresh capture timestamps missing')
            elif stamp(image['subscription_started_at_utc']) <= stamp(arrival_time) or stamp(image['received_at_utc']) <= stamp(arrival_time):
                errors.append('image subscription or receipt was not after arrival')
        except (TypeError, ValueError):
            errors.append('malformed arrival/capture timestamp')
        image_stamp = image.get('header_stamp') or {}
        joint_stamp = (arrival.get('joint_state_header') or {}).get('stamp') or {}
        try:
            image_nanos = int(image_stamp['sec']) * 1_000_000_000 + int(image_stamp['nanosec'])
            joint_nanos = int(joint_stamp['sec']) * 1_000_000_000 + int(joint_stamp['nanosec'])
            if image_nanos <= joint_nanos:
                errors.append('image simulation timestamp was not newer than arrived JointState')
        except (KeyError, TypeError, ValueError):
            errors.append('simulation image/JointState freshness timestamps missing or invalid')
        image_audit[key] = {'result': 'PASS' if not errors else 'FAIL', 'issues': errors,
                            'image_sha256': image.get('image_sha256'),
                            'received_at_utc': image.get('received_at_utc'),
                            'arrival_at_utc': arrival_time,
                            'image_header_stamp': image_stamp, 'arrival_joint_state_stamp': joint_stamp}
        issues.extend(f'{key}: {error}' for error in errors)
    expected = [key for key in IDS if truth_labels[key] == 'abnormal']
    selected = run.get('selected_targets') or []
    pointed = run.get('pointed_targets') or []
    truth_complete = all(value in LABELS for value in truth_labels.values())
    selection_correct = truth_complete and all(value in LABELS for value in predictions.values()) and 'selected_targets' in run and len(selected) == len(set(selected)) and set(selected) == set(expected)
    pointing_correct = truth_complete and all(value in LABELS for value in predictions.values()) and 'pointed_targets' in run and pointed == expected
    if not selection_correct:
        issues.append('selected abnormal target set incorrect or indeterminate')
    if not pointing_correct:
        issues.append('completed pointing sequence differs from expected A/B/C order')
    motions = run.get('motions') or []
    arrivals = []
    for motion in motions:
        arrival = motion.get('arrival') or {}
        passed = arrival.get('result', arrival.get('verification_result')) == 'PASS'
        sent_once = motion.get('publish_count') == 1
        arrivals.append({'from': motion.get('from'), 'to': motion.get('to'),
                         'command_id': motion.get('command_id'), 'arrival_pass': passed,
                         'publish_once': sent_once})
        if not passed:
            issues.append(f'motion arrival failed: {motion.get("to")}')
        if not sent_once:
            issues.append(f'motion was not sent exactly once: {motion.get("to")}')
    expected_sequence = ['observe_A', 'observe_B', 'observe_C'] + ['point_' + key for key in expected] + ['home']
    sequence_correct = [motion.get('to') for motion in motions] == expected_sequence
    if not sequence_correct:
        issues.append('motion sequence incomplete or differs from expected observed/pointed/home sequence')
    all_arrived = bool(motions) and all(row['arrival_pass'] and row['publish_once'] for row in arrivals)
    home = (run.get('home_return') or {}).get('result') == 'PASS'
    if not home:
        issues.append('home return not confirmed')
    display_audit = []
    if run_path:
        display_audit = read_lines(run_path.parent / 'display_audit.jsonl')
    display_ok = bool(display_audit) and all(row.get('run_id') == run_id and row.get('result') == 'PASS' for row in display_audit)
    displayed = {}
    for key in IDS:
        image_hash = (run.get('targets', {}).get(key, {}).get('image') or {}).get('image_sha256')
        displayed[key] = bool(image_hash and any(row.get('image_hashes', {}).get(key) == image_hash and row.get('labels', {}).get(key) == predictions[key] for row in display_audit))
    display_ok = display_ok and all(displayed.values())
    if not display_ok:
        issues.append('display hash/label audit missing, failed, or incomplete')
    started = truth.get('started_at_utc') or run.get('started_at_utc')
    finished = run.get('finished_at_utc') or truth.get('finished_at_utc') or truth.get('prepared_at_utc')
    try:
        elapsed = (stamp(finished) - stamp(started)).total_seconds() if started and finished else None
    except (TypeError, ValueError):
        elapsed = None
        issues.append('elapsed time unavailable due malformed timestamp')
    runtime_elapsed = run.get('elapsed_sec')
    success = not issues and all(image_correct.values())
    if not all(image_correct.values()):
        issues.append('one or more image labels incorrect or indeterminate')
    return {'run_id': run_id, 'campaign': truth.get('campaign', 'unspecified'),
            'combination': combination, 'runtime_result': run.get('result', 'MISSING'),
            'preparation_result': truth.get('result', 'MISSING'),
            'truth_labels': truth_labels, 'predictions': predictions, 'image_correct': image_correct,
            'image_correct_count': sum(image_correct.values()), 'image_total': 3,
            'image_observed_count': sum(p in LABELS for p in predictions.values()),
            'image_audit': image_audit, 'expected_targets': expected,
            'selected_targets': selected, 'pointed_targets': pointed,
            'selection_correct': selection_correct, 'pointing_correct': pointing_correct,
            'motion_arrivals_pass': sum(row['arrival_pass'] for row in arrivals),
            'motion_arrivals_total': len(arrivals), 'motions': arrivals,
            'all_motion_arrivals': all_arrived, 'motion_sequence_correct': sequence_correct,
            'home_return': home, 'display_audit_pass': display_ok,
            'task_success': success, 'elapsed_sec': elapsed, 'runtime_elapsed_sec': runtime_elapsed,
            'started_at_utc': started, 'finished_at_utc': finished,
            'abort_reason': run.get('abort_reason') or truth.get('abort_reason') or truth.get('error'),
            'issues': issues, 'runtime_manifest': str(run_path) if run_path else None,
            'truth_record': str(truth_path) if truth_path else None,
            'runtime_manifest_sha256': sha256(run_path) if run_path and run_path.exists() else None,
            'truth_record_sha256': sha256(truth_path) if truth_path and truth_path.exists() else None}


def metrics(rows):
    count = len(rows)
    correct = sum(row['image_correct_count'] for row in rows)
    total = 3 * count
    observed = sum(row['image_observed_count'] for row in rows)
    return {'trial_count': count, 'classification_correct': correct, 'classification_total': total,
            'classification_accuracy': correct / total if total else None,
            'observed_classification_total': observed,
            'observed_only_classification_accuracy': correct / observed if observed else None,
            'selection_correct_trials': sum(row['selection_correct'] for row in rows),
            'pointing_correct_trials': sum(row['pointing_correct'] for row in rows),
            'motion_arrivals_pass': sum(row['motion_arrivals_pass'] for row in rows),
            'motion_arrivals_total': sum(row['motion_arrivals_total'] for row in rows),
            'all_motion_arrivals_trials': sum(row['all_motion_arrivals'] for row in rows),
            'home_return_pass': sum(row['home_return'] for row in rows),
            'task_success_trials': sum(row['task_success'] for row in rows),
            'task_success_rate': sum(row['task_success'] for row in rows) / count if count else None,
            'elapsed_sec_total': sum(row['elapsed_sec'] or 0 for row in rows),
            'elapsed_sec_mean': sum(row['elapsed_sec'] or 0 for row in rows) / count if count else None}


def evaluate(results):
    run_paths = {path.parent.name: path for path in (results / 'runs').glob('*/run_manifest.json')}
    truth_paths = {path.stem: path for path in (results / 'truth').glob('*.json')}
    infrastructure = []
    for path in sorted((results / 'runs').iterdir()) if (results / 'runs').exists() else []:
        if not path.is_dir() or path.name in run_paths or path.name in truth_paths:
            continue
        final = path / 'FINAL_STATE.json'
        error = path / 'runner_error.txt'
        if final.exists() or error.exists():
            infrastructure.append({'run_id': path.name,
                'classification': 'INFRASTRUCTURE_BEFORE_TARGET_PREPARATION',
                'included_in_trial_denominator': False,
                'reason': 'No target preparation or runtime manifest; retained separately.',
                'final_state': read(final) if final.exists() else None,
                'error': error.read_text(encoding='utf-8').strip() if error.exists() else None,
                'run_directory': str(path)})
    rows = [score(key, run_paths.get(key), truth_paths.get(key)) for key in sorted(set(run_paths) | set(truth_paths))]
    by_campaign = defaultdict(list)
    for row in rows:
        by_campaign[row['campaign']].append(row)
    covered = sorted(set(row['combination'] for row in rows if '?' not in row['combination']))
    runtime_covered = sorted(set(row['combination'] for row in rows if row['runtime_result'] != 'MISSING' and '?' not in row['combination']))
    success_covered = sorted(set(row['combination'] for row in rows if row['task_success']))
    return {'result': 'PASS' if rows and all(row['task_success'] for row in rows) and set(runtime_covered) == set(COMBINATIONS) else 'PARTIAL',
            'evaluated_at_utc': datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00','Z'),
            'denominator_policy': 'Every preparation or runtime attempt; three image labels per attempt; missing labels count incorrect. No unsuccessful attempt is removed.',
            'label_legend': {'N': 'normal', 'A': 'abnormal'},
            'metrics': metrics(rows),
            'coverage': {'combinations_expected': COMBINATIONS, 'combinations_preparation_attempted': covered,
                         'combinations_executed': runtime_covered, 'combinations_successful': success_covered,
                         'missing': sorted(set(COMBINATIONS)-set(runtime_covered))},
            'by_campaign': {key: metrics(value) for key, value in by_campaign.items()},
            'runs': rows, 'infrastructure_attempts': infrastructure,
            'limitations': ['Finite known-pose Gazebo trials; no hardware/general-domain performance estimate.',
                            'The configured truth record is offline preparation evidence, never an inference input.',
                            'Elapsed time includes preparation and stops at home/abort; failed trials may be shorter.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--results', type=Path, default=ROOT / 'results')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    output = args.output or args.results / 'evaluation.json'
    report = evaluate(args.results)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    with output.with_suffix('.csv').open('w', encoding='utf-8-sig', newline='') as handle:
        columns = ['run_id','campaign','combination','runtime_result','preparation_result',
                   'image_correct_count','image_total','selection_correct','pointing_correct',
                   'motion_arrivals_pass','motion_arrivals_total','home_return','task_success','elapsed_sec','abort_reason']
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(report['runs'])
    print(json.dumps({key: value for key,value in report.items() if key != 'runs'}, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())