"""Disable idle screen overlays in this isolated X11 desktop session."""
import json,os,subprocess,time
from pathlib import Path
ROOT=Path(__file__).resolve().parent

def main():
    address=None
    deadline=time.monotonic()+10
    while not address and time.monotonic()<deadline:
      for p in Path('/proc').iterdir():
        if not p.name.isdigit():continue
        try:
            argv=(p/'cmdline').read_bytes().split(b'\0')
            if not argv or Path(argv[0].decode()).name!='mate-session':continue
            values=dict(x.split(b'=',1) for x in (p/'environ').read_bytes().split(b'\0') if b'=' in x)
            address=values.get(b'DBUS_SESSION_BUS_ADDRESS',b'').decode()
        except (OSError,UnicodeError):continue
      if not address:time.sleep(.2)
    if not address:raise RuntimeError('isolated desktop session bus unavailable; execute as desktop user ubuntu')
    env=os.environ.copy();env.update(DBUS_SESSION_BUS_ADDRESS=address,DISPLAY=':0',XAUTHORITY='/home/ubuntu/.Xauthority')
    checks=[]
    for argv in [['gsettings','set','org.mate.screensaver','idle-activation-enabled','false'],['mate-screensaver-command','--deactivate'],['xset','s','off']]:
        p=subprocess.run(argv,capture_output=True,text=True,env=env);checks.append({'argv':argv,'returncode':p.returncode,'stdout':p.stdout.strip(),'stderr':p.stderr.strip()})
    state=subprocess.check_output(['gsettings','get','org.mate.screensaver','idle-activation-enabled'],text=True,env=env).strip()
    result='PASS' if state=='false' and all(p['returncode']==0 or (p['argv'][0]=='mate-screensaver-command' and 'Screensaver is not running!' in p['stderr']) for p in checks) else 'FAIL'
    report={'result':result,'actual_desktop_session_bus_selected':True,'idle_activation_enabled':state,'checks':checks,'scope':'Only isolated multigauge desktop; no robot commands and no other container settings changed.'}
    (ROOT/'evidence/desktop_guard_qa.json').write_text(json.dumps(report,indent=2));print(json.dumps(report));return 0 if result=='PASS' else 1
if __name__=='__main__':raise SystemExit(main())