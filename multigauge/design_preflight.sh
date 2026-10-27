source /opt/ros/humble/setup.bash
source /home/ubuntu/airobot_ws/install/setup.bash
export ROS_DOMAIN_ID=46 IGN_PARTITION=physicalai_multigauge_46 GZ_PARTITION=physicalai_multigauge_46
cd /home/ubuntu/multigauge
python3 - <<'PY'
import rclpy,json
from pathlib import Path
from motion import Motion,write
rclpy.init();n=Motion();n.register_scene(Path('evidence/design_scene.json'));out={}
for name,q in n.cfg['poses'].items():
 try:n.validity(q);out[name]={'result':'PASS','fk':n.fk(q,name[-1] if name!='home' else None)}
 except Exception as exc:out[name]={'result':'FAIL','error':str(exc)}
write(Path('evidence/design_poses.json'),out);print(json.dumps({k:v['result'] for k,v in out.items()}));n.destroy_node();rclpy.shutdown()
PY