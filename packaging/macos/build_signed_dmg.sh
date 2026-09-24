#!/usr/bin/env bash
# Whisper Dictate community macOS release template.
#
# This script does not choose a signing identity and contains no credentials.
# Before running it, provide:
#   * the Apple Silicon PyInstaller app at dist/WhisperDictate.app;
#   * an installed, explicit Developer ID Application identity via
#     DEVELOPER_ID_APPLICATION="Developer ID Application: ..." ;
#   * a preconfigured xcrun notarytool keychain profile via
#     NOTARYTOOL_PROFILE=<profile name>;
#   * VERSION=<release version>.
#
# The default artifact is a notarized, stapled .app zip.  Set FORMAT=dmg to
# create, sign, notarize, staple, and verify a disk image instead.  Neither
# mode downloads or embeds a speech model; models are acquired on first run.

set -euo pipefail
umask 022

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
REPO_ROOT="$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)"

APP_PATH="${APP_PATH:-$REPO_ROOT/dist/WhisperDictate.app}"
ENTITLEMENTS_PATH="${ENTITLEMENTS_PATH:-$SCRIPT_DIR/entitlements.plist}"
OUTPUT_DIR="${OUTPUT_DIR:-$REPO_ROOT/dist/packaging}"
VERSION="${VERSION:-}"
DEVELOPER_ID_APPLICATION="${DEVELOPER_ID_APPLICATION:-}"
NOTARYTOOL_PROFILE="${NOTARYTOOL_PROFILE:-}"
BUNDLE_ID="${BUNDLE_ID:-com.beckerhub.whisperdictate}"
FORMAT="${FORMAT:-zip}"

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || fail "required command not found: $1"
}

[[ -n "$VERSION" ]] || fail "set VERSION=<release version> (for example VERSION=1.2.3)"
[[ "$VERSION" =~ ^[0-9A-Za-z][0-9A-Za-z._-]*$ ]] || fail "VERSION contains unsafe path characters"
[[ -n "$DEVELOPER_ID_APPLICATION" ]] || \
  fail "set DEVELOPER_ID_APPLICATION explicitly; this template will not assume an identity"
case "$DEVELOPER_ID_APPLICATION" in
  "Developer ID Application:"*) ;;
  *) fail "DEVELOPER_ID_APPLICATION must be an installed Developer ID Application identity" ;;
esac
[[ -n "$NOTARYTOOL_PROFILE" ]] || \
  fail "set NOTARYTOOL_PROFILE to a preconfigured xcrun notarytool keychain profile"

case "$FORMAT" in
  zip|dmg) ;;
  *) fail "FORMAT must be zip or dmg" ;;
esac

for command_name in codesign ditto file find grep lipo security shasum sysctl uname xcrun; do
  require_command "$command_name"
done
if [[ "$FORMAT" == "dmg" ]]; then
  require_command hdiutil
fi
xcrun --find notarytool >/dev/null 2>&1 || fail "xcrun notarytool is required"
xcrun --find stapler >/dev/null 2>&1 || fail "xcrun stapler is required"
require_command spctl
if ! security find-identity -v -p codesigning | grep -F -- \
    "$DEVELOPER_ID_APPLICATION" >/dev/null; then
  fail "the requested Developer ID identity is not available in the current keychain"
fi

if [[ "$APP_PATH" != /* ]]; then
  APP_PATH="$REPO_ROOT/$APP_PATH"
fi
if [[ "$ENTITLEMENTS_PATH" != /* ]]; then
  ENTITLEMENTS_PATH="$REPO_ROOT/$ENTITLEMENTS_PATH"
fi
if [[ "$OUTPUT_DIR" != /* ]]; then
  OUTPUT_DIR="$REPO_ROOT/$OUTPUT_DIR"
fi

[[ -d "$APP_PATH" ]] || fail "PyInstaller app not found: $APP_PATH"
[[ -f "$ENTITLEMENTS_PATH" ]] || fail "entitlements file not found: $ENTITLEMENTS_PATH"
APP_EXECUTABLE="$APP_PATH/Contents/MacOS/WhisperDictate"
[[ -x "$APP_EXECUTABLE" ]] || fail "app executable not found: $APP_EXECUTABLE"

# The community artifact matrix is Apple Silicon only.  Refuse an accidental
# Intel build or an x86_64 host before signing anything.
HOST_ARCH="$(uname -m)"
[[ "$HOST_ARCH" == "arm64" ]] || fail "Apple Silicon (arm64) host required; found $HOST_ARCH"
if [[ "$(sysctl -n hw.optional.arm64 2>/dev/null || true)" != "1" ]]; then
  fail "this macOS host does not report hw.optional.arm64=1"
fi
APP_ARCHS="$(lipo -archs "$APP_EXECUTABLE" 2>/dev/null || true)"
[[ ",$APP_ARCHS," == *",arm64,"* ]] || \
  fail "app executable must contain arm64; found architectures: ${APP_ARCHS:-unknown}"

# A model cache or model weights are not valid release-payload contents.
MODEL_ARTIFACT="$(find "$APP_PATH" -type f \( \
  -iname '*.safetensors' -o -iname '*.gguf' -o -iname '*.ckpt' -o \
  -iname '*.onnx' -o -iname '*.pt' -o -iname '*.pth' -o -iname '*.bin' \
\) -print -quit)"
[[ -z "$MODEL_ARTIFACT" ]] || fail "model artifact found in app payload: $MODEL_ARTIFACT"
MODEL_DIRECTORY="$(find "$APP_PATH" -type d \( \
  -name 'models' -o -name 'models--*' -o -name 'huggingface' \
\) -print -quit)"
[[ -z "$MODEL_DIRECTORY" ]] || fail "model directory found in app payload: $MODEL_DIRECTORY"

mkdir -p "$OUTPUT_DIR"
OUTPUT_NAME="WhisperDictate-$VERSION-macos-arm64-notarized"
if [[ "$FORMAT" == "zip" ]]; then
  OUTPUT_PATH="$OUTPUT_DIR/$OUTPUT_NAME.zip"
else
  OUTPUT_PATH="$OUTPUT_DIR/$OUTPUT_NAME.dmg"
fi

sign_mach_o() {
  local target="$1"
  codesign --force --options runtime --timestamp \
    --entitlements "$ENTITLEMENTS_PATH" \
    --sign "$DEVELOPER_ID_APPLICATION" "$target"
}

sign_bundle() {
  local target="$1"
  codesign --force --options runtime --timestamp \
    --entitlements "$ENTITLEMENTS_PATH" \
    --identifier "$BUNDLE_ID" --sign "$DEVELOPER_ID_APPLICATION" "$target"
}

# Sign Mach-O files from the inside out, then nested bundles and the app.
while IFS= read -r -d '' target; do
  if file -b "$target" 2>/dev/null | grep -q 'Mach-O'; then
    sign_mach_o "$target"
  fi
done < <(find "$APP_PATH/Contents" -depth -type f -print0)
while IFS= read -r -d '' target; do
  case "$target" in
    *.app|*.framework|*.xpc)
      sign_bundle "$target"
      ;;
  esac
done < <(find "$APP_PATH/Contents" -depth -type d \( -name '*.app' -o -name '*.framework' -o -name '*.xpc' \) -print0)
sign_bundle "$APP_PATH"
codesign --verify --deep --strict --verbose=2 "$APP_PATH"

WORK_DIR="$(mktemp -d "${TMPDIR:-/tmp}/whisper-dictate-notary.XXXXXX")"
trap 'rm -rf "$WORK_DIR"' EXIT
UPLOAD_ZIP="$WORK_DIR/$OUTPUT_NAME-upload.zip"
ditto -c -k --sequesterRsrc --keepParent "$APP_PATH" "$UPLOAD_ZIP"

# The keychain profile is supplied out of band.  No Apple ID, team secret,
# private key, or password is read from this repository or embedded here.
xcrun notarytool submit "$UPLOAD_ZIP" \
  --keychain-profile "$NOTARYTOOL_PROFILE" --wait
xcrun stapler staple "$APP_PATH"
xcrun stapler validate "$APP_PATH"
spctl --assess --type execute --verbose=4 "$APP_PATH"

if [[ "$FORMAT" == "zip" ]]; then
  # Recreate the archive after stapling so the published bytes contain the
  # notarization ticket, not just the pre-notarization upload.
  ditto -c -k --sequesterRsrc --keepParent "$APP_PATH" "$OUTPUT_PATH"
else
  DMG_PATH="$WORK_DIR/$OUTPUT_NAME.dmg"
  hdiutil create -volname "Whisper Dictate" -srcfolder "$APP_PATH" \
    -ov -format UDZO "$DMG_PATH"
  codesign --force --timestamp --sign "$DEVELOPER_ID_APPLICATION" "$DMG_PATH"
  xcrun notarytool submit "$DMG_PATH" \
    --keychain-profile "$NOTARYTOOL_PROFILE" --wait
  xcrun stapler staple "$DMG_PATH"
  xcrun stapler validate "$DMG_PATH"
  hdiutil verify "$DMG_PATH"
  spctl --assess --type diskimage --verbose=4 "$DMG_PATH"
  cp "$DMG_PATH" "$OUTPUT_PATH"
fi

shasum -a 256 "$OUTPUT_PATH"
printf 'Created signed/notarized artifact: %s\n' "$OUTPUT_PATH"
