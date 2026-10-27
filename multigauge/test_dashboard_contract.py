"""Offline fault injection for the on-screen input-identity gate; no robot movement."""
import importlib.util
import hashlib
import json
import tempfile
from pathlib import Path
import cv2
import numpy as np

ROOT=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('dashboard',ROOT/'dashboard.py')
d=importlib.util.module_from_spec(spec)
spec.loader.exec_module(d)
checks=[]
with tempfile.TemporaryDirectory(prefix='multigauge_display_contract_') as td:
    directory=Path(td)
    path=directory/'A.png'
    image=cv2.imread(str(ROOT.parent/'camera_demo/data/images/validation/normal/normal_02_00.png'))
    assert image is not None
    assert cv2.imwrite(str(path),image)
    sha=hashlib.sha256(path.read_bytes()).hexdigest()
    state={'targets':{k:{} for k in d.IDS},'selected_targets':[]}
    state['targets']['A']={'image':{'image_path':str(path),'image_sha256':sha},'inference':{'label':'normal','image_sha256':sha}}
    images,hashes,labels=d.verify_images(state,directory)
    assert hashes['A']==sha and labels['A']=='normal' and np.array_equal(images['A'],image)
    checks.append({'case':'same bytes decoded and hashed','result':'PASS'})
    def rejected(name):
        try:
            d.verify_images(state,directory)
        except (ValueError,OSError) as exc:
            checks.append({'case':name,'result':'PASS','rejection':str(exc)})
        else:
            raise AssertionError(name+' was accepted')
    state['targets']['A']['inference']['image_sha256']='0'*64
    rejected('inference uses another image')
    state['targets']['A']['inference']['image_sha256']=sha
    path.write_bytes(path.read_bytes()+b'corruption')
    rejected('image modified after coordinator capture')
    cv2.imwrite(str(path),np.zeros((240,320,3),np.uint8))
    state['targets']['A']['image']['image_sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
    rejected('wrong resolution')
    state['targets']['A']['image']=None
    rejected('decision exists without captured image')
    state['targets']['A']={}
    state['selected_targets']=['C','A']
    rejected('pointer target order differs from A-B-C')
report={'status':'VERIFIED','scope':'Offline image-identity/display contract fault injection; no Gazebo motion','checks':checks}
(ROOT/'evidence').mkdir(exist_ok=True)
(ROOT/'evidence/dashboard_contract_qa.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
print(json.dumps(report,indent=2))
