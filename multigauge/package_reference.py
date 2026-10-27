"""Assemble a portable source/evidence reference without duplicating video media."""
import argparse,datetime,hashlib,json,shutil,subprocess,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parent;REPO=ROOT.parent

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def entry(p,role):return {'path':str(p),'size_bytes':p.stat().st_size,'sha256':sha(p),'role':role}
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output-dir',type=Path,default=ROOT/'REPRO_REFERENCE');args=ap.parse_args();out=args.output_dir.resolve();out.mkdir(parents=True,exist_ok=False)
    for name in ['01_PROGRAMS','02_COMMANDS','03_CONFIG','04_STATE','05_MANIFEST_PROVENANCE','06_QA','07_DOCS']:(out/name).mkdir()
    external=[]
    for p in sorted(ROOT.iterdir()):
        if p.is_file() and p.suffix in ('.py','.ps1','.sh'):
            dest=out/'01_PROGRAMS/multigauge'/p.name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,dest)
    original=subprocess.check_output(['git','-c','safe.directory='+str(REPO).replace('\\','/'),'-C',str(REPO),'ls-files','camera_demo','final_project'],text=True).splitlines()
    for relative in original:
        p=REPO/relative;dest=out/'01_PROGRAMS'/relative;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,dest)
    for p in (ROOT/'configs').glob('*'):
        for folder in ['03_CONFIG','01_PROGRAMS/multigauge/configs']:
            dest=out/folder/p.name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,dest)
    shutil.copy2(ROOT/'compose.yaml',out/'01_PROGRAMS/multigauge/compose.yaml');shutil.copy2(ROOT/'compose.yaml',out/'03_CONFIG/compose.yaml')
    for p in ROOT.glob('*.md'):shutil.copy2(p,out/'07_DOCS'/p.name)
    for name in ['LICENSE','NOTICE.md']:
        if (REPO/name).exists():shutil.copy2(REPO/name,out/'01_PROGRAMS'/name)
    for p in list((ROOT/'results').glob('evaluation.*'))+list((ROOT/'results').glob('*_results.csv'))+list((ROOT/'results').glob('RESULTS.md')):shutil.copy2(p,out/'04_STATE'/p.name)
    for p in (ROOT/'results/truth').glob('*.json'):
        dest=out/'04_STATE/truth'/p.name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,dest)
    for directory in (ROOT/'results/runs').iterdir():
        if not directory.is_dir():continue
        for p in directory.iterdir():
            if not p.is_file():continue
            if p.suffix=='.mp4':external.append(entry(p,'KEEP original real Gazebo recording'));continue
            if p.name.startswith('dashboard_rev_'):external.append(entry(p,'KEEP GUI evidence snapshot'));continue
            dest=out/'04_STATE/runs'/directory.name/p.name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,dest)
        if (directory/'source_snapshot').exists():shutil.copytree(directory/'source_snapshot',out/'04_STATE/runs'/directory.name/'source_snapshot')
    for p in (ROOT/'results/campaigns').rglob('*'):
        if p.is_file():dest=out/'02_COMMANDS/campaigns'/p.relative_to(ROOT/'results/campaigns');dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,dest)
    for p in (ROOT/'generated/setup').rglob('*'):
        if p.is_file():dest=out/'04_STATE/setup'/p.relative_to(ROOT/'generated/setup');dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,dest)
    for p in (ROOT/'evidence').rglob('*'):
        if not p.is_file():continue
        if p.suffix in ('.json','.png','.txt','.urdf','.sdf'):
            dest=out/'06_QA'/p.relative_to(ROOT/'evidence');dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,dest)
        else:external.append(entry(p,'KEEP exploratory/build/simulator log'))
    # Startup consumes this base-commit marker in the portable layout.
    dest=out/'01_PROGRAMS/multigauge/evidence/base_commit.txt';dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(ROOT/'evidence/base_commit.txt',dest)
    for p in (ROOT/'results').glob('reproduction_*'):
        if p.is_dir():shutil.copytree(p,out/'06_QA'/p.name)
    for directory in (ROOT/'candidates').iterdir() if (ROOT/'candidates').exists() else []:
        if not directory.is_dir():continue
        for name,folder in [('MANIFEST.json','05_MANIFEST_PROVENANCE'),('QA.json','06_QA'),('RUN_COMMANDS.json','02_COMMANDS')]:
            if (directory/name).exists():shutil.copy2(directory/name,out/folder/(directory.name+'_'+name))
        for p in directory.glob('physicalai_multigauge_candidate.*'):
            if p.suffix in ('.mp4','.pdf'):external.append(entry(p,'KEEP candidate artifact; source and commands in candidate manifest'))
    readme='''# 再現用正本\n\n01_PROGRAMSを新しい作業場所へコピーすると、元版の必要資産と発展版コードが揃います。multigauge/README.mdのstart.ps1から起動してください。新しい場所で起動するときは既存のphysicalai-multigaugeをstopし、旧コンテナを自動流用しないガードが働くため、Compose名・コンテナ名・通信区分・ポートを分離した別設定を用意するか、保存済みデータを確認してから利用者が既存コンテナを扱ってください。保存場所を移しただけで旧バインドマウントを流用しません。\n\n04_STATEは全試行の画像・実行結果・実行後の正解・準備SDF・当時のソースコピーです。オフライン再検証では、04_STATE/runsとtruthを01_PROGRAMS/multigauge/results/へ対応する名前でコピーし、その01_PROGRAMSをComposeの作業元として起動してください。内部の/home/ubuntuマウントパスが同じになり、保存画像とsource_snapshotをそのまま参照できます。正解はruntimeへ渡さず、採点専用です。記録内の絶対パスは実行当時のcanonicalパスです。移動後のオフライン採点はパスをコピー側へ明示的に対応付けてください。元記録は書き換えません。\n\n大容量動画は外部canonical資料として保持し、05_MANIFEST_PROVENANCEに保存場所・hashを記録しています。候補PDF/MP4のmanifestは候補フォルダーにあります。\n'''
    (out/'07_DOCS/REPRODUCTION.md').write_text(readme,encoding='utf-8')
    (out/'05_MANIFEST_PROVENANCE/EXTERNAL_EVIDENCE_MANIFEST.json').write_text(json.dumps(external,ensure_ascii=False,indent=2))
    files=[entry(p,'portable reproduction asset') for p in sorted(out.rglob('*')) if p.is_file()]
    (out/'05_MANIFEST_PROVENANCE/FILES_SHA256.json').write_text(json.dumps({'created_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'status':'VERIFIED','files':files},ensure_ascii=False,indent=2))
    archive=ROOT/'physicalai_multigauge_repro.zip'
    if archive.exists():raise FileExistsError(archive)
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for p in sorted(out.rglob('*')):
            if p.is_file():z.write(p,p.relative_to(out.parent))
    report={'reference':str(out),'archive':entry(archive,'portable source and trial evidence'),'reference_file_count':len(files),'external_item_count':len(external),'no_existing_source_or_media_deleted':True}
    (ROOT/'evidence/reference_package.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps(report,ensure_ascii=False,indent=2))
if __name__=='__main__':main()