import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import tkinter as tk
import helpers
from mkv_track_manager import App
import test_engine


class Updates(unittest.TestCase):
    def test_japanese_subtitles_only(self):
        tracks = [dict(id=0, type='audio', properties={'language':'jpn'}),
                  dict(id=1, type='subtitles', properties={'language':'jpn'}),
                  dict(id=2, type='subtitles', properties={'language_ietf':'ja-JP'}),
                  dict(id=3, type='subtitles', properties={'language':'eng'}),
                  dict(id=4, type='subtitles', properties={'language':'und'})]
        self.assertEqual([t['id'] for t in helpers.language_selection(tracks, 'subtitles', 'ja')], [1,2])
        self.assertEqual(helpers.language_selection(tracks, 'subtitles', 'de'), [])

    def test_mixed_drop_dedup_recursive(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            f = root/'日本語 name.MKV'
            f.touch()
            (root/'a.txt').touch()
            sub=root/'sub'
            sub.mkdir()
            (sub/'b.mkv').touch()
            work=root/'.mkv-track-work-test'
            work.mkdir()
            (work/'output.mkv').touch()
            paths, _ = helpers.collect_paths([root,f], False)
            self.assertEqual(paths, [f.resolve()])
            paths, _ = helpers.collect_paths([root,f], True)
            self.assertEqual(len(paths), 2)
            paths, _ = helpers.collect_paths([root], True, {os.path.normcase(str(p)) for p in paths})
            self.assertEqual(paths, [])

    def test_tcl_drop_paths_with_spaces(self):
        interp = tk.Tcl()
        raw = '{C:/日本語 folder/file name.mkv} {D:/another folder}'
        self.assertEqual(interp.splitlist(raw), ('C:/日本語 folder/file name.mkv', 'D:/another folder'))

    def test_checkbox_click_applies_to_all_selected_rows(self):
        app = Mock()
        app.busy = False
        app.files.identify_column.return_value = '#1'
        app.files.identify_row.return_value = 'a'
        app.files.selection.return_value = ('a', 'b')
        app.rows = {k: dict(data=True, target=True) for k in ('a','b','c')}
        self.assertEqual(App.file_click(app, Mock(x=1,y=1)), 'break')
        self.assertFalse(app.rows['a']['target'])
        self.assertFalse(app.rows['b']['target'])
        self.assertTrue(app.rows['c']['target'])

    def test_subtitle_preset_leaves_audio_unchanged(self):
        app=Mock()
        app.files.selection.return_value=('a',)
        app.language.get.return_value='ja'
        tracks=[dict(id=0,type='audio',properties={'language':'eng'}),
                dict(id=1,type='subtitles',properties={'language':'jpn'}),
                dict(id=2,type='subtitles',properties={'language':'eng'})]
        app.rows={'a':dict(data={'tracks':tracks},keep={0,1,2})}
        App.preset(app,'subtitle_language')
        self.assertEqual(app.rows['a']['keep'], {0,1})

    def test_subtitle_missing_preserves_choices(self):
        app=Mock()
        app.files.selection.return_value=('a',)
        app.language.get.return_value='ja'
        app.rows={'a':dict(data={'tracks':[dict(id=1,type='subtitles',properties={'language':'eng'})]},keep={1})}
        with patch('mkv_track_manager.messagebox.showinfo'):
            App.preset(app,'subtitle_language')
        self.assertEqual(app.rows['a']['keep'], {1})

    @unittest.skipIf(os.name == 'nt', 'POSIX descriptor inspection models Windows writable-fsync requirement')
    def test_fsync_descriptor_is_writable(self):
        import fcntl
        import engine
        guard=test_engine.Guards()
        guard.setUp()
        try:
            original_fsync=os.fsync
            def windows_like_fsync(fd):
                access=fcntl.fcntl(fd, fcntl.F_GETFL) & os.O_ACCMODE
                if access == os.O_RDONLY:
                    raise OSError(9, 'Bad file descriptor')
                original_fsync(fd)
            with patch('engine.run',side_effect=guard.remux), patch('engine.identify',return_value=guard.after), patch('engine.os.fsync',side_effect=windows_like_fsync):
                guard.execute(backup=False)
            self.assertEqual(guard.path.read_bytes(), b'remuxed content')
        finally:
            guard.doCleanups()

if __name__ == '__main__':
    unittest.main()
