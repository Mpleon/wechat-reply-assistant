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
    def test_old_picture_does_not_take_recent_attachment_budget(self):
        rows=[{'local_type':3,'sender':'我','sort_seq':10,'create_time':100,'content':''},
              {'local_type':3,'sender':'她','sort_seq':12,'create_time':2000,'content':''}]
        context,images=self.media().prepare(rows,11)
        self.assertEqual(images,[Path('12.png')])
if __name__=='__main__':unittest.main()
