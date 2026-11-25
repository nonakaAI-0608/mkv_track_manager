import copy
import unittest
import test_engine
from engine import verify

class Attachments(unittest.TestCase):
    def pair(self):
        before=copy.deepcopy(test_engine.DATA)
        before['attachments'][0]['file_name']=r'fonts\01\font.ttf'
        after=copy.deepcopy(before)
        after['attachments'][0]['file_name']='font.ttf'
        return before,after

    def test_directory_prefix_removed(self):
        before,after=self.pair()
        verify(before,after,{0,1,2})
        before['attachments'][0]['file_name']='fonts/01/font.ttf'
        verify(before,after,{0,1,2})

    def test_real_changes_still_fail(self):
        for field,value in [('file_name','other.ttf'),('size',123),('content_type','other/type')]:
            before,after=self.pair()
            after['attachments'][0][field]=value
            with self.subTest(field=field),self.assertRaises(RuntimeError):
                verify(before,after,{0,1,2})

    def test_duplicate_loss_still_fails(self):
        before,after=self.pair()
        before['attachments'].append(copy.deepcopy(before['attachments'][0]))
        with self.assertRaises(RuntimeError):
            verify(before,after,{0,1,2})
        after['attachments'].append(copy.deepcopy(after['attachments'][0]))
        verify(before,after,{0,1,2})

    def test_chapters_checked_after_name_normalization(self):
        before,after=self.pair()
        after['chapters']=[]
        with self.assertRaisesRegex(RuntimeError,'チャプター'):
            verify(before,after,{0,1,2})
