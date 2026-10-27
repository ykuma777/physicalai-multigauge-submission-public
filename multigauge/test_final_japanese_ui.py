#!/usr/bin/env python3
"""Japanese UI state/contract diagnostics. Synthetic inputs; never task trials."""
from __future__ import annotations
import argparse
import ast
import copy
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
import cv2
import numpy as np
import dashboard as ui

ROOT = Path(__file__).resolve().parent
ACK_KEYS = {'run_id','revision','at_utc','stage','result','error','image_hashes',
            'labels','selected_targets','current_target','pointing_target'}

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--gui',action='store_true')
    parser.add_argument('--baseline',type=Path,default=ROOT/'results/runs/mg_20261027T021505Z_8ac959/source_snapshot/multigauge/dashboard.py')
    args=parser.parse_args()
    out=ROOT/'evidence'/('final_japanese_ui_'+str(time.time_ns()))
    out.mkdir(parents=True,exist_ok=False)
    checks=[]
    def check(name, condition, **evidence):
        if not condition:
            raise AssertionError(name)
        checks.append({'case':name,'result':'PASS',**evidence})
    # Prove the existing gate and ACK implementation are byte-for-byte equivalent ASTs.
    baseline=args.baseline.read_text(encoding='utf-8')
    def function_ast(source,name):
        return ast.dump(next(n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name==name),include_attributes=False)
    source=(ROOT/'dashboard.py').read_text(encoding='utf-8')
    for name in ('verify_images','main'):
        check('baseline '+name+' AST unchanged',function_ast(source,name)==function_ast(baseline,name))
    base={'run_id':out.name,'revision':1,'stage':'WAITING','current_target':None,
          'pointing_target':None,'selected_targets':[],'targets':{k:{} for k in ui.IDS}}
    # Non-camera synthetic color pattern: diagnostic display input, never passed to AI.
    yy,xx=np.indices((480,640));image=np.stack((xx%256,yy%256,(xx+yy)%256),axis=-1).astype(np.uint8)
    path=out/'synthetic.png';cv2.imwrite(str(path),image);digest=sha(path)
    completed=copy.deepcopy(base)
    for target,label in zip(ui.IDS,('normal','abnormal','normal')):
        completed['targets'][target]={'status':'COMPLETE','arrival':{'result':'PASS'},
            'image':{'image_path':str(path),'image_sha256':digest,'received_at_utc':'diagnostic-not-a-ROS-capture'},
            'inference':{'label':label,'image_sha256':digest,'svm_raw_margin':-.1234}}
    fixtures=[]
    def fixture(name,state,error=None):
        images,hashes,labels=ui.verify_images(state,out)
        wording=ui.display_text(state,error)
        frame=ui.draw(state,{} if error else images,error)
        check(name+' frame dimensions',frame.shape==(970,950,3))
        dest=out/(name+'.png');cv2.imwrite(str(dest),frame)
        fixtures.append({'name':name,'state':copy.deepcopy(state),'error':error,'wording':wording,
                         'path':str(dest),'sha256':sha(dest)})
        return wording
    initial=fixture('00_cleared',base)
    check('new run clears images/labels/selection',initial['summary']=='点検結果：A判定待ち／B判定待ち／C判定待ち' and initial['selection']=='指示対象：確定待ち')
    stages=['STARTING',*ui.OBSERVATION_STAGES,'SELECTION_COMPLETE','MOVING_TO_POINT','POINTING',
            'HOLDING_POINTER','NO_ABNORMALITY','MOVING_TO_HOME','COMPLETE_HOME','ERROR']
    for index,stage in enumerate(stages,1):
        state=copy.deepcopy(completed);state['stage']=stage;state['current_target']='C'
        if stage in ui.SELECTION_STAGES:
            state['selected_targets']=['B']
        if stage in ('MOVING_TO_POINT','POINTING','HOLDING_POINTER'):
            state['pointing_target']='B'
        if stage=='NO_ABNORMALITY':
            state['selected_targets']=[]
            for row in state['targets'].values():row['inference']['label']='normal'
        if stage=='ERROR':
            state['error']='diagnostic image-quality failure';state['targets']['C']['status']='UNDETERMINED'
        wording=fixture(f'{index:02d}_{stage.lower()}',state)
        check(stage+' Japanese primary phase',any('\u3040'<=c<='\u9fff' for c in wording['phase']))
        if stage=='AI_RESULT':
            check('all predictions available does not prematurely select targets',wording['selection']=='指示対象：確定待ち')
            check('mixed AI results stated without correctness claim',wording['summary']=='点検結果：A正常／B異常／C正常')
        if stage=='MOVING_TO_POINT':
            check('no pointing or arrival completion before target reached',wording['phase']=='指示姿勢へ移動中：ゲージB' and '確認済み' not in wording['detail'])
        if stage in ('POINTING','HOLDING_POINTER'):
            check(stage+' after confirmed arrival',wording['phase']=='指示中：ゲージB' and '確認済み' in wording['detail'])
        if stage=='ERROR':
            check('failure distinct from abnormal gauge result','処理停止' in wording['phase'] and 'C判定不能' in wording['summary'])
    images,hashes,labels=ui.verify_images(completed,out)
    check('three images retained and hash/labels unchanged',set(images)==set(ui.IDS) and hashes==dict.fromkeys(ui.IDS,digest) and labels==dict(zip(ui.IDS,('normal','abnormal','normal'))))
    captured=copy.deepcopy(completed);captured['targets']['C'].pop('inference');captured['targets']['C']['status']='CAPTURED'
    fixture('16_captured_not_inferred',captured)
    broken=copy.deepcopy(completed);broken['targets']['B']['inference']['image_sha256']='0'*64
    try:
        ui.verify_images(broken,out)
    except ValueError as exc:
        check('mismatched inference hash fails closed','display and inference input differ' in str(exc))
    else:raise AssertionError('hash mismatch accepted')
    failed_wording=fixture('17_display_error',completed,'ValueError: diagnostic display hash mismatch')
    check('unverified display cannot show usable normal result','正常' not in failed_wording['summary'] and failed_wording['summary'].count('判定不能')==3)
    # The real font must contain distinct Japanese glyphs, rather than repeated tofu boxes.
    f=ui.japanese_font(28)
    check('Japanese glyphs are present and distinct',bytes(f.getmask('異'))!=bytes(f.getmask('常')) and bytes(f.getmask('異'))!=bytes(f.getmask('\U0010ffff')))
    gui=[]
    if args.gui:
        run=out/'gui';run.mkdir()
        env={**os.environ,'DISPLAY':':0','XAUTHORITY':'/home/ubuntu/.Xauthority'}
        with (run/'dashboard.log').open('w') as log:
            process=subprocess.Popen([sys.executable,str(ROOT/'dashboard.py'),'--run-dir',str(run)],env=env,stdout=log,stderr=subprocess.STDOUT)
            def wait(path,predicate):
                deadline=time.monotonic()+25
                while time.monotonic()<deadline:
                    if path.exists():
                        value=json.loads(path.read_text(encoding='utf-8'))
                        if predicate(value):return value
                    if process.poll() is not None:raise RuntimeError((run/'dashboard.log').read_text())
                    time.sleep(.1)
                raise TimeoutError(str(path))
            try:
                wait(run/'display_ready.json',lambda x:x['run_id']==run.name)
                # Copy diagnostic image into this run so path containment is tested as usual.
                gp=run/'synthetic.png';gp.write_bytes(path.read_bytes())
                for revision,stage in enumerate(('STARTING','AI_RESULT','MOVING_TO_POINT','POINTING','ERROR'),1):
                    state=copy.deepcopy(completed if revision>1 else base)
                    state.update(run_id=run.name,revision=revision,stage=stage)
                    for row in state['targets'].values():
                        if row.get('image'):row['image']['image_path']=str(gp)
                    if stage in ('MOVING_TO_POINT','POINTING'):state.update(selected_targets=['B'],pointing_target='B')
                    expected='PASS'
                    if stage=='ERROR':
                        state['targets']['B']['inference']['image_sha256']='0'*64;expected='FAIL'
                    ui.atomic_json(run/'display_state.json',state)
                    ack=wait(run/'display_ack.json',lambda x:x['revision']==revision)
                    check('real GUI '+stage+' ACK schema and result',set(ack)==ACK_KEYS and ack['result']==expected)
                    if expected=='PASS':
                        _,hs,ls=ui.verify_images(state,run)
                        check('real GUI '+stage+' exact identity',ack['image_hashes']==hs and ack['labels']==ls and ack['selected_targets']==state['selected_targets'] and ack['pointing_target']==state['pointing_target'])
                    gui.append(ack)
                subprocess.run(['ffmpeg','-y','-f','x11grab','-video_size','1920x1080','-i',':0','-frames:v','1',str(run/'fault_screen.png')],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=True)
            finally:
                process.terminate();process.wait(timeout=8)
    report={'status':'VERIFIED','scope':'Synthetic Japanese UI state diagnostics'+(' and real X11 GUI ACK/fault test' if args.gui else '')+'; no AI inference or robot commands; excluded from Gazebo task metrics',
            'at_utc':ui.utc(),'baseline':{'path':str(args.baseline),'sha256':sha(args.baseline)},'program':{'path':str(ROOT/'dashboard.py'),'sha256':sha(ROOT/'dashboard.py')},
            'test_program':{'path':str(Path(__file__)),'sha256':sha(Path(__file__))},
            'command':'python3 /home/ubuntu/multigauge/test_final_japanese_ui.py'+(' --gui' if args.gui else ''),
            'environment':{'python':sys.version,'opencv':cv2.__version__,'numpy':np.__version__,'font':str(f.path)},
            'checks':checks,'fixtures':fixtures,'gui_acknowledgements':gui,'output_directory':str(out),
            'visual_review':'PENDING supervisor visual review of rendered diagnostic PNGs'}
    (out/'qa.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (ROOT/'evidence/final_japanese_ui_qa.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'status':report['status'],'checks':len(checks),'output_directory':str(out)},ensure_ascii=False))
    return 0

if __name__=='__main__':
    raise SystemExit(main())
