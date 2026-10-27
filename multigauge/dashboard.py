#!/usr/bin/env python3
"""Display only coordinator snapshots; acknowledge the exact decoded input images.

No setup file, needle state, expected label or scoring result is read here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
WIDTH, HEIGHT = 950, 970
WINDOW = 'MULTI-GAUGE | ROS camera + HOG/SVM'
IDS = ('A', 'B', 'C')


def utc():
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')


def atomic_json(path, value):
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    os.replace(temporary, path)


@lru_cache(maxsize=32)
def japanese_font(size):
    candidates = (Path('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc'),
                  Path('/usr/share/fonts/opentype/noto/NotoSansCJKjp-Regular.otf'))
    for path in candidates:
        if path.is_file():
            return ImageFont.truetype(str(path), size, index=0)
    raise RuntimeError('Japanese Noto CJK font required; refusing an unreadable display')


@lru_cache(maxsize=512)
def text_sprite(value, size, color):
    font = japanese_font(size)
    left, top, right, bottom = font.getbbox(value)
    sprite = Image.new('RGBA', (max(1, right-left), max(1, bottom-top)), (0, 0, 0, 0))
    ImageDraw.Draw(sprite).text((-left, -top), value, font=font, fill=(*color[::-1], 255))
    return np.asarray(sprite)


def text(canvas, value, x, y, size=19, color=(230, 233, 237)):
    """Japanese text, with cached antialiased glyph sprites; x/y is the top left."""
    sprite = text_sprite(str(value), int(size), tuple(color))
    height, width = sprite.shape[:2]
    width, height = min(width, canvas.shape[1]-x), min(height, canvas.shape[0]-y)
    if width <= 0 or height <= 0:
        return
    alpha = sprite[:height, :width, 3:4].astype(np.float32)/255
    pixels = sprite[:height, :width, :3][:, :, ::-1]
    area = canvas[y:y+height, x:x+width]
    area[:] = (pixels*alpha+area*(1-alpha)).astype(np.uint8)



def verify_images(state, run_dir):
    """Decode the same byte buffer that was hashed, avoiding a check/read race."""
    images, image_hashes, labels = {}, {}, {}
    targets = state.get('targets', {})
    if set(targets) != set(IDS):
        raise ValueError('snapshot must contain exactly target IDs A, B, C')
    for target in IDS:
        row = targets[target]
        info, inference = row.get('image'), row.get('inference')
        labels[target] = inference.get('label') if inference else None
        if inference and not info:
            raise ValueError(f'{target}: inference exists without a captured image')
        if inference and inference.get('label') not in ('normal', 'abnormal'):
            raise ValueError(f'{target}: unsupported image classification label')
        if info:
            path = Path(info['image_path'])
            if not path.resolve().is_relative_to(run_dir.resolve()):
                raise ValueError(f'{target}: image outside this run directory')
            data = path.read_bytes()
            image_hashes[target] = hashlib.sha256(data).hexdigest()
            if image_hashes[target] != info['image_sha256']:
                raise ValueError(f'{target}: displayed image SHA-256 mismatch')
            image = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
            if image is None or image.shape != (480, 640, 3):
                raise ValueError(f'{target}: unreadable or wrong-size ROS image')
            images[target] = image
        else:
            image_hashes[target] = None
        if inference and inference.get('image_sha256') != image_hashes[target]:
            raise ValueError(f'{target}: display and inference input differ')
    selected = state.get('selected_targets', [])
    if not isinstance(selected, list) or any(x not in IDS for x in selected):
        raise ValueError('invalid selected target IDs')
    if selected != sorted(set(selected)):
        raise ValueError('selected targets must be unique and ordered A, B, C')
    return images, image_hashes, labels


LABEL_JA = {'normal': '正常', 'abnormal': '異常'}
STATUS_JA = {'PENDING': '判定待ち', 'MOVING': '観測姿勢へ移動中',
             'ARRIVED': '到達確認済み・撮影待ち', 'CAPTURED': '画像取得済み',
             'INFERENCE': 'AI判定中', 'COMPLETE': '判定済み',
             'UNDETERMINED': '判定不能'}
SELECTION_STAGES = ('SELECTION_COMPLETE', 'MOVING_TO_POINT', 'POINTING',
                    'HOLDING_POINTER', 'NO_ABNORMALITY', 'MOVING_TO_HOME', 'COMPLETE_HOME')
OBSERVATION_STAGES = ('MOVING_TO_OBSERVE', 'ARRIVED_OBSERVE', 'CAMERA_IMAGE_CAPTURED',
                      'AI_INFERENCE_RUNNING', 'AI_RESULT')


def display_text(state, error=None):
    """Presentation from the same runtime snapshot only; never reads scoring inputs."""
    stage = state.get('stage', 'WAITING')
    current, pointer = state.get('current_target'), state.get('pointing_target')
    stopped = bool(error or state.get('error') or stage == 'ERROR')
    phase, detail = '開始待ち：前の試行の表示を消去済み', 'A → B → C の順に新しい画像で点検します'
    if stage == 'STARTING':
        phase, detail = '点検開始：初期姿勢を確認', 'この試行の画像とAI判定を順に記録します'
    elif stage in OBSERVATION_STAGES:
        phase = f'点検中：ゲージ{current or "?"}を撮影・判定'
        detail = {'MOVING_TO_OBSERVE': '観測姿勢へ移動中',
                  'ARRIVED_OBSERVE': '移動先への到達：確認済み・新画像を取得します',
                  'CAMERA_IMAGE_CAPTURED': '到達後の新しいROS画像を取得済み',
                  'AI_INFERENCE_RUNNING': '取得した画像をAIが判定中',
                  'AI_RESULT': 'この画像のAI判定を記録済み'}[stage]
    elif stage == 'SELECTION_COMPLETE':
        phase, detail = '点検完了：画像判定から指示対象を確定', '次の移動は結果の指示です（再点検ではありません）'
    elif stage == 'MOVING_TO_POINT':
        phase, detail = f'指示姿勢へ移動中：ゲージ{pointer or "?"}', '移動先への到達：確認中（まだ指示姿勢に到達していません）'
    elif stage in ('POINTING', 'HOLDING_POINTER'):
        phase, detail = f'指示中：ゲージ{pointer or "?"}', '移動先への到達：確認済み・点検結果を知らせています'
    elif stage == 'NO_ABNORMALITY':
        phase, detail = '異常なし：指示動作をせず初期姿勢へ', '3台ともAI判定が正常のため、指示対象はありません'
    elif stage == 'MOVING_TO_HOME':
        phase, detail = '初期姿勢へ復帰中', '移動先への到達：確認中'
    elif stage == 'COMPLETE_HOME':
        phase, detail = '完了：初期姿勢へ復帰・到達確認済み', '3台の画像とAI判定を保持して、この試行を終了しました'
    elif stage not in ('WAITING', 'STARTING'):
        phase, detail = '表示の診断中', str(stage)
    if stopped:
        phase, detail = '処理停止：後続動作を停止しました', '判定不能または検証失敗です。自動撮り直し・動作再送は行いません'
    summary = []
    for target in IDS:
        row = state.get('targets', {}).get(target, {})
        label = (row.get('inference') or {}).get('label')
        status = '判定不能' if error or row.get('status') == 'UNDETERMINED' else LABEL_JA.get(label, '判定待ち')
        summary.append(target + status)
    selected = state.get('selected_targets', [])
    if stopped:
        choice = '判定不能・処理停止' + ('（確定済み：' + '・'.join(selected) + '）' if selected else '')
    elif stage not in SELECTION_STAGES:
        choice = '確定待ち'
    else:
        choice = '・'.join(selected) if selected else 'なし（異常なし）'
    active = pointer if stage in ('MOVING_TO_POINT', 'POINTING', 'HOLDING_POINTER') else (current if stage in OBSERVATION_STAGES else None)
    return {'phase': phase, 'detail': detail, 'summary': '点検結果：'+'／'.join(summary),
            'selection': '指示対象：'+choice, 'active': active, 'stopped': stopped}


def draw(state, images, error=None, roi_center=(320, 310), roi_size=192):
    canvas = np.full((HEIGHT, WIDTH, 3), (27, 24, 22), np.uint8)
    wording = display_text(state, error)
    cv2.rectangle(canvas, (0, 0), (WIDTH, 183), (49, 37, 29), -1)
    text(canvas, '3台のゲージを自動点検し、異常箇所を指し示すロボット', 17, 10, 26, (255, 233, 200))
    text(canvas, wording['phase'], 17, 48, 28, (126, 223, 255) if not wording['stopped'] else (131, 153, 255))
    text(canvas, wording['detail'], 17, 85, 19)
    text(canvas, wording['summary'], 17, 112, 23)
    text(canvas, wording['selection'], 17, 144, 24, (128, 232, 170))
    text(canvas, 'RUN '+str(state['run_id']), 520, 163, 12, (174, 180, 186))
    text(canvas, '取得したROS画像（枠は切り出し位置）', 15, 192, 16, (158, 216, 255))
    text(canvas, '同じ画像の切り出し拡大', 332, 192, 16, (158, 216, 255))
    text(canvas, 'AI判定と処理状況', 559, 192, 20, (158, 216, 255))
    for index, target in enumerate(IDS):
        y = 225 + 232 * index
        row = state.get('targets', {}).get(target, {})
        active = wording['active'] == target
        color = (204, 187, 127) if active else (72, 68, 63)
        cv2.rectangle(canvas, (8, y-8), (941, y+222), color, 3 if active else 1)
        image = images.get(target)
        if image is not None:
            canvas[y:y+210, 15:295] = cv2.resize(image, (280, 210), interpolation=cv2.INTER_AREA)
            cx, cy = map(int, roi_center)
            half = int(roi_size)//2
            if not (0 <= cx-half < cx+half <= 640 and 0 <= cy-half < cy+half <= 480):
                raise ValueError('configured display ROI exceeds ROS image')
            cv2.rectangle(canvas, (15+round((cx-half)*280/640), y+round((cy-half)*210/480)),
                          (15+round((cx+half)*280/640), y+round((cy+half)*210/480)), (0, 216, 255), 1)
            canvas[y:y+210, 330:540] = cv2.resize(image[cy-half:cy+half, cx-half:cx+half], (210, 210))
        else:
            cv2.rectangle(canvas, (15, y), (540, y+212), (46, 44, 42), -1)
            placeholder = '画像確認失敗・表示停止' if error else ('判定不能：再撮影しません' if row.get('status') == 'UNDETERMINED' else '到達後の新しい画像を待っています')
            text(canvas, placeholder, 37, y+99, 24)
        inf = row.get('inference') or {}
        label = inf.get('label')
        label_ja = '判定不能' if error or row.get('status') == 'UNDETERMINED' else LABEL_JA.get(label, '判定待ち')
        label_color = (105, 225, 127) if label_ja == '正常' else ((111, 133, 255) if label_ja == '異常' else (221, 221, 221))
        text(canvas, 'ゲージ'+target+'　AI判定：'+label_ja, 559, y+1, 26, label_color)
        status = '表示検証に失敗・後続動作停止' if error else STATUS_JA.get(row.get('status', 'PENDING'), '表示の診断中')
        if active:
            if state.get('stage') == 'MOVING_TO_POINT':
                status = '指示姿勢へ移動中'
            elif state.get('stage') in ('POINTING', 'HOLDING_POINTER'):
                status = '指示中・到達確認済み'
            status += '（現在の対象）'
        text(canvas, status, 559, y+40, 19)
        arrival = row.get('arrival')
        if isinstance(arrival, dict):
            arrival = arrival.get('result', arrival.get('verification_result', arrival.get('status')))
        arrival_ja = '確認済み' if arrival == 'PASS' else ('確認待ち' if not arrival else '未確認')
        text(canvas, '観測姿勢への到達：'+arrival_ja, 559, y+69, 18)
        matched = image is not None and bool(inf) and not error
        text(canvas, '推論画像と表示画像：'+('一致' if matched else ('照合失敗' if error else '照合待ち')), 559, y+96, 18)
        info = row.get('image') or {}
        text(canvas, '撮影 UTC '+str(info.get('received_at_utc', '-'))[:24], 559, y+126, 14, (184, 190, 196))
        sha = info.get('image_sha256') or '-'
        text(canvas, 'SHA256 '+sha[:28], 559, y+149, 13, (184, 190, 196))
        if 'svm_raw_margin' in inf:
            text(canvas, 'SVM margin '+format(float(inf['svm_raw_margin']), '+.4f')+'（未校正）', 559, y+172, 15, (184, 190, 196))
            text(canvas, '確率・異常度ではありません', 559, y+196, 15, (184, 190, 196))
    if wording['stopped']:
        cv2.rectangle(canvas, (3, 923), (947, 968), (52, 45, 135), -1)
        reason = str(error or state.get('error') or '判定不能')
        reason_lower = reason.lower()
        reason_ja = '検証または処理に失敗しました'
        if any(word in reason_lower for word in ('hash', 'sha-256', 'input differ')):
            reason_ja = '画像の照合に失敗しました'
        elif any(word in reason_lower for word in ('image', 'capture', 'quality')):
            reason_ja = '画像の取得・品質確認に失敗しました'
        elif any(word in reason_lower for word in ('arrival', 'reach')):
            reason_ja = '移動先への到達を確認できません'
        text(canvas, '停止理由：'+reason_ja+'（自動再試行なし）', 15, 928, 16, (255, 255, 255))
        detail = reason
        while japanese_font(13).getlength(detail) > 910:
            detail = detail[:-2]
        if detail != reason:
            detail += '…'
        text(canvas, detail, 15, 951, 13, (255, 255, 255))
    else:
        text(canvas, '色＝AIの判断 ／ 到達・画像一致は、判定の正しさを意味しません', 15, 925, 17)
        text(canvas, '強調枠＝現在の対象　|　点検 → 結果を指示 → 初期姿勢　|　自動再試行なし', 15, 950, 16)
    return canvas



def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', type=Path, required=True)
    parser.add_argument('--review-only', action='store_true')
    args = parser.parse_args()
    run_dir = args.run_dir.resolve()
    if not run_dir.is_dir():
        parser.error('run directory must already exist')
    os.environ.setdefault('DISPLAY', ':0')
    os.environ.setdefault('XAUTHORITY', '/home/ubuntu/.Xauthority')
    sys.path.insert(0, str(ROOT / 'camera_demo/scripts'))
    from camera_demo_dashboard import move_gazebo_right, gazebo_above_rviz
    gazebo_window = move_gazebo_right()
    cv2.namedWindow(WINDOW, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(WINDOW, WIDTH, HEIGHT)
    cv2.moveWindow(WINDOW, 4, 48)
    state = {'run_id': run_dir.name, 'revision': 0, 'stage': 'WAITING', 'targets': {k: {} for k in IDS}}
    cv2.imshow(WINDOW, draw(state, {}))
    cv2.waitKey(100)
    if not gazebo_above_rviz(gazebo_window):
        raise RuntimeError('Gazebo remains behind RViz')
    if not args.review_only:
        atomic_json(run_dir / 'display_ready.json', {'run_id': run_dir.name, 'at_utc': utc(),
                    'gazebo_window': gazebo_window, 'dashboard_size': [WIDTH, HEIGHT], 'gazebo_above_rviz': True})
    previous_revision = 0
    while True:
        snapshot = run_dir / 'display_state.json'
        if snapshot.exists():
            try:
                incoming = json.loads(snapshot.read_text(encoding='utf-8'))
            except (OSError, json.JSONDecodeError):
                incoming = None
            if incoming and incoming.get('revision', 0) > previous_revision:
                state = incoming
                error, hashes, labels = None, {}, {}
                try:
                    if state.get('run_id') != run_dir.name:
                        raise ValueError('snapshot run ID differs from displayed run')
                    images, hashes, labels = verify_images(state, run_dir)
                    frame = draw(state, images)
                except Exception as exc:
                    error = f'{type(exc).__name__}: {exc}'
                    frame = draw(state, {}, error)
                cv2.imshow(WINDOW, frame)
                if cv2.waitKey(80) == 27:
                    raise RuntimeError('display closed before acknowledgement')
                window_info = subprocess.check_output(['xwininfo', '-name', WINDOW], text=True, timeout=5)
                if 'Map State: IsViewable' not in window_info:
                    raise RuntimeError('display window is not viewable in X11')
                ack = {'run_id': run_dir.name, 'revision': state['revision'], 'at_utc': utc(),
                       'stage': state.get('stage'), 'result': 'FAIL' if error else 'PASS', 'error': error,
                       'image_hashes': hashes, 'labels': labels, 'selected_targets': state.get('selected_targets', []),
                       'current_target': state.get('current_target'), 'pointing_target': state.get('pointing_target')}
                if not args.review_only:
                    atomic_json(run_dir / 'display_ack.json', ack)
                    with (run_dir / 'display_audit.jsonl').open('a', encoding='utf-8') as handle:
                        handle.write(json.dumps(ack, ensure_ascii=False) + '\n')
                    if state.get('stage') in ('COMPLETE_HOME', 'ERROR', 'AI_RESULT', 'POINTING', 'HOLDING_POINTER'):
                        cv2.imwrite(str(run_dir / ('dashboard_rev_' + str(state['revision']) + '.png')), frame)
                previous_revision = state['revision']
        if cv2.waitKey(40) == 27:
            break
        time.sleep(.03)
    cv2.destroyAllWindows()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
