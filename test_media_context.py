import unittest
from pathlib import Path
from media_context import MediaContext
class MediaContextTests(unittest.TestCase):
    def media(self):
        obj=object.__new__(MediaContext);obj.catalog={}
        obj.image=lambda m:Path(str(m['sort_seq'])+'.png')
        return obj
    def test_her_question_includes_previous_user_image(self):
        rows=[{'local_type':3,'sender':'我','sort_seq':10,'create_time':100,'content':''},
              {'local_type':1,'sender':'她','sort_seq':12,'create_time':105,'content':'？'}]
        context,images=self.media().prepare(rows,11)
        self.assertEqual(images,[Path('10.png')])
        self.assertEqual(context['messages'][0]['attachment'],1)
        self.assertEqual(context['messages'][0]['speaker'],'owner')
        self.assertEqual(context['messages'][1]['speaker'],'peer')
        self.assertEqual(context['last_speaker'],'peer')
        self.assertEqual(context['attachments'][0]['speaker'],'owner')
        self.assertEqual(context['attachments'][0]['message_seq'],10)
    def test_old_picture_does_not_take_recent_attachment_budget(self):
        rows=[{'local_type':3,'sender':'我','sort_seq':10,'create_time':100,'content':''},
              {'local_type':3,'sender':'她','sort_seq':12,'create_time':2000,'content':''}]
        context,images=self.media().prepare(rows,11)
        self.assertEqual(images,[Path('12.png')])
    def test_owner_last_message_is_not_a_new_peer_turn(self):
        rows=[{'local_type':1,'sender':'她','sort_seq':10,'create_time':100,'content':'在玩什么'},
              {'local_type':3,'sender':'我','sort_seq':12,'create_time':105,'content':''},
              {'local_type':1,'sender':'我','sort_seq':13,'create_time':106,'content':'是不是没见过'}]
        context,images=self.media().prepare(rows,12)
        self.assertEqual(context['last_speaker'],'owner')
        self.assertEqual([r['speaker'] for r in context['messages']],['peer','owner','owner'])
        self.assertEqual(context['attachments'][0]['speaker'],'owner')
    def test_generation_prompt_carries_identity_and_trigger(self):
        import json,app_models
        from unittest.mock import patch
        from app_store import DEFAULTS
        context={'last_speaker':'owner','generation_task':{'source':'manual'},'messages':[]}
        with patch('app_models.catalog',return_value=[]),patch('app_models.call',return_value=(json.dumps({'decision':'wait','parts':[],'reason':'等待对方'}),{})) as call:
            app_models.generate({**DEFAULTS,'use_style':False},'',context,[])
        self.assertIn('不得扮演 peer',call.call_args.args[2])
        self.assertEqual(json.loads(call.call_args.args[3])['conversation_data'],context)
if __name__=='__main__':unittest.main()
