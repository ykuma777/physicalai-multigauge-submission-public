"""Explicit new trials after inspected service failure and environment reset."""
import datetime,hashlib,json,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parent

def main():
    original=ROOT/'results/campaigns/campaign_20261027T021152Z/CAMPAIGN.json'
    prior=json.loads(original.read_text());identifier='continuation_'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ');output=ROOT/'results/campaigns'/identifier;output.mkdir(parents=True,exist_ok=False)
    record={'campaign_id':identifier,'continuation_of':str(original),'reason':'Original AAA trial stopped before observe_C send when Gazebo SDF read returned no data. Independent geometry read passed afterward. Operator reset only new environment, retained failed trial and then explicitly started fresh trials. No motion from stopped trial was resent.','source_hashes':prior['source_hashes'],'attempts':[],'result':'RUNNING'}
    def save():(output/'CAMPAIGN.json').write_text(json.dumps(record,indent=2))
    save()
    for index,(name,case,normal,abnormal) in enumerate([('eight_combinations','AAA','.045','.875'),('held_out','NNN','.095','.935'),('held_out','AAA','.095','.935')]):
        for rel,digest in record['source_hashes'].items():
            if hashlib.sha256((ROOT/rel).read_bytes()).hexdigest()!=digest:raise RuntimeError('runtime changed since original campaign: '+rel)
        argv=['bash',str(ROOT/'run.sh'),'--combination',case,'--campaign',name,'--normal-angle',normal,'--abnormal-angle',abnormal,'--record']
        print(json.dumps({'case':case,'campaign':name,'status':'STARTING'}),flush=True)
        with (output/f'case_{index+1:02d}.log').open('w') as log:p=subprocess.run(argv,stdout=log,stderr=subprocess.STDOUT)
        run_id=next((s.split('=',1)[1] for s in (output/f'case_{index+1:02d}.log').read_text().splitlines() if s.startswith('RUN_ID=')),None)
        record['attempts'].append({'case':case,'campaign':name,'run_id':run_id,'argv':argv,'returncode':p.returncode});save();print(json.dumps(record['attempts'][-1]),flush=True)
        if p.returncode:record['result']='FAIL_STOPPED';save();return 1
    record['result']='PASS';save();return 0
if __name__=='__main__':raise SystemExit(main())