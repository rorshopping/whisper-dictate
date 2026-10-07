# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for Whisper Dictate. Build with:
#   pyinstaller --noconfirm --clean WhisperDictate.spec
# Produces dist/WhisperDictate/ (onedir) — zip that folder for release.

import glob
import json
import os
import platform
import tempfile

datas = [
    ('assets', 'assets'),
    # config.json is a bundled default only.  app_paths copies/merges it into
    # the writable per-user (or PortableData) directory at frozen startup.
    ('config.json', '.'),
    ('hotwords-en.txt', '.'),
    ('hotwords-de.txt', '.'),
    ('corrections-en.txt', '.'),
    ('corrections-de.txt', '.'),
    ('snippets-en.txt', '.'),
    ('snippets-de.txt', '.'),
    ('README.md', '.'),
    ('LICENSE', '.'),
]
for extra in ('THIRD-PARTY-NOTICES.md',):
    if os.path.exists(extra):
        datas.append((extra, '.'))

# ---------------------------------------------------------------------------
# parakeet.cpp runtime (engine "parakeet-gguf", see parakeet_engine.py).
#
# packaging/parakeet-bin/ is a gitignored staging directory, never committed:
# extract parakeet.dll from a parakeet.cpp release into it before building.
#   CPU build  (parakeet-v*-lib-win-cpu-x64.zip):   just parakeet.dll (~2 MB)
#   CUDA build (parakeet-v*-lib-win-cuda-x64.zip + cudart-*.zip): parakeet.dll
#              plus cublas64_12.dll / cublasLt64_12.dll / cudart64_12.dll
# When staged, the DLLs ship in the payload and the bundled default config's
# EN profile flips to the gguf engine via packaging/windows/engine_defaults.json.
# Without a staged runtime the build stays exactly as before (torch engines).
# ---------------------------------------------------------------------------
PARAKEET_BIN = os.path.join(SPECPATH, 'packaging', 'parakeet-bin')
parakeet_binaries = sorted(glob.glob(os.path.join(PARAKEET_BIN, '*.dll')))
ENGINE_DEFAULTS = os.path.join(SPECPATH, 'packaging', 'windows', 'engine_defaults.json')
if parakeet_binaries and platform.system() == 'Windows':
    if os.path.exists(ENGINE_DEFAULTS):
        with open(os.path.join(SPECPATH, 'config.json'), encoding='utf-8') as handle:
            bundled_config = json.load(handle)
        with open(ENGINE_DEFAULTS, encoding='utf-8') as handle:
            overrides = json.load(handle)
        flipped = 0
        for profile in bundled_config.get('profiles') or []:
            override = overrides.get(profile.get('model'))
            if override:
                profile.update(override)
                flipped += 1
        if flipped:
            # datas entries are (source_file, dest_dir): the source must
            # already be named config.json to land at _internal/config.json.
            flipped_dir = tempfile.mkdtemp(prefix='parakeet-default-')
            flipped_config = os.path.join(flipped_dir, 'config.json')
            with open(flipped_config, 'w', encoding='utf-8') as handle:
                json.dump(bundled_config, handle, ensure_ascii=False, indent=2)
            datas = [entry for entry in datas if entry[0] != 'config.json']
            datas.append((flipped_config, '.'))
        print(f'parakeet runtime staged: {len(parakeet_binaries)} DLL(s), {flipped} profile default(s) flipped')

a = Analysis(
    ['launcher.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=[
        'pystray._win32',
        'pystray._darwin',
        'sounddevice',
        '_sounddevice',
        'pynput.keyboard._win32',
        'pynput.keyboard._darwin',
        'pynput.mouse._win32',
        'pynput.mouse._darwin',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'matplotlib', 'IPython', 'pytest', 'setuptools', 'pydoc_data',
        'tkinter.test', 'unittest.test',
    ],
    noarchive=False,
)
# Staged parakeet.cpp runtime (see note above); appended after Analysis so
# the DLLs land in the onedir payload next to the other binaries.
if parakeet_binaries and platform.system() == 'Windows':
    for dll in parakeet_binaries:
        a.binaries.append((os.path.basename(dll), dll, 'BINARY'))
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='WhisperDictate',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon='icon.ico',
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name='WhisperDictate',
)

# macOS only: wrap the collect output into a proper, double-clickable .app
# bundle with the usage descriptions Gatekeeper/mic access require.
if platform.system() == "Darwin":
    app = BUNDLE(
        coll,
        name='WhisperDictate.app',
        bundle_identifier='com.beckerhub.whisperdictate',
        info_plist={
            'CFBundleDisplayName': 'Whisper Dictate',
            'CFBundleName': 'Whisper Dictate',
            'NSMicrophoneUsageDescription': (
                'Whisper Dictate records audio only while you hold the '
                'push-to-talk hotkey; nothing ever leaves this Mac.'
            ),
            'NSAppleEventsUsageDescription': (
                'Whisper Dictate pastes dictated text and sends keystrokes '
                'to the app you are dictating into.'
            ),
        },
    )
