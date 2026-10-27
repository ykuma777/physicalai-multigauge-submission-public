"""Offline model equivalence and fail-closed checks, never imported by runtime."""
from __future__ import annotations
import argparse
import importlib.util
import json
import tempfile
from pathlib import Path
import cv2
import numpy as np
import vision


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    checks = []
    def expect_reject(name, callback):
        try:
            callback()
        except (ValueError, FileNotFoundError) as exc:
            checks.append({'test': name, 'result': 'PASS', 'rejection': str(exc)})
        else:
            checks.append({'test': name, 'result': 'FAIL', 'rejection': None})
    manifest = json.loads((vision.CAMERA / 'data/dataset_manifest.json').read_text())
    spec = importlib.util.spec_from_file_location('original_vision', vision.CAMERA / 'ros2_ws/src/camera_inspection/camera_inspection/vision_model.py')
    original = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(original)
    original.ROOT = vision.CAMERA
    rows = []
    for row in manifest['rows']:
        path = vision.CAMERA / row['relative_path']
        if vision.sha256(path) != row['sha256']:
            raise ValueError('dataset image hash mismatch')
        actual = vision.classify(path)
        previous = original.classify(path)
        rows.append({'image': row['relative_path'], 'split': row['split'],
                     'truth': row['label'], 'prediction': actual['label'],
                     'correct': actual['label'] == row['label'],
                     'original_prediction': previous['label'],
                     'equivalent': (actual['label'] == previous['label'] and
                                    actual['svm_raw_margin'] == previous['svm_raw_margin']),
                     'image_sha256': actual['image_sha256']})
    checks.append({'test': 'original_model_equivalence_all_saved_images',
                   'result': 'PASS' if all(r['equivalent'] for r in rows) else 'FAIL',
                   'images': len(rows)})
    held_out = [r for r in rows if r['split'] == 'validation']
    checks.append({'test': 'retained_held_out_angle_accuracy',
                   'result': 'PASS' if all(r['correct'] for r in held_out) else 'FAIL',
                   'correct': sum(r['correct'] for r in held_out), 'total': len(held_out)})
    with tempfile.TemporaryDirectory(prefix='multi_vision_test_') as temp:
        temp = Path(temp)
        blank = temp / 'blank.png'
        cv2.imwrite(str(blank), np.zeros((480,640,3), dtype=np.uint8))
        expect_reject('blank_image_rejected', lambda: vision.classify(blank))
        wrong = temp / 'wrong.png'
        cv2.imwrite(str(wrong), np.zeros((48,64,3), dtype=np.uint8))
        expect_reject('wrong_resolution_rejected', lambda: vision.classify(wrong))
        settings, _, descriptor = vision.verified_contract()
        descriptor['settings']['roi_center_xy'][0] += 1
        changed = temp / 'changed.json'
        changed.write_text(json.dumps(descriptor))
        expect_reject('changed_preprocessing_rejected', lambda: vision.verified_contract(changed))
        model_path = vision.MODEL
        bad_model = temp / 'bad_model.yml'
        bad_model.write_bytes(model_path.read_bytes() + b'\n# injected')
        vision.MODEL = bad_model
        try:
            expect_reject('changed_model_rejected', vision.verified_contract)
        finally:
            vision.MODEL = model_path
        runtime_path = vision.RUNTIME
        bad_runtime = temp / 'bad_runtime.yaml'
        bad_runtime.write_bytes(runtime_path.read_bytes() + b'\n# injected')
        vision.RUNTIME = bad_runtime
        try:
            expect_reject('changed_original_training_runtime_rejected', vision.verified_contract)
        finally:
            vision.RUNTIME = runtime_path
    _, _, descriptor = vision.verified_contract()
    result = {'result': 'PASS' if all(c['result'] == 'PASS' for c in checks) else 'FAIL',
              'environment': {'opencv': cv2.__version__, 'numpy': np.__version__},
              'model_sha256': vision.sha256(vision.MODEL),
              'original_runtime_sha256': vision.sha256(vision.RUNTIME),
              'preprocessing_sha256': vision.canonical_hash(descriptor),
              'checks': checks, 'per_image': rows,
              'limitation': 'Existing single-view saved-image regression only; real multigauge ROS observations assessed separately.'}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({k: v for k,v in result.items() if k != 'per_image'}, indent=2))
    return 0 if result['result'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())