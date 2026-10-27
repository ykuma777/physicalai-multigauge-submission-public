"""Read-only startup readiness. Never publishes any robot command."""
import argparse,json,os,time
from pathlib import Path
ROOT=Path(__file__).resolve().parent

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--process-check',action='store_true');ap.add_argument('--timeout',type=float,default=90);ap.add_argument('--report',type=Path);args=ap.parse_args()
    if args.process_check:
        matches=[]
        for p in Path('/proc').iterdir():
            if not p.name.isdigit():continue
            try:argv=(p/'cmdline').read_bytes().split(b'\0')
            except OSError:continue
            if b'launch' in argv and b'./launch.py' in argv:matches.append(int(p.name))
        print(json.dumps({'launch_pids':matches}));return 0 if len(matches)==1 else (3 if not matches else 4)
    import rclpy
    from rclpy.qos import qos_profile_sensor_data
    from sensor_msgs.msg import JointState,Image
    from controller_manager_msgs.srv import ListControllers
    expected={'ROS_DOMAIN_ID':'46','IGN_PARTITION':'physicalai_multigauge_46','GZ_PARTITION':'physicalai_multigauge_46'}
    if any(os.environ.get(k)!=v for k,v in expected.items()):raise RuntimeError('wrong isolated environment')
    rclpy.init(args=[]);node=rclpy.create_node('multigauge_readiness');samples={'joint':[],'image':[]};controllers=[];error=None;started=time.monotonic()
    def receive(kind,msg):
        stamp=msg.header.stamp;value=stamp.sec*10**9+stamp.nanosec
        if not samples[kind] or value>samples[kind][-1]:samples[kind].append(value)
        samples[kind]=samples[kind][-3:]
    node.create_subscription(JointState,'/joint_states',lambda m:receive('joint',m),qos_profile_sensor_data)
    node.create_subscription(Image,'/inspection_camera/image',lambda m:receive('image',m),qos_profile_sensor_data)
    client=node.create_client(ListControllers,'/controller_manager/list_controllers');future=None
    try:
        deadline=time.monotonic()+args.timeout
        while time.monotonic()<deadline:
            rclpy.spin_once(node,timeout_sec=.1)
            # Cache active controllers and never leave a service request pending on exit.
            active={c['name'] for c in controllers if c['state']=='active'}
            if future is None and not {'joint_state_broadcaster','crane_plus_arm_controller','crane_plus_gripper_controller'}<=active and all(len(v)>=3 for v in samples.values()) and client.service_is_ready():future=client.call_async(ListControllers.Request())
            if future and future.done():
                controllers=[{'name':c.name,'state':c.state} for c in future.result().controller];future=None
            active={c['name'] for c in controllers if c['state']=='active'}
            if future is None and {'joint_state_broadcaster','crane_plus_arm_controller','crane_plus_gripper_controller'}<=active and all(len(v)>=3 for v in samples.values()):break
        else:raise TimeoutError('controllers and advancing JointState/camera were not ready')
        result='PASS'
    except Exception as exc:result='FAIL';error=f'{type(exc).__name__}: {exc}'
    finally:node.destroy_node();rclpy.shutdown()
    report={'result':result,'elapsed_sec':time.monotonic()-started,'controllers':controllers,'advancing_header_stamps_ns':samples,'environment':expected,'error':error,'motion_publish_count':0}
    if args.report:args.report.parent.mkdir(parents=True,exist_ok=True);args.report.write_text(json.dumps(report,indent=2))
    print(json.dumps(report));return 0 if result=='PASS' else 1
if __name__=='__main__':raise SystemExit(main())