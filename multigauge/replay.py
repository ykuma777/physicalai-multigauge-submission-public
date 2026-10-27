"""Replay archived inference in a fresh directory; never used for runtime selection."""
import argparse,hashlib,importlib.util,json,tempfile,shutil,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output-dir',type=Path,required=True);args=ap.parse_args();out=args.output_dir;out.mkdir(parents=True,exist_ok=False);checks=[]
    for manifest in sorted((ROOT/'results/runs').glob('*/run_manifest.json')):
        run=json.loads(manifest.read_text())
        if run['result']!='PASS':continue
        provenance=json.loads((manifest.parent/'RUN_PROVENANCE.json').read_text())
        for asset in provenance['inputs_programs_configs']:
            if sha(Path(asset['snapshot']))!=asset['sha256']:raise ValueError('archived program/config changed')
        snapshot=manifest.parent/'source_snapshot'
        with tempfile.TemporaryDirectory(prefix='multigauge_replay_') as temp:
            workspace=Path(temp);shutil.copytree(snapshot,workspace,dirs_exist_ok=True)
            spec=importlib.util.spec_from_file_location('archived_vision_'+run['run_id'],workspace/'multigauge/vision.py');vision=importlib.util.module_from_spec(spec);spec.loader.exec_module(vision)
            rows=[]
            for ident in 'ABC':
                target=run['targets'][ident];image=Path(target['image']['image_path']);replayed_image=workspace/(ident+'.png');shutil.copy2(image,replayed_image)
                prediction=vision.classify(replayed_image);original=target['inference']
                fields=['label','image_sha256','svm_raw_margin','preprocessing_sha256','model_sha256','quality']
                for field in fields:
                    if prediction[field]!=original[field]:raise ValueError(run['run_id']+' replay differs: '+field)
                rows.append({'target_id':ident,'image_sha256':prediction['image_sha256'],'label':prediction['label'],'raw_margin_exact_match':True,'input_model_preprocessing_exact_match':True})
            record={'run_id':run['run_id'],'result':'PASS','checks':rows,'archived_source_hash_verified':True}
            (out/(run['run_id']+'.json')).write_text(json.dumps(record,indent=2));checks.append(record)
    report={'result':'PASS' if checks else 'FAIL','scope':'Saved real image inference reproduced using archived program/model/config in a fresh temporary directory per run. No re-rendering or physical determinism claim.','replayed_runs':len(checks),'replayed_images':3*len(checks),'runs':checks}
    (out/'REPLAY_QA.json').write_text(json.dumps(report,indent=2));print(json.dumps({k:v for k,v in report.items() if k!='runs'}))
if __name__=='__main__':main()