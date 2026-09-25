import json,sqlite3,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from app_store import Store,Conflict,DEFAULTS
from app_engine import Engine
from dashboard import Application

class ScopedSecrets:
    def __init__(self,data=None,scope='legacy'):self.data={} if data is None else data;self.scope=scope
    def for_profile(self,scope):return ScopedSecrets(self.data,scope or 'legacy')
    def get(self):return self.data.get(self.scope,'')
    def set(self,value):self.data[self.scope]=value

def profile(name,model):return {'name':name,'provider':'custom','base_url':'https://example.invalid/v1','api_model':model,'api_protocol':'chat_completions','api_stream':True}
class ProfilesTests(unittest.TestCase):
    def setUp(self):
        self.store=Store(':memory:');self.secrets=ScopedSecrets();self.app=Application(self.store,self.secrets,Engine(self.store,self.secrets))
    def add(self,name,model,key):return self.app.action('/api/profiles/save',{'profile':profile(name,model),'api_key':key})['profile']
    def test_multiple_profiles_keep_separate_keys(self):
        a=self.add('模型 A','model-a','key-a');b=self.add('模型 B','model-b','key-b')
        self.app.action('/api/profiles/activate',{'id':a['id']})
        self.assertEqual(self.store.settings()['api_model'],'model-a');self.assertEqual(self.secrets.for_profile(self.store.settings()['credential_scope']).get(),'key-a')
        self.app.action('/api/profiles/activate',{'id':b['id']})
        self.assertEqual(self.store.settings()['api_model'],'model-b');self.assertEqual(self.secrets.for_profile(self.store.settings()['credential_scope']).get(),'key-b')
    def test_edit_nonactive_does_not_switch_active(self):
        a=self.add('A','model-a','a');b=self.add('B','model-b','b');self.store.activate_profile(a['id'])
        self.app.action('/api/profiles/save',{'id':b['id'],'version':b['version'],'profile':{'name':'B edited','api_model':'new-b'},'api_key':''})
        self.assertEqual(self.store.settings()['api_model'],'model-a');self.assertEqual(self.secrets.for_profile(b['credential_scope']).get(),'b')
    def test_deleted_profile_only_removes_its_key(self):
        a=self.add('A','model-a','a');b=self.add('B','model-b','b')
        self.app.action('/api/profiles/delete',{'id':a['id'],'version':a['version']})
        self.assertEqual(self.secrets.for_profile(a['credential_scope']).get(),'');self.assertEqual(self.secrets.for_profile(b['credential_scope']).get(),'b')
    def test_active_and_builtin_cannot_be_deleted(self):
        a=self.add('A','model-a','a');self.store.activate_profile(a['id'])
        for item in (a,self.store.profile('codex-default')):
            with self.assertRaises(Conflict):self.app.action('/api/profiles/delete',{'id':item['id'],'version':item['version']})
    def test_no_secret_appears_in_snapshot(self):
        self.add('A','model-a','secret-for-profile-a')
        self.assertNotIn('secret-for-profile-a',json.dumps(self.app.snapshot()))
    def test_stale_editor_cannot_overwrite_profile_or_key(self):
        a=self.add('A','model-a','original');self.app.action('/api/profiles/save',{'id':a['id'],'version':1,'profile':{'name':'Updated'}})
        with self.assertRaises(Conflict):self.app.action('/api/profiles/save',{'id':a['id'],'version':1,'profile':{'name':'Stale'},'api_key':'wrong-key'})
        self.assertEqual(self.secrets.for_profile(a['credential_scope']).get(),'original')
    def test_testcase_uses_selected_profile_not_active(self):
        a=self.add('A','model-a','key-a');b=self.add('B','model-b','key-b');self.store.activate_profile(a['id'])
        with patch('app_models.call',return_value=('ok',{'seconds':1})) as call:
            self.app.test_model({'profile_id':b['id'],'settings':b,'testcase':'ping'})
            self.app.test_pool.shutdown(wait=True)
            self.assertEqual(call.call_args.args[1],'key-b')
    def test_unsaved_test_does_not_borrow_active_key(self):
        a=self.add('A','model-a','key-a');self.store.activate_profile(a['id'])
        with patch('app_models.call',return_value=('ok',{'seconds':1})) as call:
            self.app.test_model({'profile_id':'','settings':profile('new','model-new')})
            self.app.test_pool.shutdown(wait=True);self.assertEqual(call.call_args.args[1],'')
    def test_existing_single_custom_configuration_migrates_once(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'old.db';db=sqlite3.connect(p);db.execute('CREATE TABLE settings(id INTEGER PRIMARY KEY,data TEXT)')
            db.execute('INSERT INTO settings VALUES(1,?)',(json.dumps({**DEFAULTS,**profile('ignored','existing-model'),'provider':'custom'}),));db.commit();db.close()
            s=Store(p);cfg=s.settings();self.assertEqual(cfg['api_model'],'existing-model');self.assertEqual(cfg['credential_scope'],'legacy');self.assertEqual(len(s.profiles()),2);s.db.close()
            s=Store(p);self.assertEqual(len(s.profiles()),2);s.db.close()
if __name__=='__main__':unittest.main()
