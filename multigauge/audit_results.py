"""Independent consistency audit of completed real trial evidence."""
import hashlib,json,math
from pathlib import Path
ROOT=Path(__file__).resolve().parent

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    evaluation=json.loads((ROOT/'results/evaluation.json').read_text());checks=[];commands=[];max_error=0.;point_clearance=[];point_angles=[];geometry_count=0
    def check(name,value,detail=None):
        checks.append({'check':name,'result':'PASS' if value else 'FAIL','detail':detail})
    check('all_eight_combinations_have_a_successful_full_trial',set(evaluation['coverage']['combinations_successful'])==set(evaluation['coverage']['combinations_expected']))
    check('all_attempts_are_scored_with_failures_retained',evaluation['metrics']['trial_count']==len(list((ROOT/'results/truth').glob('*.json'))))
    for path in sorted((ROOT/'results/campaigns').glob('*/CAMPAIGN.json')):
        campaign=json.loads(path.read_text())
        for rel,digest in campaign['source_hashes'].items():check(campaign['campaign_id']+' frozen '+rel,sha(ROOT/rel)==digest)
    for row in evaluation['runs']:
        run=json.loads(Path(row['runtime_manifest']).read_text()) if row.get('runtime_manifest') else {}
        if run.get('result')=='PASS':
            check(row['run_id']+' label/hash/freshness/display/selection/home evidence',row['task_success'])
        for index,motion in enumerate(run.get('motions',[])):
            if motion['publish_count']==1:
                commands.append(motion['command_id']);check(row['run_id']+' one publication '+motion['to'],True)
                if motion['arrival']['result']=='PASS':max_error=max(max_error,max(abs(x) for x in motion['arrival']['errors_rad']))
            else:check(row['run_id']+' no send after rejected path',run['result']=='FAIL' and index==len(run['motions'])-1 and motion['publish_count']==0)
            geometry_path=Path(motion.get('geometry_report',''))
            if geometry_path.is_file():
                geometry=json.loads(geometry_path.read_text());geometry_count+=1
                if motion['publish_count']==1:check(row['run_id']+' actual geometry before '+motion['to'],geometry['result']=='PASS')
            if motion['to'].startswith('point_') and motion['arrival']['result']=='PASS':
                ident=motion['to'][-1];fk=motion['fk'];relation=fk['pointing_correspondence'];clearance=min(relation['tip_clearance_by_entity_m'].values());point_clearance.append(clearance);point_angles.append(fk['crane_plus_link_endtip']['axis_to_target_deg'])
                check(row['run_id']+' pointing identity '+ident,relation['selected_target']==ident and relation['nearest_entity']=='gauge_'+ident and clearance>=.025)
        if row.get('runtime_manifest'):
            rd=Path(row['runtime_manifest']).parent
            if (rd/'display_trace.jsonl').exists() and (rd/'display_audit.jsonl').exists():
                trace=[json.loads(s) for s in (rd/'display_trace.jsonl').read_text().splitlines()];acks=[json.loads(s) for s in (rd/'display_audit.jsonl').read_text().splitlines()];by_revision={a['revision']:a for a in acks};okay=True
                for state in trace:
                    ack=by_revision.get(state['revision'])
                    if not ack:okay=False;continue
                    expected_hashes={k:t['image']['image_sha256'] if t.get('image') else None for k,t in state['targets'].items()};expected_labels={k:t['inference']['label'] if t.get('inference') else None for k,t in state['targets'].items()}
                    okay &= ack['run_id']==run['run_id'] and ack['image_hashes']==expected_hashes and ack['labels']==expected_labels and ack['selected_targets']==state['selected_targets'] and ack['pointing_target']==state['pointing_target']
                # The earliest development failure is specifically the ACK schema mismatch.
                if run.get('result')=='PASS':check(row['run_id']+' every visible revision acknowledged with exact image/label/selection',okay)
    check('all_sent_command_ids_unique',len(commands)==len(set(commands)))
    original_model=ROOT.parent/'camera_demo/artifacts/gauge_hog_svm.yml';original_runtime=ROOT.parent/'camera_demo/configs/runtime.yaml'
    check('original_model_retained',sha(original_model)=='dc3192f77dbeb47af9007853dbff516758ac8d6569ce52a98560ae1009a2ea9b')
    check('original_runtime_retained',sha(original_runtime)=='7f36fd0fbc9d47ae21cf9fb076f5be5187f5af0bb3cda4a34dfb0d30fdb613e7')
    report={'result':'PASS' if all(c['result']=='PASS' for c in checks) else 'FAIL','scope':'Evidence consistency and complete case coverage; this PASS does not mean every task trial succeeded. Failures remain in metrics.','checks':checks,'metrics':evaluation['metrics'],'by_campaign':evaluation['by_campaign'],'maximum_verified_joint_error_rad':max_error,'pointing_tip_minimum_box_clearance_m':min(point_clearance) if point_clearance else None,'maximum_pointing_tip_axis_to_target_deg':max(point_angles) if point_angles else None,'geometry_reports':geometry_count,'sent_command_ids':len(commands)}
    (ROOT/'evidence/final_results_qa.json').write_text(json.dumps(report,indent=2));print(json.dumps({k:v for k,v in report.items() if k not in ('checks','metrics','by_campaign')},indent=2))
    return 0 if report['result']=='PASS' else 1
if __name__=='__main__':raise SystemExit(main())