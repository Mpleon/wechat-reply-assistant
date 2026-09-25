"""Durable local configuration, drafts and delivery audit."""
import copy,json,sqlite3,threading,time,uuid,urllib.parse
from pathlib import Path

DEFAULTS={'provider':'codex','codex_model':'gpt-6-astra','reasoning':'medium','base_url':'',
          'api_model':'','api_protocol':'chat_completions','mode':'review','quiet_seconds':3,
          'system_prompt':'对她坦诚、自然地接话。能回答的问题尽量说清楚，表情按语境选择，不机械重复。',
          'use_style':True,'api_stream':True,'revision':1}
ACTIVE_DRAFTS=('queued','preparing','generating','awaiting','send_queued')
MODEL_FIELDS=('provider','codex_model','reasoning','base_url','api_model','api_protocol','api_stream')
def now():return time.strftime('%Y-%m-%d %H:%M:%S')
class Conflict(ValueError):pass
class Store:
    def __init__(self,path):
        self.lock=threading.RLock()
        self.db=sqlite3.connect(path,check_same_thread=False)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.executescript('CREATE TABLE IF NOT EXISTS settings(id INTEGER PRIMARY KEY,data TEXT);'
          'CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,data TEXT,updated REAL);'
          'CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT,time TEXT,kind TEXT,data TEXT);'
          'CREATE TABLE IF NOT EXISTS messages(id TEXT PRIMARY KEY,data TEXT,seq INTEGER);'
          'CREATE TABLE IF NOT EXISTS model_calls(id TEXT PRIMARY KEY,time TEXT,data TEXT);'
          'CREATE TABLE IF NOT EXISTS model_profiles(id TEXT PRIMARY KEY,data TEXT);')
        if not self.db.execute('SELECT 1 FROM settings WHERE id=1').fetchone():
            self.db.execute('INSERT INTO settings VALUES(1,?)',(json.dumps(DEFAULTS),));self.db.commit()
        self._migrate_profiles()
        # An interrupted click is never automatically replayed after a restart.
        for job in self.jobs(10000):
            if job['status']=='sending':self.update(job['id'],status='uncertain',error='程序在发送期间退出，请核对微信。')
            elif job['status'] in ('preparing','generating','send_queued','queued'):
                self.update(job['id'],status='cancelled',error='服务重启，旧任务未重放。')
        for call in self.calls(10000):
            if call.get('phase') not in ('completed','failed','interrupted'):
                call['phase']='interrupted'
                call.setdefault('usage',{}).update(status='interrupted',final=False)
                self.record_call(call)
    def settings(self):
        with self.lock:
            value={**DEFAULTS,**json.loads(self.db.execute('SELECT data FROM settings WHERE id=1').fetchone()[0])}
            profile=self.profile(value.get('active_profile_id','codex-default'))
            value.update({k:profile[k] for k in MODEL_FIELDS})
            value.update(active_profile_id=profile['id'],profile_name=profile['name'],profile_version=profile['version'],credential_scope=profile['credential_scope'])
            return value
    def _migrate_profiles(self):
        if self.db.execute('SELECT 1 FROM model_profiles LIMIT 1').fetchone():return
        settings={**DEFAULTS,**json.loads(self.db.execute('SELECT data FROM settings WHERE id=1').fetchone()[0])}
        base={k:settings[k] for k in MODEL_FIELDS}
        builtin={**base,'id':'codex-default','name':'Codex 默认','provider':'codex','credential_scope':'codex-default','version':1,'updated_at':now()}
        self.db.execute('INSERT INTO model_profiles VALUES(?,?)',(builtin['id'],json.dumps(builtin,ensure_ascii=False)))
        active=builtin['id']
        # Keep the existing Credential Manager entry referenced as legacy; never copy its plaintext.
        if settings['provider']=='custom' or settings['base_url'] or settings['api_model']:
            custom={**base,'id':'custom-migrated','name':settings['api_model'] or '原自定义配置','provider':'custom',
                    'credential_scope':'legacy','version':1,'updated_at':now()}
            self.db.execute('INSERT INTO model_profiles VALUES(?,?)',(custom['id'],json.dumps(custom,ensure_ascii=False)))
            if settings['provider']=='custom':active=custom['id']
        settings['active_profile_id']=active
        self.db.execute('UPDATE settings SET data=? WHERE id=1',(json.dumps(settings,ensure_ascii=False),));self.db.commit()
    def profiles(self):
        with self.lock:return [json.loads(r[0]) for r in self.db.execute('SELECT data FROM model_profiles ORDER BY rowid')]
    def profile(self,profile_id):
        with self.lock:
            row=self.db.execute('SELECT data FROM model_profiles WHERE id=?',(profile_id,)).fetchone()
            if not row:raise ValueError('模型配置不存在')
            return json.loads(row[0])
    def prepare_profile(self,data,profile_id=None,version=None):
        old=self.profile(profile_id) if profile_id else None
        if old and version is not None and old['version']!=version:raise Conflict('模型配置已被修改，请刷新后重试')
        profile_id=profile_id or uuid.uuid4().hex
        p={**{k:DEFAULTS[k] for k in MODEL_FIELDS},**(old or {}),**{k:v for k,v in data.items() if k in MODEL_FIELDS or k=='name'}}
        p['id']=profile_id;p['credential_scope']=old['credential_scope'] if old else profile_id
        if not isinstance(p.get('name'),str) or not p['name'].strip() or len(p['name'])>80:raise ValueError('请填写 1–80 字的配置名称')
        p['name']=p['name'].strip()
        if p['provider'] not in ('codex','custom'):raise ValueError('模型来源无效')
        if profile_id=='codex-default' and p['provider']!='codex':raise ValueError('内置配置需保留为 Codex，可另外新增自定义配置')
        if p['reasoning'] not in ('low','medium','high'):raise ValueError('推理强度无效')
        if p['api_protocol'] not in ('chat_completions','responses'):raise ValueError('接口格式无效')
        for k in ('codex_model','base_url','api_model'):
            if not isinstance(p[k],str) or len(p[k])>2000:raise ValueError('模型字段无效')
            p[k]=p[k].strip()
        if p['provider']=='custom':
            u=urllib.parse.urlsplit(p['base_url'])
            if u.scheme not in ('http','https') or not u.hostname or u.username or u.password or u.query or u.fragment:raise ValueError('请填写合法 Base URL')
            if not p['api_model']:raise ValueError('请填写模型名称')
        elif not p['codex_model']:raise ValueError('请填写 Codex 模型名称')
        p['api_stream']=bool(p['api_stream']);p['version']=(old['version']+1) if old else 1;p['updated_at']=now()
        return p
    def write_profile(self,p):
        with self.lock:
            self.db.execute('INSERT INTO model_profiles VALUES(?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data',(p['id'],json.dumps(p,ensure_ascii=False)))
            settings=json.loads(self.db.execute('SELECT data FROM settings WHERE id=1').fetchone()[0])
            if settings.get('active_profile_id')==p['id']:
                settings.update({k:p[k] for k in MODEL_FIELDS});settings['revision']=settings.get('revision',1)+1
                self.db.execute('UPDATE settings SET data=? WHERE id=1',(json.dumps(settings,ensure_ascii=False),))
            self.db.commit();return p
    def activate_profile(self,profile_id):
        with self.lock:
            p=self.profile(profile_id);settings=self.settings()
            settings.update({k:p[k] for k in MODEL_FIELDS});settings.update(active_profile_id=profile_id,revision=settings['revision']+1)
            self.db.execute('UPDATE settings SET data=? WHERE id=1',(json.dumps(settings,ensure_ascii=False),));self.db.commit()
            return self.settings()
    def delete_profile(self,profile_id,version):
        with self.lock:
            p=self.profile(profile_id)
            if p['version']!=version:raise Conflict('模型配置已更新')
            if profile_id=='codex-default':raise ValueError('内置默认配置不能删除')
            if self.settings()['active_profile_id']==profile_id:raise Conflict('请先切换到其他模型，再删除当前启用的配置')
            self.db.execute('DELETE FROM model_profiles WHERE id=?',(profile_id,));self.db.commit();return p
    def save_settings(self,data):
        with self.lock:
            old=self.settings();new={**old,**{k:v for k,v in data.items() if k in DEFAULTS and k!='revision'}}
            if new['provider'] not in ('codex','custom') or new['mode'] not in ('review','auto'):raise ValueError('模型来源或回复模式无效')
            if new['api_protocol'] not in ('chat_completions','responses'):raise ValueError('接口类型无效')
            if new['reasoning'] not in ('low','medium','high'):raise ValueError('推理设置无效')
            new['quiet_seconds']=float(new['quiet_seconds'])
            if not 0.5<=new['quiet_seconds']<=30:raise ValueError('消息合并等待应在 0.5–30 秒之间')
            for k in ('codex_model','api_model','base_url','system_prompt'):
                if not isinstance(new[k],str) or len(new[k])>12000:raise ValueError('配置字段无效')
            new['use_style']=bool(new['use_style']);new['api_stream']=bool(new['api_stream']);new['revision']=old['revision']+1
            # Compatibility for older clients: model edits update the currently active profile.
            changed={k:new[k] for k in MODEL_FIELDS if k in data and new[k]!=old[k]}
            if changed:
                profile=self.prepare_profile(changed,old['active_profile_id'])
                self.db.execute('UPDATE model_profiles SET data=? WHERE id=?',(json.dumps(profile,ensure_ascii=False),profile['id']))
            self.db.execute('UPDATE settings SET data=? WHERE id=1',(json.dumps(new,ensure_ascii=False),));self.db.commit()
            return new
    def create(self,source,instruction='',parent=None):
        job={'id':uuid.uuid4().hex,'source':source,'instruction':instruction,'parent':parent,
             'status':'queued','parts':[],'reason':'','error':'','version':1,'created_at':now(),'updated_at':now(),
             'baseline':None,'proofs':[],'skipped':[]}
        with self.lock:
            self.db.execute('INSERT INTO jobs VALUES(?,?,?)',(job['id'],json.dumps(job,ensure_ascii=False),time.time()));self.db.commit()
        return job
    def job(self,jobid):
        with self.lock:
            r=self.db.execute('SELECT data FROM jobs WHERE id=?',(jobid,)).fetchone()
            if not r:raise ValueError('草稿不存在')
            return json.loads(r[0])
    def update(self,jobid,expected_version=None,allowed=None,**fields):
        with self.lock:
            job=self.job(jobid)
            if expected_version is not None and job['version']!=expected_version:raise Conflict('草稿已更新，请刷新后重试')
            if allowed and job['status'] not in allowed:raise Conflict('这条草稿的状态已改变，不能重复操作')
            job.update(fields);job['version']+=1;job['updated_at']=now()
            self.db.execute('UPDATE jobs SET data=?,updated=? WHERE id=?',(json.dumps(job,ensure_ascii=False),time.time(),jobid));self.db.commit()
            return job
    def jobs(self,limit=40):
        with self.lock:return [json.loads(r[0]) for r in self.db.execute('SELECT data FROM jobs ORDER BY updated DESC LIMIT ?',(limit,))]
    def event(self,kind,**data):
        with self.lock:
            self.db.execute('INSERT INTO events(time,kind,data) VALUES(?,?,?)',(now(),kind,json.dumps(data,ensure_ascii=False)));self.db.commit()
    def events(self,limit=100):
        with self.lock:return [{'id':r[0],'time':r[1],'kind':r[2],**json.loads(r[3])} for r in self.db.execute('SELECT id,time,kind,data FROM events ORDER BY time DESC,id DESC LIMIT ?',(limit,))]
    def cache_messages(self,rows):
        with self.lock:
            self.db.executemany('INSERT OR REPLACE INTO messages VALUES(?,?,?)',[(m['id'],json.dumps(m,ensure_ascii=False),m['seq']) for m in rows]);self.db.commit()
    def record_call(self,metrics,**context):
        with self.lock:
            self.db.execute('INSERT INTO model_calls(id,time,data) VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data',
                (metrics['call_id'],now(),json.dumps({**metrics,**context},ensure_ascii=False)));self.db.commit()
    def calls(self,limit=100):
        with self.lock:return [{'time':r[0],**json.loads(r[1])} for r in self.db.execute('SELECT time,data FROM model_calls ORDER BY time DESC,rowid DESC LIMIT ?',(limit,))]
    def messages(self,limit=160):
        with self.lock:return list(reversed([json.loads(r[0]) for r in self.db.execute('SELECT data FROM messages ORDER BY seq DESC LIMIT ?',(limit,))]))
