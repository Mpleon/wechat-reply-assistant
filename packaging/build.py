"""Build only tracked source in a clean staging directory; never bundle user files."""
import argparse,hashlib,json,os,shutil,subprocess,sys,tempfile,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app_version import VERSION

def run(args,**kwargs):subprocess.run([str(x) for x in args],check=True,**kwargs)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--iscc',required=True);args=parser.parse_args()
    output=ROOT/'release'/VERSION;output.mkdir(parents=True,exist_ok=True)
    work=ROOT/'build';work.mkdir(exist_ok=True)
    stage=Path(tempfile.mkdtemp(prefix='release-',dir=work))
    files=subprocess.check_output(['git','ls-files','-z'],cwd=ROOT).decode().split('\0')
    forbidden={'local-runtime.json','peer.json','stickers.json','reply_examples.json','STYLE.md'}
    for name in filter(None,files):
        path=Path(name)
        if (len(path.parts)==1 and path.name in forbidden) or path.parts[0] in ('app-data','incoming-media','stickers','.deps'):raise RuntimeError('Private file tracked: '+name)
        target=stage/path;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(ROOT/path,target)
    env={**os.environ,'WECHAT_ASSISTANT_HOME':str(stage/'clean-user-data'),'WECHAT_ASSISTANT_DEPS':str(stage/'no-local-deps')}
    run([sys.executable,'-m','PyInstaller','--noconfirm','--distpath',stage/'dist','--workpath',stage/'work',stage/'packaging/desktop.spec'],cwd=stage,env=env)
    bundle=stage/'dist/WechatReplyAssistant';exe=bundle/'WechatReplyAssistant.exe'
    run([exe,'--self-test'],cwd=bundle,env=env,timeout=90)
    report=stage/'clean-user-data/self-test.json'
    if not report.exists() or not json.loads(report.read_text())['ok']:raise RuntimeError('Frozen smoke test failed')
    shutil.copy2(report,output/'self-test.json')
    run([args.iscc,'/DAppVersion='+VERSION,'/DBundleDir='+str(bundle),'/DOutputDir='+str(output),stage/'packaging/installer.iss'])
    archive=output/('WechatReplyAssistant-'+VERSION+'-windows-x64-portable.zip')
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
        for file in bundle.rglob('*'):
            if file.is_file():z.write(file,Path('WechatReplyAssistant')/file.relative_to(bundle))
    artifacts=sorted(output.glob('*.exe'))+[archive]
    (output/'SHA256SUMS.txt').write_text(''.join(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.name+'\n' for p in artifacts),encoding='ascii')
    (output/'build-info.json').write_text(json.dumps({'version':VERSION,'commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),'bundle':str(bundle)},indent=2),encoding='utf-8')
    print('Release artifacts: '+str(output))

if __name__=='__main__':main()
