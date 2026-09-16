#!/usr/bin/env python3
"""PyInstaller spec: standalone Whisper Dictate bundles.

One spec, three platforms - PyInstaller always builds for the machine it runs
on, so the release scripts run this spec on each OS (see docs/RELEASE.md).

Deliberate choices:

* The entry point is ``launcher.py``, not ``main.py``: launcher applies the
  macOS platform patches (Tk/AppKit ordering, main-thread paste, Cmd+V,
  stale-lock recovery) around ``main``. Freezing ``main.py`` directly would
  silently ship the macOS bugs the module exists to fix.
* ``packaging/defaults`` ships as ``defaults``: the app copies it into the
  per-user data folder on first run (``app_paths.ensure_initialized``). It holds
  a clean config plus empty templates - never a developer's hotwords,
  corrections or history.
* Model weights are NOT bundled. They are downloaded on first use and cached by
  ``huggingface_hub`` (the app sets ``HF_HUB_OFFLINE=1`` once they are cached),
  which keeps the download a few hundred MB instead of several GB.
* ``console`` is off for the windowed app; ``--doctor`` still prints because
  main.py writes to the log file and, on Windows, to an attached console when
  one exists.
"""

import os
import sys

from PyInstaller.utils.hooks import collect_all, collect_submodules

# SPECPATH is injected by PyInstaller and points at this file's directory
# (packaging/); BASE_DIR is the repository root. __file__ is not defined in a
# spec, which is a common first-build failure.
BASE_DIR = os.path.dirname(os.path.abspath(SPECPATH))
PACKAGING = os.path.join(BASE_DIR, "packaging")
ICON = os.path.join(BASE_DIR, "icon.ico")

datas = [(os.path.join(PACKAGING, "defaults"), "defaults")]
binaries = []
hiddenimports = [
    # The app's own add-on modules are imported by name at runtime.
    "app_paths",
    "text_tools",
    "history_store",
    "desktop_ui",
    "hotword_fuzzy",
    "enhanced_features",
    "platform_mac",
]

# Packages whose dynamic imports PyInstaller cannot see through (transformers is
# the worst offender: it resolves model classes by name and uses lazy module
# attributes). collect_all is used only where it is actually needed - it inflates
# the bundle, so the list stays short and every entry is justified below.
COLLECT_ALL_PACKAGES = (
    # AutoModelForRNNT/AutoProcessor are resolved dynamically.
    "transformers",
    # Imported at runtime for the MPS fallback path and vendored libs.
    "torch",
    # Dynamic backend loading inside faster_whisper/ctranslate2.
    "faster_whisper",
    "ctranslate2",
    # Backend selected at import time (pulse/alsa/coreaudio).
    "sounddevice",
    # Platform backends are chosen at runtime (Quartz/Win32/Xlib).
    "pynput",
    "pystray",
    # Audio decoding (soundfile/soxr); librosa is deliberately NOT collected.
    "soundfile",
    "av",
    "tokenizers",
    "safetensors",
    "huggingface_hub",
)

for name in COLLECT_ALL_PACKAGES:
    try:
        pkg_datas, pkg_binaries, pkg_hidden = collect_all(name)
        datas += pkg_datas
        binaries += pkg_binaries
        hiddenimports += pkg_hidden
    except Exception as exc:  # pragma: no cover - build-time diagnostics
        print(f"[spec] collect_all({name}) failed: {exc}")

# Optional dependencies: collected when installed, skipped otherwise.
for name in ("rapidfuzz",):
    try:
        hiddenimports += collect_submodules(name)
    except Exception:
        pass

# Trim what an offline dictation app never needs; without this PyInstaller walks
# into matplotlib/IPython/pytest pulled in by transitive test extras.
#
# Do NOT be tempted to drop librosa here: nothing in this repository imports it,
# but transformers' NemotronAsrStreamingFeatureExtractor does, and a build
# without it fails at model load with "requires the librosa library" - see the
# model-load check in scripts/build_release.sh, which exists because that was
# shipped once. librosa pulls in numba/llvmlite/scikit-learn, which is why this
# list stays short.
excludes = [
    "matplotlib",
    "IPython",
    "jupyter",
    "notebook",
    "pytest",
    "pandas",
    "pyarrow",
    "torchvision",
    "torchaudio",
    "tensorboard",
    "sphinx",
    "setuptools._distutils",
]

# "Slim" bundle: drop torch as well. The Nemotron profiles need it (they run
# through transformers, and their feature extractor needs librosa); the
# faster-whisper engine does not - it uses CTranslate2, which is CUDA-capable on
# its own. Saves several hundred MB for users who only want a Whisper
# checkpoint. The slim build must ship defaults-slim/, or the app starts with
# profiles it cannot load.
SLIM = os.environ.get("WHISPER_DICTATE_SLIM") == "1"
if SLIM:
    excludes += [
        "torch",
        "transformers",
        "safetensors",
        "sympy",
        "librosa",
        "numba",
        "llvmlite",
        "sklearn",
        "scikit_learn",
    ]
    if not os.path.isdir(os.path.join(PACKAGING, "defaults-slim")):
        raise SystemExit(
            "[spec] WHISPER_DICTATE_SLIM=1 needs packaging/defaults-slim/ "
            "with faster-whisper profiles"
        )
    datas = [(os.path.join(PACKAGING, "defaults-slim"), "defaults")]
    print("[spec] SLIM build: torch/transformers excluded, faster-whisper defaults")

block_cipher = None

a = Analysis(
    [os.path.join(BASE_DIR, "launcher.py")],
    pathex=[BASE_DIR],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Whisper Dictate",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,  # signed by scripts/build_release.sh, in the right order
    entitlements_file=None,
    icon=ICON if os.path.exists(ICON) else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="WhisperDictate",
)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="Whisper Dictate.app",
        icon=ICON if os.path.exists(ICON) else None,
        bundle_identifier="com.beckerhub.whisperdictate",
        version="1.1.0",
        info_plist={
            "CFBundleShortVersionString": "1.1.0",
            "CFBundleVersion": "1.1.0",
            "CFBundleDisplayName": "Whisper Dictate",
            "LSUIElement": True,
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "11.0",
            "NSMicrophoneUsageDescription": (
                "Whisper Dictate records the microphone only while a dictation "
                "hotkey is held and transcribes it locally on this Mac."
            ),
            "NSAppleEventsUsageDescription": (
                "Whisper Dictate pastes the transcription at the cursor with "
                "Cmd+V through System Events."
            ),
            "NSHumanReadableCopyright": "Local, offline dictation.",
        },
    )
