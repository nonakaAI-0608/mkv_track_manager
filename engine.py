"""Lossless MKV track selection and guarded replacement. Python 3.10+."""
import collections
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import time


class Cancelled(Exception):
    pass


def run(args, cancel=None, timeout=None):
    flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
    started = time.monotonic()
    with subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          creationflags=flags) as p:
        while True:
            try:
                out, err = p.communicate(timeout=0.2)
                break
            except subprocess.TimeoutExpired:
                expired = timeout is not None and time.monotonic() - started >= timeout
                if expired or (cancel and cancel.is_set()):
                    p.terminate()
                    try:
                        p.communicate(timeout=3)
                    except subprocess.TimeoutExpired:
                        p.kill()
                        p.communicate()
                    if expired:
                        raise RuntimeError(f'解析が{timeout}秒を超えたため、このファイルをスキップしました。')
                    raise Cancelled('中止しました。元ファイルは保持されています。')
        if cancel and cancel.is_set():
            raise Cancelled('中止しました。')
        return p.returncode, out.decode('utf-8-sig', 'replace'), err.decode('utf-8-sig', 'replace')


def identify(exe, path, cancel=None):
    code, out, err = run([exe, '-J', str(path)], cancel, timeout=120)
    if code != 0:
        raise RuntimeError('トラック解析でエラー／警告:\n' + (out + err)[-6000:])
    data = json.loads(out)
    if data.get('errors') or data.get('warnings'):
        raise RuntimeError(str(data.get('errors', []) + data.get('warnings', [])))
    if not data.get('container', {}).get('recognized') or not data['container'].get('supported'):
        raise RuntimeError('未対応または認識できないコンテナです。')
    if data['container'].get('type') != 'Matroska':
        raise RuntimeError('Matroska形式ではありません。')
    if not data.get('tracks'):
        raise RuntimeError('トラックが見つかりません。')
    return compact_metadata(data)


def compact_metadata(data):
    """Keep every field used by selection and verification, omit unused tags/blobs."""
    property_keys = ('uid', 'codec_id', 'language', 'language_ietf', 'track_name',
                     'default_track', 'forced_track')
    return {
        'tracks': [dict(id=t['id'], type=t['type'], codec=t.get('codec'),
                        properties={k: t.get('properties', {})[k] for k in property_keys
                                    if k in t.get('properties', {})}) for t in data['tracks']],
        'attachments': [{k: a[k] for k in ('file_name', 'content_type', 'size') if k in a}
                        for a in data.get('attachments', [])],
        'chapters': [{'num_entries': c.get('num_entries', 0)} for c in data.get('chapters', [])],
    }


def stamp(path):
    s = Path(path).stat()
    return (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)


def selection_args(data, keep):
    tracks = data['tracks']
    ids = {t['id'] for t in tracks}
    if not keep or not set(keep) <= ids:
        raise ValueError('残すトラックを1つ以上選択してください。')
    if any(t['type'] not in ('video', 'audio', 'subtitles', 'buttons') for t in tracks):
        raise ValueError('未対応のトラック種別が含まれるため処理を停止します。')
    args = []
    for kind, opt, no in [('video', '--video-tracks', '--no-video'),
                          ('audio', '--audio-tracks', '--no-audio'),
                          ('subtitles', '--subtitle-tracks', '--no-subtitles'),
                          ('buttons', '--button-tracks', '--no-buttons')]:
        selected = [str(t['id']) for t in tracks if t['type'] == kind and t['id'] in keep]
        args.extend([opt, ','.join(selected)] if selected else [no])
    args.extend(['--track-order', ','.join('0:' + str(t['id']) for t in tracks if t['id'] in keep)])
    return args


def signature(t):
    p = t.get('properties', {})
    return (t['type'], p.get('codec_id', t.get('codec')), p.get('uid'))


def verify(before, after, keep):
    expected = collections.Counter(signature(t) for t in before['tracks'] if t['id'] in keep)
    actual = collections.Counter(signature(t) for t in after['tracks'])
    if actual != expected:
        raise RuntimeError('出力トラックの検証に失敗しました。元ファイルは変更しません。')
    # Attachments and chapter entry counts must survive remuxing.
    def attachments(d):
        return collections.Counter((x.get('file_name'), x.get('content_type'), x.get('size'))
                                   for x in d.get('attachments', []))
    old = attachments(before)
    new = attachments(after)
    # Match unchanged entries first; only allow removal of directory prefixes
    # from input attachment names. Preserve MIME, byte size and multiplicity.
    common = old & new
    stripped = collections.Counter()
    for (name, mime, size), count in (old - common).items():
        basename = name.replace('\\', '/').rsplit('/', 1)[-1] if isinstance(name, str) else name
        stripped[(basename, mime, size)] += count
    if stripped != new - common:
        def describe(counter):
            if not counter:
                return '  （なし）'
            return '\n'.join(
                f'  名前={name!r} / MIME={mime!r} / サイズ={size!r} bytes / 個数={count}'
                for (name, mime, size), count in counter.items())
        def names_sizes(counter):
            result = collections.Counter()
            for (name, mime, size), count in counter.items():
                result[(name, size)] += count
            return result
        hint = ('名前・サイズ・個数は一致し、MIMEタイプの表記だけが異なります。'
                if names_sizes(old) == names_sizes(new) else
                '添付ファイルの名前・サイズ・個数にも相違があります。')
        raise RuntimeError(
            '添付ファイルの検証に失敗しました。元ファイルは変更しません。\n'
            + hint + '\n'
            + f'処理前 {sum(old.values())}個 / 処理後 {sum(new.values())}個\n'
            + '【処理前にのみ存在する情報】\n' + describe(old - new) + '\n'
            + '【処理後にのみ存在する情報】\n' + describe(new - old) + '\n'
            + '※「情報」の差分です。添付データそのものの欠落とは限りません。\n'
            + 'このログをコピーしてお知らせください。')
    if sum(x.get('num_entries', 0) for x in before.get('chapters', [])) != sum(
            x.get('num_entries', 0) for x in after.get('chapters', [])):
        raise RuntimeError('チャプター数の検証に失敗しました。')


def process(exe, path, data, keep, original_stamp, backup=True, cancel=None):
    path = Path(path)
    if path.is_symlink():
        raise RuntimeError('シンボリックリンクは処理できません。')
    args = selection_args(data, keep)
    if stamp(path) != original_stamp:
        raise RuntimeError('解析後にファイルが変更されました。再読み込みしてください。')
    if set(keep) == {t['id'] for t in data['tracks']}:
        return '変更なし', None
    if shutil.disk_usage(path.parent).free < path.stat().st_size + 16 * 1024 * 1024:
        raise RuntimeError('作業用空き容量不足です。元ファイルサイズ＋16MB以上が必要です。')
    bak = path.with_name(path.name + '.bak')
    if backup and bak.exists():
        raise RuntimeError(str(bak) + ' が既に存在します。バックアップは上書きしません。')
    with tempfile.TemporaryDirectory(prefix='.mkv-track-work-', dir=path.parent) as work:
        output = Path(work) / 'output.mkv'
        options = Path(work) / 'options.json'
        # Global track order precedes per-input options.
        order = args[-2:]
        command = ['--output', str(output)] + order + args[:-2] + [str(path)]
        options.write_text(json.dumps(command, ensure_ascii=False), encoding='utf-8')
        code, out, err = run([exe, '@' + str(options)], cancel)
        if code != 0:
            raise RuntimeError('出力でエラー／警告が発生。元ファイルは保持します。\n' + (out + err)[-6000:])
        if not output.exists() or output.stat().st_size == 0:
            raise RuntimeError('正常な出力ファイルがありません。')
        result = identify(exe, output, cancel)
        verify(data, result, keep)
        if stamp(path) != original_stamp:
            raise RuntimeError('処理中に元ファイルが変更されました。置き換えを停止します。')
        if cancel and cancel.is_set():
            raise Cancelled('中止しました。')
        # Windows _commit (os.fsync) requires a writable descriptor.
        with output.open('r+b') as f:
            f.flush()
            os.fsync(f.fileno())
        if backup:
            # A hard link preserves the old bytes without a rename gap or copy.
            # Exclusive creation prevents overwriting an earlier backup.
            try:
                os.link(path, bak)
            except FileExistsError:
                raise RuntimeError('バックアップが既に存在します。')
            except OSError:
                created = False
                try:
                    with bak.open('xb') as dst:
                        created = True
                        with path.open('rb') as src:
                            shutil.copyfileobj(src, dst, 1024 * 1024)
                        dst.flush()
                        os.fsync(dst.fileno())
                except Exception:
                    if created:
                        bak.unlink(missing_ok=True)
                    raise
                if stamp(path) != original_stamp:
                    raise RuntimeError('バックアップ中に元ファイルが変更されました。')
        # Atomic same-filesystem replacement: the original is never deleted first.
        os.replace(output, path)
        return '完了', result


def find_executable():
    candidates = [Path(__file__).parent / 'mkvmerge.exe']
    for key in ('ProgramFiles', 'ProgramFiles(x86)', 'LOCALAPPDATA'):
        if os.environ.get(key):
            candidates.append(Path(os.environ[key]) / 'MKVToolNix' / 'mkvmerge.exe')
    found = shutil.which('mkvmerge')
    return found or next((str(p) for p in candidates if p.is_file()), '')
