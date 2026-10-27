"""Create a fresh final portable reference and ZIP, never replacing legacy assets."""
from __future__ import annotations
import argparse,datetime,hashlib,json,shutil,subprocess,sys,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parent;REPO=ROOT.parent
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def read(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def dump(p,v):Path(p).write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def entry(p,role):return {'canonical_path':str(p.resolve()),'size_bytes':p.stat().st_size,'sha256':sha(p),'role':role}
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output-dir',type=Path,required=True);ap.add_argument('--archive-name',default='physicalai_multigauge_final_repro.zip');ap.add_argument('--reference-name',default='REPRO_REFERENCE_FINAL');ap.add_argument('--validate-replay',action='store_true');args=ap.parse_args();base=args.output_dir.resolve()
    if not base.is_dir():raise FileNotFoundError(base)
    evaluation=read(ROOT/'results/finalization_20261027/evaluation_final.json')
    if evaluation['audit_result']!='PASS' or evaluation['groups']['new_final_ui']['task_success_trials']!=3:raise ValueError('final evaluation not accepted')
    qa=read(base/'QA.json')
    if qa.get('result')!='PASS':raise ValueError('final media QA not PASS')
    out=base/args.reference_name;archive=base/args.archive_name
    if out.parent!=base or archive.parent!=base:raise ValueError('reference/archive names must be direct child names')
    if out.exists() or archive.exists():raise FileExistsError('reference or archive exists: choose a new final folder')
    initial_files=[p for p in base.rglob('*') if p.is_file()]
    out.mkdir();external=[];copied_sources={}
    for name in ['01_PROGRAMS','02_COMMANDS','03_CONFIG','04_STATE','05_MANIFEST_PROVENANCE','06_QA','07_DOCS']:(out/name).mkdir()
    def copy(p,relative):
        p=Path(p);dest=out/relative;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,dest);copied_sources[dest.relative_to(out).as_posix()]=entry(p,'embedded original asset')
    def tree(source,relative,exclude=None):
        if not source.exists():return
        for p in sorted(source.rglob('*')):
            if p.is_file() and (not exclude or not exclude(p)) and '__pycache__' not in p.parts:copy(p,Path(relative)/p.relative_to(source))
    for p in sorted(ROOT.iterdir()):
        if p.is_file() and p.suffix in ('.py','.ps1','.sh','.yaml'):copy(p,Path('01_PROGRAMS/multigauge')/p.name)
    original=subprocess.check_output(['git','-c','core.quotepath=false','-c','safe.directory='+str(REPO).replace('\\','/'),'-C',str(REPO),'ls-files','camera_demo','final_project'],text=True,encoding='utf-8').splitlines()
    for relative in original:
        p=REPO/relative
        # Preserve submitted results in place; only original source, model, config and training data are needed here.
        if any(part in {'results','logs','outputs','submission','__pycache__'} for part in Path(relative).parts):continue
        copy(p,Path('01_PROGRAMS')/relative)
    for package in ['camera_demo/ros2_ws/src','final_project/ros2_ws/src']:
        tree(REPO/package,Path('01_PROGRAMS')/package,lambda p:p.suffix=='.pyc')
    for name in ['LICENSE','NOTICE.md','.gitattributes']:
        if (REPO/name).exists():copy(REPO/name,Path('01_PROGRAMS')/name)
    for p in ROOT.glob('*.md'):copy(p,Path('01_PROGRAMS/multigauge')/p.name);copy(p,Path('07_DOCS/source_docs')/p.name)
    tree(ROOT/'configs','01_PROGRAMS/multigauge/configs');tree(ROOT/'configs','03_CONFIG/final')
    copy(ROOT/'compose.yaml','03_CONFIG/compose.yaml');copy(ROOT/'evidence/base_commit.txt','01_PROGRAMS/multigauge/evidence/base_commit.txt')
    for name in ['evaluation.json','evaluation.csv','RESULTS.md','target_results.csv','motion_results.csv']:
        p=ROOT/'results'/name
        if p.exists():copy(p,Path('04_STATE/baseline16')/name)
    tree(ROOT/'results/truth','04_STATE/truth')
    final_ids={r['run_id'] for r in evaluation['runs'] if r['group']=='new_final_ui'}
    for rd in sorted((ROOT/'results/runs').iterdir()):
        if not rd.is_dir():continue
        for p in sorted(rd.rglob('*')):
            if not p.is_file() or '__pycache__' in p.parts:continue
            if p.suffix=='.mp4' and rd.name not in final_ids:
                external.append({**entry(p,'KEEP legacy recording'),'reason_not_embedded':'Previous recordings remain canonical; final three raw recordings are embedded.'});continue
            if p.name.startswith('dashboard_rev_'):
                external.append({**entry(p,'KEEP original GUI revision evidence'),'reason_not_embedded':'Full display traces, hashes and final representative frames are embedded; intermediate desktop PNGs remain canonical.'});continue
            copy(p,Path('04_STATE/runs')/rd.name/p.relative_to(rd))
    tree(ROOT/'results/campaigns','02_COMMANDS/campaigns');tree(ROOT/'generated/setup','04_STATE/setup')
    tree(ROOT/'results/finalization_20261027','04_STATE/finalization_20261027')
    for directory in (ROOT/'results').glob('reproduction_*'):
        if directory.is_dir():tree(directory,Path('06_QA')/directory.name)
    for p in sorted((ROOT/'evidence').rglob('*')):
        if not p.is_file() or '__pycache__' in p.parts:continue
        if p.name in {'environment_inventory.json','public_main_verification.json','source_preservation_qa.json'} or p.suffix=='.log':
            external.append({**entry(p,'KEEP original environment/preservation/log evidence'),'reason_not_embedded':'Unnecessary environment-specific inventory and verbose legacy logs remain canonical.'});continue
        if p.suffix in ('.json','.png','.txt','.urdf','.sdf'):copy(p,Path('06_QA/evidence')/p.relative_to(ROOT/'evidence'))
    for name in ['CODEX_FINALIZE.md','MULTIGAUGE_FINAL_SPEC.pdf']:copy(ROOT/'results'/name,Path('07_DOCS/USER_TARGET_SPEC_NOT_IMPLEMENTATION_PROOF')/name)
    for p in initial_files:
        if p.suffix=='.mp4' and p.name!='PAI最終課題_ykumakuma777.mp4' and p.name!='physicalai_multigauge_final.mp4':
            external.append({**entry(p,'KEEP final generation intermediate'),'reason_not_embedded':'Final encoded video plus all three complete raw videos and generator are embedded.'});continue
        copy(p,Path('07_DOCS/final_artifacts')/p.relative_to(base))
    commands={'exact_argv':[sys.executable,*sys.argv],'python_version':sys.version,'program_sha256':sha(__file__),'evaluation_sha256':sha(ROOT/'results/finalization_20261027/evaluation_final.json'),'final_run_ids':sorted(final_ids),'created_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat()}
    dump(out/'02_COMMANDS/FINAL_PACKAGE_COMMAND.json',commands)
    text='''# 完成版の再現用資産

01_PROGRAMS が起動用リポジトリの構造です。camera_demo のモデル・設定・学習画像と、camera_inspection/inspection_task のROSパッケージソースを含みます。コードのLICENSE・NOTICEは元の由来を保持します。

04_STATE は旧16＋日本語UI追加3の全19試行、対象準備後の正解、失敗記録、各試行時点のソースsnapshot、観測画像、軌道とFKです。対象準備前に終了した基盤試行も別記で保持します。正解は採点専用で、ロボットへ渡しません。絶対パスは実行時のcanonical pathです。

07_DOCS/USER_TARGET_SPEC_NOT_IMPLEMENTATION_PROOF はユーザー提供の目標仕様です。実装確認済みの人向け仕様と提出PDF・動画は07_DOCS/final_artifactsです。目標仕様を実施証拠として扱わないでください。

起動する場合は01_PROGRAMSを新規作業フォルダーへコピーし、multigauge/README.mdのstart.ps1を実行します。Docker Desktopと固定イメージが必要です。既存container名/Compose/ROS/Gazebo/VNCが使用中なら起動ガードが停止します。他環境を自動停止・再作成しません。別名・domain・partition・portにそろえた別設定を用意するか、利用者が既存環境を確認して操作してください。

保存画像の推論を新しい一時作業先から再現するには、04_STATE/runsとtruthを01_PROGRAMS/multigauge/resultsへコピーします。Docker mountの /home/ubuntu/multigauge をこのコピー先へ対応させます。保存記録は書き換えません。replay.py は成功試行のみ対象です。最終版の全観測画像（失敗AAAのA・Bを含む）の検証結果と各画像hashは04_STATE/finalization_20261027/replay_observed_finalにあります。再実行コードはfinal_evaluate.pyです。例（展開先を/home/ubuntu/final_referenceへ対応させた場合）：`python3 /home/ubuntu/final_reference/01_PROGRAMS/multigauge/final_evaluate.py --replay-only --state-dir /home/ubuntu/final_reference/04_STATE --legacy-replay /home/ubuntu/final_reference/06_QA/reproduction_20261027_final/REPLAY_QA.json --output-dir /tmp/multigauge_replay_fresh`。出力先は未存在の新規フォルダーを指定してください。このモードは保存記録の絶対パスを書き換えず、04_STATE内の各runの画像・snapshotを相対対応させ、ロボット命令を出しません。

今回確認した範囲は、実際の日本語画面を伴う3試行、到達・画像hash・表示ACK・対象位置対応、保存済み全観測画像の推論完全一致、全同梱資産hashとZIP CRCです。任意PCの完全な環境構築やGazebo再描画の画素一致は主張しません。初回のROSビルドはcamera_demo/scripts/build_ros.shが担当します。

最終動画と追加3試行のscreen.mp4は同梱します。旧録画・GUI中間スクリーンショット・環境依存の詳細情報は元の場所に保持し、EXTERNAL_EVIDENCE_MANIFEST.jsonへサイズ・SHAを記録します。原記録の削除はしていません。
'''
    (out/'07_DOCS/REPRODUCTION_FINAL.md').write_text(text,encoding='utf-8')
    dump(out/'05_MANIFEST_PROVENANCE/EXTERNAL_EVIDENCE_MANIFEST.json',external)
    files=[{'path':p.relative_to(out).as_posix(),'size_bytes':p.stat().st_size,'sha256':sha(p),'source':copied_sources.get(p.relative_to(out).as_posix())} for p in sorted(out.rglob('*')) if p.is_file()]
    dump(out/'05_MANIFEST_PROVENANCE/FILES_SHA256.json',{'status':'VERIFIED','files':files,'self_exclusion':'This manifest excludes itself to avoid a circular hash.'})
    for f in files:
        if sha(out/f['path'])!=f['sha256']:raise ValueError('copied asset mismatch '+f['path'])
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for p in sorted(out.rglob('*')):
            if p.is_file():z.write(p,Path(out.name)/p.relative_to(out))
    with zipfile.ZipFile(archive) as z:
        bad=z.testzip()
        if bad:raise ValueError('CRC mismatch '+bad)
        manifest=read(out/'05_MANIFEST_PROVENANCE/FILES_SHA256.json')
        for item in manifest['files']:
            if hashlib.sha256(z.read(out.name+'/'+item['path'])).hexdigest()!=item['sha256']:raise ValueError('ZIP asset hash mismatch '+item['path'])
        zip_count=len(z.namelist())
    extracted_qa={'result':'NOT_TESTED'}
    if args.validate_replay:
        validation=base/'ZIP_REPLAY_VALIDATION';validation.mkdir(exist_ok=False)
        with zipfile.ZipFile(archive) as z:
            for name in z.namelist():
                if not (validation/name).resolve().is_relative_to(validation.resolve()):raise ValueError('archive path outside validation folder')
            z.extractall(validation)
        extracted=validation/out.name
        for item in read(extracted/'05_MANIFEST_PROVENANCE/FILES_SHA256.json')['files']:
            if sha(extracted/item['path'])!=item['sha256']:raise ValueError('extracted SHA mismatch '+item['path'])
        def linux(p):return '/home/ubuntu/multigauge/'+p.resolve().relative_to(ROOT.resolve()).as_posix()
        output=validation/'replayed_images';command=['docker','exec','physicalai-multigauge','python3',linux(extracted/'01_PROGRAMS/multigauge/final_evaluate.py'),'--replay-only','--state-dir',linux(extracted/'04_STATE'),'--legacy-replay',linux(extracted/'06_QA/reproduction_20261027_final/REPLAY_QA.json'),'--output-dir',linux(output)]
        dump(validation/'RUN_COMMANDS.json',[command])
        with (validation/'replay.log').open('w',encoding='utf-8') as log:subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,check=True)
        replay=read(output/'REPLAY_QA.json')
        if replay['result']!='PASS' or replay['all_observed_replayed_images']!=evaluation['groups']['overall']['observed_classification_total']:raise ValueError('extracted inference replay did not match')
        extracted_qa={'result':'PASS','scope':'Fresh ZIP extraction; every included file hash and all archived observed-image inference fields exactly matched. No robot commands or simulator re-rendering.','extraction_directory':str(validation),'replayed_images':replay['all_observed_replayed_images'],'report':entry(output/'REPLAY_QA.json','Fresh extracted asset inference QA'),'exact_command':command}
    report={'result':'PASS','archive':entry(archive,'Final portable source, all trials and final media'),'reference':str(out),'reference_asset_count':len(files),'zip_entries':zip_count,'crc':'PASS','all_embedded_file_sha256':'PASS','external_item_count':len(external),'task_records':evaluation['groups']['overall']['trial_count'],'raw_final_videos_embedded':len(final_ids),'legacy_assets_preserved':True,'scope':'Archive integrity and source/evidence completeness, not a new simulator trial.','producer':commands,'fresh_zip_extraction_replay':extracted_qa}
    dump(base/'PACKAGE_QA.json',report);print(json.dumps(report,ensure_ascii=False,indent=2))
if __name__=='__main__':main()