import json,unittest,urllib.error,tempfile
from pathlib import Path
from unittest.mock import patch
from app_update import check_update,version_tuple
from app_store import Store,Conflict
from app_engine import Engine
from dashboard import Application
from test_profiles import ScopedSecrets

class UpdateTests(unittest.TestCase):
    def test_numeric_version_comparison(self):
        self.assertGreater(version_tuple('v0.10.0'),version_tuple('0.9.0'))
        for value in ('../bad','v0.1.0/other','0.1.0-beta'):
            with self.assertRaises(ValueError):version_tuple(value)
    def test_release_url_cannot_be_replaced(self):
        with patch('app_update.urllib.request.urlopen') as call:
            call.return_value.__enter__.return_value.read.return_value=json.dumps({'tag_name':'v99.0.0','html_url':'https://evil.invalid','body':'notes'}).encode()
            result=check_update()
        self.assertTrue(result['available']);self.assertEqual(result['url'],'https://github.com/Mpleon/wechat-reply-assistant/releases/tag/v99.0.0')
    def test_missing_public_release(self):
        with patch('app_update.urllib.request.urlopen',side_effect=urllib.error.HTTPError('',404,'missing',{},None)):
            with self.assertRaisesRegex(ValueError,'公开'):check_update()

class SetupTests(unittest.TestCase):
    def test_first_setup_and_existing_account_protection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'xwechat_files'/'test_account'/'db_storage').mkdir(parents=True)
            store=Store(':memory:');secrets=ScopedSecrets()
            with patch('dashboard.BASE',root):app=Application(store,secrets,Engine(store,secrets))
            cfg={}
            with patch('runtime_paths.CONFIG',cfg),patch('runtime_paths.LOCAL_FILE',root/'local-runtime.json'):
                with self.assertRaises(ValueError):app.action('/api/setup',{'data_root':str(root),'identifier':'wxid_example'})
                app.action('/api/setup',{'data_root':str(root/'xwechat_files'),'identifier':'wxid_example'})
                self.assertEqual(app.contacts.records['legacy']['username'],'wxid_example')
                self.assertFalse(app.engine.enabled)
                with self.assertRaises(Conflict):app.action('/api/setup',{'data_root':str(root),'identifier':'other'})
            app.test_pool.shutdown();store.db.close()

if __name__=='__main__':unittest.main()
