#!/usr/bin/env python3
"""Create reviewable Japanese PDF and MP4 from scored Gazebo evidence.

Run on Windows host (XeLaTeX installed). Video encoding uses the already running
isolated simulator container. Original recordings and trial evidence are retained.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
CONTAINER = 'physicalai-multigauge'
COMMANDS = []


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def entry(path):
    return {'path': str(path.resolve()), 'bytes': path.stat().st_size, 'sha256': sha(path)}


def command(argv, *, cwd=None):
    result = subprocess.run([str(x) for x in argv], cwd=cwd, capture_output=True)
    COMMANDS.append({'argv': [str(x) for x in argv], 'cwd': str(cwd) if cwd else None,
                     'returncode': result.returncode, 'stdout': result.stdout.decode(errors='replace'),
                     'stderr': result.stderr.decode(errors='replace')})
    if result.returncode:
        raise RuntimeError(f'command failed: {argv!r}\n' + result.stderr.decode(errors='replace')[-2000:])
    return result.stdout.decode(errors='replace')


def linux(path):
    return '/home/ubuntu/multigauge/' + path.resolve().relative_to(ROOT.resolve()).as_posix()


def docker(*args):
    return command(['docker', 'exec', CONTAINER, *args])


def probe(path):
    return json.loads(docker('ffprobe', '-v', 'error', '-show_format', '-show_streams', '-of', 'json', linux(path)))


def font(size, bold=False):
    candidates = [Path('C:/Windows/Fonts/YuGothB.ttc' if bold else 'C:/Windows/Fonts/YuGothM.ttc'),
                  Path('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc')]
    for path in candidates:
        if path.exists():
            return ImageFont.truetype(str(path), size)
    raise FileNotFoundError('Japanese font required for candidate video cards')


def card(path, title, lines, footer):
    im = Image.new('RGB', (1920,1080), '#151f2b')
    draw = ImageDraw.Draw(im)
    draw.rectangle((0,0,1920,22), fill='#6ad9c6')
    draw.text((100,100), title, font=font(63,True), fill='#eaf9fb')
    y=240
    for line in lines:
        draw.text((110,y), line, font=font(39), fill='#d1e0ed')
        y += 83
    draw.text((110,978), footer, font=font(26), fill='#85b7ca')
    im.save(path)


def tex_escape(value):
    replacements={'\\':r'\textbackslash{}','&':r'\&','%':r'\%','$':r'\$','#':r'\#','_':r'\_','{':r'\{','}':r'\}','~':r'\textasciitilde{}','^':r'\textasciicircum{}'}
    return ''.join(replacements.get(c,c) for c in str(value))


def targets(value):
    return ','.join(value) if value else '-'


def percent(n,d):
    return f'{n}/{d} ({100*n/d:.1f}\\%)' if d else '未評価'


def make_video(recording, output, evaluation, run_id, speed, scene_labels=None, normal_recording=None, normal_run_id=None):
    info=probe(recording)
    source_duration=float(info['format']['duration'])
    streams=[x for x in info['streams'] if x.get('codec_type')=='video']
    if len(streams)!=1:
        raise ValueError('exactly one source video stream required')
    if speed not in (1,2):
        raise ValueError('only 1x or 2x motion playback supported')
    motion_duration=source_duration/speed
    normal_duration=float(probe(normal_recording)['format']['duration'])/speed if normal_recording else 0
    total_motion_duration=motion_duration+normal_duration+(4 if normal_recording else 0)
    if total_motion_duration+24>180:
        raise ValueError(f'full recording at {speed}x exceeds 3 minutes; choose a shorter full trial')
    intro_duration=8
    result_duration=8
    limits_duration=max(8, math.ceil(60-total_motion_duration-intro_duration-result_duration))
    metrics=evaluation['metrics']
    cards=[
      ('intro','3台のゲージを自動点検',[
        'CRANE+ V2 の手先カメラで、既知地点 A → B → C を巡回',
        '到達確認 → 新しい ROS 画像 → HOG＋線形 SVM',
        '画像の判定結果から、異常対象を A・B・C 順に指示',
        f'この後は Gazebo の実行録画（動作映像 {speed} 倍速）',
        '正解ラベル・針角度は、推論と指示選択へ渡しません',
      ],intro_duration),
      ('results','全試行を残した検証',[
        f"全 {metrics['trial_count']} 試行（失敗試行も分母へ含む）",
        f"画像判定：{metrics['classification_correct']}/{metrics['classification_total']}、タスク成功：{metrics['task_success_trials']}/{metrics['trial_count']}",
        f"正常／異常の組合せ：{len(evaluation['coverage']['combinations_executed'])}/8 通りを実行",
        '指示対象集合・到達・home 復帰・全体成功を別々に採点',
        '設定した正解との照合は、各試行の実行終了後に実施',
      ],result_duration),
      ('limits','今回の範囲と残る課題',[
        'Gazebo 内の既知位置巡回点検。実機・実設備は未検証',
        '未知位置の探索、撮り直し、VLM、把持は今回の対象外',
        '画像・品質・推論・表示照合・到達の失敗で後続動作を停止',
        '元映像、失敗ログ、画像、設定、モデル、採点結果を保存',
        '候補動画・候補 PDF：既提出物の差し替え・公開は未実施',
      ],limits_duration),
    ]
    if normal_recording:
        cards.append(('normal_intro','全正常の場合も確認',[
          '別の試行：3台を観測して、全て正常なら「異常なし」',
          '指示対象は空集合、home 復帰までを実際に録画',
          f'この区間も動作映像 {speed} 倍速。原録画を保存',
        ],4))
    for name,title,lines,duration in cards:
        image_path=output/(name+'.png')
        card(image_path,title,lines,'Physical AI 最終課題の発展版 / Multi-gauge inspection / Candidate')
        docker('ffmpeg','-y','-loop','1','-i',linux(image_path),'-t',str(duration),'-r','30','-c:v','libx264','-preset','fast','-crf','20','-pix_fmt','yuv420p',linux(output/(name+'.mp4')))
    # The only moving scene comes from the unmodified full source recording.
    filter_string=f"setpts=PTS/{speed},fps=30,scale=1920:1080,drawbox=x=0:y=1048:w=1920:h=32:color=black@0.85:t=fill,drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf:text='Gazebo recording | {speed}x playback | run {run_id}':fontcolor=white:fontsize=21:x=16:y=1052"
    if scene_labels:
        labels = json.loads(scene_labels.read_text(encoding='utf-8-sig'))
        if set(labels.get('targets', {})) != {'A','B','C'} or labels.get('coordinate_frame') != 'screen_1920x1080':
            raise ValueError('scene labels require exactly A/B/C in screen_1920x1080 coordinates')
        overlay = Image.new('RGBA', (1920,1080), (0,0,0,0))
        painter = ImageDraw.Draw(overlay)
        for ident, values in labels['targets'].items():
            ax,ay = map(int,values['anchor_xy']); lx,ly = map(int,values['label_xy'])
            if not (960<=ax<1920 and 100<=ay<1048 and 960<=lx<1880 and 100<=ly<1000):
                raise ValueError('scene annotation must remain inside the actual Gazebo viewport')
            painter.line((lx+22,ly+22,ax,ay), fill=(0,0,0,230), width=7)
            painter.line((lx+22,ly+22,ax,ay), fill=(95,246,221,255), width=3)
            painter.ellipse((ax-5,ay-5,ax+5,ay+5), outline=(95,246,221,255), width=3)
            painter.rounded_rectangle((lx-3,ly-3,lx+46,ly+53), radius=8, fill=(12,32,44,235), outline=(95,246,221,255), width=2)
            painter.text((lx+8,ly-4),ident,font=font(37,True),fill=(246,255,255,255))
        overlay_path=output/'scene_labels.png';overlay.save(overlay_path)
        complex_filter='[0:v]'+filter_string+'[base];[base][1:v]overlay=0:0:format=auto[out]'
        docker('ffmpeg','-y','-i',linux(recording),'-i',linux(overlay_path),'-filter_complex',complex_filter,'-map','[out]','-an','-c:v','libx264','-preset','fast','-crf','20','-pix_fmt','yuv420p',linux(output/'motion.mp4'))
        shutil.copy2(scene_labels, output/'SCENE_LABELS.json')
    else:
        docker('ffmpeg','-y','-i',linux(recording),'-vf',filter_string,'-an','-c:v','libx264','-preset','fast','-crf','20','-pix_fmt','yuv420p',linux(output/'motion.mp4'))
    if normal_recording:
        normal_filter=filter_string.replace(run_id,normal_run_id)
        if scene_labels:
            normal_complex='[0:v]'+normal_filter+'[base];[base][1:v]overlay=0:0:format=auto[out]'
            docker('ffmpeg','-y','-i',linux(normal_recording),'-i',linux(overlay_path),'-filter_complex',normal_complex,'-map','[out]','-an','-c:v','libx264','-preset','fast','-crf','20','-pix_fmt','yuv420p',linux(output/'normal_motion.mp4'))
        else:
            docker('ffmpeg','-y','-i',linux(normal_recording),'-vf',normal_filter,'-an','-c:v','libx264','-preset','fast','-crf','20','-pix_fmt','yuv420p',linux(output/'normal_motion.mp4'))
    concat=output/'concat.txt'
    concat.write_text(''.join("file '"+linux(output/(name+'.mp4'))+"'\n" for name in (('intro','motion','normal_intro','normal_motion','results','limits') if normal_recording else ('intro','motion','results','limits'))),encoding='utf-8')
    final=output/'physicalai_multigauge_candidate.mp4'
    docker('ffmpeg','-y','-f','concat','-safe','0','-i',linux(concat),'-c','copy','-movflags','+faststart',linux(final))
    final_probe=probe(final)
    duration=float(final_probe['format']['duration'])
    if not 60<=duration<=180:
        raise AssertionError('candidate MP4 duration outside 1-3 minutes')
    pointing_at=intro_duration+motion_duration/2
    run_dir=ROOT/'results/runs'/run_id
    if (run_dir/'display_trace.jsonl').exists():
        run=json.loads((run_dir/'run_manifest.json').read_text())
        began=datetime.fromisoformat(run['started_at_utc'].replace('Z','+00:00'))
        trace=[json.loads(line) for line in (run_dir/'display_trace.jsonl').read_text().splitlines()]
        pointing=next((row for row in trace if row.get('stage')=='POINTING'),None)
        if pointing:
            at=datetime.fromisoformat(pointing['at_utc'].replace('Z','+00:00'))
            pointing_at=intro_duration+((at-began).total_seconds()+4.0)/speed
    for name,at in [('motion_start',intro_duration+2),('motion_middle',pointing_at),('motion_end',intro_duration+motion_duration-1)]:
        docker('ffmpeg','-y','-ss',f'{at:.3f}','-i',linux(final),'-frames:v','1',linux(output/(name+'.png')))
    return {'path':final,'source':entry(recording),'source_duration_sec':source_duration,'playback_speed':speed,'duration_sec':duration,'probe':final_probe,'intro_duration_sec':intro_duration,'results_duration_sec':result_duration,'limits_duration_sec':limits_duration,'normal_segment':{'run_id':normal_run_id,'source':entry(normal_recording),'playback_speed':speed,'duration_sec':normal_duration} if normal_recording else None}


def make_report(output,evaluation,run_id,video_info):
    m=evaluation['metrics']
    rows=[]
    for row in evaluation['runs']:
        rows.append(' & '.join([
          tex_escape(row['run_id'][-14:]),tex_escape(row.get('combination','?')),
          f"{row.get('image_correct_count',0)}/3",
          tex_escape(targets(row.get('selected_targets',[])))+'/'+tex_escape(targets(row.get('pointed_targets',[]))),
          f"{row.get('motion_arrivals_pass',0)}/{row.get('motion_arrivals_total',0)}",
          '可' if row.get('home_return') else '否',
          '成功' if row.get('task_success') else '失敗',
          f"{row['elapsed_sec']:.1f}" if row.get('elapsed_sec') is not None else '-',
        ])+r' \\')
    campaign_rows = '\n'.join(' & '.join([tex_escape(k), str(v['trial_count']), str(v['classification_correct'])+'/'+str(v['classification_total']), str(v['selection_correct_trials'])+'/'+str(v['trial_count']), str(v['task_success_trials'])+'/'+str(v['trial_count'])])+r' \\' for k,v in evaluation.get('by_campaign', {}).items())
    text=r'''\documentclass[a4paper,10pt]{article}
\usepackage[margin=16mm]{geometry}
\usepackage{fontspec,xeCJK,graphicx,booktabs,array,longtable,xcolor,hyperref,xurl}
\setmainfont{Arial}
\setCJKmainfont{Noto Sans JP}
\setCJKmonofont{Noto Sans JP}
\setlength{\parindent}{0pt}
\setlength{\parskip}{5pt}
\begin{document}
{\LARGE\bfseries 3台のゲージを順番に自動点検するロボット}\par
{\large Physical AI 最終課題の発展版／候補レポート／2026年10月27日（日本時間）}\par
\textbf{目的}\quad CRANE+ V2 の手先カメラと画像AIを組み合わせ、既知位置にある3台のゲージを巡回し、異常と判定した対象の位置を指し示す。一つの対象に対する左右応答から、対象A・B・Cと対応する動作へ発展させる。\par
\textbf{概要}\quad home $\rightarrow$ Aの観測姿勢への移動・到達確認・新画像取得・AI判定 $\rightarrow$ B $\rightarrow$ C $\rightarrow$ 画像AIが異常と判定した対象をA・B・Cの順に非接触姿勢で指示 $\rightarrow$ home復帰。全対象正常の場合は「異常なし」を表示してhomeへ戻る。未知位置の探索・観測の撮り直し・VLM・模倣学習・強化学習・把持は対象外とした。\par
\textbf{配置と動作}\quad ロボット前方の円弧上に3台を配置し、盤面をロボット側へ向けた。4関節アームの関節制限、手先カメラの向き、対象との距離を確認して観測・指示姿勢を定義した。カメラ筐体20mm角を衝突形状へ追加したところhomeで自己衝突したため、手先からの取付距離を15mmから32.5mmへ変更した。観測関節角を補正して従来の光学位置・向きを維持し、元モデルを継続利用した。衝突検査の無効化による回避は行っていない。机と3台をGazeboと同じ位置・寸法でMoveItの環境衝突物へ登録し、経路不成立時は実行しない。到達関節角に加え、手先の位置・姿勢と選択対象の対応を各runへ記録する。\par
\textbf{画像AI}\quad 既存のHOG特徴＋線形SVMを出発点とし、元モデルを保存した。固定ROI（中心320,310、192画素角）を128画素角へ縮小する。A・B・Cそれぞれの実際のROS画像でROI内に針と中心軸が収まることと判定を確認した（外周の一部は元モデルと同様に切れる）。モデルが検証する前処理設定と、巡回・動作設定の整合性検証を分離し、検証を維持した。SVM marginは判別境界からの符号付き出力であり、正解確率や異常度として解釈しない。\par
\textbf{工夫}\quad 対象準備・実行・採点を別工程に分け、正解ラベル、針角度、準備用状態値を推論・異常対象選択へ渡さない。各画像は観測姿勢への到達後に購読し、新規取得する。run ID、取得時刻、画像SHA-256、推論入力SHA-256、画面表示の確認応答を対応付ける。表示は3台分の画像と判定を保持し、観測中・指示中・最終指示対象を明示する。\par
\textbf{停止条件}\quad 画像取得、品質、推論、表示照合、到達確認のいずれかに失敗した場合は、その試行の後続動作を停止する。動作命令は自動再送信しない。判定不能は失敗として残し、自動で撮り直さない。\par
\includegraphics[width=\linewidth]{motion_middle.png}\par
{\footnotesize 実際のGazebo実行録画から抜き出した画面。代表run：RUNID。候補MP4の動作映像はSPEED倍速。原録画を保持する。}\par
\newpage
{\Large\bfseries 検証結果：失敗試行も含む全記録}\par
\textbf{検証単位}\quad 対象準備からhome復帰までを1試行とする。設定した正解と判定を実行後に照合し、画像判定、指示対象集合、実際の指示、各動作の到達、home復帰、全体成功、所要時間を別々に評価した。Nはnormal、Aはabnormal。組合せはゲージA・B・Cの順に記載する。\par
METRICS\par
\textbf{キャンペーン別内訳}\quad 総合成績に初期の失敗を含めたうえで、開発・固定設定検証・追加角度検証の内訳も区別する。\par
\begin{tabular}{lrrrr}\toprule 区分 & 試行 & 画像正解 & 選択集合正解 & 全体成功 \\
\midrule
CAMPAIGNROWS
\bottomrule\end{tabular}\par
INFRASTRUCTURE\par
\textbf{失敗と分母}\quad 初期4試行は移動前に停止した。固定設定の中断1試行はGazebo形状取得の応答欠落で、C移動を送信せず停止し、別runで全異常を完走した。未取得13画像を除外せず35/48と集計する。取得・推論できた35画像は全て正解だった。移動処理64件のうち送信前停止1件を未到達へ含め、送信済み63軌道は全て到達した。\par
\textbf{全試行一覧}\quad 指示欄は「選択した集合／実際に指示完了した集合」。未取得画像は正解数へ加算しない。各試行は独立して保存し、失敗後の自動再実行は行わない。\par
{\scriptsize
\begin{longtable}{lclllccc}
\toprule run ID末尾 & 組合せ & 画像 & 指示 & 到達 & home & 全体 & 秒 \\
\midrule\endhead
ROWS
\bottomrule
\end{longtable}}
\textbf{結果の扱い}\quad この表と集計は保存済みの全runおよび実行後の正解ファイルから機械的に生成した。詳細な失敗理由、各対象の画像判定、指示対象集合の正誤は\path{multigauge/results/evaluation.json}と\path{evaluation.csv}に保存した。診断用の画面故障注入試験はタスク試行とは区別する。\par
\textbf{画像照合の故障注入}\quad 実際のGUIで、推論入力hash不一致と画像ファイル改変がFAIL確認応答になることを確認した。解像度違い、画像なしでの判定、指示順序の不整合も拒否する。試験結果は\path{multigauge/evidence/dashboard_gui_qa.json}および\path{dashboard_contract_qa.json}に保存した。\par
\newpage
{\Large\bfseries 再現性と限界}\par
\textbf{再現手順}\quad 独立作業フォルダーの\path{multigauge/README.md}に起動・実行・採点手順を保存した。固定Dockerイメージを再利用し、コンテナ名とComposeプロジェクトを\path{physicalai-multigauge}、ROS domainを46、Gazebo partitionを\path{physicalai_multigauge_46}、VNCをlocalhost:6084に分離した。元の提出版と公開mainは保持し、本候補では既提出物の差し替え、YouTube投稿、mainへの反映を実施しない。\par
\textbf{証拠}\quad 各runのmanifest、各対象のROS画像、到達関節角とFK、MoveIt経路検査、表示確認応答、コマンド記録、設定とプログラムのSHA-256、採点結果を保持する。候補MP4・PDFの生成コマンド、入力・出力のSHA-256とQAは候補フォルダーのmanifestへ保存する。\par
\textbf{限界}\quad 今回の評価は同じGazebo環境と固定された既知位置のゲージで行ったもので、実設備の故障診断や実機安全性を保証しない。学習・検証画像の背景や照明は限定され、反射、遮蔽、汚れ、カメラ取付誤差、盤面の種類、未知角度への一般化は十分に検証していない。正常／異常の境界付近、画像品質劣化、通信断の網羅試験と長時間のサービス応答安定性は今後の課題である。画像表示の確認応答はソフトウェアとX11の可視状態の検査であり、表示装置の光学的な検証ではない。\par
\textbf{次の段階}\quad 実機での低速検証と安全対策、照明・角度・盤面を変えた独立データでの再評価、判定不能時の人への通知を先に進める。未知位置の探索や自動撮り直し等は、今回の既知位置巡回とは別の評価として追加する。\par
\textbf{状態}\quad 本書は候補であり、公開・提出前のレビュー対象。実施した検証と未検証範囲を区別し、原録画と失敗記録を保持する。\par
\end{document}
'''
    metrics='\\textbf{集計}\\quad '+ '、'.join([
      f"全{m['trial_count']}試行",
      '画像判定 '+percent(m['classification_correct'],m['classification_total']),
      '指示集合正解 '+percent(m['selection_correct_trials'],m['trial_count']),
      '各動作到達 '+percent(m['motion_arrivals_pass'],m['motion_arrivals_total']),
      'home復帰 '+percent(m['home_return_pass'],m['trial_count']),
      'タスク成功 '+percent(m['task_success_trials'],m['trial_count']),
      f"組合せ実行{len(evaluation['coverage']['combinations_executed'])}/8",
    ])+'。'
    text=text.replace('RUNID',tex_escape(run_id)).replace('SPEED',str(video_info['playback_speed'])).replace('METRICS',metrics).replace('CAMPAIGNROWS',campaign_rows).replace('INFRASTRUCTURE',f"試行ハーネス内で対象準備前に起きた環境障害は別途{len(evaluation.get('infrastructure_attempts',[]))}件を保存した。これらは対象準備を開始していないため試行分母へ含めず、記録を削除しない。").replace('ROWS','\n'.join(rows))
    if video_info.get('normal_segment'):
        text=text.replace('原録画を保持する。}', '原録画を保持する。全正常の別run：'+tex_escape(video_info['normal_segment']['run_id'])+'。}')
    source=output/'physicalai_multigauge_candidate.tex'
    source.write_text(text,encoding='utf-8')
    for _ in range(2):
        command(['xelatex','-interaction=nonstopmode','-halt-on-error',source.name],cwd=output)
    pdf=output/'physicalai_multigauge_candidate.pdf'
    command(['pdftotext','-layout',str(pdf),str(output/'pdf_text.txt')])
    pdf_text=(output/'pdf_text.txt').read_text(encoding='utf-8')
    assert all(x in pdf_text for x in ['目的','概要','工夫','検証結果','限界'])
    return pdf


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evaluation',type=Path,default=ROOT/'results/evaluation.json')
    parser.add_argument('--recording',type=Path,required=True)
    parser.add_argument('--run-id',required=True)
    parser.add_argument('--normal-recording',type=Path)
    parser.add_argument('--normal-run-id')
    parser.add_argument('--scene-labels',type=Path,help='Verified neutral A/B/C annotations for this fixed Gazebo camera')
    parser.add_argument('--speed',type=int,choices=[1,2],default=2)
    parser.add_argument('--output-dir',type=Path,required=True)
    args=parser.parse_args()
    output=args.output_dir.resolve()
    output.mkdir(parents=True,exist_ok=False)
    try:
        evaluation=json.loads(args.evaluation.read_text(encoding='utf-8-sig'))
        representative=[r for r in evaluation['runs'] if r['run_id']==args.run_id]
        if len(representative)!=1 or not representative[0].get('task_success'):
            raise ValueError('representative recording must correspond to a scored successful full trial')
        if bool(args.normal_recording)!=bool(args.normal_run_id):raise ValueError('normal clip requires its scored run ID')
        if args.normal_recording:
            normal=[r for r in evaluation['runs'] if r['run_id']==args.normal_run_id]
            if len(normal)!=1 or not normal[0].get('task_success') or normal[0].get('selected_targets'):raise ValueError('normal clip must be a scored successful all-normal trial')
        video_info=make_video(args.recording.resolve(),output,evaluation,args.run_id,args.speed,args.scene_labels,args.normal_recording.resolve() if args.normal_recording else None,args.normal_run_id)
        pdf=make_report(output,evaluation,args.run_id,video_info)
        qa={'status':'PARTIAL_PENDING_VISUAL_REVIEW','mp4_duration_within_1_to_3_minutes':True,
            'pdf_text_required_sections':True,'source_recording_retained':True,
            'representative_trial_scored_success':True,'visual_review':'PENDING'}
        (output/'QA.json').write_text(json.dumps(qa,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        manifest={'generated_at_utc':datetime.now(timezone.utc).isoformat(),'status':'CANDIDATE',
          'scene_labels':entry(args.scene_labels) if args.scene_labels else None,
          'representative_run':args.run_id,'evaluation':entry(args.evaluation),'source_recording':entry(args.recording),
          'program':entry(Path(__file__)),'report_source':entry(output/'physicalai_multigauge_candidate.tex'),
          'outputs':[entry(video_info['path']),entry(pdf)],
          'supporting_inputs':[entry(p) for p in sorted(set(
             list((ROOT/'configs').glob('*')) + list((ROOT/'evidence').glob('*qa.json')) +
             list((ROOT/'results/runs').glob('*/run_manifest.json')) +
             [REPO/'camera_demo/configs/runtime.yaml', REPO/'camera_demo/artifacts/gauge_hog_svm.yml', REPO/'camera_demo/artifacts/gauge_model_metadata.json']
          )) if p.is_file()],
          'video':{k:v for k,v in video_info.items() if k not in ('path','probe')},
          'environment':{'python':sys.version,'platform':platform.platform(),'container':CONTAINER},
          'external_submission_performed':False,'main_updated':False}
        (output/'MANIFEST.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(json.dumps(manifest['outputs'],ensure_ascii=False,indent=2))
    finally:
        (output/'RUN_COMMANDS.json').write_text(json.dumps(COMMANDS,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


if __name__=='__main__':
    main()
