from pathlib import Path
import json,ctypes
import native_access as n
from runtime_paths import DATA_DIR
p=DATA_DIR/'accessibility-state.json'
state=json.loads(p.read_text(encoding='utf-8'))
pid=n.WeChatUIA._pid_from_hwnd(n.window())
if pid!=state['pid']:raise RuntimeError('WeChat process changed; no restore needed')
base,_,path=n.WeChatUIA._weixin_dll_module(pid)
if path!=state['module'] or base+state['rva']!=state['address']:raise RuntimeError('Module changed; refuse stale address')
k=ctypes.windll.kernel32;k.OpenProcess.argtypes=[ctypes.c_ulong,ctypes.c_bool,ctypes.c_ulong];k.OpenProcess.restype=ctypes.c_void_p
h=k.OpenProcess(0x438,False,pid)
try:
    if not h or not n.WeChatUIA._write_process_byte(h,state['address'],state['original']):raise RuntimeError('Restore failed')
finally:
    if h:k.CloseHandle(h)
print('Original accessibility flag restored')
