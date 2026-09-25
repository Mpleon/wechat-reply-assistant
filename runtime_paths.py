"""Machine-local paths are configuration, never source-code constants."""
from pathlib import Path
import json,os,sys

BASE=Path(__file__).resolve().parent
RESOURCE_DIR=BASE
DATA_DIR=Path(os.environ.get('WECHAT_ASSISTANT_HOME') or (str(Path(os.environ['LOCALAPPDATA'])/'WechatReplyAssistant') if getattr(sys,'frozen',False) else str(BASE))).resolve()
DATA_DIR.mkdir(parents=True,exist_ok=True)
LOCAL_FILE=DATA_DIR/'local-runtime.json'
CONFIG=json.loads(LOCAL_FILE.read_text(encoding='utf-8-sig')) if LOCAL_FILE.exists() else {}
DEPS=Path(os.environ.get('WECHAT_ASSISTANT_DEPS') or CONFIG.get('deps_dir') or BASE/'.deps').expanduser()
UPSTREAM=BASE/'vendor'/'wechatauto'
_DLL_HANDLES=[]
for folder in (DEPS,DEPS/'win32',DEPS/'win32/lib'):
    if folder.is_dir() and str(folder) not in sys.path:sys.path.insert(0,str(folder))
if os.name=='nt' and (DEPS/'pywin32_system32').is_dir():
    _DLL_HANDLES.append(os.add_dll_directory(str(DEPS/'pywin32_system32')))

def data_root():
    value=os.environ.get('WECHAT_DATA_ROOT') or CONFIG.get('data_root')
    if not value:raise RuntimeError('请在 local-runtime.json 中配置 data_root（xwechat_files 目录）')
    path=Path(value).expanduser().resolve()
    if not path.is_dir():raise RuntimeError('配置的微信数据目录不存在')
    return path
