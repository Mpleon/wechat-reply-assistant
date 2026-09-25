"""Read encrypted SQLite pages on demand, with a committed WAL snapshot."""
from pathlib import Path
import sys,ast,json,hashlib,hmac,struct,collections,base64
from runtime_paths import UPSTREAM as AUDIT,data_root,CONFIG,DATA_DIR
from wechat_backend import scope,wal_frames
import apsw,zstandard
def signature(p):
    s=p.stat();return s.st_size,s.st_mtime_ns
class PageFile(apsw.VFSFile):
    def __init__(self,name,flags,key):
        super().__init__('',name,flags)
        self.path=Path(name.filename() if isinstance(name,apsw.URIFilename) else name)
        self.sig=signature(self.path)
        w=Path(str(self.path)+'-wal');data=w.read_bytes() if w.exists() else b''
        self.frames,self.pages=wal_frames(data)
        self.overlay=dict(self.frames)
        self.key=key
        self.cache={}
        self.size=self.pages*4096 if self.pages else self.sig[0]
        salt=super().xRead(16,0)
        self.mac_key=hashlib.pbkdf2_hmac('sha512',key[:32],bytes(x^0x3a for x in salt),2,32)
    def xRead(self,amount,offset):
        result=bytearray()
        start=offset//4096
        for pageidx in range(start,(offset+amount+4095)//4096):
            pg=pageidx+1
            if pg not in self.cache:
                encrypted=self.overlay.get(pg)
                if encrypted is None:encrypted=super().xRead(4096,pageidx*4096)
                skip=16 if pg==1 else 0
                mac=hmac.new(self.mac_key,encrypted[skip:4032]+struct.pack('<I',pg),'sha512').digest()
                if mac!=encrypted[4032:4096]:raise apsw.IOError('Encrypted page integrity failed')
                plain=scope['_decrypt_page'](self.key,encrypted,pg)
                if pg==1:plain=plain[:18]+b'\x01\x01'+plain[20:]
                self.cache[pg]=plain
            result.extend(self.cache[pg])
        if signature(self.path)!=self.sig:raise apsw.BusyError('Main database changed during query')
        begin=offset-start*4096
        return bytes(result[begin:begin+amount])
    def xFileSize(self):return self.size
    def xWrite(self,*args):raise apsw.ReadOnlyError('Source database is read-only')
    def xTruncate(self,*args):raise apsw.ReadOnlyError('Source database is read-only')
class ReadVFS(apsw.VFS):
    def __init__(self,keys):
        self.keys={str(Path(k).resolve()).lower():v for k,v in keys.items()}
        self.name='wechat_read_'+str(id(self));super().__init__(self.name,'')
    def xOpen(self,name,flags):
        p=str(Path(name.filename()).resolve()).lower()
        if p not in self.keys:raise apsw.CantOpenError('Unlisted database')
        return PageFile(name,flags,self.keys[p])
class Reader:
    def __init__(self,contact_only=False):
        roots=[p/'db_storage' for p in data_root().iterdir() if (p/'db_storage').is_dir()]
        if len(roots)!=1:raise RuntimeError('Ambiguous account')
        self.root=roots[0]
        self.files=[self.root/'contact/contact.db',self.root/'emoticon/emoticon.db',*sorted((self.root/'message').glob('message_[0-9]*.db'))]
        probe=object.__new__(scope['WeChatDB'])
        probe._db_files=[(str(p),str(p),p.stat().st_size) for p in self.files]
        keys={};tested=set()
        for pid in probe._find_weixin_pids():
            keys.update(probe._extract_keys_pid(pid,tested))
            if len(keys)==len(self.files):break
        if len(keys)!=len(self.files):raise RuntimeError('Missing database key')
        self.vfs=ReadVFS(keys)
        self.self_id=self.root.parent.name.rsplit('_',1)[0]
        if contact_only:return
        peer_file=DATA_DIR/'peer.json'
        if peer_file.exists():
            peer=json.loads(peer_file.read_text(encoding='utf-8'))
            found=self.query(self.files[0],'SELECT username,nick_name,remark FROM contact WHERE username=?',(peer['username'],))
        else:
            name=CONFIG.get('target_name','').strip()
            if not name:raise RuntimeError('请配置 peer.json 的联系人账号标识，或 local-runtime.json 的 target_name')
            found=self.query(self.files[0],'SELECT username,nick_name,remark FROM contact WHERE nick_name=? OR remark=?',(name,)*2)
        if len(found)!=1:raise RuntimeError('Ambiguous contact')
        self.target=found[0]['username'];self.target_name=found[0]['remark'] or found[0]['nick_name'] or self.target
        self.self_id=self.root.parent.name.rsplit('_',1)[0]
    def resolve_contact(self,identifier):
        identifier=identifier.strip()
        if not identifier or len(identifier)>200:raise ValueError('请填写微信号或内部 wxid')
        columns={r['name'] for r in self.query(self.files[0],'PRAGMA table_info(contact)')}
        fields=['username']+(['alias'] if 'alias' in columns else [])
        found=self.query(self.files[0],'SELECT username,nick_name,remark FROM contact WHERE '+' OR '.join(f+'=?' for f in fields),tuple(identifier for _ in fields))
        if len(found)!=1:raise ValueError('未找到唯一联系人，请填写微信号或内部 wxid；不支持昵称搜索')
        row=found[0];username=row['username']
        if username==self.self_id or username.endswith('@chatroom') or username.startswith('gh_'):raise ValueError('目前仅支持其他个人联系人')
        name=row['remark'] or row['nick_name'] or username
        matches=self.query(self.files[0],"SELECT username FROM contact WHERE COALESCE(NULLIF(remark,''),NULLIF(nick_name,''),username)=?",(name,))
        if len(matches)!=1:raise ValueError('联系人显示名称重复，请先在微信中设置唯一备注，再重试')
        return {'username':username,'display_name':name,'identifier':identifier}
    def for_contact(self,identifier):
        import copy
        peer=self.resolve_contact(identifier);reader=copy.copy(self)
        reader.target=peer['username'];reader.target_name=peer['display_name']
        return reader
    def query(self,path,sql,args=()):
        for attempt in range(3):
            conn=None
            try:
                conn=apsw.Connection(Path(path).as_uri()+'?immutable=1',flags=apsw.SQLITE_OPEN_READONLY|apsw.SQLITE_OPEN_URI,vfs=self.vfs.name)
                cursor=conn.cursor();iterator=cursor.execute(sql,args)
                try:cols=[c[0] for c in cursor.get_description()]
                except apsw.ExecutionCompleteError:return []
                return [dict(zip(cols,r)) for r in iterator]
            except apsw.BusyError:
                if attempt==2:raise
            finally:
                if conn:conn.close()
    def recent(self,user=None,limit=80):
        user=user or self.target
        table='Msg_'+hashlib.md5(user.encode()).hexdigest()
        rows=[]
        for path in self.files[2:]:
            if not self.query(path,'SELECT 1 FROM sqlite_master WHERE name=?',(table,)):continue
            shard=self.query(path,'SELECT local_id,server_id,local_type,sort_seq,real_sender_id,create_time,message_content,packed_info_data FROM "'+table+'" ORDER BY sort_seq DESC LIMIT ?',(limit,))
            ids={m['real_sender_id'] for m in shard}
            mapping={r['rowid']:r['user_name'] for r in self.query(path,'SELECT rowid,user_name FROM Name2Id') if r['rowid'] in ids}
            for m in shard:
                packed=m.pop('packed_info_data',None)
                m['packed_base64']=base64.b64encode(packed).decode() if isinstance(packed,bytes) else ''
                c=m.pop('message_content')
                if isinstance(c,bytes):
                    if c.startswith(b'\x28\xb5\x2f\xfd'):c=zstandard.ZstdDecompressor().decompress(c,max_output_size=2000000)
                    c=c.decode('utf-8')
                m['content']=c;m['database']=path.name
                u=mapping.get(m['real_sender_id'])
                m['sender']='我' if u==self.self_id else '她' if u==user else '系统'
            rows.extend(shard)
        return sorted(rows,key=lambda m:(m['sort_seq'],m['create_time'],m['local_id']))[-limit:]
if __name__=='__main__':
    r=Reader()
    if '--schema' in sys.argv:
        print(json.dumps(r.query(r.files[1],"SELECT name,sql FROM sqlite_master WHERE type='table'"),ensure_ascii=False))
    else:
        data=r.recent('filehelper' if '--self-test' in sys.argv else None,6)
        public=[{'local_id':m['local_id'],'server_id':m['server_id'],'sender':m['sender'],
                 'create_time':m['create_time'],'type':m['local_type'],
                 'content':m['content'] if m['local_type']==1 else '[media metadata omitted]'} for m in data]
        print(json.dumps(public,ensure_ascii=False,indent=2))
