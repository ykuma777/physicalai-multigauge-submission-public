#!/usr/bin/env python3
"""Build final Japanese media from three scored, complete, real Gazebo runs.

Windows host: Pillow, XeLaTeX/Noto Sans JP and Poppler. Encoding is delegated to
existing isolated physicalai-multigauge container. Never overwrites an output dir.
"""
from __future__ import annotations
import argparse, json, math, platform, shutil, sys
from datetime import datetime, timezone
from pathlib import Path
from PIL import Image, ImageDraw
import artifacts as legacy

ROOT=Path(__file__).resolve().parent
COMMANDS=legacy.COMMANDS
entry, command, docker, linux, probe, font, tex_escape = (legacy.entry,legacy.command,legacy.docker,legacy.linux,legacy.probe,legacy.font,legacy.tex_escape)
TITLE='PAI最終課題_ykumakuma777'
WORK='3台のゲージを自動点検し、異常箇所を指し示すロボット'
EXPECTED=[('NAN',['B']),('NAA',['B','C']),('NNN',[])]


def read(path):return json.loads(path.read_text(encoding='utf-8-sig'))
def write_json(path,value):path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def frac(n,d):return f'{n}/{d}'
def labels(values):return '、'.join(values) if values else 'なし'
def jp(label):return {'normal':'正常','abnormal':'異常'}[label]
def utc(value):return datetime.fromisoformat(value.replace('Z','+00:00'))

def draw_card(path,title,lines,footer='実際のGazebo実行を収録／動作映像は2倍速／ykumakuma777'):
    im=Image.new('RGB',(1920,1080),'#13222e');d=ImageDraw.Draw(im)
    d.rectangle((0,0,1920,18),fill='#5bd8c0')
    for i,line in enumerate(title.split('\n')):d.text((90,95+i*90),line,font=font(62,True),fill='#f4fbff')
    y=340 if '\n' in title else 270
    for line in lines:
        if d.textbbox((0,0),line,font=font(42))[2]>1740:raise ValueError('card line too wide: '+line)
        d.text((95,y),line,font=font(42),fill='#d7e5ef');y+=92
    d.text((95,985),footer,font=font(27),fill='#9cbacc');im.save(path)

def encode_card(output,name,title,lines,duration):
    png=output/(name+'.png');mp4=output/(name+'.mp4');draw_card(png,title,lines)
    docker('ffmpeg','-y','-loop','1','-i',linux(png),'-t',f'{duration:.3f}','-r','30','-c:v','libx264','-preset','fast','-crf','20','-pix_fmt','yuv420p',linux(mp4))
    return mp4

def overlay(output,scene_path):
    scene=read(scene_path)
    if set(scene['targets'])!=set('ABC') or scene['coordinate_frame']!='screen_1920x1080':raise ValueError('invalid scene IDs')
    im=Image.new('RGBA',(1920,1080),(0,0,0,0));d=ImageDraw.Draw(im)
    for ident,v in scene['targets'].items():
        ax,ay=map(int,v['anchor_xy']);lx,ly=map(int,v['label_xy'])
        if not (960<=ax<1920 and 100<=ay<1030 and 960<=lx<1880 and 100<=ly<990):raise ValueError('annotation outside Gazebo viewport')
        d.line((lx+22,ly+22,ax,ay),fill=(0,0,0,240),width=7);d.line((lx+22,ly+22,ax,ay),fill='#60f6dd',width=3)
        d.ellipse((ax-5,ay-5,ax+5,ay+5),outline='#60f6dd',width=3)
        d.rounded_rectangle((lx-3,ly-3,lx+46,ly+53),radius=8,fill=(12,32,44,235),outline='#60f6dd',width=2)
        d.text((lx+8,ly-4),ident,font=font(37,True),fill='white')
    d.rectangle((0,1044,1920,1080),fill=(0,0,0,245))
    d.text((18,1044),'実際のGazebo実行・2倍速  |  点検 → 画像AI判定 → 結果を指示 → 初期姿勢',font=font(25),fill='white')
    p=output/'neutral_scene_and_speed_overlay.png';im.save(p);shutil.copy2(scene_path,output/'SCENE_LABELS.json');return p

def load_trials(ids,evaluation):
    scored={r['run_id']:r for r in evaluation['runs']};trials=[]
    for ident,(combination,selected) in zip(ids,EXPECTED):
        rd=ROOT/'results/runs'/ident;m=read(rd/'run_manifest.json');truth=read(ROOT/'results/truth'/(ident+'.json'))
        score=scored.get(ident)
        if not score or not score.get('task_success'):raise ValueError('source run not scored successful: '+ident)
        if truth['combination']!=combination or m['selected_targets']!=selected or m['pointed_targets']!=selected or m['result']!='PASS':raise ValueError('scenario mismatch: '+ident)
        recording=rd/'screen.mp4'
        if not recording.is_file():raise FileNotFoundError(recording)
        info=probe(recording);streams=[s for s in info['streams'] if s['codec_type']=='video']
        if len(streams)!=1 or (streams[0]['width'],streams[0]['height'])!=(1920,1080):raise ValueError('source must be 1920x1080 actual recording')
        trials.append({'id':ident,'dir':rd,'manifest':m,'truth':truth,'score':score,'recording':recording,'source_probe':info,'source_duration_sec':float(info['format']['duration'])})
    return trials

def build_video(output,trials,evaluation,scene_path):
    moving=sum(t['source_duration_sec']/2 for t in trials)
    results_duration=max(8,min(22,160-moving-19))
    if moving+19+results_duration>180:raise ValueError('three untrimmed recordings at 2x exceed 180 seconds')
    overlay_path=overlay(output,scene_path)
    segments=[encode_card(output,'00_intro',TITLE,['3台のゲージを自動点検し、','異常箇所を指し示すロボット','手先カメラで A → B → C を撮影・判定','その後の指示動作は、点検結果を知らせる動きです'],6)]
    scene_titles=['例1：Bだけが異常の場合','別の試行：BとCが異常の場合','別の試行：3台とも正常の場合']
    scene_lines=[['準備条件：A正常／B異常／C正常','3台を点検 → AI判定 → Bだけを指示 → 初期姿勢'],['準備条件：A正常／B異常／C異常','3台を点検 → AI判定 → B、Cの順に指示 → 初期姿勢'],['準備条件：A正常／B正常／C正常','3台を点検 → 「異常なし」 → 指示せず初期姿勢']]
    timeline=[];offset=6
    for i,t in enumerate(trials):
        segments.append(encode_card(output,f'{i+1}0_case',scene_titles[i],scene_lines[i]+['正解との比較は実行後に行います。'],3));offset+=3
        dest=output/f'{i+1}1_actual_run.mp4'
        docker('ffmpeg','-y','-i',linux(t['recording']),'-i',linux(overlay_path),'-filter_complex','[0:v]setpts=PTS/2,fps=30[base];[base][1:v]overlay=0:0:format=auto[out]','-map','[out]','-an','-c:v','libx264','-preset','fast','-crf','20','-pix_fmt','yuv420p',linux(dest))
        duration=float(probe(dest)['format']['duration']);segments.append(dest)
        timeline.append({'run_id':t['id'],'start_sec':offset,'duration_sec':duration,'source':entry(t['recording']),'source_duration_sec':t['source_duration_sec'],'playback_speed':2,'trimmed':False,'run_utc_start_to_recording_offset':'not_inferred; exported phase labels are from actual recorded Japanese UI'})
        offset+=duration
    segments.append(encode_card(output,'40_results','今回の日本語UIでの確認',['混在例・複数異常・全正常：3試行すべて完了','画像AI判定：9画像すべて実行後の正解と一致','指示対象・指示順序・移動先への到達・初期姿勢を確認','旧16試行11成功も保持し、新規試行とは分けて集計'],results_duration))
    segments.append(encode_card(output,'50_limits','確認した範囲と、次の課題',['既知位置・限定されたGazebo環境での実演です。','実設備の故障診断や、実機での安全性は未検証です。','撮り直し・未知位置探索・把持は今回の対象外です。'],4))
    listing=output/'concat.txt';listing.write_text(''.join("file '"+linux(p)+"'\n" for p in segments),encoding='utf-8')
    final=output/(TITLE+'.mp4');docker('ffmpeg','-y','-f','concat','-safe','0','-i',linux(listing),'-c','copy','-metadata','title='+TITLE,'-metadata','artist=','-metadata','author=','-movflags','+faststart',linux(final))
    info=probe(final);duration=float(info['format']['duration'])
    if not 60<=duration<=180 or next(s for s in info['streams'] if s['codec_type']=='video')['codec_name']!='h264':raise AssertionError('MP4 format/length failed')
    docker('ffmpeg','-v','error','-xerror','-i',linux(final),'-f','null','-')
    for i,t in enumerate(trials):
        trace=[json.loads(x) for x in (t['dir']/'display_trace.jsonl').read_text().splitlines()]
        for target in t['manifest']['selected_targets'] or [None]:
            state=next(r for r in trace if r['stage']==('HOLDING_POINTER' if target else 'NO_ABNORMALITY') and (not target or r['pointing_target']==target))
            # Candidate frame only: recorder precedes coordinator imports; +4 sec is visually reviewed below.
            at=max(0,(utc(state['at_utc'])-utc(t['manifest']['started_at_utc'])).total_seconds()+4.0)
            image=output/f'representative_{i+1}_{target or "none"}.png'
            docker('ffmpeg','-y','-ss',f'{at:.3f}','-i',linux(t['recording']),'-i',linux(overlay_path),'-filter_complex','[0:v][1:v]overlay=0:0:format=auto[out]','-map','[out]','-frames:v','1',linux(image))
    return {'file':final,'duration_sec':duration,'probe':info,'timeline':timeline,'results_card_duration_sec':results_duration,'full_decode':'PASS'}

PREAMBLE=r'''\documentclass[a4paper,10pt]{article}
\usepackage[margin=16mm]{geometry}
\usepackage{fontspec,xeCJK,graphicx,booktabs,array,xcolor,hyperref,xurl}
\setmainfont{Arial}
\setCJKmainfont{Noto Sans JP}
\setCJKmonofont{Noto Sans JP}
\hypersetup{pdftitle={PAI最終課題\_ykumakuma777},pdfauthor={},pdfsubject={3台のゲージ点検と異常箇所の指示},pdfkeywords={Gazebo,画像AI,ykumakuma777}}
\setlength{\parindent}{0pt}\setlength{\parskip}{5pt}
\setlength{\tabcolsep}{5pt}
\newcommand{\topic}[1]{\par\vspace{3pt}{\large\bfseries #1}\par}
\begin{document}
'''


def compile_pdf(output,name,body,required):
    source=output/(name+'.tex');source.write_text(PREAMBLE+body+'\n\\end{document}\n',encoding='utf-8')
    for _ in range(2):command(['xelatex','-interaction=nonstopmode','-halt-on-error',source.name],cwd=output)
    pdf=output/(name+'.pdf');command(['pdftotext','-layout',str(pdf),str(output/(name+'_text.txt'))])
    text=(output/(name+'_text.txt')).read_text(encoding='utf-8')
    if not all(x in text for x in required):raise AssertionError('missing Japanese report text')
    if text.count('\f')!=3:raise AssertionError('final document must have exactly three pages')
    command(['pdftoppm','-scale-to','1500','-png',str(pdf),str(output/(name+'_page'))])
    return pdf

def metric_lines(evaluation):
    m=evaluation.get('metrics',evaluation.get('groups',{}).get('overall',{}));observed=m['observed_classification_total']
    correct=m.get('observed_classification_correct',m.get('classification_correct'));planned=m.get('planned_image_total',m.get('classification_total'));complete=m.get('correct_planned_image_completion',m.get('classification_correct'))
    return [f"タスク全体：{m['task_success_trials']}/{m['trial_count']}成功",f"取得・推論できた画像：{correct}/{observed}正解",f"予定画像への正しい判定完了：{complete}/{planned}",f"指示対象集合：{m['selection_correct_trials']}/{m['trial_count']}正解／実際の指示：{m['pointing_correct_trials']}/{m['trial_count']}正解",f"送信済み軌道の到達：{m.get('sent_trajectory_arrivals_pass',m.get('motion_arrivals_pass'))}/{m.get('sent_trajectories','別表参照')}（送信前停止{m.get('unsent_motion_handlers','別表参照')}件）",f"初期姿勢への復帰：{m['home_return_pass']}/{m['trial_count']}"]

def scenario_rows(trials):
    rows=[]
    for i,t in enumerate(trials):
        s=t['score'];p=t['manifest'];truth=t['truth'];condition='／'.join(jp(truth['targets'][k]['truth_label']) for k in 'ABC');prediction='／'.join(jp(p['targets'][k]['inference']['label']) for k in 'ABC')
        rows.append(f"{i+1} & {condition} & {prediction} & {labels(p['pointed_targets'])} & {s['motion_arrivals_pass']}/{s['motion_arrivals_total']} & 済 & 成功 & {s['elapsed_sec']:.1f} \\\\")
    return '\n'.join(rows)

def build_docs(output,trials,evaluation,baseline,video):
    total='。'.join(metric_lines(evaluation))+'。'
    baseline_text='従来は16試行中11成功。固定設定は9試行中8成功で全8条件を網羅し、追加角度は2試行中2成功。取得・推論できた35画像は35正解、未取得13画像を含む予定48画像への正しい判定完了は35/48。送信済み63軌道は63到達、送信前に止まった移動処理1件を別記する。'
    meaning='緑「AI判定：正常」と赤橙「AI判定：異常」は画像AIの分類であり、正解の表示ではない。灰色は判定待ち。判定不能・処理停止は理由を併記し、正常扱いしない。強調枠は現在の対象と工程を示す。「移動先への到達：確認済み」は関節状態からの到達確認、「推論画像と表示画像：一致」は画像対応の照合であり、分類の正しさを意味しない。'
    ai='針がほぼ縦に見える合成画像を正常、強く傾いた合成画像を異常の学習例として作成した既存のHOG＋線形SVMを使う。これは学習例の説明であり、正常角度の連続した範囲や実設備の故障を定義するものではない。元モデルと固定ROIを保持し、各地点の実際のROS画像で確認した。'
    safety='観測姿勢への到達後に新しいROS画像を取得する。画像SHA-256、run ID、撮影時刻、推論入力と表示画像の照合を記録する。机・ゲージ・手先カメラを含むMoveIt衝突検査を保ち、計画や到達が不成立なら後続を止める。画像取得・品質・推論・表示照合の失敗も停止し、自動で撮り直さず、動作命令も自動再送しない。'
    limits='既知位置・限定照明のGazebo環境での結果であり、実機の安全性や実設備の故障診断能力を示さない。反射、遮蔽、盤面の違い、境界角度、未知角度、取付誤差、長時間の応答安定性は未十分検証。未知位置探索、自動撮り直し、VLM、模倣学習、強化学習、把持は今回の対象外。'
    replay='旧推論再現の33枚は完走11試行の各3枚。中断したAAA試行で取得・判定された2枚は旧再現処理の対象外だったため、判定記録35件との差は2枚となる。今回の監査では成功分だけの集計と混同しない。'
    failure='過去の中断試行では形状取得・解析照合の前段で「could not parse Gazebo world SDF safely」と記録され、Cへの移動命令は送信されず停止した。原因の確定は未了で、通信障害や形状不一致と断定しない。後の独立した読み戻しが通った事実とは区別する。'
    rows=scenario_rows(trials)
    table=r'''\begin{tabular}{clllcccr}\toprule 例 & 準備 A/B/C & AI判定 A/B/C & 指示順 & 到達 & 復帰 & 全体 & 秒\\\midrule
'''+rows+r'''\bottomrule\end{tabular}\par'''
    body=r'''{\LARGE\bfseries 3台のゲージを自動点検し、\\異常箇所を指し示すロボット}\par
{\large PAI最終課題\_ykumakuma777／ローカル完成版／2026年10月27日}\par
\topic{目的・概要}
ロボットの手先カメラで、既知位置のゲージA・B・Cを順番に撮影し、画像AIで正常／異常を判断する。その結果に応じ、異常と判定した場所だけをロボットで指し示し、初期姿勢（home）へ戻る。
\topic{動きは「点検」と「結果を知らせる指示」の2段階}
点検ではA、B、Cの観測姿勢に順番に移動し、到達確認後の新しい画像をAIへ入力する。3台の結果が揃った後、異常と判定した対象だけをA・B・C順に非接触姿勢で指す。この2回目の移動は、撮り直し・再判定・経時変化の監視ではない。全台正常なら「異常なし」と表示し、指示動作をせず戻る。
\topic{画面で見ること}
'''+meaning+r'''
\includegraphics[width=\linewidth]{representative_1_B.png}\par
{\small 実際の日本語UIとGazebo録画からの代表画面。Bのみを指示する例。右のA・B・Cは対象識別用の編集注釈。元のROS画像と録画は保持する。}
\newpage
{\LARGE\bfseries 実行後の採点と検証結果}\par
\topic{今回確認した3例}
準備時の条件、実行中に画像から得たAI判定、実行後の採点を分ける。準備用の正解ラベル・針角度は推論や指示対象の選択へ渡さない。以下の秒数は対象準備から初期姿勢への復帰までを含む。\\
'''+table+r'''
3試行とも、画像9件、指示対象集合、指示順序、送信済みの移動先への到達、初期姿勢復帰を確認した。日本語表示への変更で、動作・画像取得・推論・表示確認応答の契約は変えていない。従来の全8条件を保持し、今回は混在・複数異常・全正常を追加確認した。
\topic{従来の16試行を保持する}
'''+baseline_text+r'''
35/35は取得できた限定条件の画像の結果であり、一般的な分類精度100\%を主張しない。35/48は未取得も含む「正しい判定の完了」であり、単に分類精度72.9\%とは呼ばない。8条件の網羅は全試行成功とは別である。
\topic{追加後の全試行}
'''+tex_escape(total)+r'''
開発失敗も含む全試行を残し、旧16試行と今回追加した全試行を区分して集計する。個別結果、到達記録、指示対象集合、初期姿勢復帰、所要時間は評価JSON・CSVに保存する。
\topic{失敗記録と推論再現の読み方}
'''+failure+replay+r'''
\newpage
{\LARGE\bfseries 工夫・再現手順・限界}\par
\topic{画像AIと学習条件}
'''+ai+r'''
正常学習例の針角度は $-0.13,-0.08,0.02,0.07$ rad、異常学習例は $0.72,0.78,0.90,0.96$ rad。検証用角度はそれぞれ $-0.03,0.12$ rad、$0.84,1.02$ rad。これらは設定された点値であり、角度範囲ではない。SVM marginは符号付き分類出力で、正解確率や異常度として表示しない。
\topic{安全と記録の工夫}
'''+safety+r'''
前方の円弧上に3台を置き、盤面をロボットへ向ける。観測と指示を別姿勢として定義し、到達関節角、手先位置・向き、対象位置との対応を記録する。固定ROIと元モデルは保管し、前処理設定と動作設定の検証範囲を分けて整合性検証を維持した。
\topic{起動と再現}
分離した作業ブランチで、既存Dockerイメージを利用する。\path{multigauge/start.ps1}で起動後、\path{multigauge/README.md}の手順で対象準備・巡回・実行後採点を行う。コンテナ／Compose名は\path{physicalai-multigauge}、ROS domainは46、Gazebo区分は\path{physicalai_multigauge_46}、VNCはlocalhost:6084。各runの実行ソース・設定snapshot、画像、コマンド、到達・表示ACKを保存する。
本動画の全3試行は実録の全区間を2倍速とし、途中の動作を省略していない。候補フォルダーのmanifestには入力・出力hash、実測尺、生成コマンドとQAを記録する。説明カードとID注釈は編集であり、推論の入力ではない。
\topic{限界と次の課題}
'''+limits+r'''
\topic{作成と公開の区別}
本成果はローカルで作成・確認した版。既提出物と公開mainを保持し、push、YouTube投稿、提出物差し替えは行っていない。ライセンス・由来情報と失敗記録を保持する。
'''
    report=compile_pdf(output,'説明資料_'+TITLE,body,['目的','概要','工夫','検証結果','限界'])
    spec_md=f'''# {WORK}

実装確認済み仕様書／{TITLE}／2026-10-27

## 1. 何をする作品か

手先カメラで既知位置のA・B・Cを順番に撮影し、画像AIが正常／異常に分類する。異常と判断した場所だけを非接触姿勢で指し示し、初期姿勢（home）に戻る。

## 2. 点検と結果の指示の違い

点検はA→B→Cの観測姿勢への移動、到達確認、新規撮影、画像AI判定。3台の結果確定後の指示は、異常と判定した対象をA・B・C順に知らせる動作である。再撮影、再判定、経時監視はしない。全台正常なら「異常なし」、指示せず初期姿勢へ戻る。

{safety}

## 3. シグナルの意味

{meaning}

取得画像と判定は指示中も残す。指示姿勢への移動中と、到達確認後の「指示中」を区別する。run ID、撮影時刻、hash、SVM出力は詳細証拠。marginは正解確率・異常度ではない。A・B・Cの注釈は対象IDで、正解ラベルではない。

## 4. 3例の動作

'''
    for i,t in enumerate(trials):
        spec_md+=f"- 例{i+1}：準備条件 {t['truth']['combination']}（A/B/C順）。実録run `{t['id']}`。画像AIの判定から選んだ指示対象：{labels(t['manifest']['selected_targets'])}。実際の指示順：{labels(t['manifest']['pointed_targets'])}。初期姿勢復帰と全体成功を実行後に確認。対象準備からの所要時間 {t['score']['elapsed_sec']:.1f} 秒。\n"
    spec_md+=f'''
Nは正常、Aは異常を表す。条件は対象準備の情報であり、実行中の推論へ渡さない。別の条件への切替は「別の試行」と明示する。

## 5. 検証結果と限界

### 学習上の正常・異常

{ai}

`camera_demo/configs/dataset.yaml`のtrain_angle_indices=[0,1,3,4]による正常学習角度は[-0.13,-0.08,0.02,0.07] rad、異常は[0.72,0.78,0.90,0.96] rad。検証角度は正常[-0.03,0.12] rad、異常[0.84,1.02] rad。連続した正常範囲や物理的故障の定義ではない。

### 成績の分母

{baseline_text}

追加後の全試行：{total}

{replay}

{failure}

### 検証範囲

{limits}

元の提出版、公開main、旧動画・PDF・失敗試行を保持する。ここでいう完成はローカルの作成・検証であり、公開や提出物差し替えではない。詳細は同梱README、評価JSON/CSV、run別manifest、生成MANIFESTとQAを参照する。
'''
    md=output/'MULTIGAUGE_FINAL_SPEC_CONFIRMED.md';md.write_text(spec_md,encoding='utf-8')
    spec_body=r'''{\LARGE\bfseries 3台のゲージを自動点検し、\\異常箇所を指し示すロボット}\par
{\large 実装確認済み仕様書／PAI最終課題\_ykumakuma777／2026年10月27日}\par
\topic{1. 何をする作品か}
手先カメラで、決められた場所にあるゲージA・B・Cを順番に撮影する。画像AIが各画像を正常／異常に分類し、その後、異常と判断した対象だけを指し示す。最後は初期姿勢（home）へ戻る。
\topic{2. 点検と結果の指示の違い}
\begin{tabular}{p{30mm}p{140mm}}\toprule 工程 & 動きと意味\\\midrule
点検 & A→B→Cの観測姿勢に移動し、到達後に新しいROS画像を取得、AIで分類する。\\
結果の確定 & 3台の画像と判定を保持し、異常と判定した対象を選ぶ。\\
結果の指示 & 選んだ対象だけをA・B・C順に非接触姿勢で指す。再撮影・再判定はしない。\\
終了 & 指示後は初期姿勢へ。全台正常なら「異常なし」を表示し、指示せず戻る。\\\bottomrule\end{tabular}\par
\topic{動作と停止の契約}
'''+safety+r'''
ロボット前方の円弧上の3台を盤面がロボットを向くよう配置する。観測姿勢と指示姿勢を分け、実際の関節角・手先位置と向き・選択対象の位置対応を記録する。到達不能や経路不成立なら実行しない。
\includegraphics[width=\linewidth]{representative_1_B.png}\par
{\small 実際の混在例。3台の撮影後、画像AIが異常としたBだけを指示する。A・B・Cは対象の識別ID。}
\newpage
{\LARGE\bfseries 表示を読む・3例の動きを比べる}\par
\topic{3. シグナルの意味}
'''+meaning+r'''
\begin{tabular}{p{57mm}p{113mm}}\toprule 主表示 & 意味\\\midrule
点検中：ゲージAを撮影・判定 & Aを観測するための移動・新規取得・判定の工程。\\
指示対象：B、C & 今回のAI判定で異常になった対象の集合。\\
指示中：ゲージB & 指示姿勢への到達を確認し、Bを知らせている。移動中とは区別する。\\
異常なし & 全台正常。指示動作をせず初期姿勢へ戻る。\\
初期姿勢へ復帰中／完了 & 移動中／到達が確認できた。\\
判定待ち／判定不能 & 未判定／成立しなかった。正常として扱わない。\\
処理停止：理由 & 後続を停止。ゲージの異常判定と区別する。\\\bottomrule\end{tabular}\par
3台の取得画像とAI判定は指示中にも残す。SVM margin、hash、時刻、run IDは詳細証拠として保持し、主表示の日本語の意味を優先する。SVM marginは確率や異常の深刻さではない。正解は実行後に照合し、推論や選択へ渡さない。
\topic{4. 実際に確認した3例}
'''+table+r'''
NANはBのみを指示、NAAはB→Cを指示、NNNは指示せず初期姿勢へ復帰した。各例は別の試行で、準備条件・実行中のAI判定・実行後の採点を分けて記録する。3試行9画像の判定、指示集合と順序、送信済み移動の到達、初期姿勢復帰、全体完了を確認した。
\topic{実録の対応}
'''+''.join(r'例'+str(i+1)+r'：\path{'+t['id']+r'}\par ' for i,t in enumerate(trials))+r'''
動画は実録3本を全区間2倍速で使用し、工程順序や途中動作を省略しない。冒頭・切替・結果カードと中立ID注釈は編集である。主な工程表示・取得画像・AI判定は実際の日本語UIの録画。
\newpage
{\LARGE\bfseries 検証結果と限界}\par
\topic{5. 学習上の正常・異常}
'''+ai+r'''
正常学習角度：$-0.13,-0.08,0.02,0.07$ rad。異常学習角度：$0.72,0.78,0.90,0.96$ rad。検証角度：正常$-0.03,0.12$ rad、異常$0.84,1.02$ rad。\path{camera_demo/configs/dataset.yaml}の点値と分割を確認した。これらから連続した正常範囲を推定しない。
\topic{失敗を含めた成績}
'''+baseline_text+r'''
取得済み35画像の35正解と、未取得を含む予定48画像への35判定完了を分ける。前者は限定条件での結果、後者は単純な分類精度ではない。8条件網羅と全試行成功も区別する。
追加後の全試行：'''+tex_escape(total)+r'''
\topic{記録の監査}
'''+replay+failure+r'''
\topic{限界と今後}
'''+limits+r'''
日本語表示と編集のみを変更し、動作・推論・画像表示ACKの契約は保つ。新しい3例と必要な表示状態を確認し、今回の変更に無関係な全8条件の再実行は行わない。再現手順、全試行結果、各runの実行ソースとSHA、画像・到達・FK・衝突検査・ACKの記録を残す。
\topic{作成と公開}
既提出版、公開main、旧候補、全失敗試行を保持。ローカルでの作成・確認と、公開・提出差し替えは別工程であり、今回は投稿・push・差し替えを行わない。
'''
    spec=compile_pdf(output,'MULTIGAUGE_FINAL_SPEC_CONFIRMED',spec_body,['何をする作品か','点検と結果の指示','シグナル','検証結果','限界'])
    return report,spec,md

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run-ids',nargs=3,required=True,metavar=('NAN','NAA','NNN'));p.add_argument('--evaluation',type=Path,required=True);p.add_argument('--baseline-evaluation',type=Path,default=ROOT/'results/evaluation.json');p.add_argument('--scene-labels',type=Path,default=ROOT/'evidence/scene_labels.json');p.add_argument('--output-dir',type=Path,default=ROOT/'candidates/final_20261027_v1');p.add_argument('--resume-docs',action='store_true',help='Resume unfinished output after media encoding; never rewrite a canonical manifest');args=p.parse_args()
    output=args.output_dir.resolve()
    if args.resume_docs:
        if not output.is_dir() or (output/'MANIFEST.json').exists():raise ValueError('resume only unfinished generated output')
        COMMANDS.extend(read(output/'RUN_COMMANDS.json'))
    else:output.mkdir(parents=True,exist_ok=False)
    try:
        evaluation=read(args.evaluation);baseline=read(args.baseline_evaluation)
        if baseline['metrics']['trial_count']!=16 or baseline['metrics']['task_success_trials']!=11:raise ValueError('baseline is not preserved 16-trial evaluation')
        trials=load_trials(args.run_ids,evaluation)
        if args.resume_docs:
            final=output/(TITLE+'.mp4');info=probe(final);duration=float(info['format']['duration'])
            if not 60<=duration<=180:raise ValueError('invalid unfinished video')
            docker('ffmpeg','-v','error','-xerror','-i',linux(final),'-f','null','-')
            timeline=[];offset=6
            for i,t in enumerate(trials):
                clip=output/f'{i+1}1_actual_run.mp4';clip_duration=float(probe(clip)['format']['duration']);offset+=3
                matching=[c for c in COMMANDS if linux(t['recording']) in c['argv'] and '[0:v]setpts=PTS/2,fps=30[base];[base][1:v]overlay=0:0:format=auto[out]' in c['argv'] and c['returncode']==0]
                if len(matching)!=1:raise ValueError('cannot recover exact full-source media producer command')
                timeline.append({'run_id':t['id'],'start_sec':offset,'duration_sec':clip_duration,'source':entry(t['recording']),'source_duration_sec':t['source_duration_sec'],'playback_speed':2,'trimmed':False,'run_utc_start_to_recording_offset':'not_inferred; actual recorded UI used'})
                offset+=clip_duration
            video={'file':final,'duration_sec':duration,'probe':info,'timeline':timeline,'results_card_duration_sec':float(probe(output/'40_results.mp4')['format']['duration']),'full_decode':'PASS','resumed_docs_without_reencoding':True}
        else:video=build_video(output,trials,evaluation,args.scene_labels)
        report,spec,md=build_docs(output,trials,evaluation,baseline,video)
        snapshots=output/'program_snapshot';snapshots.mkdir(exist_ok=True)
        for program in [Path(__file__),Path(legacy.__file__)]:shutil.copy2(program,snapshots/program.name)
        qa={'status':'PARTIAL_PENDING_VISUAL_REVIEW','h264':True,'duration_sec':video['duration_sec'],'within_60_180_sec':True,'full_video_decode':'PASS','untrimmed_actual_run_count':3,'playback_speed':2,'all_three_scored_success':True,'all_pdf_pages_rendered':True,'visual_review':'PENDING','personal_data_review':'PENDING','metadata_author':''}
        write_json(output/'QA.json',qa)
        inputs=[args.evaluation,args.baseline_evaluation,args.scene_labels,ROOT/'results/CODEX_FINALIZE.md',ROOT/'results/MULTIGAUGE_FINAL_SPEC.pdf',ROOT.parent/'camera_demo/configs/dataset.yaml']
        for t in trials:inputs.extend([t['recording'],t['dir']/'run_manifest.json',ROOT/'results/truth'/(t['id']+'.json'),t['dir']/'display_trace.jsonl',t['dir']/'RUN_PROVENANCE.json'])
        manifest={'generated_at_utc':datetime.now(timezone.utc).isoformat(),'invocation':[sys.executable,*sys.argv],'status':'LOCAL_FINAL_PENDING_VISUAL_QA','title':TITLE,'inputs':[entry(x) for x in inputs],'programs':[entry(x) for x in [Path(__file__),Path(legacy.__file__),*sorted(snapshots.glob('*initial_attempt.py'))]],'outputs':[entry(x) for x in [video['file'],report,spec,md]],'video':{k:v for k,v in video.items() if k not in ('file','probe')},'video_probe':video['probe'],'run_ids':args.run_ids,'baseline_group':baseline['metrics'],'combined_group':evaluation.get('metrics',evaluation.get('groups',{}).get('overall',{})),'qa':qa,'environment':{'python':sys.version,'platform':platform.platform(),'encoder_container':'physicalai-multigauge'},'external_submission_performed':False,'main_updated':False}
        write_json(output/'MANIFEST.json',manifest);print(json.dumps(manifest['outputs'],ensure_ascii=False,indent=2))
    finally:write_json(output/'RUN_COMMANDS.json',COMMANDS)

if __name__=='__main__':main()