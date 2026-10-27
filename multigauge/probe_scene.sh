source /opt/ros/humble/setup.bash
source /home/ubuntu/airobot_ws/install/setup.bash
export ROS_DOMAIN_ID=46
python3 - <<'PY'
import rclpy,json
from moveit_msgs.srv import GetPlanningScene
from rosidl_runtime_py.convert import message_to_ordereddict
rclpy.init();n=rclpy.create_node('scene_probe');c=n.create_client(GetPlanningScene,'/get_planning_scene');c.wait_for_service(timeout_sec=5)
r=GetPlanningScene.Request();r.components.components=16;f=c.call_async(r);rclpy.spin_until_future_complete(n,f,timeout_sec=5)
print(json.dumps(message_to_ordereddict(f.result().scene.world),indent=2));n.destroy_node();rclpy.shutdown()
PY