source /opt/ros/humble/setup.bash
export DISPLAY=:0 XAUTHORITY=/home/ubuntu/.Xauthority
python3 - <<'PY'
import cv2,sys,platform,numpy,yaml,scipy,json,subprocess
from pathlib import Path
report={'os':platform.platform(),'python':sys.version,'opencv':cv2.__version__,'numpy':numpy.__version__,'yaml':yaml.__version__,'scipy':scipy.__version__,'ros':'humble','container':'physicalai-multigauge','image_digest':'sha256:b58ec74c019aacd9ce4818fa25fc5a9e0a1f22f8c9cd1f5260994bf15cd9eb63'}
for key,argv in [('gazebo',['ign','gazebo','--versions']),('ffmpeg',['ffmpeg','-version']),('graphics',['glxinfo','-B']),('ros_packages',['dpkg-query','-W','ros-humble-moveit*','ros-humble-ros-gz*','libignition-gazebo6*'])]:
 p=subprocess.run(argv,capture_output=True,text=True);report[key]={'argv':argv,'returncode':p.returncode,'stdout':p.stdout,'stderr':p.stderr}
Path('/home/ubuntu/multigauge/evidence/software_environment.json').write_text(json.dumps(report,indent=2));print(json.dumps({k:v for k,v in report.items() if k not in ('ffmpeg','ros_packages','graphics')}))
PY