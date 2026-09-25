import unittest
from unittest.mock import patch,Mock
import native_send

class StickerFailureTests(unittest.TestCase):
    def test_preparation_failure_is_definitely_not_sent(self):
        with patch.object(native_send,'_prepare_sticker',side_effect=RuntimeError('bitmap mismatch')):
            with self.assertRaises(native_send.StickerNotSent):
                native_send.send_sticker('target','digest',None)
    def test_click_failure_is_not_safe_to_retry(self):
        item=Mock();item.Click.side_effect=OSError('delivery result unknown')
        with patch.object(native_send,'_prepare_sticker',return_value=item):
            with self.assertRaises(OSError):
                native_send.send_sticker('target','digest',None)
        item.Click.assert_called_once()
    def test_success_clicks_exactly_once(self):
        item=Mock()
        with patch.object(native_send,'_prepare_sticker',return_value=item),patch.object(native_send.time,'sleep'):
            native_send.send_sticker('target','digest',None)
        item.Click.assert_called_once()
if __name__=='__main__':unittest.main()
