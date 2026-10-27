"""Final offline evaluation; preserves baseline results and scores all attempts.
Run in the retained container so archived canonical /home/ubuntu paths resolve.
"""
from __future__ import annotations
import argparse,csv,hashlib,importlib.util,json,shutil,sys,tempfile
from datetime import datetime,timezone
from pathlib import Path
import evaluate
ROOT=Path(__file__).resolve().parent
FAIL_RUN='mg_20261027T022420Z_1b03b1'
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def read(p): return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def dump(p,v): Path(p).write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def metrics(rows):
    m=evaluate.metrics(rows); motions=[x for r in rows for x in r['motions']]
    sent=[x for x in motions if x['publish_once']]
    return {'trial_count':len(rows),'observed_classification_correct':m['classification_correct'],
      'observed_classification_total':m['observed_classification_total'],
      'observed_classification_correct_fraction':m['observed_only_classification_accuracy'],
      'planned_image_total':3*len(rows),'correct_planned_image_completion':m['classification_correct'],
      'correct_planned_image_completion_fraction':m['classification_accuracy'],
      'missing_or_unclassified_images':3*len(rows)-m['observed_classification_total'],
      'selection_correct_trials':m['selection_correct_trials'],'pointing_correct_trials':m['pointing_correct_trials'],
      'motion_handlers_attempted':len(motions),'sent_trajectories':len(sent),
      'sent_trajectory_arrivals_pass':sum(x['arrival_pass'] for x in sent),
      'unsent_motion_handlers':sum(not x['publish_once'] for x in motions),
      'all_motion_arrivals_trials':m['all_motion_arrivals_trials'],'home_return_pass':m['home_return_pass'],
      'task_success_trials':m['task_success_trials'],'task_success_rate':m['task_success_rate'],
      'elapsed_sec_total':m['elapsed_sec_total'],'elapsed_sec_mean':m['elapsed_sec_mean']}
def replay(rows,out,legacy_path=None):
    out.mkdir(exist_ok=False); records=[]
    for row in rows:
        rd=Path(row['runtime_manifest']).parent; run=read(rd/'run_manifest.json')
        available=[k for k in 'ABC' if (run.get('targets',{}).get(k,{}).get('inference') or {}).get('label') in evaluate.LABELS]
        if not available: continue
        prov=read(rd/'RUN_PROVENANCE.json')
        for asset in prov['inputs_programs_configs']:
            relative=asset['snapshot'].replace('\\','/').split('/source_snapshot/',1)[1]
            local_snapshot=rd/'source_snapshot'/relative
            if sha(local_snapshot)!=asset['sha256']: raise ValueError('snapshot SHA mismatch: '+str(local_snapshot))
        with tempfile.TemporaryDirectory(prefix='final_archived_inference_') as tmp:
            workspace=Path(tmp);shutil.copytree(rd/'source_snapshot',workspace,dirs_exist_ok=True)
            spec=importlib.util.spec_from_file_location('final_archived_'+run['run_id'],workspace/'multigauge/vision.py')
            vision=importlib.util.module_from_spec(spec);spec.loader.exec_module(vision)
            checks=[]
            for ident in available:
                target=run['targets'][ident];img=rd/Path(target['image']['image_path']).name;copy=workspace/(ident+'.png');shutil.copy2(img,copy)
                p=vision.classify(copy);orig=target['inference']
                fields=['label','image_sha256','svm_raw_margin','preprocessing_sha256','model_sha256','quality']
                mismatches=[k for k in fields if p[k]!=orig[k]]
                if mismatches:raise ValueError(run['run_id']+': replay mismatch '+str(mismatches))
                checks.append({'target_id':ident,'label':p['label'],'image_sha256':sha(img),'svm_raw_margin':p['svm_raw_margin'],'exact_fields':fields,'result':'PASS'})
            record={'run_id':run['run_id'],'group':row['group'],'runtime_result':run['result'],'result':'PASS','archived_source_hash_verified':True,'checks':checks}
            dump(out/(run['run_id']+'.json'),record);records.append(record)
    legacy_path=legacy_path or ROOT/'results/reproduction_20261027_final/REPLAY_QA.json'
    legacy=read(legacy_path)
    legacy_pairs={(r['run_id'],c['target_id'],c['image_sha256']) for r in legacy['runs'] for c in r['checks']}
    old_pairs={(r['run_id'],c['target_id'],c['image_sha256']) for r in records if r['group']=='old16' for c in r['checks']}
    difference=sorted(old_pairs-legacy_pairs)
    if len(legacy_pairs)!=33 or len(old_pairs)!=35 or {(r,t) for r,t,h in difference}!={(FAIL_RUN,'A'),(FAIL_RUN,'B')}:raise ValueError('33 vs 35 reconciliation failed')
    report={'result':'PASS','scope':'Offline archived-image inference only, using each exact source/model/config snapshot in a fresh temporary directory. No ROS commands, scene reconstruction or simulator determinism claim.',
      'legacy_success_only_images':len(legacy_pairs),'legacy_filter_evidence':{'program':str(ROOT/'replay.py'),'sha256':sha(ROOT/'replay.py'),'source_predicate':"if run['result']!='PASS':continue",'legacy_report_sha256':sha(legacy_path)},
      'old_observed_images':len(old_pairs),'old_failed_run_images':len(difference),'legacy_difference':[{'run_id':r,'target_id':t,'image_sha256':h} for r,t,h in difference],
      'all_observed_replayed_images':sum(len(r['checks']) for r in records),'replayed_runs':len(records),'runs':records}
    dump(out/'REPLAY_QA.json',report);return report

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output-dir',type=Path,required=True);ap.add_argument('--replay-observed',action='store_true');ap.add_argument('--replay-only',action='store_true');ap.add_argument('--state-dir',type=Path);ap.add_argument('--legacy-replay',type=Path);args=ap.parse_args();out=args.output_dir
    if args.replay_only:
        if not args.state_dir or not args.legacy_replay:raise ValueError('--state-dir and --legacy-replay required')
        oldids={r['run_id'] for r in read(args.state_dir/'baseline16/evaluation.json')['runs']}
        rows=[{'runtime_manifest':str(p),'group':'old16' if p.parent.name in oldids else 'new_final_ui'} for p in sorted((args.state_dir/'runs').glob('*/run_manifest.json'))]
        result=replay(rows,out,args.legacy_replay);print(json.dumps({k:v for k,v in result.items() if k!='runs'},ensure_ascii=False,indent=2));return 0
    out.mkdir(parents=True,exist_ok=True)
    for n in ['evaluation_final.json','evaluation_final.csv','RESULTS_FINAL.md','target_results_final.csv','motion_results_final.csv']:
        if (out/n).exists():raise FileExistsError(out/n)
    baseline=read(ROOT/'results/evaluation.json');oldids={r['run_id'] for r in baseline['runs']};raw=evaluate.evaluate(ROOT/'results');rows=raw['runs']
    if any(not r['finished_at_utc'] for r in rows):raise ValueError('unfinished trial: do not score while running')
    if len(oldids)!=16:raise ValueError('baseline must remain 16')
    for row in rows: row['group']='old16' if row['run_id'] in oldids else 'new_final_ui'
    old=[r for r in rows if r['group']=='old16'];new=[r for r in rows if r['group']=='new_final_ui']
    if {r['campaign'] for r in new}!={'final_japanese_ui'}:raise ValueError('unexpected new campaign')
    if len(new)!=3 or sorted(r['combination'] for r in new)!=['NAA','NAN','NNN']:raise ValueError('expected exactly three new UI scenarios')
    groups={'old16':metrics(old),'new_final_ui':metrics(new),'overall':metrics(rows)}
    if (groups['old16']['task_success_trials'],groups['old16']['observed_classification_correct'],groups['old16']['sent_trajectories'],groups['old16']['unsent_motion_handlers'])!=(11,35,63,1):raise ValueError('baseline changed')
    checks=[]
    def check(name,okay,detail=None):checks.append({'check':name,'result':'PASS' if okay else 'FAIL','detail':detail})
    start=read(out/'START_MANIFEST.json')
    for asset in start['inputs']:
        p=Path(asset['path']);p=p if p.exists() else ROOT.joinpath(*str(asset['path']).replace('\\','/').split('/multigauge/',1)[1].split('/'))
        check('immutable input '+p.name,sha(p)==asset['sha256'])
    frozen=read(ROOT/'results/campaigns/campaign_20261027T021152Z/CAMPAIGN.json')['source_hashes']
    for rel,digest in frozen.items():
        if rel!='dashboard.py':check('motion/inference contract unchanged '+rel,sha(ROOT/rel)==digest)
    check('original model retained',sha(ROOT.parent/'camera_demo/artifacts/gauge_hog_svm.yml')=='dc3192f77dbeb47af9007853dbff516758ac8d6569ce52a98560ae1009a2ea9b')
    check('original runtime contract retained',sha(ROOT.parent/'camera_demo/configs/runtime.yaml')=='7f36fd0fbc9d47ae21cf9fb076f5be5187f5af0bb3cda4a34dfb0d30fdb613e7')
    commands=[];max_error=0.;clearances=[];angles=[];geometry_count=0
    target_rows=[];motion_rows=[]
    for row in rows:
        rd=Path(row['runtime_manifest']).parent;run=read(rd/'run_manifest.json')
        check(row['run_id']+' runtime excludes preparation truth',run.get('truth_input')=='ABSENT')
        if row['group']=='new_final_ui':
            for rel,digest in frozen.items():
                if rel!='dashboard.py':check(row['run_id']+' archived motion/inference contract '+rel,sha(rd/'source_snapshot/multigauge'/rel)==digest)
        if run['result']=='PASS':check(row['run_id']+' full task image/selection/arrival/display/home evidence',row['task_success'])
        for ident in 'ABC':
            target=run.get('targets',{}).get(ident,{})
            target_rows.append({'run_id':row['run_id'],'group':row['group'],'campaign':row['campaign'],'combination':row['combination'],'target_id':ident,'truth_label':row['truth_labels'][ident],'prediction':row['predictions'][ident],'correct':row['image_correct'][ident],'observed':row['predictions'][ident] in evaluate.LABELS,'image_sha256':(target.get('image') or {}).get('image_sha256'),'captured_at_utc':(target.get('image') or {}).get('received_at_utc'),'image_audit':row['image_audit'][ident]['result']})
        for i,motion in enumerate(run.get('motions',[])):
            sent=motion.get('publish_count')==1;arrived=(motion.get('arrival') or {}).get('result')=='PASS'
            geometry_path=Path(motion.get('geometry_report',''));geometry=read(geometry_path) if geometry_path.is_file() else {};geometry_count+=bool(geometry)
            if sent:
                commands.append(motion['command_id']);check(row['run_id']+' geometry before '+motion['to'],geometry.get('result')=='PASS')
                check(row['run_id']+' reached sent '+motion['to'],arrived)
                if arrived:max_error=max(max_error,max(abs(v) for v in motion['arrival']['errors_rad']))
            else:check(row['run_id']+' no publication after stopped geometry/path',run['result']=='FAIL' and motion.get('publish_count')==0 and i==len(run['motions'])-1)
            fk=motion.get('fk') or {};rel=fk.get('pointing_correspondence') or {}
            if motion['to'].startswith('point_') and arrived:
                c=min(rel['tip_clearance_by_entity_m'].values());clearances.append(c);angles.append(fk['crane_plus_link_endtip']['axis_to_target_deg'])
                check(row['run_id']+' physical target identity '+motion['to'],rel['selected_target']==motion['to'][-1] and rel['nearest_entity']=='gauge_'+motion['to'][-1] and c>=.025)
            motion_rows.append({'run_id':row['run_id'],'group':row['group'],'command_id':motion.get('command_id'),'from':motion.get('from'),'to':motion.get('to'),'publish_count':motion.get('publish_count'),'arrival_pass':arrived,'geometry_result':geometry.get('result'),'actual_joint_positions':json.dumps((motion.get('arrival') or {}).get('actual_positions'),ensure_ascii=False),'fk':json.dumps(fk,ensure_ascii=False),'selected_target':rel.get('selected_target'),'nearest_entity':rel.get('nearest_entity')})
        trace=evaluate.read_lines(rd/'display_trace.jsonl');acks=evaluate.read_lines(rd/'display_audit.jsonl');byrev={a['revision']:a for a in acks}
        if run['result']=='PASS':
            okay=True
            for state in trace:
                ack=byrev.get(state['revision'],{});hashes={k:(v.get('image') or {}).get('image_sha256') for k,v in state['targets'].items()};labels={k:(v.get('inference') or {}).get('label') for k,v in state['targets'].items()}
                okay &= ack.get('run_id')==run['run_id'] and ack.get('image_hashes')==hashes and ack.get('labels')==labels and ack.get('selected_targets')==state['selected_targets'] and ack.get('pointing_target')==state['pointing_target']
            check(row['run_id']+' all display revisions exact ACK',bool(trace) and okay)
    check('sent command IDs unique, no resend',len(commands)==len(set(commands)))
    fail=read(ROOT/'results/runs'/FAIL_RUN/'run_manifest.json');geom=read(ROOT/'results/runs'/FAIL_RUN/'geometry_03.json')
    check('AAA failure retained and observe_C never sent',fail['result']=='FAIL' and len(fail['motions'])==3 and fail['motions'][-1]['to']=='observe_C' and fail['motions'][-1]['publish_count']==0)
    replay_report=replay(rows,out/'replay_observed_final') if args.replay_observed else {'result':'NOT_TESTED'}
    check('all observed images replayed including failed-run A/B',replay_report.get('result')=='PASS' and replay_report.get('all_observed_replayed_images')==groups['overall']['observed_classification_total'])
    audit_result='PASS' if all(c['result']=='PASS' for c in checks) else 'FAIL'
    report={'schema_version':1,'audit_result':audit_result,'task_result':raw['result'],'evaluated_at_utc':datetime.now(timezone.utc).isoformat(),'producer':{'program':str(Path(__file__)),'sha256':sha(__file__),'imported_scorer_sha256':sha(ROOT/'evaluate.py'),'exact_argv':sys.argv},
      'denominator_policy':'Every prepared/runtime attempt is retained. Observed classification excludes unacquired images; planned completion includes all three requested images per attempt. No failure is discarded.',
      'groups':groups,'by_campaign':{c:metrics([r for r in rows if r['campaign']==c]) for c in sorted({r['campaign'] for r in rows})},'coverage':raw['coverage'],'runs':rows,'infrastructure_attempts':raw['infrastructure_attempts'],'replay':replay_report,
      'failed_AAA':{'run_id':FAIL_RUN,'geometry_error':geom['error'],'geometry_elapsed_sec':geom['elapsed_sec'],'observe_C_publish_count':0,'interpretation':'形状照合の前段取得・解析で停止。C軌道は未送信。原因の確定は未了。'},
      'limits':['既知姿勢・合成盤面・有限のGazebo条件。実機故障や一般環境の分類性能は未検証。','追加3試行は日本語UI確認。動作・推論契約を保持し、全8条件の再実行はしていない。','再現は保存画像の推論と資産一致。物理シミュレーションの完全な決定論的再現を主張しない。']}
    dump(out/'evaluation_final.json',report)
    def csvwrite(name,data,columns=None):
        with (out/name).open('w',encoding='utf-8-sig',newline='') as f:
            w=csv.DictWriter(f,fieldnames=columns or list(data[0]),extrasaction='ignore');w.writeheader();w.writerows(data)
    csvwrite('evaluation_final.csv',rows,['run_id','group','campaign','combination','runtime_result','image_correct_count','image_observed_count','image_total','selection_correct','pointing_correct','motion_arrivals_pass','motion_arrivals_total','home_return','task_success','elapsed_sec','abort_reason'])
    csvwrite('target_results_final.csv',target_rows);csvwrite('motion_results_final.csv',motion_rows)
    lines=['# 完成版の実測結果','','旧16試行を保持し、日本語UIの追加3試行を区別して採点した。採点の正解は実行後に照合した。','','| 区分 | タスク成功 | 取得・推論画像の正解 | 予定画像の正しい判定完了 | 送信軌道到達 | 未送信停止 | home復帰 |','|---|---:|---:|---:|---:|---:|---:|']
    for group,m in groups.items():lines.append(f"| {group} | {m['task_success_trials']}/{m['trial_count']} | {m['observed_classification_correct']}/{m['observed_classification_total']} | {m['correct_planned_image_completion']}/{m['planned_image_total']} | {m['sent_trajectory_arrivals_pass']}/{m['sent_trajectories']} | {m['unsent_motion_handlers']} | {m['home_return_pass']}/{m['trial_count']} |")
    lines+=['','取得できた限定条件の正解割合であり、一般的な精度100%を主張しない。予定画像の完了割合は分類精度と呼ばない。','','| 試行 | 区分 | 条件 | 指示対象 | 指示完了 | home | タスク | 所要秒 |','|---|---|---|---|---|---|---|---:|']
    for r in rows:lines.append(f"| {r['run_id']} | {r['group']} | {r['combination']} | {','.join(r['selected_targets']) or 'なし'} | {','.join(r['pointed_targets']) or 'なし'} | {r['home_return']} | {r['task_success']} | {r['elapsed_sec']:.3f} |")
    lines+=['','旧推論再現33画像は成功11試行のみを抽出したため。失敗AAA試行で停止前に取得・正しく判定できたA・Bの2画像を加えると、旧観測35画像になる。新しいオフライン再現は失敗試行を含む観測済み全画像を対象とする。','','AAA停止：形状照合の前段取得・解析で停止し、observe_Cの軌道は未送信。元記録のエラーは `could not parse Gazebo world SDF safely`。通信障害や形状不一致と断定しない。','','所要時間は対象準備開始からhome到達または停止まで。失敗試行も分母に含む。','','検証範囲：保存画像の推論、画像hash・表示ACK・到達・実位置対応・送信回数・衝突形状照合。実機と未知条件は未検証。']
    (out/'RESULTS_FINAL.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    audit={'result':audit_result,'scope':'Evidence consistency; failures remain task failures. UI-only changes accepted separately from motion/inference contract.','checks':checks,'groups':groups,'maximum_verified_joint_error_rad':max_error,'pointing_tip_minimum_box_clearance_m':min(clearances),'maximum_pointing_tip_axis_to_target_deg':max(angles),'geometry_reports':geometry_count,'sent_command_ids':len(commands),'evaluation_sha256':sha(out/'evaluation_final.json'),'replay_report_sha256':sha(out/'replay_observed_final/REPLAY_QA.json')}
    dest=ROOT/'evidence/final_metrics_audit.json'
    if dest.exists():raise FileExistsError(dest)
    dump(dest,audit);print(json.dumps({'audit_result':audit_result,'groups':groups,'replay_images':replay_report.get('all_observed_replayed_images')},indent=2));return 0 if audit_result=='PASS' else 1
if __name__=='__main__':raise SystemExit(main())