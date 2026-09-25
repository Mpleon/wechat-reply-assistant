"""Load the reviewed read-only subset of the vendored WeChat adapter."""
import ast,ctypes,struct
from runtime_paths import UPSTREAM

tree=ast.parse((UPSTREAM/'db.py').read_text(encoding='utf-8-sig'))
helpers={'_pbkdf2','_aes_cbc_decrypt','_verify_enc_key','_decrypt_page'}
methods={'_find_weixin_pids','_extract_keys_pid','_probable_key','_find_bytes'}
selected=[]
for node in tree.body:
    if isinstance(node,(ast.Import,ast.ImportFrom)):selected.append(node)
    elif isinstance(node,(ast.Assign,ast.AnnAssign)) and node.lineno<121:selected.append(node)
    elif isinstance(node,ast.ClassDef) and node.name=='_MBI':selected.append(node)
    elif isinstance(node,ast.FunctionDef) and node.name in helpers:selected.append(node)
    elif isinstance(node,ast.ClassDef) and node.name=='WeChatDB':
        node.body=[n for n in node.body if isinstance(n,ast.FunctionDef) and n.name in methods];selected.append(node)
scope={}
exec(compile(ast.Module(body=selected,type_ignores=[]),'reviewed_readonly_subset','exec'),scope)
scope['_k32'].CloseHandle.argtypes=[ctypes.c_void_p]
scope['_k32'].CloseHandle.restype=ctypes.c_int

def checksum(data,state=(0,0),endian='<'):
    values=struct.unpack(endian+str(len(data)//4)+'I',data);a,b=state
    for i in range(0,len(values),2):
        a=(a+values[i]+b)&0xffffffff;b=(b+values[i+1]+a)&0xffffffff
    return a,b

def wal_frames(data):
    if len(data)<32:return [],0
    magic,version,pagesize=struct.unpack('>III',data[:12])
    if magic not in (0x377f0682,0x377f0683) or pagesize!=4096:raise ValueError('Unsupported WAL format')
    endian='<' if magic==0x377f0682 else '>'
    state=checksum(data[:24],endian=endian)
    if state!=struct.unpack('>II',data[24:32]):raise ValueError('WAL header checksum failed')
    frames=[];committed=0;dbsize=0
    for offset in range(32,len(data)-4119,4120):
        header=data[offset:offset+24];page=data[offset+24:offset+4120]
        if header[8:16]!=data[16:24]:break
        page_number,commit_size=struct.unpack('>II',header[:8])
        if page_number==0:break
        state=checksum(header[:8]+page,state,endian)
        if state!=struct.unpack('>II',header[16:24]):raise ValueError('WAL frame checksum failed')
        frames.append((page_number,page))
        if commit_size:committed=len(frames);dbsize=commit_size
    return frames[:committed],dbsize
