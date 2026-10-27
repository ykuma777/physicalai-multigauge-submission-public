"""Offline ROI QA contact sheet from saved real ROS observations (no truth access)."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import cv2
import numpy as np
import vision


def put(canvas, value, x, y, scale=.5, color=(235,235,235)):
    cv2.putText(canvas, str(value), (x,y), cv2.FONT_HERSHEY_SIMPLEX, scale, color, 1, cv2.LINE_AA)


def geometry(image):
    """Diagnostic ellipse fit, never used for class prediction or action selection."""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 40, 120)
    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
    candidates = []
    for contour in contours:
        if len(contour) < 40:
            continue
        (x,y),(a,b),angle = cv2.fitEllipse(contour)
        major,minor = max(a,b),min(a,b)
        if abs(x-320) < 55 and abs(y-310) < 55 and 170 < major < 300 and 65 < minor < 185:
            candidates.append({'center_xy':[float(x),float(y)],'axes_px':[float(a),float(b)],
                               'angle_deg':float(angle),'contour_points':len(contour),
                               'score':float(abs(x-320)+abs(y-310)+abs(major-235)*.1)})
    return min(candidates,key=lambda item:item['score']) if candidates else None


def build(run_dir, output):
    run = json.loads((run_dir/'run_manifest.json').read_text())
    settings,_,_ = vision.verified_contract()
    canvas = np.full((770,1152,3),(26,26,26),np.uint8)
    put(canvas,'REAL ROS CAMERA / FIXED ROI REVIEW',20,28,.8)
    put(canvas,'Run '+run['run_id'],20,53,.48)
    rows={}
    for index,key in enumerate('ABC'):
        target = run['targets'][key]
        info = target.get('image') or {}
        if not info:
            raise ValueError(key+' has no captured ROS image; cannot claim ROI review')
        path=Path(info['image_path'])
        if vision.sha256(path)!=info['image_sha256']:
            raise ValueError(key+' saved image hash changed')
        image=cv2.imread(str(path),cv2.IMREAD_COLOR)
        gray,quality=vision.preprocess(image,settings)
        x,y=map(int,settings['roi_center_xy']);half=int(settings['roi_size_px'])//2
        original_crop=image[y-half:y+half,x-half:x+half].copy()
        annotated=image.copy()
        cv2.rectangle(annotated,(x-half,y-half),(x+half-1,y+half-1),(0,220,255),2)
        ellipse=geometry(image)
        if ellipse:
            center=tuple(int(v) for v in ellipse['center_xy'])
            cv2.drawMarker(annotated,center,(255,150,0),cv2.MARKER_CROSS,14,1)
        left=index*384
        label=(target.get('inference') or {}).get('label','indeterminate')
        put(canvas,f'{key}  AI: {label}',left+12,85,.75)
        canvas[100:388,left:left+384]=cv2.resize(annotated,(384,288))
        put(canvas,'Yellow box: exact fixed 192px ROI',left+12,410,.48)
        put(canvas,'Unmodified crop, 1.33x for review',left+12,435,.48)
        canvas[450:706,left+64:left+320]=cv2.resize(original_crop,(256,256),interpolation=cv2.INTER_NEAREST)
        put(canvas,info['image_sha256'][:24],left+12,731,.42)
        put(canvas,'ROI std %.2f / edges %d'%(quality['roi_std'],quality['roi_canny_edges']),left+12,754,.46)
        rows[key]={'source_image':str(path),'source_sha256':info['image_sha256'],
                   'capture_received_at_utc':info.get('received_at_utc'),
                   'roi_bounds_xyxy':quality['roi_bounds_xyxy'],'roi_quality':quality,
                   'diagnostic_dial_ellipse':ellipse,'label':label}
    output.parent.mkdir(parents=True,exist_ok=True)
    if not cv2.imwrite(str(output),canvas):
        raise RuntimeError('contact sheet write failed')
    report={'run_id':run['run_id'],'contact_sheet':str(output),'contact_sheet_sha256':vision.sha256(output),
            'sources':rows,'preprocessing_sha256':vision.canonical_hash(vision.contract(settings)),
            'source_images_unmodified':True,
            'qa_scope':'Read-only visual/geometry review; no angle/truth read; ellipse diagnostic only, not inference input.',
            'manual_review':'PENDING'}
    output.with_suffix('.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    build(args.run_dir,args.output)


if __name__=='__main__':
    main()