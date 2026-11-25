"""Install the optional drag/drop dependency into the app folder, then launch."""
import sys as _sys
if _sys.stdout is None or _sys.stderr is None:
    # Started with pythonw (no console): send print/progress output to a log file
    # instead of crashing on writes to a missing stdout/stderr.
    try:
        _console_log = open(__import__('os').path.join(__import__('os').path.dirname(__import__('os').path.abspath(__file__)), 'console.log'), 'w', encoding='utf-8', buffering=1)
    except OSError:
        _console_log = open(__import__('os').devnull, 'w')
    _sys.stdout = _sys.stdout or _console_log
    _sys.stderr = _sys.stderr or _console_log
import importlib.util
from pathlib import Path
import runpy
import subprocess
import sys

base = Path(__file__).resolve().parent
vendor = base / 'vendor'
sys.path.insert(0, str(vendor))
if importlib.util.find_spec('tkinterdnd2') is None:
    print('Installing drag-and-drop support (tkinterdnd2). Internet is needed on first launch.', flush=True)
    result = subprocess.run([sys.executable, '-m', 'pip', 'install', '--disable-pip-version-check',
                             '--target', str(vendor), 'tkinterdnd2>=0.4,<0.5'])
    if result.returncode:
        print('Drag-and-drop installation failed. File/folder selection buttons remain available.', flush=True)
runpy.run_path(str(base / 'mkv_track_manager.py'), run_name='__main__')
