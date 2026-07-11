# -*- mode: python ; coding: utf-8 -*-
#
# VoiceSync をMacアプリ(.app)としてパッケージ化するためのPyInstaller設定。
#
# 実行:
#   cd backend && source venv/bin/activate
#   pyinstaller voicesync.spec --noconfirm
#
# 依存関係が多い（Vosk・GiNZA/spaCy・SudachiPy）ため、
# collect_all で各パッケージのデータファイルを漏れなく含めている。

from PyInstaller.utils.hooks import collect_all, copy_metadata

datas = []
binaries = []
hiddenimports = []

# データファイル・隠れた依存を自動検出しづらいパッケージ群
for pkg in [
    "vosk",
    "spacy",
    "ja_ginza",
    "ginza",
    "sudachipy",
    "sudachidict_core",
    "pykakasi",
    "sounddevice",
    "thinc",
    "srsly",
    "spacy_alignments",
    "spacy_loggers",
    "spacy_legacy",
    "blis",
    "murmurhash",
    "preshed",
    "cymem",
    "catalogue",
    "wasabi",
    "confection",
    "langcodes",
]:
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

# spaCyはレジストリ関数（spacy.Tagger.v1等）をentry_points経由で解決する。
# entry_pointsはパッケージのdist-infoメタデータが無いと参照できないため、
# collect_allだけでは不十分で、copy_metadataで明示的に含める必要がある。
for pkg in [
    "spacy",
    "spacy-legacy",
    "spacy-loggers",
    "thinc",
    "catalogue",
    "confection",
    "srsly",
    "wasabi",
    "typer",
    "click",
    "ja-ginza",
    "ginza",
    "sudachipy",
    "sudachidict-core",
]:
    datas += copy_metadata(pkg)

# アプリ本体のリソース（フロントエンド一式・Voskモデル）
datas += [
    ("../app", "app"),
    ("models/vosk-model-small-ja-0.22", "backend/models/vosk-model-small-ja-0.22"),
]

a = Analysis(
    ["launcher.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="VoiceSync",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,  # 動作確認がしやすいよう、まずはターミナル表示ありにしておく
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="VoiceSync",
)

app = BUNDLE(
    coll,
    name="VoiceSync.app",
    icon=None,
    bundle_identifier="com.voicesync.app",
    info_plist={
        "NSMicrophoneUsageDescription": "VoiceSyncは会場マイクの音声をリアルタイムで文字化するために使用します。",
        "NSHighResolutionCapable": True,
    },
)
