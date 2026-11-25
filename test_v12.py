from pathlib import Path
import queue
import tempfile
import unittest
from unittest.mock import Mock, patch
from mkv_track_manager import App

class V12(unittest.TestCase):
    def test_drop_replaces_and_sets_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = Mock(busy=False)
            app.tk.splitlist.return_value = (tmp,)
            app.load_paths.return_value = True
            self.assertEqual(App.on_drop(app, Mock(data='drop')), 'copy')
            app.load_paths.assert_called_once_with([Path(tmp).resolve()], append=False, confirm_replace=False)
            app.folder.set.assert_called_once_with(str(Path(tmp).resolve()))

    def test_file_drop_displays_parent(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)/'日本語 name.mkv'
            p.touch()
            app = Mock(busy=False)
            app.tk.splitlist.return_value = (str(p),)
            app.load_paths.return_value = True
            App.on_drop(app, Mock(data='drop'))
            app.folder.set.assert_called_once_with(str(p.parent.resolve()))

    def test_invalid_drop_does_not_clear(self):
        app = Mock(busy=False)
        app.tk.splitlist.return_value = ('/nonexistent/video.mp4',)
        self.assertEqual(App.on_drop(app, Mock(data='drop')), 'none')
        app.load_paths.assert_not_called()
        app.folder.set.assert_not_called()

    def test_replace_clears_existing_rows_without_prompt(self):
        app = Mock(busy=False)
        app.exe.get.return_value='mkvmerge'
        app.rows={'old': {'path':Path('/old.mkv')}}
        app.files.get_children.return_value=('old',)
        app.tracks.get_children.return_value=('track',)
        with patch('mkv_track_manager.threading.Thread'), patch('mkv_track_manager.messagebox.askyesno') as ask:
            self.assertTrue(App.load_paths(app, ['/new'], append=False, confirm_replace=False))
        ask.assert_not_called()
        self.assertEqual(app.rows,{})
        app.files.delete.assert_called_once_with('old')
        app.tracks.delete.assert_called_once_with('track')

    def test_timer_and_completed_time(self):
        app = Mock(started_at=100.0, elapsed_seconds=0)
        with patch('mkv_track_manager.time.monotonic',return_value=3761):
            self.assertEqual(App.elapsed_text(app),'01:01:01')
        app.started_at=None
        app.elapsed_seconds=62.4
        self.assertEqual(App.elapsed_text(app),'00:01:02')

    def test_status_is_also_logged(self):
        app = Mock()
        app.events=queue.Queue()
        text='処理中 2/12件：test.mkv'
        app.events.put(('status',text))
        App.poll(app)
        app.status.set.assert_called_once_with(text)
        app.add_log.assert_called_once_with(text)

if __name__=='__main__':
    unittest.main()
