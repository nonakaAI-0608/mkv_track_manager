"""Guard tests; no external mkvmerge needed. Run: python -m unittest -v"""
import copy
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import engine

DATA = {'container': {'recognized': True, 'supported': True, 'type': 'Matroska'},
        'tracks': [{'id': i, 'type': kind, 'codec': codec, 'properties': {'uid': 101+i, 'codec_id': codec}}
                   for i, kind, codec in [(0, 'video', 'V_MPEG4/ISO/AVC'), (1, 'audio', 'A_AAC'), (2, 'subtitles', 'S_TEXT/ASS')]],
        'attachments': [{'file_name': 'font.ttf', 'content_type': 'font/ttf', 'size': 10}],
        'chapters': [{'num_entries': 2}]}

class Guards(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / '日本語 file.mkv'
        self.path.write_bytes(b'original content')
        self.before = engine.stamp(self.path)
        self.after = copy.deepcopy(DATA)
        self.after['tracks'] = self.after['tracks'][:2]

    def remux(self, command, cancel):
        opts = json.loads(Path(command[1][1:]).read_text(encoding='utf-8'))
        self.assertIn('--no-subtitles', opts)
        self.assertEqual(opts[-1], str(self.path))
        Path(opts[opts.index('--output')+1]).write_bytes(b'remuxed content')
        return 0, '', ''

    def execute(self, **kw):
        return engine.process('mkvmerge', self.path, DATA, {0, 1}, self.before, **kw)

    def test_success_backup(self):
        with patch('engine.run', side_effect=self.remux), patch('engine.identify', return_value=self.after):
            self.execute(backup=True)
        self.assertEqual(self.path.read_bytes(), b'remuxed content')
        self.assertEqual(self.path.with_suffix('.mkv.bak').read_bytes(), b'original content')
        self.assertFalse(list(self.path.parent.glob('.mkv-track-work-*')))

    def test_success_no_backup(self):
        with patch('engine.run', side_effect=self.remux), patch('engine.identify', return_value=self.after):
            self.execute(backup=False)
        self.assertEqual(self.path.read_bytes(), b'remuxed content')
        self.assertFalse(self.path.with_suffix('.mkv.bak').exists())

    def test_warning_preserves_original(self):
        with patch('engine.run', return_value=(1, 'Warning: test', '')):
            with self.assertRaises(RuntimeError):
                self.execute()
        self.assertEqual(self.path.read_bytes(), b'original content')

    def test_wrong_output_preserves_original(self):
        with patch('engine.run', side_effect=self.remux), patch('engine.identify', return_value=DATA):
            with self.assertRaises(RuntimeError):
                self.execute()
        self.assertEqual(self.path.read_bytes(), b'original content')

    def test_input_changed(self):
        self.path.write_bytes(b'changed while recording')
        with self.assertRaises(RuntimeError):
            self.execute()
        self.assertEqual(self.path.read_bytes(), b'changed while recording')

    def test_existing_backup_preserved(self):
        bak = self.path.with_suffix('.mkv.bak')
        bak.write_bytes(b'older backup')
        with self.assertRaises(RuntimeError):
            self.execute()
        self.assertEqual(bak.read_bytes(), b'older backup')
        self.assertEqual(self.path.read_bytes(), b'original content')

    def test_cancel_before_replace(self):
        cancel = threading.Event()
        cancel.set()
        with patch('engine.run', side_effect=self.remux), patch('engine.identify', return_value=self.after):
            with self.assertRaises(engine.Cancelled):
                self.execute(cancel=cancel)
        self.assertEqual(self.path.read_bytes(), b'original content')

    def test_replace_failure_preserves_original(self):
        with patch('engine.run', side_effect=self.remux), patch('engine.identify', return_value=self.after), patch('engine.os.replace', side_effect=PermissionError('locked')):
            with self.assertRaises(PermissionError):
                self.execute()
        self.assertEqual(self.path.read_bytes(), b'original content')
        self.assertEqual(self.path.with_suffix('.mkv.bak').read_bytes(), b'original content')

    def test_backup_copy_fallback(self):
        with patch('engine.run', side_effect=self.remux), patch('engine.identify', return_value=self.after), patch('engine.os.link', side_effect=OSError('unsupported')):
            self.execute()
        self.assertEqual(self.path.with_suffix('.mkv.bak').read_bytes(), b'original content')
