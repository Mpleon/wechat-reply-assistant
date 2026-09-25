import tempfile,threading,time,unittest,json
from pathlib import Path
from unittest.mock import patch
from app_store import Store,Conflict
from app_engine import Engine
from app_contacts import Contacts
from dashboard import Application
from test_profiles import ScopedSecrets

class Resolver:
    def resolve_contact(self,value):
        if value not in ('second','wxid_second'):raise ValueError('unknown')
        return {'username':'wxid_second','identifier':value,'display_name':'Second'}

class ContactTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.base=Path(self.tmp.name)
        (self.base/'peer.json').write_text(json.dumps({'username':'wxid_first','display_name':'First'}))
        self.store=Store(self.base/'main.db');self.secrets=ScopedSecrets()
        self.hub=Contacts(self.store,self.secrets,self.base,Engine(self.store,self.secrets));self.hub.reader=Resolver()
        self.peer=self.hub.add('second');self.second=self.hub.get(self.peer['id'])
    def tearDown(self):
        self.hub.close()
        for engine in self.hub.engines.values():engine.pool.shutdown(wait=True);engine.store.db.close()
        self.tmp.cleanup()
    def test_alias_and_wxid_deduplicate(self):
        with self.assertRaises(Conflict):self.hub.add('wxid_second')
        self.assertEqual(len(self.hub.list()),2)
        self.assertFalse(self.second.enabled)
    def test_histories_drafts_usage_are_isolated(self):
        for index,engine in enumerate(self.hub.engines.values()):
            engine.store.cache_messages([{'id':'same-id','seq':1,'text':str(index)}])
            engine.store.event('test',message=str(index))
            engine.store.record_call({'call_id':'same-call','phase':'completed','marker':index})
        self.assertEqual(self.store.messages()[0]['text'],'0')
        self.assertEqual(self.second.store.messages()[0]['text'],'1')
        job=self.store.create('manual')
        with self.assertRaises(ValueError):self.second.approve(job['id'],job['version'],[{'kind':'text','value':'x'}])
        self.assertEqual(self.second.store.calls()[0]['marker'],1)
        self.assertEqual(self.store.calls()[0]['marker'],0)
    def test_shared_model_but_private_examples_excluded(self):
        self.store.save_settings({'system_prompt':'shared','use_style':True})
        self.assertEqual(self.second.store.settings()['system_prompt'],'shared')
        self.assertFalse(self.second.store.settings()['use_style'])
        self.assertTrue(self.store.settings()['use_style'])
    def test_per_contact_control_and_stop_all(self):
        self.second.control(True)
        self.assertFalse(self.hub.get().enabled)
        self.hub.stop_all();self.assertFalse(self.second.enabled)
    def test_registry_and_history_survive_restart_paused(self):
        self.second.store.create('manual');self.second.control(True)
        restored=Contacts(self.store,self.secrets,self.base,Engine(self.store,self.secrets))
        try:
            other=restored.get(self.peer['id'])
            self.assertFalse(other.enabled);self.assertEqual(other.store.jobs()[0]['status'],'cancelled')
            self.assertEqual(len(restored.list()),2)
        finally:
            for key,engine in restored.engines.items():
                engine.pool.shutdown(wait=True)
                if key!='legacy':engine.store.db.close()
    def test_api_selects_contact_without_mutating_global_selection(self):
        with patch('dashboard.BASE',self.base):app=Application(self.store,self.secrets,self.hub.get())
        # Use the test hub to avoid reconnecting to real WeChat.
        for key,engine in app.contacts.engines.items():
            if key!='legacy':engine.store.db.close();engine.pool.shutdown(wait=True)
        app.contacts=self.hub
        self.second.store.create('manual')
        self.assertEqual(len(app.snapshot(self.peer['id'])['jobs']),1)
        self.assertEqual(app.snapshot()['jobs'],[])
        with self.assertRaises(ValueError):app.snapshot('../../invalid')
        app.test_pool.shutdown(wait=True)
    def test_native_sends_are_serialized(self):
        calls=[];barrier=threading.Barrier(2)
        def worker(engine,key):
            def send(job):calls.append(key+' start');time.sleep(.03);calls.append(key+' end')
            engine._send_locked=send;barrier.wait();engine._send('unused')
        threads=[threading.Thread(target=worker,args=(engine,str(i))) for i,engine in enumerate(self.hub.engines.values())]
        for thread in threads:thread.start()
        for thread in threads:thread.join()
        self.assertEqual(calls[0].split()[0],calls[1].split()[0])
        self.assertEqual(calls[2].split()[0],calls[3].split()[0])

class ResolutionTests(unittest.TestCase):
    def test_exact_alias_and_duplicate_name(self):
        from reader import Reader
        reader=object.__new__(Reader);reader.self_id='me';reader.files=['contacts']
        queries=[]
        def query(path,sql,args=()):
            queries.append((sql,args))
            if sql.startswith('PRAGMA'):return [{'name':'username'},{'name':'alias'}]
            if 'COALESCE' in sql:return [{'username':'wxid_x'}]
            return [{'username':'wxid_x','nick_name':'Nick','remark':'Unique remark'}]
        reader.query=query
        self.assertEqual(reader.resolve_contact('public_id')['username'],'wxid_x')
        self.assertEqual(queries[1][1],('public_id','public_id'))
        self.assertNotIn('nick_name=?',queries[1][0])
        original=query
        reader.query=lambda path,sql,args=():[{},{}] if 'COALESCE' in sql else original(path,sql,args)
        with self.assertRaises(ValueError):reader.resolve_contact('public_id')

if __name__=='__main__':unittest.main()
