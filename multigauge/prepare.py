#!/usr/bin/env python3
"""Prepare known Gazebo gauges. Truth lives only in this setup/evaluation process.

No inference, target selection, trajectory publication, or automatic mutation
retries occur here. The runtime coordinator must never import this module.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import time
from datetime import datetime, timezone
import xml.etree.ElementTree as ET

import yaml

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT.parent / 'camera_demo/scripts/target_model.py'
sys.path.insert(0, str(SOURCE.parent))
from target_model import build_sdf


def utc():
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    os.replace(tmp, path)


def command(argv, log, timeout=12):
    started = utc()
    try:
        result = subprocess.run(argv, text=True, capture_output=True, timeout=timeout)
        row = {'started_at_utc': started, 'finished_at_utc': utc(), 'argv': argv,
               'returncode': result.returncode, 'stdout': result.stdout, 'stderr': result.stderr}
    except subprocess.TimeoutExpired as exc:
        row = {'started_at_utc': started, 'finished_at_utc': utc(), 'argv': argv,
               'returncode': None, 'error': 'TIMEOUT_NO_RESEND',
               'stdout': str(exc.stdout), 'stderr': str(exc.stderr)}
        with log.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(row, ensure_ascii=False) + '\n')
        raise TimeoutError(f'command timed out; no resend: {argv[0]}') from exc
    with log.open('a', encoding='utf-8') as stream:
        stream.write(json.dumps(row, ensure_ascii=False) + '\n')
    if result.returncode:
        raise RuntimeError(f'command failed; no resend: {argv[0]}: {result.stderr[-500:]}')
    return result.stdout


def entity_poses(world, log):
    raw = command(['ign', 'topic', '-e', '-t', f'/world/{world}/pose/info',
                   '-n', '1', '--json-output'], log)
    # Adjacent messages are possible. Parse each actual JSON document, never infer
    # an entity pose from the requested preparation values.
    decoder = json.JSONDecoder()
    poses = {}
    text = raw.lstrip()
    while text:
        message, end = decoder.raw_decode(text)
        for entity in message.get('pose', []):
            p, q = entity.get('position', {}), entity.get('orientation', {})
            poses[entity.get('name', '')] = {
                'xyz': [float(p.get(k, 0.0)) for k in ('x', 'y', 'z')],
                'quaternion_xyzw': [float(q.get(k, 1.0 if k == 'w' else 0.0)) for k in ('x', 'y', 'z', 'w')],
            }
        text = text[end:].lstrip()
    return poses


def mutation(world, suffix, reqtype, request, log):
    output = command(['ign', 'service', '-s', f'/world/{world}/{suffix}',
                      '--reqtype', reqtype, '--reptype', 'ignition.msgs.Boolean',
                      '--timeout', '3000', '--req', request], log, timeout=8)
    if not re.search(r'\bdata\s*:\s*true\b', output):
        raise RuntimeError(f'{suffix} response was not true; no resend: {output}')


def make_sdf(entity, angle, target):
    # Reuse the historical appearance/needle geometry and extend its physical
    # collision envelope to exactly match the configured MoveIt box.
    model = ET.fromstring(build_sdf({'target_entity': entity}, angle))
    collision = model.find('./model/link/collision[@name="housing_collision"]')
    center = [float(v) for v in target['collision_center_local']]
    size = [float(v) for v in target['collision_dimensions']]
    if len(center) != 3 or len(size) != 3 or any(not math.isfinite(v) for v in center + size) or any(v <= 0 for v in size):
        raise ValueError('invalid shared gauge collision box')
    collision.find('pose').text = ' '.join(map(str, center)) + ' 0 0 0'
    collision.find('./geometry/box/size').text = ' '.join(map(str, size))
    ET.indent(model, space='  ')
    return ET.tostring(model, encoding='unicode', xml_declaration=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--combination', required=True, help='Three symbols in A/B/C order: N normal, A abnormal')
    parser.add_argument('--campaign', default='pilot')
    parser.add_argument('--normal-angle', type=float, default=.045)
    parser.add_argument('--abnormal-angle', type=float, default=.875)
    parser.add_argument('--config', type=Path, default=ROOT / 'configs/motion.yaml')
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,100}', args.run_id):
        parser.error('invalid run ID')
    if not re.fullmatch('[NA]{3}', args.combination):
        parser.error('--combination must be exactly three N/A symbols, in target A/B/C order')
    if any(not math.isfinite(x) or abs(x) > 1.25 for x in (args.normal_angle, args.abnormal_angle)):
        parser.error('angles must be finite within +/-1.25 rad')
    truth_dir = ROOT / 'results/truth'
    truth_dir.mkdir(parents=True, exist_ok=True)
    truth_path = truth_dir / (args.run_id + '.json')
    # x-mode reserves this ID. An existing trial is never overwritten.
    with truth_path.open('x', encoding='utf-8') as stream:
        stream.write('{}\n')
    started = time.monotonic()
    setup_dir = ROOT / 'generated/setup' / args.run_id
    setup_dir.mkdir(parents=True, exist_ok=False)
    log = setup_dir / 'setup_commands.jsonl'
    record = {'schema_version': 1, 'run_id': args.run_id, 'campaign': args.campaign,
              'combination': args.combination, 'started_at_utc': utc(),
              'prepared_at_utc': None, 'finished_at_utc': None, 'result': 'PREPARING',
              'targets': {}, 'commands_path': str(log), 'error': None,
              'program_sha256': sha(__file__), 'source_target_model_sha256': sha(SOURCE),
              'exact_command': shlex.join([sys.executable, *sys.argv])}
    write(truth_path, record)
    try:
        cfg = yaml.safe_load(args.config.read_text(encoding='utf-8-sig'))
        record['config_sha256'] = sha(args.config)
        record['world'] = cfg['world']
        if os.environ.get('ROS_DOMAIN_ID') != str(cfg['ros_domain_id']):
            raise RuntimeError('wrong ROS_DOMAIN_ID; setup stopped before mutation')
        if any(os.environ.get(key) != cfg['partition'] for key in ('IGN_PARTITION', 'GZ_PARTITION')):
            raise RuntimeError('wrong Gazebo communication partition; setup stopped before mutation')
        if set(cfg['targets']) != {'A', 'B', 'C'}:
            raise ValueError('exactly A/B/C targets required')
        for target_id, symbol in zip('ABC', args.combination):
            t = cfg['targets'][target_id]
            record['targets'][target_id] = {
                'truth_label': 'normal' if symbol == 'N' else 'abnormal',
                'needle_angle_rad': args.normal_angle if symbol == 'N' else args.abnormal_angle,
                'entity': t['entity'], 'expected_world_bottom_xyz': t['world_bottom_xyz'],
                'expected_yaw_rad': t['yaw_rad'], 'result': 'PENDING',
                'collision_center_local': t['collision_center_local'],
                'collision_dimensions': t['collision_dimensions'],
            }
        write(truth_path, record)
        available = command(['ign', 'service', '-l'], log).splitlines()
        world = cfg['world']
        for suffix in ('remove', 'create'):
            if f'/world/{world}/{suffix}' not in available:
                raise RuntimeError(f'missing Gazebo {suffix} service')
        existing = entity_poses(world, log)
        for target_id in 'ABC':
            target = cfg['targets'][target_id]
            item = record['targets'][target_id]
            entity = item['entity']
            if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*', entity):
                raise ValueError('unsafe entity name')
            if entity in existing:
                mutation(world, 'remove', 'ignition.msgs.Entity', f'name: "{entity}" type: MODEL', log)
                deadline = time.monotonic() + 10
                while True:
                    poses = entity_poses(world, log)
                    if entity not in poses:
                        break
                    if time.monotonic() > deadline:
                        raise TimeoutError('removed entity remains present; no create attempted')
                    time.sleep(.1)
            sdf_path = setup_dir / (entity + '.sdf')
            sdf_path.write_text(make_sdf(entity, item['needle_angle_rad'], target), encoding='utf-8')
            command(['ign', 'sdf', '-k', str(sdf_path)], log)
            item['sdf_path'], item['sdf_sha256'] = str(sdf_path), sha(sdf_path)
            xyz = [float(v) for v in target['world_bottom_xyz']]
            yaw = float(target['yaw_rad'])
            if len(xyz) != 3 or not all(math.isfinite(v) for v in xyz + [yaw]):
                raise ValueError('invalid target pose')
            qz, qw = math.sin(yaw / 2), math.cos(yaw / 2)
            request = (f'sdf_filename: "{sdf_path}" name: "{entity}" allow_renaming: false '
                       f'pose {{ position {{ x: {xyz[0]} y: {xyz[1]} z: {xyz[2]} }} '
                       f'orientation {{ x: 0 y: 0 z: {qz} w: {qw} }} }}')
            mutation(world, 'create', 'ignition.msgs.EntityFactory', request, log)
            deadline = time.monotonic() + 10
            while True:
                poses = entity_poses(world, log)
                if entity in poses:
                    break
                if time.monotonic() > deadline:
                    raise TimeoutError('created entity is absent; no resend')
                time.sleep(.1)
            actual = poses[entity]
            error = max(abs(a-b) for a,b in zip(xyz, actual['xyz']))
            wanted = [0., 0., qz, qw]
            # q and -q represent the same orientation.
            orientation_error = min(max(abs(a-b) for a,b in zip(wanted, actual['quaternion_xyzw'])),
                                    max(abs(a+b) for a,b in zip(wanted, actual['quaternion_xyzw'])))
            item.update(actual_world_pose=actual, position_error_m=error,
                        quaternion_max_error=orientation_error)
            if error > .002 or orientation_error > .002:
                raise RuntimeError(f'Gazebo pose mismatch for {target_id}: {actual}')
            item['result'] = 'PREPARED'
            existing = poses
            write(truth_path, record)
        record['result'], record['prepared_at_utc'] = 'PREPARED', utc()
        return 0
    except Exception as exc:
        record['result'], record['error'] = 'FAIL', f'{type(exc).__name__}: {exc}'
        return 1
    finally:
        record['finished_at_utc'], record['preparation_elapsed_sec'] = utc(), time.monotonic() - started
        write(truth_path, record)
        print(json.dumps({'run_id': args.run_id, 'result': record['result'],
                          'truth_path': str(truth_path), 'error': record['error']}, ensure_ascii=False))


if __name__ == '__main__':
    raise SystemExit(main())