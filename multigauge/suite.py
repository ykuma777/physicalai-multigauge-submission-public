"""Explicit finite campaign. One fresh trial per case, stop on any failure."""
import argparse,datetime,hashlib,json,os,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--include-held-out',action='store_true');args=parser.parse_args()
    campaign='campaign_'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    output=ROOT/'results/campaigns'/campaign;output.mkdir(parents=True,exist_ok=False)
    frozen={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [ROOT/'configs/motion.yaml',ROOT/'motion.py',ROOT/'coordinator.py',ROOT/'prepare.py',ROOT/'vision.py',ROOT/'dashboard.py',ROOT/'geometry_check.py',ROOT/'runner.py']}
    cases=[('eight_combinations',c,'.045','.875') for c in ['NNN','NNA','NAN','NAA','ANN','ANA','AAN','AAA']]
    if args.include_held_out:cases += [('held_out',c,'.095','.935') for c in ['NNN','AAA']]
    record={'campaign_id':campaign,'source_hashes':frozen,'cases':cases,'attempts':[],'result':'RUNNING','policy':'No automatic resends or retries. Stop campaign immediately after any failed trial.'}
    def save():(output/'CAMPAIGN.json').write_text(json.dumps(record,indent=2))
    save()
    for index,(name,case,normal,abnormal) in enumerate(cases):
        for rel,digest in frozen.items():
            if hashlib.sha256((ROOT/rel).read_bytes()).hexdigest()!=digest:raise RuntimeError('runtime changed during frozen campaign: '+rel)
        argv=['bash',str(ROOT/'run.sh'),'--combination',case,'--campaign',name,'--normal-angle',normal,'--abnormal-angle',abnormal]
        if case in ('NNN','AAA'):argv.append('--record')
        print(json.dumps({'case':index+1,'campaign':name,'combination':case,'status':'STARTING'}),flush=True)
        with (output/f'case_{index+1:02d}.log').open('w') as log:proc=subprocess.run(argv,stdout=log,stderr=subprocess.STDOUT)
        text=(output/f'case_{index+1:02d}.log').read_text();run_id=next((line.split('=',1)[1] for line in text.splitlines() if line.startswith('RUN_ID=')),None)
        record['attempts'].append({'case':case,'campaign':name,'run_id':run_id,'argv':argv,'returncode':proc.returncode});save()
        print(json.dumps({'case':index+1,'run_id':run_id,'returncode':proc.returncode}),flush=True)
        if proc.returncode:record['result']='FAIL_STOPPED';save();return 1
    record['result']='PASS';save();return 0
if __name__=='__main__':raise SystemExit(main())