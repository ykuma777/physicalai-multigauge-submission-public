from pathlib import Path
import sys,xml.etree.ElementTree as ET,yaml
sys.path.insert(0,'/home/ubuntu/camera_demo/scripts')
from build_camera_robot import main
main()
p=Path('/home/ubuntu/camera_demo/generated/camera_robot.urdf');r=ET.parse(p)
config=yaml.safe_load(Path('/home/ubuntu/multigauge/configs/motion.yaml').read_text())
r.getroot().find("joint[@name='inspection_camera_joint']/origin").set('xyz',' '.join(map(str,config['camera_mount_xyz'])))
link=r.getroot().find("link[@name='inspection_camera_link']")
c=ET.SubElement(link,'collision');g=ET.SubElement(c,'geometry');ET.SubElement(g,'box',size='0.02 0.02 0.02')
ET.indent(r,space='  ');r.write(p,encoding='unicode',xml_declaration=True)
from ament_index_python.packages import get_package_share_directory
source=Path(get_package_share_directory('crane_plus_gazebo'))/'gui/gui.config'
text=source.read_text();root=ET.fromstring('<root>'+text[text.index('<window>'):]+'</root>')
for plugin in list(root.findall('plugin')):
 if plugin.get('filename') not in ('GzScene3D','WorldControl','WorldStats'):root.remove(plugin)
root.find("plugin[@filename='GzScene3D']/camera_pose").text='-0.32 -0.55 1.58 0 0.53 1.00'
Path('/home/ubuntu/multigauge/generated/gui.config').write_text('\n'.join(ET.tostring(x,encoding='unicode') for x in root))