"""Fault injection into the real coordinator; simulated dependencies, no ROS command."""
import copy,hashlib,json,sys,tempfile,types
from pathlib import Path
import cv2,numpy as np
import coordinator as c

SOURCE_ROOT=c.ROOT
checks=[]
for case in ['acquisition','quality','inference','display','arrival']:
 with tempfile.TemporaryDirectory(prefix='multigauge_stop_') as temp:
    root=Path(temp);rd=root/'results/runs'/'fault';rd.mkdir(parents=True);cfg=root/'motion.yaml';cfg.write_text('fault-injection dependency config')
    calls=[];node=types.SimpleNamespace(init=lambda **k:None,ok=lambda:False,shutdown=lambda:None)
    class FakeMotion:
        cfg={'camera_topic':'/test','image_timeout_sec':.1,'minimum_image_std':4,'hold_sec':0}
        def register_scene(self,p):c.write(p,{'result':'PASS','scope':'SIMULATED'})
        def confirm_home(self):return {'result':'PASS'}
        def move(self,source,target,rd,m,persist):
            calls.append(target)
            if case=='arrival':raise TimeoutError('injected failed arrival')
            entry={'from':source,'to':target,'publish_count':1,'arrival':{'result':'PASS','at_utc':'2026-10-27T00:00:00.000Z','joint_state_header':{'stamp':{'sec':1,'nanosec':0}}}}
            m['motions'].append(entry);persist();return entry
        def destroy_node(self):pass
    def atomic(path,value):
        c.write(path,value)
        ack={'run_id':rd.name,'revision':value['revision'],'result':'FAIL' if case=='display' and value['stage']=='CAMERA_IMAGE_CAPTURED' else 'PASS','error':'injected image display failure','image_hashes':{k:t['image']['image_sha256'] if t['image'] else None for k,t in value['targets'].items()},'labels':{k:t['inference']['label'] if t['inference'] else None for k,t in value['targets'].items()},'selected_targets':value['selected_targets'],'pointing_target':value['pointing_target']}
        c.write(rd/'display_ack.json',ack)
    def run(argv,**kwargs):
        if case=='acquisition':return types.SimpleNamespace(returncode=1,stdout='',stderr='injected camera timeout')
        path=Path(argv[argv.index('--output')+1]);image=np.zeros((480,640,3),np.uint8) if case=='quality' else np.random.default_rng(42).integers(0,255,(480,640,3),np.uint8);cv2.imwrite(str(path),image)
        sha=hashlib.sha256(path.read_bytes()).hexdigest();c.write(path.with_suffix('.json'),{'image_sha256':sha,'image_path':str(path),'subscription_started_at_utc':'2026-10-27T00:00:01.000Z','received_at_utc':'2026-10-27T00:00:02.000Z','header_stamp':{'sec':2,'nanosec':0}})
        return types.SimpleNamespace(returncode=0,stdout='',stderr='')
    original={k:getattr(c,k) for k in ['ROOT','CFG','Motion','rclpy','atomic','classify']};old_run=c.subprocess.run;old_argv=sys.argv;old_sleep=c.time.sleep
    try:
        c.ROOT=root;c.CFG=cfg;c.Motion=FakeMotion;c.rclpy=node;c.atomic=atomic;c.subprocess.run=run;c.time.sleep=lambda t:None
        if case=='inference':
            def fail(*args):raise RuntimeError('injected classifier failure')
            c.classify=fail
        sys.argv=['coordinator.py','--run-dir',str(rd)]
        code=c.main();manifest=json.loads((rd/'run_manifest.json').read_text())
        assert code==1 and manifest['result']=='FAIL',case
        assert calls==['observe_A'],(case,calls)
        assert not manifest['pointed_targets'] and manifest['home_return'] is None
        checks.append({'case':case,'result':'PASS','motion_attempts':calls,'no_point_or_home_after_failure':True,'abort_reason':manifest['abort_reason'],'scope':'SIMULATED_DEPENDENCIES_REAL_COORDINATOR'})
    finally:
        for k,v in original.items():setattr(c,k,v)
        c.subprocess.run=old_run;sys.argv=old_argv;c.time.sleep=old_sleep
report={'result':'PASS','scope':'Control-flow fault injection; no Gazebo results and no trajectory publisher. Separate real GUI/vision/geometry faults have their own evidence.','checks':checks}
(SOURCE_ROOT/'evidence/coordinator_stop_qa.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))