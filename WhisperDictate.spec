# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for Whisper Dictate. Build with:
#   pyinstaller --noconfirm --clean WhisperDictate.spec
# Produces dist/WhisperDictate/ (onedir) — zip that folder for release.

import os

datas = [
    ('assets', 'assets'),
    ('hotwords-en.txt', '.'),
    ('hotwords-de.txt', '.'),
    ('corrections-en.txt', '.'),
    ('snippets-en.txt', '.'),
    ('snippets-de.txt', '.'),
    ('README.md', '.'),
    ('LICENSE', '.'),
]
for extra in ('THIRD-PARTY-NOTICES.md',):
    if os.path.exists(extra):
        datas.append((extra, '.'))

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
import platform
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
