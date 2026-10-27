source /opt/ros/humble/setup.bash
source /home/ubuntu/airobot_ws/install/setup.bash
export ROS_DOMAIN_ID=46 IGN_PARTITION=physicalai_multigauge_46
ros2 service list
python3 - <<'PY'
import rclpy
from moveit_msgs.srv import GetPositionFK
from sensor_msgs.msg import JointState
rclpy.init(); n=rclpy.create_node('probe_fk'); c=n.create_client(GetPositionFK,'/compute_fk'); print('FK ready',c.wait_for_service(timeout_sec=10))
for q in [[0,0,0,0],[0,.4452598083,-.2765561289,.1015189153],[0,.65,-.35,.14],[0,.8,-.45,.1]]:
 r=GetPositionFK.Request();r.header.frame_id='world';r.fk_link_names=['crane_plus_link_endtip','inspection_camera_link'];r.robot_state.joint_state=JointState(name=['crane_plus_joint'+str(i) for i in range(1,5)]+['crane_plus_joint_hand'],position=q+[0.])
 f=c.call_async(r);rclpy.spin_until_future_complete(n,f,timeout_sec=5); print(q,f.result())
n.destroy_node();rclpy.shutdown()
PY