import copy,json,tempfile,threading,time,unittest,urllib.request,urllib.error,uuid
from pathlib import Path
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
from concurrent.futures import Future
from unittest.mock import patch
from app_store import Store,Conflict,DEFAULTS
from app_engine import Engine,revision
import app_models
from dashboard import Application,handler

def msg(seq,sender='她',text='你好'):
    return {'server_id':seq,'local_id':seq,'database':'message_0.db','sort_seq':seq,'create_time':1700000000+seq,'sender':sender,'local_type':1,'content':text}
class MemorySecrets:
    def __init__(self):self.value=''
    def get(self):return self.value
    def set(self,value):self.value=value
class FakeReader:
    target='test-id';target_name='测试联系人'
    def __init__(self):self.rows=[msg(1)]
    def recent(self,*args,**kwargs):return copy.deepcopy(self.rows)
class FakeSender:
    class StickerNotSent(RuntimeError):pass
    def __init__(self,r):self.r=r;self.sent=[];self.fail=False;self.incoming_during_send=False
    def send_text(self,target,text):
        if self.fail:raise OSError('click outcome unknown')
        self.sent.append((target,text));self.r.rows.append(msg(self.r.rows[-1]['sort_seq']+1,'我',text))
        self.proof={'server_id':self.r.rows[-1]['server_id']}
        if self.incoming_during_send:self.r.rows.append(msg(self.r.rows[-1]['sort_seq']+1,'她','等一下'))
    def verify(self,*args):return self.proof
class DraftTests(unittest.TestCase):
    def setUp(self):
        self.store=Store(':memory:');self.r=FakeReader();self.sender=FakeSender(self.r)
        self.e=Engine(self.store,MemorySecrets(),sender=self.sender)
        self.e.reader=self.r;self.e._refresh();self.e.state(connected=True)
    def draft(self):
        j=self.store.create('manual','主动打招呼')
        return self.store.update(j['id'],status='awaiting',parts=[{'kind':'text','value':'你好呀'}],baseline=self.e.rev,epoch=0,mode='review',model='test')
    def test_approval_delivers_once_and_requires_version(self):
        j=self.draft();self.e.approve(j['id'],j['version'],j['parts']);self.e._send(j['id'])
        self.assertEqual(self.store.job(j['id'])['status'],'sent');self.assertEqual(len(self.sender.sent),1)
        with self.assertRaises(Conflict):self.e.approve(j['id'],j['version'],j['parts'])
        self.e._send(j['id']);self.assertEqual(len(self.sender.sent),1)
    def test_new_message_blocks_approved_old_draft(self):
        j=self.draft();self.e.approve(j['id'],j['version'],j['parts']);self.r.rows.append(msg(2))
        self.e._send(j['id']);self.assertEqual(self.sender.sent,[]);self.assertEqual(self.store.job(j['id'])['status'],'stale')
    def test_pause_cancels_queued_send(self):
        j=self.draft();self.e.approve(j['id'],j['version'],j['parts']);self.e.control(False);self.e._send(j['id'])
        self.assertEqual(self.sender.sent,[])
    def test_uncertain_delivery_never_retries(self):
        j=self.draft();self.e.approve(j['id'],j['version'],j['parts']);self.sender.fail=True;self.e.enabled=True;self.e._send(j['id'])
        self.assertEqual(self.store.job(j['id'])['status'],'uncertain');self.assertFalse(self.e.enabled)
    def test_conversation_change_cancels_remaining_parts(self):
        j=self.draft();parts=j['parts']*2;self.e.approve(j['id'],j['version'],parts);self.sender.incoming_during_send=True
        self.e._send(j['id']);self.assertEqual(len(self.sender.sent),1);self.assertEqual(self.store.job(j['id'])['status'],'partial')
    def test_revision_preserves_previous_and_uses_owner_prompt(self):
        j=self.draft();n=self.e.revise(j['id'],j['version'],'更俏皮一点',j['parts'])
        self.assertEqual(n['instruction'],'更俏皮一点');self.assertEqual(n['parent']['parts'],j['parts'])
        self.assertEqual(self.store.job(j['id'])['status'],'superseded')
    def test_manual_generation_does_not_require_new_incoming(self):
        self.r.rows=[msg(2,'我')];j=self.e.proactive('问她想不想看电影')
        self.assertEqual(j['status'],'queued');self.assertEqual(j['source'],'manual')
    def test_configuration_is_persistent_and_key_not_stored_in_it(self):
        value=self.store.save_settings({'system_prompt':'我的新提示词','mode':'auto','api_key':'must-not-save'})
        self.assertEqual(self.store.settings()['system_prompt'],'我的新提示词')
        self.assertNotIn('api_key',value)
    def test_pause_discards_finished_generation(self):
        j=self.draft();self.store.update(j['id'],status='generating')
        f=Future();f.set_result(({'decision':'reply','parts':j['parts'],'reason':'fixture'},{'seconds':1}))
        self.e.future=f;self.e.future_job=j['id'];self.e.control(False);self.e._finish()
        self.assertEqual(self.store.job(j['id'])['status'],'cancelled');self.assertEqual(self.sender.sent,[])
    def test_start_listening_cannot_autosend_a_preview_requested_while_paused(self):
        self.store.save_settings({'mode':'auto'})
        j=self.draft();self.store.update(j['id'],status='generating',mode='auto',auto_send_requested=False)
        f=Future();f.set_result(({'decision':'reply','parts':j['parts'],'reason':'fixture'},{'seconds':1}))
        self.e.future=f;self.e.future_job=j['id'];self.e.control(True);self.e._finish()
        self.assertEqual(self.store.job(j['id'])['status'],'awaiting')
    def test_explicit_auto_round_queues_and_sends(self):
        self.store.save_settings({'mode':'auto'});self.e.enabled=True
        j=self.draft();self.store.update(j['id'],status='generating',source='incoming',mode='auto',auto_send_requested=True)
        f=Future();f.set_result(({'decision':'reply','parts':j['parts'],'reason':'fixture'},{'seconds':1}))
        self.e.future=f;self.e.future_job=j['id'];self.e._finish()
        self.assertEqual(self.store.job(j['id'])['status'],'send_queued')
        self.e._send(j['id']);self.assertEqual(len(self.sender.sent),1)
    def test_restart_marks_inflight_send_uncertain(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'app.db';s=Store(path);j=s.create('manual');s.update(j['id'],status='sending');s.db.close()
            restored=Store(path);self.assertEqual(restored.job(j['id'])['status'],'uncertain');restored.db.close()

class MockProvider(BaseHTTPRequestHandler):
    captured=[]
    def log_message(self,*a):pass
    def do_POST(self):
        body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));type(self).captured.append((self.path,body))
        if self.headers.get('Authorization')=='Bearer bad':
            self.send_response(401);self.end_headers();self.wfile.write(b'invalid key: bad');return
        if body.get('model')=='missing-model':
            self.send_response(404);self.end_headers();self.wfile.write(b'model_not_found');return
        if body.get('model')=='slow-model':time.sleep(.2)
        payload={'output':[{'type':'message','content':[{'type':'output_text','text':'CONNECTED'}]}]} if self.path.endswith('/responses') else {'choices':[{'message':{'content':'CONNECTED'}}]}
        data=json.dumps(payload).encode();self.send_response(200);self.send_header('Content-Length',str(len(data)));self.end_headers()
        try:self.wfile.write(data)
        except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError):pass
class ProviderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server=ThreadingHTTPServer(('127.0.0.1',0),MockProvider);threading.Thread(target=cls.server.serve_forever,daemon=True).start()
    @classmethod
    def tearDownClass(cls):cls.server.shutdown();cls.server.server_close()
    def settings(self,protocol):return {**DEFAULTS,'provider':'custom','api_model':'fixture-model','base_url':f'http://127.0.0.1:{self.server.server_port}/v1','api_protocol':protocol}
    def test_chat_completions_and_responses_actual_http(self):
        for protocol in ('chat_completions','responses'):
            text,metrics=app_models.call(self.settings(protocol),'fake-test-key','system','test')
            self.assertEqual(text,'CONNECTED');self.assertEqual(metrics['model'],'fixture-model')
    def test_key_redacted_from_error(self):
        with self.assertRaises(ValueError) as result:app_models.call(self.settings('chat_completions'),'bad','system','test')
        self.assertNotIn('key: bad',str(result.exception));self.assertIn('401',str(result.exception))
    def test_model_switch_payload_and_image_shape(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'tiny.png';p.write_bytes(b'test fixture')
            app_models.call(self.settings('responses'),'fake','system','image',[p])
            _,body=MockProvider.captured[-1]
            self.assertEqual(body['model'],'fixture-model');self.assertTrue(body['input'][0]['content'][1]['image_url'].startswith('data:image/png;base64,'))
    def test_system_prompt_is_sent(self):
        app_models.call(self.settings('chat_completions'),'fake','MY SYSTEM','test')
        self.assertEqual(MockProvider.captured[-1][1]['messages'][0]['content'],'MY SYSTEM')
    def test_wrong_model_reports_failure(self):
        settings=self.settings('responses');settings['api_model']='missing-model'
        with self.assertRaises(ValueError) as result:app_models.call(settings,'fake','system','test')
        self.assertIn('404',str(result.exception))
    def test_timeout_does_not_report_success(self):
        settings=self.settings('responses');settings['api_model']='slow-model'
        with self.assertRaises(ValueError):app_models.call(settings,'fake','system','test',timeout=.05)

class HTTPTests(unittest.TestCase):
    def setUp(self):
        store=Store(':memory:');secret=MemorySecrets();secret.set('never-return-this-key')
        engine=Engine(store,secret);self.app=Application(store,secret,engine)
        self.server=ThreadingHTTPServer(('127.0.0.1',0),handler(self.app));threading.Thread(target=self.server.serve_forever,daemon=True).start()
        self.url=f'http://127.0.0.1:{self.server.server_port}'
    def tearDown(self):self.server.shutdown();self.server.server_close()
    def test_public_state_has_presence_but_no_key(self):
        body=urllib.request.urlopen(self.url+'/api/state').read().decode();self.assertNotIn('never-return-this-key',body)
        self.assertTrue(json.loads(body)['settings']['has_api_key'])
    def test_cross_origin_post_denied(self):
        request=urllib.request.Request(self.url+'/api/control',data=b'{}',headers={'Origin':'https://evil.test','X-CSRF-Token':self.app.token})
        with self.assertRaises(urllib.error.HTTPError) as e:urllib.request.urlopen(request)
        self.assertEqual(e.exception.code,403)
    def test_csrf_required(self):
        with self.assertRaises(urllib.error.HTTPError) as e:urllib.request.urlopen(urllib.request.Request(self.url+'/api/control',data=b'{}'))
        self.assertEqual(e.exception.code,403)
    def test_traversal_cannot_read_settings_or_logs(self):
        with self.assertRaises(urllib.error.HTTPError):urllib.request.urlopen(self.url+'/media/stickers/%2e%2e%2fpeer.json')
if __name__=='__main__':unittest.main()
