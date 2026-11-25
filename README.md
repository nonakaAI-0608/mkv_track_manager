# MKV トラック管理（mkv_track_manager）

指定フォルダの MKV から、選んだ字幕・音声・映像トラックを削除して同じファイル名で置き換える Windows 向け GUI ツールです。
mkvmerge で再多重化するだけなので、再エンコードはしません。

## 必要なもの
- Windows 10 / 11
- Python 3.10 以降（python.org 版。インストール時に Tcl/Tk と Python Launcher を含める）
- MKVToolNix の mkvmerge.exe（v98.0 を同梱。別の版を使いたい場合は [MKVToolNix](https://mkvtoolnix.download/) から入手）

## インストール
1. このリポジトリを ZIP でダウンロードして展開するか、`git clone` します。
2. `start.bat` をダブルクリックします。初回のみ tkinterdnd2 を `vendor\` に自動インストールします。
3. 同梱の `mkvmerge.exe` を自動で使います。インストール済みの MKVToolNix など別の mkvmerge を使う場合は、画面上段の「参照」で指定します。

## 使い方
詳しい操作説明は [README.txt](README.txt) を参照してください。
設定は `%LOCALAPPDATA%\MKVTrackManager\settings.json` に保存されます。

## テスト
```powershell
py -3 -m unittest discover -p "test_*.py"
```

## ライセンス
MIT License（[LICENSE](LICENSE)）。
同梱の `mkvmerge.exe` は MKVToolNix の一部で、GPL-2.0 で配布されています（[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)）。
