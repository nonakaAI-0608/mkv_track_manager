import copy
import queue
import sys
import unittest
from unittest.mock import Mock
import test_engine
from engine import compact_metadata, verify, run
from mkv_track_manager import App

class LargeLoad(unittest.TestCase):
    def test_large_backlog_yields_to_gui(self):
        app=Mock()
        app.events=queue.Queue()
        for n in range(20000):
            app.events.put(('status',f'解析中 {n}/20000件'))
        App.poll(app)
        consumed=20000-app.events.qsize()
        self.assertGreater(consumed,0)
        self.assertLessEqual(consumed,64)
        app.after.assert_called_once_with(50,app.poll)

    def test_unused_metadata_is_not_retained(self):
        data=copy.deepcopy(test_engine.DATA)
        data['global_tags']=[{'large_unused_data':'x'*1000000}]
        data['tracks'][0]['properties']['codec_private_data']='x'*1000000
        compact=compact_metadata(data)
        self.assertNotIn('global_tags',compact)
        self.assertNotIn('codec_private_data',compact['tracks'][0]['properties'])
        verify(data,compact,{0,1,2})

    def test_probe_timeout_terminates_process(self):
        with self.assertRaisesRegex(RuntimeError,'秒を超えた'):
            run([sys.executable,'-c','import time; time.sleep(10)'],timeout=0.05)

    def test_poll_reschedules_after_error(self):
        app=Mock()
        app.events=queue.Queue()
        app.events.put(('status','test'))
        app.add_log.side_effect=RuntimeError('test failure')
        App.poll(app)
        app.report_callback_exception.assert_called_once()
        app.after.assert_called_once_with(50,app.poll)

if __name__=='__main__':
    unittest.main()
