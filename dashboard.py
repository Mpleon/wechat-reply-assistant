"""Loopback-only web application for the WeChat reply assistant."""
from pathlib import Path
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
from concurrent.futures import ThreadPoolExecutor
import argparse,ctypes,json,mimetypes,os,secrets,socket,threading,time,urllib.parse,uuid
from app_store import Store,Conflict,DEFAULTS,now
from app_engine import Engine
from app_contacts import Contacts
import app_models
BASE=Path(__file__).resolve().parent
WEB=BASE/'web'
class Application:
    def __init__(self,store=None,secret_store=None,engine=None):
        data=BASE/'app-data';data.mkdir(exist_ok=True)
        self.store=store or Store(data/'dashboard.sqlite3');self.secrets=secret_store or app_models.Secrets()
        self.contacts=Contacts(self.store,self.secrets,BASE,engine)
        self.engine=self.contacts.get()
        self.token=secrets.token_urlsafe(32);self.tests={};self.test_lock=threading.RLock()
        self.test_pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='model-connectivity')
        if store is None:self.import_legacy()
    def import_legacy(self):
        marker=BASE/'app-data'/'legacy-imported'
        if marker.exists():return
        for filename in ('send-journal.jsonl','decision-journal.jsonl'):
            path=BASE/filename
            if not path.exists():continue
            for line in path.read_text(encoding='utf-8').splitlines()[-250:]:
                try:
                    old=json.loads(line);data={'message':'历史代发记录' if 'part' in old else old.get('reason',''),
                      'legacy':True,'part':old.get('part'),'proof':old.get('proof')}
                    with self.store.lock:
                        self.store.db.execute('INSERT INTO events(time,kind,data) VALUES(?,?,?)',
                          (old.get('time',now()),'sent' if 'part' in old else 'generated',json.dumps(data,ensure_ascii=False)))
                        self.store.db.commit()
                except (ValueError,KeyError):pass
        marker.write_text(now(),encoding='utf-8')
    def snapshot(self,peer_id=None):
        engine=self.contacts.get(peer_id);local=engine.store
        cfg=self.store.settings()
        try:cfg['has_api_key']=bool(app_models.credential_for(self.secrets,cfg).get())
        except Exception:cfg['has_api_key']=False
        profiles=[]
        for profile in self.store.profiles():
            try:profile['has_api_key']=bool(app_models.credential_for(self.secrets,profile).get()) if profile['provider']=='custom' else False
            except Exception:profile['has_api_key']=False
            profiles.append(profile)
        stickers=[{k:s.get(k) for k in ('md5','description','file','native_verified')} for s in app_models.catalog()]
        with self.test_lock:tests=list(self.tests.values())[-8:]
        return {'csrf':self.token,'peer_id':peer_id or 'legacy','contacts':self.contacts.list(),'runtime':engine.snapshot(),'settings':cfg,'jobs':local.jobs(),
                'messages':local.messages(),'events':local.events(),'calls':local.calls(),'stickers':stickers,'tests':tests,'profiles':profiles}
    def test_model(self,payload):
        cfg={**self.store.settings(),**{k:v for k,v in payload.get('settings',{}).items() if k in DEFAULTS}}
        if cfg['provider'] not in ('codex','custom'):raise ValueError('未知模型来源')
        if cfg['provider']=='custom':app_models.endpoint(cfg)
        selected=payload.get('profile_id',cfg.get('active_profile_id'))
        if selected:
            profile=self.store.profile(selected)
            cfg.update(active_profile_id=profile['id'],profile_name=profile['name'],credential_scope=profile['credential_scope'])
        else:cfg.update(active_profile_id=None,profile_name='未保存的配置',credential_scope=None)
        key=payload.get('api_key') or (app_models.credential_for(self.secrets,cfg).get() if selected and cfg['provider']=='custom' else '')
        testcase=payload.get('testcase') or '只回复：连接测试成功'
        if not isinstance(testcase,str) or len(testcase)>2000:raise ValueError('测试问题最多 2000 字')
        testid=uuid.uuid4().hex
        with self.test_lock:self.tests[testid]={'id':testid,'state':'running','created_at':now(),'provider':cfg['provider'],'testcase':testcase}
        def progress(metrics):
            with self.test_lock:self.tests[testid]['progress']=metrics
            self.store.record_call(metrics,test_id=testid,operation='connectivity_test')
        def work():
            try:
                images=[]
                if payload.get('with_image'):
                    from PIL import Image
                    image=BASE/'app-data'/'connectivity-test.png'
                    if not image.exists():Image.new('RGB',(64,64),(0,170,100)).save(image)
                    images=[image]
                text,metrics=app_models.call(cfg,key,'这是用户发起的模型连通性测试。不要使用工具。',testcase,images,timeout=90,progress=progress)
                result={'state':'success','response':text[:6000],**metrics}
            except Exception as exc:result={'state':'failed','error':str(exc).replace(key,'[REDACTED]') if key else str(exc)}
            with self.test_lock:self.tests[testid].update(result,finished_at=now())
            self.store.event('model_test',message='连通性测试成功' if result['state']=='success' else result.get('error','测试失败'),
                test_id=testid,metrics=self.tests[testid].get('progress'))
        self.test_pool.submit(work)
        return {'id':testid}
    def action(self,path,p):
        if path=='/api/contacts/add':return self.contacts.add(p.get('identifier',''))
        if path=='/api/control' and p.get('all') and p.get('enabled') is not True:return self.contacts.stop_all()
        engine=self.contacts.get(p.get('peer_id'))
        if path=='/api/control':return engine.control(p.get('enabled') is True)
        if path=='/api/reconnect':
            with self.contacts.read_lock:self.contacts.reader=None
            engine.commands.put(('reconnect',None));return {'ok':True}
        if path=='/api/settings':
            cfg=p.get('settings',{})
            if cfg.get('provider')=='custom':app_models.endpoint({**self.store.settings(),**cfg})
            key=p.get('api_key')
            if key is not None and not isinstance(key,str):raise ValueError('API Key 格式不正确')
            saved=self.store.save_settings(cfg)
            credential=app_models.credential_for(self.secrets,saved)
            if p.get('clear_key'):credential.set('')
            elif key:credential.set(key)
            self.store.event('settings',message='设置已保存，下轮生成使用新配置',revision=saved['revision'])
            return {'settings':saved}
        if path=='/api/profiles/save':
            key=p.get('api_key')
            if key is not None and (not isinstance(key,str) or any(ord(c)<32 for c in key)):raise ValueError('API Key 格式无效')
            with self.store.lock:
                profile=self.store.prepare_profile(p.get('profile',{}),p.get('id') or None,p.get('version'))
                credential=app_models.credential_for(self.secrets,profile)
                original_key=credential.get() if key or p.get('clear_key') else None
                try:
                    if p.get('clear_key'):credential.set('')
                    elif key:credential.set(key)
                    self.store.write_profile(profile)
                except Exception:
                    if original_key is not None:credential.set(original_key)
                    raise
            self.store.event('settings',message='模型配置已保存：'+profile['name'],profile_id=profile['id'])
            return {'profile':profile}
        if path=='/api/profiles/activate':
            cfg=self.store.activate_profile(p['id'])
            self.store.event('settings',message='已切换模型配置：'+cfg['profile_name'],profile_id=p['id'])
            return {'settings':cfg}
        if path=='/api/profiles/delete':
            with self.store.lock:
                profile=self.store.profile(p['id'])
                if p['id']=='codex-default' or self.store.settings()['active_profile_id']==p['id']:raise Conflict('请先切换到其他配置；内置配置不能删除')
                if profile['version']!=p['version']:raise Conflict('模型配置已被修改')
                credential=app_models.credential_for(self.secrets,profile);old_key=credential.get()
                credential.set('')
                try:self.store.delete_profile(p['id'],p['version'])
                except Exception:credential.set(old_key);raise
            self.store.event('settings',message='模型配置已删除：'+profile['name']);return {'ok':True}
        if path=='/api/model-test':return self.test_model(p)
        if path=='/api/generate':
            instruction=p.get('instruction','')
            if not isinstance(instruction,str) or len(instruction)>6000:raise ValueError('话题说明最多 6000 字')
            return engine.proactive(instruction)
        if path=='/api/media':engine.commands.put(('media',str(p['message_id'])));return {'ok':True}
        if path.startswith('/api/jobs/'):
            _,_,_,jobid,operation=path.split('/')
            version=int(p['version'])
            if operation=='approve':return engine.approve(jobid,version,p['parts'])
            if operation=='edit':return engine.edit(jobid,version,p['parts'])
            if operation=='revise':return engine.revise(jobid,version,p.get('instruction',''),p.get('parts',[]))
            if operation=='skip':return engine.skip(jobid,version)
        raise ValueError('未知操作')

def handler(app):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def allowed(self):
            port=self.server.server_port
            if self.headers.get('Host') not in ('127.0.0.1:'+str(port),'localhost:'+str(port)):return False
            origin=self.headers.get('Origin')
            if origin and origin not in ('http://127.0.0.1:'+str(port),'http://localhost:'+str(port)):return False
            return self.headers.get('Sec-Fetch-Site') not in ('cross-site',)
        def send(self,status,data,content_type='application/json; charset=utf-8'):
            body=json.dumps(data,ensure_ascii=False).encode() if not isinstance(data,bytes) else data
            self.send_response(status);self.send_header('Content-Type',content_type)
            self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Referrer-Policy','no-referrer')
            self.send_header('Content-Security-Policy',"default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'")
            self.send_header('Content-Length',str(len(body)));self.end_headers()
            try:self.wfile.write(body)
            except (BrokenPipeError,ConnectionResetError):pass
        def do_GET(self):
            if not self.allowed():return self.send(403,{'error':'只允许本机页面访问'})
            path=urllib.parse.unquote(urllib.parse.urlsplit(self.path).path)
            if path=='/api/health':return self.send(200,{'service':'wechat-reply-dashboard','pid':os.getpid()})
            if path=='/api/state':
                peer_id=urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query).get('peer_id',[None])[0]
                try:return self.send(200,app.snapshot(peer_id))
                except ValueError as exc:return self.send(400,{'error':str(exc)})
            if path.startswith('/media/'):
                pieces=path.split('/')
                if len(pieces)!=4 or pieces[2] not in ('stickers','incoming'):return self.send(404,{'error':'文件不存在'})
                root=BASE/('stickers' if pieces[2]=='stickers' else 'incoming-media')
                file=(root/pieces[3]).resolve()
                if file.parent!=root.resolve() or file.suffix.lower() not in ('.png','.jpg','.jpeg','.gif','.webp'):return self.send(403,{'error':'不允许访问该文件'})
            else:
                names={'/':'index.html','/app.js':'app.js','/app.css':'app.css'}
                if path not in names:return self.send(404,{'error':'不存在'})
                file=WEB/names[path]
            if not file.is_file():return self.send(404,{'error':'文件不存在'})
            return self.send(200,file.read_bytes(),(mimetypes.guess_type(file.name)[0] or 'application/octet-stream')+'; charset=utf-8')
        def do_POST(self):
            if not self.allowed() or not secrets.compare_digest(self.headers.get('X-CSRF-Token',''),app.token):return self.send(403,{'error':'请求校验失败，请刷新页面'})
            try:
                length=int(self.headers.get('Content-Length','0'))
                if length<0 or length>200000:raise ValueError('请求过大')
                payload=json.loads(self.rfile.read(length) or b'{}')
                if not isinstance(payload,dict):raise ValueError('请求格式无效')
                result=app.action(urllib.parse.urlsplit(self.path).path,payload);self.send(200,result)
            except Conflict as e:self.send(409,{'error':str(e)})
            except (ValueError,KeyError,TypeError) as e:self.send(400,{'error':str(e)})
            except Exception:self.send(500,{'error':'操作失败，请检查后台连接状态'})
    return Handler

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=8765);args=parser.parse_args()
    k=ctypes.windll.kernel32;k.CreateMutexW.restype=ctypes.c_void_p
    mutex=k.CreateMutexW(None,True,'Local\\CodexWechatReplySingleTarget')
    if k.GetLastError()==183:raise SystemExit('Another reply worker is active; stop it before launching the dashboard')
    app=Application()
    server=ThreadingHTTPServer(('127.0.0.1',args.port),handler(app))
    app.contacts.start()
    (BASE/'dashboard.pid').write_text(str(os.getpid()),encoding='ascii')
    print('Local dashboard: http://127.0.0.1:'+str(args.port),flush=True)
    try:server.serve_forever()
    finally:app.contacts.close();server.server_close()
if __name__=='__main__':main()
