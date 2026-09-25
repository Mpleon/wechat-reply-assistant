"""Recipient registry, isolated histories and a shared read-only database reader."""
import json,threading,uuid
from pathlib import Path
from app_store import Store,Conflict
from app_engine import Engine

class ContactStore:
    def __init__(self,local,shared,legacy=False):
        self.local=local;self.shared=shared;self.legacy=legacy
    def __getattr__(self,name):return getattr(self.local,name)
    def settings(self):
        cfg=self.shared.settings()
        # The original contact's private examples must not enter another conversation.
        if not self.legacy:cfg['use_style']=False
        return cfg

class Contacts:
    def __init__(self,store,secrets,base,engine=None):
        self.store=store;self.secrets=secrets;self.base=Path(base)
        self.lock=threading.RLock();self.read_lock=threading.RLock();self.reader=None;self.started=False
        self.engines={};self.records={}
        with store.lock:
            store.db.execute('CREATE TABLE IF NOT EXISTS contacts(id TEXT PRIMARY KEY,data TEXT)')
            rows=store.db.execute('SELECT data FROM contacts ORDER BY rowid').fetchall()
            if not rows:
                path=self.base/'peer.json'
                old=json.loads(path.read_text(encoding='utf-8-sig')) if path.exists() else {}
                record={'id':'legacy','identifier':old.get('username',''),'username':old.get('username',''),'display_name':old.get('display_name','原联系人')}
                self._save(record);rows=[(json.dumps(record),)]
        for row in rows:
            record=json.loads(row[0]);self.records[record['id']]=record
            self.engines[record['id']]=engine if engine is not None and record['id']=='legacy' else self._engine(record)
    def _save(self,record):
        with self.store.lock:
            self.store.db.execute('INSERT OR REPLACE INTO contacts VALUES(?,?)',(record['id'],json.dumps(record,ensure_ascii=False)));self.store.db.commit()
    def _reader(self,record):
        with self.read_lock:
            from reader import Reader
            if self.reader is None:
                self.reader=Reader(contact_only=True) if record['username'] else Reader()
            identifier=record['username'] or self.reader.target
            reader=self.reader.for_contact(identifier)
            with self.lock:
                record.update(username=reader.target,display_name=reader.target_name)
                self._save(record)
            return reader
    def _engine(self,record):
        legacy=record['id']=='legacy'
        directory=self.base/'app-data'/'contacts';directory.mkdir(parents=True,exist_ok=True)
        local=self.store if legacy else Store(directory/(record['id']+'.sqlite3'))
        return Engine(ContactStore(local,self.store,legacy),self.secrets,reader_factory=lambda:self._reader(record))
    def get(self,peer_id=None):
        with self.lock:
            if peer_id is None or peer_id=='':peer_id='legacy'
            if peer_id not in self.engines:raise ValueError('联系人配置不存在')
            return self.engines[peer_id]
    def list(self):
        with self.lock:
            result=[]
            for key,record in self.records.items():
                runtime=self.engines[key].snapshot()
                result.append({**record,'display_name':runtime.get('target') or record['display_name'],'runtime':runtime})
            return result
    def add(self,identifier):
        if not isinstance(identifier,str) or not identifier.strip() or len(identifier)>200:raise ValueError('请填写微信号或内部 wxid')
        with self.read_lock:
            if self.reader is None:
                from reader import Reader
                self.reader=Reader(contact_only=True)
            resolved=self.reader.resolve_contact(identifier)
        with self.lock:
            for key,record in self.records.items():
                existing=self.engines[key].reader
                username=record['username'] or (existing.target if existing else '')
                if username==resolved['username']:raise Conflict('该联系人已配置，请在列表中切换')
            record={**resolved,'id':uuid.uuid4().hex}
            engine=self._engine(record);self._save(record)
            self.records[record['id']]=record;self.engines[record['id']]=engine
            if self.started:engine.start()
            return record
    def start(self):
        with self.lock:
            self.started=True
            for engine in self.engines.values():engine.start()
    def stop_all(self):
        with self.lock:
            for engine in self.engines.values():engine.control(False)
        return {'ok':True}
    def close(self):
        with self.lock:
            for engine in self.engines.values():engine.closed=True
