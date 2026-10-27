"""Trial harness; preparation arguments are never passed to the runtime process."""
import argparse,datetime,fcntl,hashlib,json,os,signal,shutil,subprocess,sys,time,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parent

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--combination',required=True);ap.add_argument('--campaign',default='pilot');ap.add_argument('--normal-angle',default='.045');ap.add_argument('--abnormal-angle',default='.875');ap.add_argument('--record',action='store_true');args=ap.parse_args()
    lock=(ROOT/'results/runner.lock').open('w');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    run_id='mg_'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ_')+uuid.uuid4().hex[:6]
    rd=ROOT/'results/runs'/run_id;rd.mkdir(parents=True,exist_ok=False)
    print('RUN_ID='+run_id,flush=True)
    commands=[];dashboard=recorder=None;started=time.monotonic();result='FAIL'
    def command(argv,log,timeout):
        commands.append(argv);(rd/'RUN_COMMANDS.json').write_text(json.dumps(commands,indent=2))
        with (rd/log).open('w') as f:return subprocess.run(argv,stdout=f,stderr=subprocess.STDOUT,timeout=timeout).returncode
    try:
        snapshot=rd/'source_snapshot';snapshot.mkdir()
        files=list(ROOT.glob('*.py'))+list(ROOT.glob('*.sh'))+list((ROOT/'configs').glob('*'))+[ROOT/'compose.yaml',ROOT.parent/'camera_demo/configs/runtime.yaml',ROOT.parent/'camera_demo/artifacts/gauge_model_metadata.json',ROOT.parent/'camera_demo/artifacts/gauge_hog_svm.yml']
        provenance=[]
        for p in files:
            dest=snapshot/p.relative_to(ROOT.parent);dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,dest)
            provenance.append({'path':str(p),'snapshot':str(dest),'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'size_bytes':p.stat().st_size})
        (rd/'RUN_PROVENANCE.json').write_text(json.dumps({'inputs_programs_configs':provenance,'python':sys.version,'source_commit':(ROOT/'evidence/base_commit.txt').read_text().strip(),'status':'VERIFIED'},indent=2))
        prepare=[sys.executable,str(ROOT/'prepare.py'),'--run-id',run_id,'--combination',args.combination,'--campaign',args.campaign,'--normal-angle',args.normal_angle,'--abnormal-angle',args.abnormal_angle]
        if command(prepare,'preparation.log',100):raise RuntimeError('preparation failed; no runtime motion attempted')
        dashboard_argv=[sys.executable,str(ROOT/'dashboard.py'),'--run-dir',str(rd)];commands.append(dashboard_argv)
        dashboard_log=(rd/'dashboard.log').open('w');dashboard=subprocess.Popen(dashboard_argv,stdout=dashboard_log,stderr=subprocess.STDOUT)
        deadline=time.monotonic()+20
        while not (rd/'display_ready.json').exists():
            if dashboard.poll() is not None or time.monotonic()>deadline:raise RuntimeError('display not ready; no runtime motion attempted')
            time.sleep(.1)
        if args.record:
            recording=["ffmpeg","-y","-nostdin","-f","x11grab","-video_size","1920x1080","-framerate","20","-i",":0.0","-c:v","libx264","-preset","ultrafast","-crf","24","-pix_fmt","yuv420p",str(rd/'screen.mp4')]
            commands.append(recording);recorder_log=(rd/'recording.log').open('w');recorder=subprocess.Popen(recording,stdout=recorder_log,stderr=subprocess.STDOUT);time.sleep(.5)
            if recorder.poll() is not None:raise RuntimeError('screen recorder failed before motion')
        coordinator=[sys.executable,str(ROOT/'coordinator.py'),'--run-dir',str(rd)]
        rc=command(coordinator,'coordinator.log',1000)
        result='PASS' if rc==0 else 'FAIL'
        print(json.dumps({'run_id':run_id,'result':result,'run_dir':str(rd)}),flush=True)
        return rc
    except Exception as exc:
        (rd/'runner_error.txt').write_text(f'{type(exc).__name__}: {exc}\n');print(str(exc),flush=True);return 1
    finally:
        if recorder and recorder.poll() is None:
            recorder.send_signal(signal.SIGINT)
            try:recorder.wait(timeout=10)
            except subprocess.TimeoutExpired:recorder.terminate();recorder.wait(timeout=5)
        if dashboard and dashboard.poll() is None:dashboard.terminate();dashboard.wait(timeout=5)
        (rd/'RUN_COMMANDS.json').write_text(json.dumps(commands,indent=2))
        (rd/'FINAL_STATE.json').write_text(json.dumps({'run_id':run_id,'result':result,'elapsed_sec':time.monotonic()-started,'recording':str(rd/'screen.mp4') if args.record else None},indent=2))
if __name__=='__main__':raise SystemExit(main())