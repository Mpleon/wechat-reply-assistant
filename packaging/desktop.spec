from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files,collect_submodules,copy_metadata
import sys
root=Path(SPECPATH).parent
datas=[(str(root/'web'),'web'),(str(root/'examples'),'examples'),
       (str(root/'vendor/wechatauto'),'vendor/wechatauto'),
       (str(root/'reply.schema.json'),'.'),(str(root/'THIRD_PARTY_NOTICES.md'),'.')]
for package in ('webview','uiautomation','imageio_ffmpeg'):
    datas+=collect_data_files(package)
for package in ('pywebview','pythonnet','clr_loader','bottle','proxy_tools','typing_extensions','comtypes',
                'uiautomation','cryptography','cffi','pycparser','apsw','zstandard','pillow','pywin32','imageio-ffmpeg'):
    datas+=copy_metadata(package)
python_license=Path(sys.base_prefix)/'LICENSE.txt'
if python_license.exists():datas.append((str(python_license),'licenses/python'))
a=Analysis([str(root/'desktop.py')],pathex=[str(root)],datas=datas,
    hiddenimports=['win32cred','win32gui','win32process','win32timezone','_cffi_backend']+collect_submodules('comtypes'),
    excludes=['PyQt5','PyQt6','PySide2','PySide6','matplotlib','numpy','pandas','pytest','IPython'],noarchive=False)
pyz=PYZ(a.pure)
exe=EXE(pyz,a.scripts,[],exclude_binaries=True,name='WechatReplyAssistant',console=False,upx=False)
coll=COLLECT(exe,a.binaries,a.datas,strip=False,upx=False,name='WechatReplyAssistant')
