source /opt/ros/humble/setup.bash
export ROS_DOMAIN_ID=46
python3 - <<'PY'
import rclpy,hashlib,json,xml.etree.ElementTree as ET
from pathlib import Path
from rcl_interfaces.srv import GetParameters
root=Path('/home/ubuntu/multigauge');robot=Path('/home/ubuntu/camera_demo/generated/camera_robot.urdf')
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
rclpy.init();node=rclpy.create_node('verify_loaded_robot_description');results={}
for service in ['/move_group/get_parameters','/robot_state_publisher/get_parameters']:
 c=node.create_client(GetParameters,service)
 if not c.wait_for_service(timeout_sec=5):raise TimeoutError(service)
 req=GetParameters.Request();req.names=['robot_description'];f=c.call_async(req);rclpy.spin_until_future_complete(node,f,timeout_sec=5);value=f.result().values[0].string_value
 digest=hashlib.sha256(value.encode()).hexdigest();canonical=ET.canonicalize(value,strip_text=True);expected=ET.canonicalize(robot.read_text(),strip_text=True)
 results[service]={'raw_sha256':digest,'raw_bytes_equal':digest==sha(robot),'canonical_xml_sha256':hashlib.sha256(canonical.encode()).hexdigest(),'canonical_xml_equal':canonical==expected}
 if canonical!=expected:raise RuntimeError('loaded robot semantic XML differs')
 print(service,'loaded_length',len(value),'file_length',len(robot.read_text()),'loaded_prefix',repr(value[:70]),'generated_prefix',repr(robot.read_text()[:70]))
 (root/('evidence/loaded_'+service.split('/')[1]+'.urdf')).write_text(value)
report={'result':'PASS','generated_robot':{'path':str(robot),'sha256':sha(robot)},'loaded_descriptions':results,'world':{'path':str(root/'generated/world.sdf'),'sha256':sha(root/'generated/world.sdf')},'gui':{'path':str(root/'generated/gui.config'),'sha256':sha(root/'generated/gui.config')},'scope':'Loaded MoveIt/robot_state_publisher descriptions are canonically identical to generated URDF; ROS launch folds XML whitespace, so raw byte hashes differ. No robot command or scene modification.'}
(root/'evidence/loaded_robot_qa.json').write_text(json.dumps(report,indent=2));(root/'evidence/final_robot_description.urdf').write_bytes(robot.read_bytes());print(json.dumps(report,indent=2));node.destroy_node();rclpy.shutdown()
PY