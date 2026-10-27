"""Real-GUI display gate fault injection, deliberately separate from task trials."""
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
ROOT=Path(__file__).resolve().parent
run_dir=ROOT/'results'/('dashboard_gui_contract_'+str(time.time_ns()))
run_dir.mkdir(exist_ok=False)
state={'run_id':run_dir.name,'revision':1,'stage':'DIAGNOSTIC_DISPLAY_TEST','current_target':None,'pointing_target':None,'selected_targets':[],'targets':{k:{} for k in ('A','B','C')}}
env={**os.environ,'DISPLAY':':0','XAUTHORITY':'/home/ubuntu/.Xauthority'}
log=(run_dir/'dashboard.log').open('w')
process=subprocess.Popen([sys.executable,str(ROOT/'dashboard.py'),'--run-dir',str(run_dir)],env=env,stdout=log,stderr=subprocess.STDOUT)
checks=[]
def wait_json(path,predicate,timeout=20):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        if path.exists():
            data=json.loads(path.read_text())
            if predicate(data):
                return data
        if process.poll() is not None:
            raise RuntimeError('dashboard exited: '+(run_dir/'dashboard.log').read_text())
        time.sleep(.1)
    raise TimeoutError(str(path))
try:
    ready=wait_json(run_dir/'display_ready.json',lambda x: x.get('run_id')==run_dir.name)
    checks.append({'case':'real GUI ready with Gazebo visible','result':'PASS','evidence':ready})
    def send(revision,expected):
        state['revision']=revision
        temp=run_dir/'display_state.json.tmp'
        temp.write_text(json.dumps(state),encoding='utf-8')
        temp.replace(run_dir/'display_state.json')
        ack=wait_json(run_dir/'display_ack.json',lambda x:x.get('revision')==revision)
        assert ack['result']==expected,ack
        return ack
    checks.append({'case':'empty initial state displayed','result':'PASS','ack':send(1,'PASS')})
    data=(ROOT.parent/'camera_demo/data/images/validation/normal/normal_02_00.png').read_bytes()
    path=run_dir/'A.png';path.write_bytes(data)
    sha=hashlib.sha256(data).hexdigest()
    state['targets']['A']={'status':'DIAGNOSTIC_SAVED_IMAGE','arrival':'NOT_A_TASK_TRIAL','image':{'image_path':str(path),'image_sha256':sha,'received_at_utc':'diagnostic original dataset'},'inference':{'label':'normal','image_sha256':sha}}
    checks.append({'case':'same saved PNG displayed and acknowledged','result':'PASS','ack':send(2,'PASS')})
    state['targets']['A']['inference']['image_sha256']='0'*64
    checks.append({'case':'mismatched inference identity yields FAIL acknowledgement','result':'PASS','ack':send(3,'FAIL')})
    state['targets']['A']['inference']['image_sha256']=sha
    path.write_bytes(data+b'corruption')
    checks.append({'case':'changed image file yields FAIL acknowledgement','result':'PASS','ack':send(4,'FAIL')})
    subprocess.run(['ffmpeg','-y','-f','x11grab','-video_size','1920x1080','-i',':0','-frames:v','1',str(run_dir/'fault_screen.png')],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=True)
    report={'status':'VERIFIED','scope':'Real GUI fault injection, saved original dataset image; no robot command, no task result','checks':checks}
    (ROOT/'evidence/dashboard_gui_qa.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,indent=2))
finally:
    process.terminate()
    process.wait(timeout=5)
    log.close()
