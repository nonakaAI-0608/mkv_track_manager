"""File discovery and language matching shared by GUI and tests."""
import os
from pathlib import Path

ALIASES = {'ja': 'jpn', 'en': 'eng', 'de': 'deu', 'ger': 'deu', 'fr': 'fra',
           'fre': 'fra', 'zh': 'zho', 'chi': 'zho', 'ko': 'kor', 'es': 'spa',
           'it': 'ita', 'pt': 'por', 'ru': 'rus'}


def normalize_language(value):
    code = str(value or '').strip().lower().split('-')[0]
    return ALIASES.get(code, code)


def language_selection(tracks, kind, language):
    want = normalize_language(language)
    if not want:
        return []
    result = []
    for t in tracks:
        if t['type'] != kind:
            continue
        props = t.get('properties', {})
        # Prefer a meaningful IETF tag; fall back to the legacy language field.
        tag = props.get('language_ietf')
        if not tag or normalize_language(tag) == 'und':
            tag = props.get('language', 'und')
        if normalize_language(tag) == want:
            result.append(t)
    return result


def collect_paths(sources, recursive=False, existing=(), cancel=None, progress=None):
    seen = set(existing)
    paths, notices = [], []
    def add(p):
        if p.is_symlink() or not p.is_file() or p.suffix.lower() != '.mkv':
            return
        if any(x.startswith('.mkv-track-work-') for x in p.parts):
            return
        p = p.resolve()
        key = os.path.normcase(str(p))
        if key not in seen:
            seen.add(key)
            paths.append(p)
            if progress and len(paths) % 500 == 0:
                progress(len(paths))
    for source in sources:
        if cancel and cancel.is_set():
            break
        p = Path(source).expanduser()
        try:
            if p.is_symlink():
                notices.append(f'リンクは読み込み対象外：{p}')
            elif p.is_dir():
                # Prune temporary folders before traversing them.
                for root, dirs, files in os.walk(p, followlinks=False, onerror=lambda e: notices.append(str(e))):
                    dirs[:] = [d for d in dirs if recursive and not d.startswith('.mkv-track-work-')]
                    if cancel and cancel.is_set():
                        break
                    for name in files:
                        if cancel and cancel.is_set():
                            break
                        add(Path(root) / name)
            elif p.is_file() and p.suffix.lower() == '.mkv':
                add(p)
            else:
                notices.append(f'MKV／フォルダ以外、または存在しないためスキップ：{p}')
        except OSError as e:
            notices.append(f'{p}: {e}')
    return sorted(paths, key=lambda p: str(p).lower()), notices
