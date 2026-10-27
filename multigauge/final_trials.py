"""Three explicit real scenarios for Japanese UI verification; no automatic retries."""
import datetime,hashlib,json,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parent
SESSION=ROOT/'results/finalization_20261027'

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def main():
    marker=SESSION/'FINAL_TRIAL_PLAN.json'
    if marker.exists():raise FileExistsError('Final trial plan exists; never silently repeat a trial campaign')
    baseline=json.loads((SESSION/'CONTRACT_BASELINE.json').read_text())
    frozen={row['relative_path'].replace(chr(92),'/'):row['sha256'] for row in baseline['files']};frozen['dashboard.py']=sha(ROOT/'dashboard.py')
    # The order is specified by CODEX_FINALIZE.md. Preparation arguments stay in runner/prepare only.
    cases=['NAN','NAA','NNN'];record={'campaign':'final_japanese_ui','cases':cases,'started_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'frozen_hashes':frozen,'attempts':[],'result':'RUNNING','scope':'Display-only changes; no motion/inference contract edits; each case is a new real Gazebo run.'}
    def save():marker.write_text(json.dumps(record,indent=2))
    save()
    for index,case in enumerate(cases):
        for rel,digest in frozen.items():
            if sha(ROOT/rel)!=digest:raise RuntimeError('contract/UI changed during final trials: '+rel)
        argv=['bash',str(ROOT/'run.sh'),'--combination',case,'--campaign','final_japanese_ui','--record']
        print(json.dumps({'case':case,'stage':'STARTING'}),flush=True)
        log=SESSION/f'final_trial_{index+1:02d}.log'
        with log.open('w') as stream:result=subprocess.run(argv,stdout=stream,stderr=subprocess.STDOUT)
        run_id=next((line.split('=',1)[1] for line in log.read_text().splitlines() if line.startswith('RUN_ID=')),None)
        entry={'condition':case,'run_id':run_id,'returncode':result.returncode,'argv':argv,'log':str(log)}
        record['attempts'].append(entry);save();print(json.dumps(entry),flush=True)
        if result.returncode:record['result']='FAIL_STOPPED';save();return result.returncode
    record['result']='PASS';record['finished_at_utc']=datetime.datetime.now(datetime.timezone.utc).isoformat();save();return 0
if __name__=='__main__':raise SystemExit(main())