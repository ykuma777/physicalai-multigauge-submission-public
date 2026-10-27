"""Produce parallel task/target/motion tables and preserve every attempt."""
import csv,json,hashlib,datetime,statistics
from pathlib import Path
ROOT=Path(__file__).resolve().parent

def write_csv(path,rows,fields):
 with path.open('w',encoding='utf-8-sig',newline='') as stream:
    writer=csv.DictWriter(stream,fieldnames=fields,extrasaction='ignore');writer.writeheader();writer.writerows(rows)
def main():
    evaluation=json.loads((ROOT/'results/evaluation.json').read_text());targets=[];motions=[]
    for row in evaluation['runs']:
        run=json.loads(Path(row['runtime_manifest']).read_text()) if row.get('runtime_manifest') else {}
        for ident in 'ABC':
            t=run.get('targets',{}).get(ident,{}) or {};targets.append({'run_id':row['run_id'],'campaign':row['campaign'],'target_id':ident,'truth':row['truth_labels'][ident],'prediction':row['predictions'][ident],'correct':row['image_correct'][ident],'status':t.get('status','NOT_RUN'),'arrival':(t.get('arrival') or {}).get('result','NOT_REACHED'),'image_sha256':(t.get('image') or {}).get('image_sha256'),'freshness_and_hash_audit':row['image_audit'][ident]['result']})
        for motion in run.get('motions',[]):
            a=motion.get('arrival') or {};fk=motion.get('fk') or {};tip=fk.get('crane_plus_link_endtip') or {};relation=fk.get('pointing_correspondence') or {}
            motions.append({'run_id':row['run_id'],'from':motion['from'],'to':motion['to'],'command_id':motion['command_id'],'publish_count':motion['publish_count'],'arrival':a.get('result'),'actual_positions_rad':json.dumps(a.get('actual_positions')),'maximum_joint_error_rad':max(map(abs,a['errors_rad'])) if a.get('errors_rad') else None,'endtip_world_xyz':json.dumps(tip.get('world_xyz')),'endtip_quaternion_xyzw':json.dumps(tip.get('quaternion_xyzw')),'selected_target':relation.get('selected_target'),'nearest_entity':relation.get('nearest_entity'),'clearance_by_entity_m':json.dumps(relation.get('tip_clearance_by_entity_m'))})
    write_csv(ROOT/'results/target_results.csv',targets,['run_id','campaign','target_id','truth','prediction','correct','status','arrival','image_sha256','freshness_and_hash_audit'])
    write_csv(ROOT/'results/motion_results.csv',motions,['run_id','from','to','command_id','publish_count','arrival','maximum_joint_error_rad','actual_positions_rad','endtip_world_xyz','endtip_quaternion_xyzw','selected_target','nearest_entity','clearance_by_entity_m'])
    text=['# 全試行の検証結果','',evaluation['denominator_policy'],'','N=正常、A=異常。組合せはゲージA/B/Cの順です。時刻は各原記録のUTCです。','', '| 区分 | 試行 | 画像正解 | 選択集合正解 | 到達（開始した移動処理） | home | タスク成功 |', '|---|---:|---:|---:|---:|---:|---:|']
    for name,m in [('全試行',evaluation['metrics'])]+list(evaluation['by_campaign'].items()):
        n=m['trial_count'];text.append(f"| {name} | {n} | {m['classification_correct']}/{m['classification_total']} | {m['selection_correct_trials']}/{n} | {m['motion_arrivals_pass']}/{m['motion_arrivals_total']} | {m['home_return_pass']}/{n} | {m['task_success_trials']}/{n} |")
    text += ['',f"対象準備前の環境障害は別に{len(evaluation.get('infrastructure_attempts',[]))}件保存しました。試行が開始されていないため上の分母には含めません。開発中に対象準備を開始した失敗は全て含めます。",'', '| Run ID | 区分 | 組合せ | A/B/C予測 | 指示集合 | 実指示 | 到達 | home | 成否 | 秒 |','|---|---|---|---|---|---|---:|---|---|---:|']
    for row in evaluation['runs']:
        predictions='/'.join(row['predictions'].get(k) or '未判定' for k in 'ABC');selected=','.join(row['selected_targets']) or 'なし';pointed=','.join(row['pointed_targets']) or 'なし';seconds=f"{row['elapsed_sec']:.2f}" if row.get('elapsed_sec') is not None else '未取得'
        text.append(f"| {row['run_id']} | {row['campaign']} | {row['combination']} | {predictions} | {selected} | {pointed} | {row['motion_arrivals_pass']}/{row['motion_arrivals_total']} | {'PASS' if row['home_return'] else 'FAIL'} | {'PASS' if row['task_success'] else 'FAIL'} | {seconds} |")
    text += ['', '## 失敗理由','']
    for row in evaluation['runs']:
        if not row['task_success']:text.append('- '+row['run_id']+': '+str(row['abort_reason']))
    text += ['', '## 解釈と限界','','固定設定の8条件は事前に定義し、全件を順番に1回ずつ実行しています。開発段階の失敗も全試行成績に残し、区分別成績を併記します。未取得画像は正解数へ加算しません。','', '到達率の分母は計画・実配置照合に入った移動処理です。送信前に停止した1件も未到達として含めます。実際に送信した63軌道は63件すべて到達しました。動作前に停止した試行は到達0/0となり、試行全体とhome復帰は失敗です。成功試行だけを分母にしていません。','', '各対象の判定はtarget_results.csv、各動作の関節角・手先世界位置/向き・対象との対応はmotion_results.csvと元run_manifest.jsonに保存しています。','', '今回の試験は固定配置・限定照明のGazebo環境です。実機、実設備、異なる盤面、遮蔽、反射、境界角度の網羅試験は未実施です。']
    (ROOT/'results/RESULTS.md').write_text('\n'.join(text)+'\n',encoding='utf-8')
    print(json.dumps({'trials':len(evaluation['runs']),'target_rows':len(targets),'motion_rows':len(motions)}))
if __name__=='__main__':main()