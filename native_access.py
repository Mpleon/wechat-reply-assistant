"""Expose native accessibility controls with a verified reversible runtime flag."""
from pathlib import Path
import sys,os,ast,ctypes,json,logging,time,struct,re
from ctypes import wintypes
from functools import lru_cache
from typing import List,Optional,Tuple,Dict
BASE=Path(__file__).resolve().parent
from runtime_paths import DEPS,UPSTREAM
import uiautomation as auto
import win32gui,win32process
_HAS_WIN32=True
wxlog=logging.getLogger('native-access')
source=(UPSTREAM/'uia_driver.py').read_text(encoding='utf-8-sig')
tree=ast.parse(source)
names={'_pid_from_hwnd','_process_modules','_weixin_dll_module','_pe_sections','_section_for_rva',
       '_offset_to_rva','_rip_xrefs_to_rva','_scan_qaccessible_candidates','_read_process_byte','_write_process_byte','_mmui_present'}
nodes=[]
for n in tree.body:
    if isinstance(n,(ast.Assign,ast.AnnAssign)) and 140<n.lineno<210:nodes.append(n)
    elif isinstance(n,ast.ClassDef) and n.name=='MODULEENTRY32W':nodes.append(n)
    elif isinstance(n,ast.ClassDef) and n.name=='WeChatUIA':
        n.body=[m for m in n.body if isinstance(m,ast.FunctionDef) and m.name in names];nodes.append(n)
exec(compile(ast.Module(body=nodes,type_ignores=[]),'reviewed_accessibility_helpers','exec'))
def window():
    found=[]
    win32gui.EnumWindows(lambda h,_:found.append(h) if win32gui.GetWindowText(h)=='微信' else None,None)
    if len(found)!=1:raise RuntimeError('Main window missing or ambiguous')
    return found[0]
def activate():
    h=window()
    if WeChatUIA._mmui_present(h,.1):return h
    pid=WeChatUIA._pid_from_hwnd(h)
    base,size,path=WeChatUIA._weixin_dll_module(pid)
    candidates=WeChatUIA._scan_qaccessible_candidates(path)
    print(json.dumps({'candidate_count':len(candidates),'pid':pid}),flush=True)
    if len(candidates)!=1:raise RuntimeError('Accessibility flag is not uniquely identified')
    k=ctypes.windll.kernel32
    k.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD];k.OpenProcess.restype=wintypes.HANDLE
    handle=k.OpenProcess(0x438,False,pid)
    if not handle:raise RuntimeError('Cannot access runtime flag')
    address=base+candidates[0]
    try:
        original=WeChatUIA._read_process_byte(handle,address)
        if original not in (0,1):raise RuntimeError('Unexpected flag value')
        state={'pid':pid,'address':address,'original':original,'module':path,'rva':candidates[0],'verified':False}
        (BASE/'accessibility-state.json').write_text(json.dumps(state),encoding='utf-8')
        if not WeChatUIA._write_process_byte(handle,address,1):raise RuntimeError('Flag write failed')
        if not WeChatUIA._mmui_present(h,2):
            WeChatUIA._write_process_byte(handle,address,original)
            raise RuntimeError('Native controls unavailable; original flag restored')
        state['verified']=True
        (BASE/'accessibility-state.json').write_text(json.dumps(state),encoding='utf-8')
    finally:k.CloseHandle(handle)
    return h
def inspect(h):
    rows=[];stack=[(auto.ControlFromHandle(h),0)]
    while stack and len(rows)<250:
        c,d=stack.pop()
        if d>10:continue
        rows.append({'depth':d,'name':c.Name,'class':c.ClassName,'aid':c.AutomationId,'type':c.ControlTypeName})
        stack.extend((x,d+1) for x in reversed(c.GetChildren()))
    (BASE/'native-controls.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(rows[:45],ensure_ascii=False),flush=True)
if __name__=='__main__':inspect(activate())
