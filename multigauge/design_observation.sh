source /opt/ros/humble/setup.bash
source /home/ubuntu/airobot_ws/install/setup.bash
export ROS_DOMAIN_ID=46
python3 - <<'PY'
import rclpy,numpy as np,json,math
from scipy.optimize import least_squares
from moveit_msgs.srv import GetPositionFK
from sensor_msgs.msg import JointState
from pathlib import Path
rclpy.init();n=rclpy.create_node('design_observation');c=n.create_client(GetPositionFK,'/compute_fk');c.wait_for_service(timeout_sec=5)
def fk(q):
 r=GetPositionFK.Request();r.header.frame_id='world';r.fk_link_names=['crane_plus_link_endtip'];r.robot_state.joint_state=JointState(name=['crane_plus_joint'+str(i) for i in range(1,5)]+['crane_plus_joint_hand'],position=[0.]+list(map(float,q))+[0.]);f=c.call_async(r);rclpy.spin_until_future_complete(n,f,timeout_sec=5);p=f.result().pose_stamped[0].pose;return p
old=[.4452598083,-.2765561289,.1015189153];p=fk(old);pitch=2*math.atan2(p.orientation.y,p.orientation.w);oldtip=[p.position.x,p.position.z];target=[oldtip[0]-.0175*math.cos(pitch),oldtip[1]+.0175*math.sin(pitch)]
def fun(q):
 p=fk(q);return [p.position.x-target[0],p.position.z-target[1],2*math.atan2(p.orientation.y,p.orientation.w)-pitch]
res=least_squares(fun,old,xtol=1e-11,ftol=1e-11,gtol=1e-11,diff_step=1e-4)
report={'old_observation_q234':old,'new_observation_q234':list(res.x),'new_camera_offset_xyz':[.0325,0,0],'old_tip_xz':oldtip,'desired_tip_xz':target,'residual':list(res.fun),'purpose':'Preserve optical transform after moving collision housing clear of upstream link at home'}
Path('/home/ubuntu/multigauge/evidence/observation_design.json').write_text(json.dumps(report,indent=2));print(json.dumps(report));n.destroy_node();rclpy.shutdown()
PY