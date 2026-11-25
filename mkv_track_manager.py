"""MKV Track Manager 1.4.1 — Windows GUI, with optional tkinterdnd2 drag and drop."""
import json
import os
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import traceback
import time
import shutil
import faulthandler
from datetime import datetime
from tkinter.scrolledtext import ScrolledText
from helpers import collect_paths, language_selection
try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    Root = TkinterDnD.Tk
except ImportError:
    Root = tk.Tk
    DND_FILES = None
from engine import identify, stamp, process, find_executable, Cancelled

TYPES = {'video': '映像', 'audio': '音声', 'subtitles': '字幕', 'buttons': 'ボタン'}
CONFIG = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'MKVTrackManager' / 'settings.json'


class App(Root):
    def __init__(self):
        self.dnd_error = ''
        try:
            super().__init__()
        except RuntimeError as e:
            # TkinterDnD creates the Tk root before loading its extension.
            if not hasattr(self, 'tk'):
                raise
            self.dnd_error = str(e)
        self.title('MKV トラック管理 v1.4.1 — 再エンコードなし')
        self.geometry(f'{min(1160, self.winfo_screenwidth()-40)}x{min(820, self.winfo_screenheight()-90)}')
        self.minsize(960, 620)
        self.busy = False
        self.started_at = None
        self.elapsed_seconds = 0.0
        self.drop_folder_display = None
        self.drop_folders = []
        self.rows = {}
        self.log_window = None
        self.log_view = None
        self.session_log = CONFIG.parent / 'logs' / (datetime.now().strftime('%Y%m%d_%H%M%S_%f') + '.log')
        self.fault_log = self.session_log.with_name(self.session_log.stem + '_errors.log')
        self._fault_handle = None
        try:
            self.fault_log.parent.mkdir(parents=True, exist_ok=True)
            self._fault_handle = self.fault_log.open('a', encoding='utf-8')
            faulthandler.enable(file=self._fault_handle)
        except (OSError, RuntimeError):
            pass
        threading.excepthook = lambda args: self.write_fault(args.exc_type, args.exc_value, args.exc_traceback)
        self.events = queue.Queue(maxsize=256)
        self.cancel = threading.Event()
        self.controls = []
        self.exe = tk.StringVar(value=find_executable())
        self.folder = tk.StringVar()
        self.recursive = tk.BooleanVar(value=True)
        self.backup = tk.BooleanVar(value=False)
        self.language = tk.StringVar(value='ja')
        self.elapsed = tk.StringVar(value='経過時間 00:00:00')
        self.status = tk.StringVar(value='フォルダを選択して「読み込み」を押してください。')
        try:
            cfg = json.loads(CONFIG.read_text(encoding='utf-8'))
            if Path(cfg.get('exe', '')).is_file():
                self.exe.set(cfg['exe'])
            self.folder.set(cfg.get('folder', ''))
        except (OSError, ValueError):
            pass
        self.build()
        self.setup_drop()
        self.after(100, self.poll)
        self.protocol('WM_DELETE_WINDOW', self.close)

    def button(self, frame, text, command):
        b = ttk.Button(frame, text=text, command=command)
        b.pack(side='left', padx=3, pady=3)
        self.controls.append(b)
        return b

    def build(self):
        style = ttk.Style(self)
        if 'vista' in style.theme_names():
            style.theme_use('vista')
        style.configure('Treeview', rowheight=27)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        body = self.body = ttk.Frame(self)
        body.grid(row=0, column=0, sticky='nsew')
        footer = ttk.Frame(self)
        footer.grid(row=1, column=0, sticky='ew')
        top = ttk.Frame(body, padding=8)
        top.pack(fill='x')
        for label, var, cmd in [('mkvmerge', self.exe, self.choose_exe), ('対象フォルダ', self.folder, self.choose_folder)]:
            line = ttk.Frame(top)
            line.pack(fill='x')
            ttk.Label(line, text=label, width=14).pack(side='left')
            entry = ttk.Entry(line, textvariable=var)
            entry.pack(side='left', fill='x', expand=True, padx=4)
            self.controls.append(entry)
            self.button(line, '参照…', cmd)
        line = ttk.Frame(top)
        line.pack(fill='x')
        c = ttk.Checkbutton(line, text='サブフォルダも対象', variable=self.recursive)
        c.pack(side='left', padx=4)
        self.controls.append(c)
        self.button(line, '読み込み', self.scan)
        self.button(line, 'ファイルを追加…', self.choose_files)
        ttk.Label(line, text='Ctrl / Shiftで複数選択。処理対象は左端の「対象」が ✓ の行。').pack(side='left', padx=12)
        self.files = self.tree(body, [('target', '対象', 45), ('file', 'ファイル名', 410),
                               ('tracks', '映像 / 音声 / 字幕', 150), ('plan', '削除予定', 130), ('state', '状態', 250)], 1)
        self.files.bind('<<TreeviewSelect>>', lambda e: self.show_tracks())
        self.files.bind('<Button-1>', self.file_click)
        self.files.bind('<space>', self.file_space)
        self.files.bind('<Button-3>', self.file_menu)
        self.files.bind('<Double-1>', self.file_error)
        self.bind('<Control-a>', self.select_all_files)
        self.bind('<Control-A>', self.select_all_files)
        line = ttk.Frame(body, padding=(8, 3))
        line.pack(fill='x')
        self.button(line, '全ファイルを選択', self.select_all_files)
        self.button(line, '選択行の字幕を全削除', lambda: self.preset('subtitles'))
        self.button(line, '選択行の日本語以外音声を削除', lambda: self.preset('japanese_audio'))
        self.button(line, '選択行の設定を元に戻す', lambda: self.preset('reset'))
        line = ttk.Frame(body, padding=(8, 0))
        line.pack(fill='x')
        ttk.Label(line, text='残す言語：').pack(side='left')
        entry = ttk.Entry(line, textvariable=self.language, width=14)
        entry.pack(side='left')
        self.controls.append(entry)
        self.button(line, '選択行でこの言語の音声だけ残す', lambda: self.preset('language'))
        self.button(line, '選択行でこの言語の字幕だけ残す', lambda: self.preset('subtitle_language'))
        ttk.Label(body, text='言語例：ja / jpn / en / eng。該当言語がないファイルは変更しません。', padding=(12, 0)).pack(fill='x')
        self.detail = ttk.Label(body, text='ファイルを1つ選ぶとトラックを表示します。', padding=(12, 6))
        self.detail.pack(fill='x')
        self.tracks = self.tree(body, [('keep', '残す', 50), ('id', 'ID', 45), ('type', '種類', 70),
                                ('codec', '形式', 210), ('lang', '言語', 80), ('name', 'トラック名', 250),
                                ('default', '既定', 50), ('forced', '強制', 50)], 1)
        self.tracks.bind('<Button-1>', self.track_click)
        self.tracks.bind('<space>', self.track_space)
        ttk.Label(body, text='「残す」の ✓ をクリックして切替。✓なしのトラックを削除します。チャプター・添付ファイルは維持します。', padding=(12, 3)).pack(fill='x')
        logbar = ttk.Frame(footer, padding=(8, 0))
        logbar.pack(fill='x')
        ttk.Button(logbar, text='ログを別ウィンドウで開く', command=self.open_log).pack(side='left', padx=4)
        ttk.Button(logbar, text='表示中のログをコピー', command=self.copy_log).pack(side='left', padx=4)
        ttk.Button(logbar, text='ログを保存…', command=self.save_log).pack(side='left', padx=4)
        ttk.Button(logbar, text='ログフォルダを開く', command=self.open_log_folder).pack(side='left', padx=4)
        bottom = ttk.Frame(footer, padding=8)
        bottom.pack(fill='x')
        c = ttk.Checkbutton(bottom, text='元ファイルを .mkv.bak で残す', variable=self.backup)
        c.pack(side='left', padx=4)
        self.controls.append(c)
        self.button(bottom, '変更内容を確認して上書き実行', self.start)
        self.stop = ttk.Button(bottom, text='中止', command=self.cancel.set, state='disabled')
        self.stop.pack(side='left', padx=5)
        self.progress = ttk.Progressbar(bottom, mode='indeterminate')
        self.progress.pack(side='left', fill='x', expand=True, padx=8)
        ttk.Label(footer, textvariable=self.elapsed, padding=(12, 1)).pack(fill='x')
        status_label = ttk.Label(footer, textvariable=self.status, padding=(12, 2), anchor='w')
        status_label.pack(fill='x')
        self.log = ScrolledText(footer, height=5, wrap='word', state='disabled')
        self.log.pack(fill='both', expand=False, padx=10, pady=(3, 10))

        self.layout_body()

    def layout_body(self):
        self.body.columnconfigure(0, weight=1)
        children = list(self.body.pack_slaves())
        for child in children:
            child.pack_forget()
        for i, child in enumerate(children):
            child.grid(row=i, column=0, sticky='nsew')
            weight = 3 if child is self.files.master else 2 if child is self.tracks.master else 0
            self.body.rowconfigure(i, weight=weight, minsize=50 if weight else 0)

    def tree(self, parent, cols, height):
        frame = ttk.Frame(parent, padding=(10, 0))
        frame.pack(fill='both', expand=True)
        t = ttk.Treeview(frame, columns=[x[0] for x in cols], show='headings', height=height)
        for key, title, width in cols:
            t.heading(key, text=title)
            t.column(key, width=width, minwidth=40, stretch=key in ('file', 'name', 'state', 'codec'))
        scroll = ttk.Scrollbar(frame, orient='vertical', command=t.yview)
        t.configure(yscrollcommand=scroll.set)
        t.pack(side='left', fill='both', expand=True)
        scroll.pack(side='right', fill='y')
        return t

    def choose_exe(self):
        p = filedialog.askopenfilename(title='MKVToolNix の mkvmerge.exe', filetypes=[('mkvmerge', 'mkvmerge.exe'), ('すべて', '*')])
        if p:
            self.exe.set(p)

    def choose_folder(self):
        p = filedialog.askdirectory()
        if p:
            self.folder.set(p)

    def append_log_view(self, widget, text):
        widget.configure(state='normal')
        widget.insert('end', text[-100000:] + '\n')
        # Both log windows have the same bound; the disk log keeps all messages.
        lines = int(widget.index('end-1c').split('.')[0])
        if lines > 2000:
            widget.delete('1.0', f'{lines - 2000 + 1}.0')
        chars = int(widget.count('1.0', 'end-1c', 'chars')[0])
        if chars > 500000:
            widget.delete('1.0', f'1.0 + {chars - 500000} chars')
        widget.see('end')
        widget.configure(state='disabled')

    def add_log(self, text):
        text = f'[{datetime.now():%H:%M:%S} / 経過 {self.elapsed_text()}] {text}'
        try:
            self.session_log.parent.mkdir(parents=True, exist_ok=True)
            with self.session_log.open('a', encoding='utf-8') as f:
                f.write(text + '\n')
        except OSError:
            pass
        self.append_log_view(self.log, text)
        if self.log_view is not None and self.log_view.winfo_exists():
            self.append_log_view(self.log_view, text)

    def write_fault(self, exc_type, exc_value, exc_tb):
        # May run on a worker thread: never touch Tk here.
        try:
            with self.fault_log.open('a', encoding='utf-8') as f:
                f.write(f'\n[{datetime.now().isoformat()}] v1.4.1\n')
                traceback.print_exception(exc_type, exc_value, exc_tb, file=f)
        except OSError:
            pass

    def report_callback_exception(self, exc_type, exc_value, exc_tb):
        self.write_fault(exc_type, exc_value, exc_tb)
        self.cancel.set()
        try:
            self.status.set('画面更新エラー：処理を中止しています。ログフォルダの _errors.log を確認してください。')
        except tk.TclError:
            pass

    def set_busy(self, yes):
        self.busy = yes
        for c in self.controls:
            c.configure(state='disabled' if yes else 'normal')
        self.stop.configure(state='normal' if yes else 'disabled')
        if yes:
            self.started_at = time.monotonic()
            self.elapsed_seconds = 0.0
            self.update_elapsed()
            self.cancel.clear()
            self.progress.start(12)
        else:
            if self.started_at is not None:
                self.elapsed_seconds = time.monotonic() - self.started_at
            self.started_at = None
            self.update_elapsed()
            self.progress.stop()

    def elapsed_text(self):
        seconds = time.monotonic() - self.started_at if self.started_at is not None else self.elapsed_seconds
        seconds = max(0, int(seconds))
        return f'{seconds // 3600:02d}:{seconds // 60 % 60:02d}:{seconds % 60:02d}'

    def update_elapsed(self):
        self.elapsed.set('経過時間 ' + self.elapsed_text())

    def scan(self):
        if self.drop_folder_display and self.folder.get() == self.drop_folder_display:
            self.load_paths(self.drop_folders, append=False)
            return
        root = Path(self.folder.get()).expanduser()
        if not root.is_dir():
            messagebox.showerror('設定', '対象フォルダを指定してください。')
            return
        self.load_paths([root], append=False)

    def choose_files(self):
        paths = filedialog.askopenfilenames(filetypes=[('MKV', '*.mkv'), ('すべて', '*')])
        if paths:
            self.load_paths(paths, append=True)

    def setup_drop(self):
        if DND_FILES is None or self.dnd_error:
            self.add_log('ドラッグ＆ドロップを利用できません。start.batで起動して依存ライブラリを導入してください。' + self.dnd_error)
            return
        label = self.detail
        label.configure(text='フォルダ／MKVのドロップで一覧を入れ替えます。1ファイル選択でトラックを表示。')
        for widget in (self, label, self.files, self.tracks):
            widget.drop_target_register(DND_FILES)
            widget.dnd_bind('<<Drop>>', self.on_drop)

    def on_drop(self, event):
        if self.busy:
            self.status.set('処理中は読み込めません。終了後にドロップしてください。')
            return 'none'
        paths = [Path(p).expanduser() for p in self.tk.splitlist(event.data)]
        paths = [p.resolve() for p in paths if not p.is_symlink() and
                 (p.is_dir() or (p.is_file() and p.suffix.lower() == '.mkv'))]
        if not paths:
            self.add_log('ドロップした項目にフォルダ／MKVがありません。一覧は変更していません。')
            return 'none'
        if self.load_paths(paths, append=False, confirm_replace=False):
            folders = list(dict.fromkeys(str(p if p.is_dir() else p.parent) for p in paths))
            self.drop_folders = folders
            self.drop_folder_display = ' | '.join(folders)
            self.folder.set(self.drop_folder_display)
            return 'copy'
        return 'none'

    def load_paths(self, sources, append=True, confirm_replace=True):
        if self.busy:
            return
        if not self.exe.get().strip():
            messagebox.showerror('設定', 'mkvmerge.exeを指定してください。')
            return
        if not append and confirm_replace and self.rows and not messagebox.askyesno('再読み込み', '現在のトラック選択を破棄して再読み込みしますか？'):
            return
        if not append:
            self.rows.clear()
            self.files.delete(*self.files.get_children())
            self.tracks.delete(*self.tracks.get_children())
            self.detail.configure(text='ファイルを1つ選ぶとトラックを表示します。')
        existing = {os.path.normcase(str(r['path'].resolve())) for r in self.rows.values()}
        self.set_busy(True)
        self.add_log(f'読み込み開始：指定 {len(sources)}項目。ファイルを検索しています。')
        exe, recursive = self.exe.get().strip(), self.recursive.get()
        def worker():
            added = 0
            try:
                paths, notices = collect_paths(sources, recursive, existing, self.cancel,
                    progress=lambda count: self.events.put(('status', f'検索中：MKV {count}件検出')))
                for note in notices:
                    self.events.put(('log', note))
                for i, p in enumerate(paths):
                    if self.cancel.is_set():
                        break
                    self.events.put(('status', f'解析中 {i + 1}/{len(paths)}件：{p.name}'))
                    row = dict(path=p, label=str(p), data=None, keep=set(), target=False, state='', error='')
                    try:
                        before = stamp(p)
                        data = identify(exe, p, self.cancel)
                        if stamp(p) != before:
                            raise RuntimeError('解析中にファイルが変更されました。')
                        row.update(data=data, keep={t['id'] for t in data['tracks']}, stamp=before, target=True, state='解析済み')
                    except Cancelled:
                        break
                    except Exception as e:
                        row.update(state='解析失敗（ダブルクリックで詳細）', error=str(e))
                        self.events.put(('log', f'{p}: {e}'))
                    self.events.put(('row', row))
                    added += 1
            except Exception as e:
                self.events.put(('log', str(e)))
            finally:
                self.events.put(('done', f'読み込み終了：{added}件読み込み。読み込んだファイルは全トラック保持です。'))
        threading.Thread(target=worker, daemon=True).start()
        return True

    def refresh(self, key):
        r = self.rows[key]
        ts = r['data']['tracks'] if r['data'] else []
        counts = ' / '.join(str(sum(t['type'] == kind for t in ts)) for kind in ('video', 'audio', 'subtitles'))
        removed = [t for t in ts if t['id'] not in r['keep']]
        plan = ' '.join(f'{TYPES[k]}{sum(t["type"] == k for t in removed)}' for k in TYPES if any(t['type'] == k for t in removed)) or 'なし'
        self.files.item(key, values=('✓' if r['target'] else '', r['label'], counts, plan, r['state']))

    def select_all_files(self, event=None):
        if event is not None:
            if event.widget.winfo_toplevel() is not self:
                return
            if event.widget.winfo_class() in ('Entry', 'TEntry', 'Text', 'TCombobox', 'Spinbox', 'TSpinbox'):
                return
        if not self.busy:
            self.files.selection_set(self.files.get_children())
            self.files.focus_set()
        return 'break'

    def single(self):
        selection = self.files.selection()
        return selection[0] if len(selection) == 1 else None

    def show_tracks(self):
        self.tracks.delete(*self.tracks.get_children())
        key = self.single()
        if key is None:
            self.detail.configure(text='トラック詳細はファイルを1つ選択すると表示されます。')
            return
        r = self.rows[key]
        self.detail.configure(text=r['label'])
        if not r['data']:
            return
        for t in r['data']['tracks']:
            p = t.get('properties', {})
            self.tracks.insert('', 'end', iid=str(t['id']), values=('✓' if t['id'] in r['keep'] else '', t['id'], TYPES.get(t['type'], t['type']),
                t.get('codec', ''), p.get('language_ietf') or p.get('language', 'und'), p.get('track_name', ''),
                '✓' if p.get('default_track') else '', '✓' if p.get('forced_track') else ''))

    def file_click(self, e):
        if not self.busy and self.files.identify_column(e.x) == '#1':
            key = self.files.identify_row(e.y)
            if key and self.rows[key]['data']:
                keys = self.files.selection() if key in self.files.selection() else (key,)
                enabled = not self.rows[key]['target']
                for rowkey in keys:
                    if self.rows[rowkey]['data']:
                        self.rows[rowkey]['target'] = enabled
                        self.refresh(rowkey)
                return 'break'

    def file_space(self, e):
        if not self.busy and self.files.selection():
            keys = [k for k in self.files.selection() if self.rows[k]['data']]
            if keys:
                self.target(not all(self.rows[k]['target'] for k in keys))
        return 'break'

    def file_menu(self, e):
        if self.busy:
            return
        key = self.files.identify_row(e.y)
        if not key:
            return
        if key not in self.files.selection():
            self.files.selection_set(key)
        menu = tk.Menu(self, tearoff=False)
        menu.add_command(label='選択行をまとめてチェック', command=lambda: self.target(True))
        menu.add_command(label='選択行のチェックを外す', command=lambda: self.target(False))
        menu.add_command(label='ログを開く', command=self.open_log)
        try:
            menu.tk_popup(e.x_root, e.y_root)
        finally:
            menu.grab_release()

    def file_error(self, e):
        key = self.files.identify_row(e.y)
        if key and self.rows[key].get('error'):
            self.open_log()

    def open_log(self):
        if self.log_window is not None and self.log_window.winfo_exists():
            self.log_window.lift()
            return
        self.log_window = win = tk.Toplevel(self)
        win.title('処理ログ — コピーして原因の確認に使用できます')
        win.geometry('920x540')
        bar = ttk.Frame(win, padding=8)
        bar.pack(fill='x')
        ttk.Button(bar, text='表示中のログをコピー', command=self.copy_log).pack(side='left', padx=4)
        ttk.Button(bar, text='保存…', command=self.save_log).pack(side='left', padx=4)
        ttk.Label(win, text='自動保存先：' + str(self.session_log), wraplength=880, padding=8).pack(fill='x')
        self.log_view = ScrolledText(win, wrap='word')
        self.log_view.pack(fill='both', expand=True, padx=8, pady=8)
        self.log_view.insert('end', self.log.get('1.0', 'end-1c'))
        self.log_view.configure(state='disabled')
        self.log_view.see('end')

    def open_log_folder(self):
        try:
            self.session_log.parent.mkdir(parents=True, exist_ok=True)
            if os.name == 'nt':
                os.startfile(str(self.session_log.parent))
            else:
                messagebox.showinfo('ログフォルダ', str(self.session_log.parent))
        except OSError as e:
            messagebox.showerror('フォルダを開けません', str(e))

    def copy_log(self):
        self.clipboard_clear()
        self.clipboard_append(self.log.get('1.0', 'end-1c'))
        self.status.set('画面内の最新ログをコピーしました。全履歴は「ログを保存…」で保存できます。')

    def save_log(self):
        name = filedialog.asksaveasfilename(defaultextension='.txt', initialfile='mkv_track_manager_log.txt', filetypes=[('テキスト', '*.txt')])
        if name:
            try:
                if self.session_log.exists():
                    if Path(name).resolve() != self.session_log.resolve():
                        shutil.copyfile(self.session_log, name)
                else:
                    Path(name).write_text(self.log.get('1.0', 'end-1c'), encoding='utf-8-sig')
            except OSError as e:
                messagebox.showerror('保存失敗', str(e))

    def toggle_track(self, track):
        key = self.single()
        if self.busy or key is None or not track:
            return
        keep = self.rows[key]['keep']
        tid = int(track)
        keep.remove(tid) if tid in keep else keep.add(tid)
        self.refresh(key)
        self.show_tracks()
        self.tracks.selection_set(track)

    def track_click(self, e):
        if self.tracks.identify_column(e.x) == '#1':
            self.toggle_track(self.tracks.identify_row(e.y))

    def track_space(self, e):
        if self.tracks.selection():
            self.toggle_track(self.tracks.selection()[0])
        return 'break'

    def target(self, enabled):
        if self.busy:
            return
        for key in self.files.selection():
            if self.rows[key]['data']:
                self.rows[key]['target'] = enabled
                self.refresh(key)

    def preset(self, mode):
        selected = self.files.selection()
        if not selected:
            messagebox.showinfo('ファイル選択', '一覧から変更するファイルを選択してください。')
            return
        lang = 'ja' if mode == 'japanese_audio' else self.language.get().strip().lower()
        skipped = 0
        for key in selected:
            r = self.rows[key]
            if not r['data']:
                continue
            ts = r['data']['tracks']
            if mode == 'reset':
                r['keep'] = {t['id'] for t in ts}
            elif mode == 'subtitles':
                r['keep'] -= {t['id'] for t in ts if t['type'] == 'subtitles'}
            else:
                kind = 'subtitles' if mode == 'subtitle_language' else 'audio'
                audio = [t for t in ts if t['type'] == kind]
                chosen = audio[:1] if mode == 'first_audio' else language_selection(ts, kind, lang)
                if not chosen:
                    skipped += 1
                    continue
                r['keep'] -= {t['id'] for t in audio}
                r['keep'] |= {t['id'] for t in chosen}
            self.refresh(key)
        self.show_tracks()
        if skipped:
            messagebox.showinfo('言語の指定', f'{skipped}件は該当トラックがないため変更していません。')

    def start(self):
        jobs = [(key, dict(r, keep=set(r['keep']))) for key, r in self.rows.items()
                if r['target'] and r['data'] and r['keep'] != {t['id'] for t in r['data']['tracks']}]
        if not jobs:
            messagebox.showinfo('変更なし', '処理対象に削除予定のトラックがありません。')
            return
        if any(not r['keep'] for _, r in jobs):
            messagebox.showerror('選択エラー', '全トラック削除はできません。各ファイルで少なくとも1つ残してください。')
            return
        backup, exe = self.backup.get(), self.exe.get().strip()
        dialog = tk.Toplevel(self)
        dialog.title('上書き内容の確認')
        dialog.geometry('820x470')
        dialog.transient(self)
        ttk.Label(dialog, text=f'{len(jobs)}ファイルを同じパスに上書きします。再エンコードなし。\n' +
                  ('元ファイルは .mkv.bak として残します。' if backup else 'バックアップなし：削除したトラックはこのツールでは戻せません。'), padding=12).pack(fill='x')
        box = tk.Text(dialog, wrap='word')
        box.pack(fill='both', expand=True, padx=12)
        for _, r in jobs:
            deleted = [f'{TYPES.get(t["type"], t["type"])} ID {t["id"]} ({t.get("properties", {}).get("language_ietf") or t.get("properties", {}).get("language", "und")})'
                       for t in r['data']['tracks'] if t['id'] not in r['keep']]
            box.insert('end', r['label'] + '\n  削除：' + ', '.join(deleted) + '\n\n')
        box.configure(state='disabled')
        buttons = ttk.Frame(dialog, padding=10)
        buttons.pack()
        def execute():
            dialog.destroy()
            self.set_busy(True)
            self.add_log(f'処理開始：0/{len(jobs)}件完了')
            def worker():
                success = errors = 0
                try:
                    for n, (key, r) in enumerate(jobs):
                        if self.cancel.is_set():
                            break
                        self.events.put(('state', (key, '処理中')))
                        self.events.put(('status', f'処理中 {n + 1}/{len(jobs)}件：{r["path"].name}'))
                        try:
                            state, data = process(exe, r['path'], r['data'], r['keep'], r['stamp'], backup, self.cancel)
                            success += 1
                            self.events.put(('result', (key, state, data, stamp(r['path']))))
                            self.events.put(('log', f'完了 {n + 1}/{len(jobs)}件：{r["path"].name}'))
                        except Cancelled:
                            self.events.put(('state', (key, '中止・元ファイル保持')))
                            break
                        except Exception as e:
                            errors += 1
                            self.events.put(('state', (key, '失敗・ログを確認')))
                            self.events.put(('error', (key, str(e))))
                            self.events.put(('log', f'失敗 {n + 1}/{len(jobs)}件：{r["label"]}: {e}'))
                finally:
                    self.events.put(('done', f'{"中止" if self.cancel.is_set() else "処理終了"}：完了 {success}件 / 失敗 {errors}件 / 未処理 {len(jobs) - success - errors}件'))
            threading.Thread(target=worker, daemon=True).start()
        ttk.Button(buttons, text='上書きを実行', command=execute).pack(side='left', padx=8)
        ttk.Button(buttons, text='戻る', command=dialog.destroy).pack(side='left', padx=8)
        dialog.grab_set()

    def poll(self):
        self.update_elapsed()
        deadline = time.monotonic() + 0.015
        try:
            for _ in range(64):
                if time.monotonic() >= deadline:
                    break
                kind, value = self.events.get_nowait()
                if kind == 'row':
                    key = str(len(self.rows))
                    self.rows[key] = value
                    self.files.insert('', 'end', iid=key)
                    self.refresh(key)
                elif kind == 'status':
                    self.status.set(value)
                    self.add_log(value)
                elif kind == 'log':
                    self.add_log(value)
                elif kind == 'error':
                    key, error = value
                    self.rows[key]['error'] = error
                    self.rows[key]['state'] = '失敗（ダブルクリックでログ）'
                    self.refresh(key)
                elif kind == 'state':
                    key, state = value
                    self.rows[key]['state'] = state
                    self.refresh(key)
                elif kind == 'result':
                    key, state, data, current = value
                    r = self.rows[key]
                    if data:
                        r.update(data=data, keep={t['id'] for t in data['tracks']}, stamp=current)
                    r['state'] = state
                    r['error'] = ''
                    self.refresh(key)
                    self.show_tracks()
                elif kind == 'done':
                    self.set_busy(False)
                    self.status.set(value)
                    self.add_log(value)
                    if any(r.get('error') for r in self.rows.values()):
                        self.open_log()
        except queue.Empty:
            pass
        except Exception as e:
            self.report_callback_exception(type(e), e, e.__traceback__)
        finally:
            self.after(50, self.poll)

    def close(self):
        if self.busy:
            messagebox.showinfo('処理中', '「中止」を押し、処理終了後に閉じてください。')
            return
        try:
            CONFIG.parent.mkdir(parents=True, exist_ok=True)
            CONFIG.write_text(json.dumps({'exe': self.exe.get(), 'folder': self.folder.get()}, ensure_ascii=False), encoding='utf-8')
        except OSError:
            pass
        if self._fault_handle is not None:
            faulthandler.disable()
            self._fault_handle.close()
        self.destroy()


if __name__ == '__main__':
    try:
        App().mainloop()
    except Exception:
        error = traceback.format_exc()
        print(error)
        try:
            messagebox.showerror('起動エラー', error)
        except Exception:
            pass
