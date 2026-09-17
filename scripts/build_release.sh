#!/usr/bin/env bash
# Build the standalone, self-contained macOS app bundle.
#
#   scripts/build_release.sh                  # ad-hoc preview, not for release
#   scripts/build_release.sh --sign           # signed preview, not for release
#   scripts/build_release.sh --sign --notarize --zip  # verified release archive
#   scripts/build_release.sh --zip            # explicitly named preview archive
#
# Difference to build_macos_app.sh: that script builds a *thin launcher* bundle
# that runs launcher.py from this checkout with the checkout's .venv - fine for
# the machine the checkout lives on, useless on any other Mac. This script
# freezes the interpreter, the app, and every dependency into the bundle, so the
# .app is a normal double-clickable download.
#
# Signing order that macOS actually requires: sign every nested binary first,
# then the bundle, and notarize after that. PyInstaller's --codesign-identity is
# deliberately NOT used - it signs before the bundle is assembled, which leaves
# dylibs whose signature does not match the final bundle.
set -euo pipefail

BASE_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VENV_PY="$BASE_DIR/.venv/bin/python"
APP="$BASE_DIR/dist/Whisper Dictate.app"
DIST_DIR="$BASE_DIR/dist"
ENTITLEMENTS="$BASE_DIR/packaging/entitlements.plist"
SPEC="$BASE_DIR/packaging/whisper_dictate.spec"
BUNDLE_ID="com.beckerhub.whisperdictate"
APPLE_TEAM="AGYVQ59A5S"

OPT_SIGN=0
OPT_NOTARIZE=0
OPT_ZIP=0
NOTARY_PROFILE="${NOTARY_PROFILE:-whisper-dictate}"

for arg in "$@"; do
    case "$arg" in
        --sign) OPT_SIGN=1 ;;
        --notarize) OPT_NOTARIZE=1; OPT_SIGN=1 ;;
        --zip) OPT_ZIP=1 ;;
        *) echo "usage: build_release.sh [--sign] [--notarize] [--zip]" >&2; exit 2 ;;
    esac
done

if [ "$(uname -s)" != "Darwin" ]; then
    echo "build_release.sh builds the macOS bundle - run it on macOS." >&2
    exit 2
fi

# Validate signing credentials before installing anything or replacing a build.
DEV_ID=""
if [ "$OPT_SIGN" = "1" ]; then
    for tool in security codesign; do
        command -v "$tool" >/dev/null || { echo "ERROR: missing $tool." >&2; exit 3; }
    done
    DEV_ID="$(security find-identity -v -p codesigning | \
        sed -nE "s/.*\"(Developer ID Application: .*\\($APPLE_TEAM\\))\".*/\\1/p" | \
        head -1)"
    if [ -z "$DEV_ID" ]; then
        echo "ERROR: no valid Developer ID Application identity for team $APPLE_TEAM." >&2
        echo "No build produced; signing credentials are required for --sign." >&2
        exit 3
    fi
fi
if [ "$OPT_NOTARIZE" = "1" ]; then
    command -v spctl >/dev/null || { echo "ERROR: missing spctl." >&2; exit 3; }
    xcrun --find notarytool >/dev/null
    xcrun --find stapler >/dev/null
    if ! xcrun notarytool history --keychain-profile "$NOTARY_PROFILE" >/dev/null; then
        echo "ERROR: notary profile '$NOTARY_PROFILE' is unavailable or invalid. No build produced." >&2
        exit 3
    fi
fi

if [ ! -x "$VENV_PY" ]; then
    echo "No virtualenv at $BASE_DIR/.venv - run: python3 install.py --platform macos" >&2
    exit 2
fi

if ! "$VENV_PY" -c "import PyInstaller" 2>/dev/null; then
    echo "PyInstaller is not installed in the venv; installing it now." >&2
    "$VENV_PY" -m pip install --quiet "pyinstaller>=6.16"
fi

# --- clean build --------------------------------------------------------------

echo "==> Freezing the app (this takes a few minutes)"
rm -rf "$DIST_DIR/Whisper Dictate.app" "$BASE_DIR/build/whisper-dictate"
"$VENV_PY" -m PyInstaller \
    --noconfirm \
    --clean \
    --distpath "$DIST_DIR" \
    --workpath "$BASE_DIR/build/whisper-dictate" \
    "$SPEC"

if [ ! -d "$APP" ]; then
    echo "Build failed: $APP was not produced." >&2
    exit 1
fi

# --- strip dead symbols -------------------------------------------------------
# torch's libtorch_cpu.dylib carries local (non-global) symbols nothing needs at
# runtime: stripping them removes ~58 MB from that one library and a little more
# from the rest. This must happen BEFORE signing, because strip invalidates a
# signature - the order below is strip, then sign, then notarize.

echo "==> Stripping local symbols from Mach-O binaries"
BEFORE_KB="$(du -sk "$APP" | awk '{print $1}')"
find "$APP/Contents" -type f \( -name "*.so" -o -name "*.dylib" \) -print0 |
    xargs -0 -n1 -P4 strip -x 2>/dev/null || true
# The executables themselves keep their symbols: the PyInstaller bootloader is
# small, and stripping it buys nothing while risking a broken signature chain.
AFTER_KB="$(du -sk "$APP" | awk '{print $1}')"
echo "    $(du -sh "$APP" | awk '{print $1}') (was $((BEFORE_KB / 1024)) MB)"

# --- signing ------------------------------------------------------------------
#
# Order is load-bearing: strip (above) invalidates any signature a nested binary
# already carried, so every Mach-O must be (re)signed *after* stripping, from
# the inside out, and the bundle last. codesign --deep is not a substitute: it
# does not repair nested binaries here, and macOS kills the app with
# "SIGKILL (Code Signature Invalid) / Invalid Page" when one is stale.

sign_nested() {
    local identity="$1"
    shift
    # Sign all Mach-O payloads (including extensionless framework binaries).
    # find -depth keeps nested payloads ahead of their containing bundle.
    local file
    while IFS= read -r -d '' file; do
        if file -b "$file" | grep -q 'Mach-O'; then
            codesign --force "$@" --sign "$identity" "$file" || return 1
        fi
    done < <(find "$APP/Contents" -depth -type f -print0)
    while IFS= read -r -d '' file; do
        codesign --force "$@" --sign "$identity" "$file" || return 1
    done < <(find "$APP/Contents" -depth -type d \( -name '*.framework' -o -name '*.app' -o -name '*.xpc' \) -print0)
}

verify_nested() {
    local bad=0
    while IFS= read -r -d '' file; do
        if ! codesign --verify --strict "$file"; then
            echo "    invalid signature: ${file#$APP/Contents/}" >&2
            bad=$((bad + 1))
        fi
    done < <(find "$APP/Contents" -type f \( -name "*.so" -o -name "*.dylib" \) -print0 2>/dev/null)
    if [ "$bad" != "0" ]; then
        echo "ERROR: $bad nested binaries still have an invalid signature." >&2
        echo "The app would be killed at launch with 'Code Signature Invalid'." >&2
        return 1
    fi
    return 0
}

if [ "$OPT_SIGN" = "1" ]; then
    echo "==> Signing with: $DEV_ID"
    sign_nested "$DEV_ID" --timestamp --options runtime --entitlements "$ENTITLEMENTS"
    codesign --force --timestamp --options runtime \
        --entitlements "$ENTITLEMENTS" \
        --identifier "$BUNDLE_ID" --sign "$DEV_ID" "$APP"
    verify_nested
    codesign --verify --deep --strict --verbose=2 "$APP"
    echo "==> Signature verified"
else
    echo "==> Ad-hoc signing (development build only - Gatekeeper will not trust it)"
    sign_nested "-"
    codesign --force --identifier "$BUNDLE_ID" --sign - "$APP"
    # The nested check is not cosmetic: an ad-hoc build with a stale nested
    # signature is killed on launch exactly like a broken Developer ID one.
    verify_nested || exit 6
    codesign --verify --deep --strict --verbose=2 "$APP"
    echo "==> Ad-hoc signature verified (nested binaries included)"
fi

# --- verify the payload without changing quarantine --------------------------

echo "==> Bundle contents"
du -sh "$APP"

# HOME and cwd are both isolated: app_paths can migrate config from cwd.
# Copy ONLY model cache payloads, never tokens or private app configuration.
# APFS clones share storage but not writes; ordinary copies are the fallback.
TEST_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/whisper-release.XXXXXX")"
TEST_HOME="$TEST_ROOT/home"
DOCTOR_PID=""
APP_PID=""
cleanup() {
    for pid in "$DOCTOR_PID" "$APP_PID"; do
        if [ -n "$pid" ]; then
            kill -9 "$pid" 2>/dev/null || true
            wait "$pid" 2>/dev/null || true
        fi
    done
    rm -rf "$TEST_ROOT"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
mkdir -p "$TEST_HOME/.cache/huggingface/hub" "$TEST_ROOT/tmp"
CACHE_SOURCE="${HF_HUB_CACHE:-${HUGGINGFACE_HUB_CACHE:-${HF_HOME:-$HOME/.cache/huggingface}/hub}}"
if [ -d "$CACHE_SOURCE" ]; then
    cp -cR "$CACHE_SOURCE/." "$TEST_HOME/.cache/huggingface/hub/" 2>/dev/null || \
        cp -R "$CACHE_SOURCE/." "$TEST_HOME/.cache/huggingface/hub/"
fi
run_isolated() (
    cd "$TEST_HOME"
    exec env -i HOME="$TEST_HOME" PATH="$PATH" \
        USER="${USER:-}" LOGNAME="${LOGNAME:-}" TMPDIR="$TEST_ROOT/tmp/" \
        XDG_CACHE_HOME="$TEST_HOME/.cache" XDG_CONFIG_HOME="$TEST_HOME/.config" \
        XDG_DATA_HOME="$TEST_HOME/.local/share" \
        HF_HOME="$TEST_HOME/.cache/huggingface" \
        HF_HUB_CACHE="$TEST_HOME/.cache/huggingface/hub" \
        HF_HUB_OFFLINE=1 HF_HUB_DISABLE_TELEMETRY=1 \
        "$APP/Contents/MacOS/Whisper Dictate" "$@"
)

echo "==> Self-check (isolated home, bundled defaults, offline model cache)"
DATA_DIR="$TEST_HOME/Library/Application Support/Whisper Dictate"
REPORT="$DATA_DIR/doctor-report.txt"
run_isolated --doctor >"$TEST_ROOT/doctor-console.log" 2>&1 &
DOCTOR_PID=$!
for _ in $(seq 1 180); do
    if ! kill -0 "$DOCTOR_PID" 2>/dev/null; then break; fi
    sleep 1
done
if kill -0 "$DOCTOR_PID" 2>/dev/null; then
    echo "ERROR: --doctor timed out after 180s." >&2
    exit 5
fi
DOCTOR_STATUS=0
wait "$DOCTOR_PID" || DOCTOR_STATUS=$?
DOCTOR_PID=""
if [ -f "$REPORT" ]; then cat "$REPORT"; fi
if [ "$DOCTOR_STATUS" != "0" ] || [ ! -s "$REPORT" ] || grep -q 'FAIL' "$REPORT"; then
    echo "ERROR: --doctor failed (exit $DOCTOR_STATUS), wrote no report, or reported FAIL." >&2
    cat "$TEST_ROOT/doctor-console.log" >&2
    exit 5
fi

# --- model load check ---------------------------------------------------------
# --doctor only *imports* modules, so it cannot catch a missing runtime
# dependency inside a lazily-imported library. It has already happened once:
# excluding librosa built cleanly and passed --doctor, then failed at model load
# with "NemotronAsrStreamingFeatureExtractor requires the librosa library".
# So: actually start the app, let it preload its default model, and fail the
# build if the log says the load broke.

echo "==> Model load check"
rm -f "$DATA_DIR/dictate.log"
run_isolated >"$TEST_ROOT/model-console.log" 2>&1 &
APP_PID=$!
LOADED=0
for _ in $(seq 1 90); do
    if [ -f "$DATA_DIR/dictate.log" ]; then
        if grep -qE "ready on|Model loaded" "$DATA_DIR/dictate.log"; then
            LOADED=1
            break
        fi
        if grep -qE "requires the librosa library|Preload of default model failed|Error" "$DATA_DIR/dictate.log"; then
            break
        fi
    fi
    kill -0 "$APP_PID" 2>/dev/null || break
    sleep 1
done
kill "$APP_PID" 2>/dev/null || true
wait "$APP_PID" 2>/dev/null || true
APP_PID=""

if [ "$LOADED" = "1" ]; then
    grep -E "ready on|MacOS GPU|MPS|Model loaded" "$DATA_DIR/dictate.log" | head -3 | sed 's/^/    /'
    echo "    model loaded"
else
    echo "ERROR: the frozen app did not load its model. Log:" >&2
    tail -12 "$DATA_DIR/dictate.log" 2>/dev/null | sed 's/^/    /' >&2
    echo "This build is broken - do not publish it." >&2
    exit 5
fi

# --- notarization -------------------------------------------------------------

if [ "$OPT_NOTARIZE" = "1" ]; then
    if [ -z "$DEV_ID" ]; then
        echo "ERROR: notarization needs a signed build." >&2
        exit 3
    fi
    ZIP_FOR_NOTARY="$DIST_DIR/notarize.zip"
    rm -f "$ZIP_FOR_NOTARY"
    ditto -c -k --keepParent "$APP" "$ZIP_FOR_NOTARY"
    echo "==> Submitting to Apple's notary service (profile: $NOTARY_PROFILE)"
    if ! xcrun notarytool submit "$ZIP_FOR_NOTARY" \
        --keychain-profile "$NOTARY_PROFILE" --wait; then
        cat >&2 <<MSG
ERROR: notarization failed. The profile "$NOTARY_PROFILE" must exist:
  xcrun notarytool store-credentials "$NOTARY_PROFILE" \\
      --apple-id <apple-id> --team-id $APPLE_TEAM --password <app-specific-password>
MSG
        exit 4
    fi
    xcrun stapler staple "$APP"
    xcrun stapler validate "$APP"
    codesign --verify --deep --strict --verbose=2 "$APP"
    spctl --assess --type execute --verbose=2 "$APP"
    rm -f "$ZIP_FOR_NOTARY"
    echo "==> Notarized and stapled"
fi

# --- zip for the download page ------------------------------------------------

if [ "$OPT_ZIP" = "1" ]; then
    VERSION="$("$VENV_PY" -c "print('1.1.0')")"
    SUFFIX=""
    if [ "$OPT_NOTARIZE" != "1" ]; then
        if [ "$OPT_SIGN" = "1" ]; then
            SUFFIX="-signed-preview"
        else
            SUFFIX="-unsigned-preview"
        fi
    fi
    OUT="$DIST_DIR/WhisperDictate-$VERSION-macos-arm64$SUFFIX.zip"
    rm -f "$OUT"
    ditto -c -k --keepParent "$APP" "$OUT"
    shasum -a 256 "$OUT" | awk '{print $1}' > "$OUT.sha256"
    echo "==> $OUT"
    cat "$OUT.sha256"
fi

echo
echo "Built: $APP"
if [ "$OPT_NOTARIZE" = "1" ]; then
    echo "Release gates passed: signed, notarized, stapled, Gatekeeper accepted."
else
    echo "PREVIEW ONLY: not notarized; not release-ready or approved for distribution."
fi
