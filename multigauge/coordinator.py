"""Known-position patrol. No setup state, label, or needle-angle input is read."""
from __future__ import annotations
import argparse, hashlib, json, os, subprocess, sys, time
from pathlib import Path
import rclpy
from motion import Motion,now,write,ROOT,CFG
from vision import classify

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def atomic(p,value):
    temp=p.with_suffix('.tmp');write(temp,value);os.replace(temp,p)
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--run-dir',type=Path,required=True);args=ap.parse_args();rd=args.run_dir.resolve()
    if rd.parent!=ROOT/'results/runs' or not rd.is_dir() or (rd/'run_manifest.json').exists():raise RuntimeError('fresh run directory required')
    started=time.monotonic()
    m={'run_id':rd.name,'started_at_utc':now(),'finished_at_utc':None,'elapsed_sec':None,'result':'RUNNING','targets':{k:{'status':'PENDING','image':None,'inference':None,'arrival':None} for k in 'ABC'},'selected_targets':[],'pointed_targets':[],'motions':[],'home_return':None,'abort_reason':None,'runtime_config_sha256':sha(CFG),'truth_input':'ABSENT'}
    state={'run_id':rd.name,'revision':0,'stage':'STARTING','current_target':None,'pointing_target':None,'selected_targets':[],'targets':m['targets'],'error':None}
    def persist():write(rd/'run_manifest.json',m)
    def display(stage,current=None,pointing=None,error=None):
        state.update(revision=state['revision']+1,at_utc=now(),stage=stage,current_target=current,pointing_target=pointing,selected_targets=m['selected_targets'],error=error)
        atomic(rd/'display_state.json',state)
        with (rd/'display_trace.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(state)+'\n')
        deadline=time.monotonic()+10
        while time.monotonic()<deadline:
            try:ack=json.loads((rd/'display_ack.json').read_text())
            except (OSError,ValueError):time.sleep(.05);continue
            if ack.get('run_id')==rd.name and ack.get('revision')==state['revision']:
                if ack.get('result')!='PASS':raise RuntimeError('display verification failed: '+str(ack.get('error')))
                expected_hash={k:t['image']['image_sha256'] if t['image'] else None for k,t in m['targets'].items()}
                expected_labels={k:t['inference']['label'] if t['inference'] else None for k,t in m['targets'].items()}
                if ack.get('image_hashes')!=expected_hash or ack.get('labels')!=expected_labels or ack.get('selected_targets')!=m['selected_targets'] or ack.get('pointing_target')!=pointing:raise RuntimeError('display acknowledgement differs from inference/selection state')
                return
            time.sleep(.05)
        raise TimeoutError('display acknowledgement timeout')
    def event(event,**kw):
        value={'at_utc':now(),'event':event,**kw}
        with (rd/'execution_log.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(value)+'\n')
        print(json.dumps(value),flush=True)
    motion=None
    try:
        persist();display('STARTING');rclpy.init(args=[]);motion=Motion();motion.register_scene(rd/'collision_scene.json');m['initial_home']=motion.confirm_home();persist()
        source='home'
        for ident in 'ABC':
            target=m['targets'][ident];target['status']='MOVING';persist();display('MOVING_TO_OBSERVE',ident)
            entry=motion.move(source,'observe_'+ident,rd,m,persist);source='observe_'+ident
            target['arrival']=entry['arrival'];target['status']='ARRIVED';persist();display('ARRIVED_OBSERVE',ident)
            time.sleep(.35)
            capture=rd/f'observation_{ident}.png';argv=['ros2','run','camera_inspection','capture_image','--topic',motion.cfg['camera_topic'],'--output',str(capture),'--timeout-sec',str(motion.cfg['image_timeout_sec']),'--minimum-image-std',str(motion.cfg['minimum_image_std'])]
            proc=subprocess.run(argv,capture_output=True,text=True,timeout=30)
            event('capture_command',argv=argv,returncode=proc.returncode,stdout=proc.stdout,stderr=proc.stderr)
            if proc.returncode:raise RuntimeError('new ROS image acquisition failed')
            info=json.loads(capture.with_suffix('.json').read_text());arrival=entry['arrival'];stamp=arrival['joint_state_header']['stamp'];image_stamp=info['header_stamp']
            if info['subscription_started_at_utc']<=arrival['at_utc'] or info['received_at_utc']<=arrival['at_utc'] or (image_stamp['sec'],image_stamp['nanosec'])<=(stamp['sec'],stamp['nanosec']):raise RuntimeError('camera frame is stale relative to arrival')
            if sha(capture)!=info['image_sha256']:raise RuntimeError('capture file hash changed')
            target['image']=info;target['status']='CAPTURED';persist();display('CAMERA_IMAGE_CAPTURED',ident)
            target['status']='INFERENCE';display('AI_INFERENCE_RUNNING',ident);inference=classify(capture)
            if inference['image_sha256']!=info['image_sha256'] or inference['label'] not in ('normal','abnormal'):raise RuntimeError('inference input/label mismatch')
            target['inference']=inference;target['status']='COMPLETE';write(rd/f'inference_{ident}.json',inference);persist();display('AI_RESULT',ident);event('image_inference',target_id=ident,**inference);time.sleep(.4)
        m['selected_targets']=[k for k in 'ABC' if m['targets'][k]['inference']['label']=='abnormal'];persist();display('SELECTION_COMPLETE');time.sleep(1)
        for ident in m['selected_targets']:
            display('MOVING_TO_POINT',pointing=ident);motion.move(source,'point_'+ident,rd,m,persist);source='point_'+ident
            m['pointed_targets'].append(ident);persist();display('POINTING',pointing=ident);event('target_pointed',target_id=ident)
            display('HOLDING_POINTER',pointing=ident);time.sleep(float(motion.cfg['hold_sec']))
        if not m['selected_targets']:display('NO_ABNORMALITY');event('no_abnormality',message='異常なし');time.sleep(2)
        display('MOVING_TO_HOME');entry=motion.move(source,'home',rd,m,persist);m['home_return']=motion.confirm_home();persist();display('COMPLETE_HOME');m['result']='PASS';event('run_complete');time.sleep(1)
        return 0
    except Exception as exc:
        m['result']='FAIL';m['abort_reason']=f'{type(exc).__name__}: {exc}'
        for t in m['targets'].values():
            if t['status'] not in ('COMPLETE','PENDING'):t['status']='UNDETERMINED'
        persist()
        try:display('ERROR',error=m['abort_reason'])
        except Exception as display_error:event('display_abort_error',reason=str(display_error))
        event('run_aborted',reason=m['abort_reason']);return 1
    finally:
        m['finished_at_utc']=now();m['elapsed_sec']=time.monotonic()-started;persist()
        if motion:motion.destroy_node()
        if rclpy.ok():rclpy.shutdown()
if __name__=='__main__':raise SystemExit(main())