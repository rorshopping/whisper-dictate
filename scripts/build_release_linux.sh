#!/usr/bin/env bash
# Build the standalone Linux bundle (X11 session).
#
#   scripts/build_release.sh                 # freeze only
#   scripts/build_release.sh --tar           # freeze + tar.gz + sha256
#   scripts/build_release.sh --appimage      # also build an AppImage (if appimagetool is present)
#
# Run this on the oldest distribution you intend to support: a frozen bundle
# links against the build machine's glibc, so a build made on Ubuntu 24.04 will
# not start on 22.04. CI (or a container) with the oldest supported base image
# is the reliable way to do this.
#
# Wayland: the app records with sounddevice/PortAudio (works through
# PipeWire/PulseAudio) and injects the paste with pynput, whose Linux backend is
# X11. On a Wayland session synthetic paste only works through XWayland, and
# global hotkeys are captured only for XWayland clients. Run the app in an X11
# session (or a session with XWayland) for full functionality; the README says
# so, and packaging/README-linux.md repeats it for the download page.
set -euo pipefail

BASE_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VENV_PY="$BASE_DIR/.venv/bin/python"
DIST_DIR="$BASE_DIR/dist"
SPEC="$BASE_DIR/packaging/whisper_dictate.spec"
OUT_DIR="$DIST_DIR/WhisperDictate"
VERSION="1.1.0"

OPT_TAR=0
OPT_APPIMAGE=0
for arg in "$@"; do
    case "$arg" in
        --tar) OPT_TAR=1 ;;
        --appimage) OPT_APPIMAGE=1; OPT_TAR=1 ;;
        *) echo "usage: build_release.sh [--tar] [--appimage]" >&2; exit 2 ;;
    esac
done

if [ "$(uname -s)" != "Linux" ]; then
    echo "This script builds the Linux bundle - run it on Linux." >&2
    exit 2
fi

if [ ! -x "$VENV_PY" ]; then
    echo "No virtualenv at $BASE_DIR/.venv - run: python3 install.py --platform linux" >&2
    exit 2
fi

# --- runtime dependencies the frozen bundle still needs on the host ----------
# These are dlopen'ed by PortAudio/X11/xkbcommon, so PyInstaller cannot bundle
# them; they must be listed for the user instead of silently failing at start.
echo "==> Checking host libraries"
MISSING=()
check_lib() {
    if ! ldconfig -p 2>/dev/null | grep -q "$1"; then MISSING+=("$2"); fi
}
check_lib "libportaudio" "libportaudio2 (microphone capture)"
check_lib "libX11" "libx11-6 (X11 session)"
check_lib "libxcb" "libxcb1"
check_lib "libxkbcommon" "libxkbcommon0 (keyboard layout)"
check_lib "libasound\|libpulse" "libasound2 or libpulse0 (audio backend)"
if [ "${#MISSING[@]}" -gt 0 ]; then
    printf '    missing: %s\n' "${MISSING[@]}"
    echo "    (the bundle will still build; these are runtime host libraries)"
fi

# On Linux, PyPI's default torch wheel bundles the whole CUDA runtime (~3 GB of
# nvidia-* packages) because that is what most Linux users want. Shipping it in
# a dictation app multiplies the download for nothing: the models are 0.6B
# parameters and load in about two seconds on a CPU. Report it instead of
# silently producing a multi-gigabyte artifact.
if "$VENV_PY" -c "import torch" 2>/dev/null; then
    "$VENV_PY" - <<'PY' || true
import os
import shutil
import sys

import torch

site = os.path.dirname(os.path.dirname(torch.__file__))
nvidia = os.path.join(site, "nvidia")
nvidia_mb = 0
if os.path.isdir(nvidia):
    total = 0
    for root, _dirs, files in os.walk(nvidia):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass
    nvidia_mb = total // (1024 * 1024)

cuda = bool(getattr(torch.version, "cuda", None))
if cuda or nvidia_mb > 500:
    print(
        "WARNING: this virtualenv has a CUDA build of torch "
        f"({torch.__version__}, CUDA {torch.version.cuda}"
        + (f", {nvidia_mb} MB of nvidia-* packages" if nvidia_mb else "")
        + ").",
        file=sys.stderr,
    )
    print(
        "         The bundle will carry several GB of GPU libraries. For a\n"
        "         downloadable artifact, install the CPU wheel first:\n"
        "\n"
        "             .venv/bin/pip uninstall -y torch\n"
        "             .venv/bin/pip install --index-url https://download.pytorch.org/whl/cpu torch\n"
        "\n"
        "         A user with an NVIDIA GPU can install the CUDA wheel afterwards;\n"
        "         the app reports the CPU fallback in its log rather than failing\n"
        "         (see docs/BUILD_MACHINES.md).",
        file=sys.stderr,
    )
PY
fi

if ! "$VENV_PY" -c "import PyInstaller" 2>/dev/null; then
    echo "==> Installing PyInstaller"
    "$VENV_PY" -m pip install --quiet "pyinstaller>=6.16"
fi

echo "==> Freezing the app (several minutes)"
rm -rf "$OUT_DIR" "$BASE_DIR/build/whisper-dictate"
"$VENV_PY" -m PyInstaller \
    --noconfirm --clean \
    --distpath "$DIST_DIR" \
    --workpath "$BASE_DIR/build/whisper-dictate" \
    "$SPEC"

if [ ! -x "$OUT_DIR/Whisper Dictate" ]; then
    echo "Build failed: no executable at $OUT_DIR/Whisper Dictate" >&2
    exit 1
fi

echo "==> Self-check"
"$OUT_DIR/Whisper Dictate" --doctor || echo "warning: doctor reported problems"

if [ "$OPT_TAR" = "1" ]; then
    ARCH="$(uname -m)"
    TARBALL="$DIST_DIR/WhisperDictate-$VERSION-linux-$ARCH.tar.gz"
    rm -f "$TARBALL"
    tar -C "$DIST_DIR" -czf "$TARBALL" WhisperDictate
    sha256sum "$TARBALL" | awk '{print $1}' > "$TARBALL.sha256"
    echo "==> $TARBALL"
    cat "$TARBALL.sha256"
fi

if [ "$OPT_APPIMAGE" = "1" ]; then
    if ! command -v appimagetool >/dev/null 2>&1; then
        echo "appimagetool not found; skipping the AppImage (the tarball is complete)." >&2
    else
        APPDIR="$BASE_DIR/build/WhisperDictate.AppDir"
        rm -rf "$APPDIR"
        mkdir -p "$APPDIR/usr/bin"
        cp -r "$OUT_DIR/." "$APPDIR/usr/bin/"
        cat > "$APPDIR/whisper-dictate.desktop" <<'DESKTOP'
[Desktop Entry]
Type=Application
Name=Whisper Dictate
Comment=Local, offline push-to-talk dictation
Exec=Whisper Dictate
Icon=whisper-dictate
Categories=Utility;Accessibility;
Terminal=false
DESKTOP
        cat > "$APPDIR/AppRun" <<'APPRUN'
#!/bin/bash
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/bin/Whisper Dictate" "$@"
APPRUN
        chmod +x "$APPDIR/AppRun"
        if [ -f "$BASE_DIR/icon.ico" ]; then
            "$VENV_PY" - "$BASE_DIR/icon.ico" "$APPDIR/whisper-dictate.png" <<'PY'
import sys
from PIL import Image
image = Image.open(sys.argv[1])
image.load()
image.resize((256, 256), Image.LANCZOS).save(sys.argv[2])
PY
        fi
        OUT_APPIMAGE="$DIST_DIR/WhisperDictate-$VERSION-x86_64.AppImage"
        ARCH=x86_64 appimagetool "$APPDIR" "$OUT_APPIMAGE"
        sha256sum "$OUT_APPIMAGE" | awk '{print $1}' > "$OUT_APPIMAGE.sha256"
        echo "==> $OUT_APPIMAGE"
    fi
fi

echo
echo "Built: $OUT_DIR"
echo "Note:  the tarball is the primary artifact for the site; an AppImage needs"
echo "       FUSE on the user's machine, a tarball never does."
