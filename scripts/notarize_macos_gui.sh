#!/bin/bash
# Whisper Dictate macOS release build + sign + notarize.
# Runs inside the GUI (Aqua) LaunchAgent session so the login keychain
# (Developer ID identity + notarytool profile "whisper-dictate") is reachable.
set -uo pipefail
export LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8

STEP() { echo "STEP-$1-DONE"; }
FAIL() { echo "JOB-FAILED: $1"; exit 1; }

cd ~/target || FAIL "no ~/target"

# --- clone the exact release tag ---------------------------------------------
rm -rf whisperdictate-rel
git clone --depth 1 --branch v1.0.2 https://github.com/rorshopping/whisper-dictate.git whisperdictate-rel 2>&1 | tail -1
cd whisperdictate-rel || FAIL "clone"
[ -f WhisperDictate.spec ] || FAIL "spec missing"
echo "STEP-clone-DONE"

# --- venv + dependencies -----------------------------------------------------
PY=/opt/homebrew/bin/python3
$PY -m venv .venv || FAIL "venv"
./.venv/bin/pip install --quiet --upgrade pip
./.venv/bin/pip install --quiet faster-whisper sounddevice numpy pystray pynput pyperclip Pillow torch transformers librosa rapidfuzz "pyinstaller>=6.16" || FAIL "pip"
./.venv/bin/python -c "import torch, PyInstaller" || FAIL "imports"
echo "STEP-deps-DONE"

# --- freeze -------------------------------------------------------------------
rm -rf dist build
./.venv/bin/pyinstaller --noconfirm --clean WhisperDictate.spec 2>&1 | tail -3
APP=dist/WhisperDictate.app
[ -d "$APP" ] || FAIL "app bundle missing"
echo "STEP-build-DONE"

# --- entitlements (from the verified 1.1.0 packaging) -------------------------
cat > /tmp/wd_entitlements.plist << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>com.apple.security.device.audio-input</key>
    <true/>
    <key>com.apple.security.automation.apple-events</key>
    <true/>
    <key>com.apple.security.cs.allow-jit</key>
    <true/>
    <key>com.apple.security.cs.allow-unsigned-executable-memory</key>
    <true/>
</dict>
</plist>
EOF
echo "STEP-entitlements-DONE"

# --- strip dead symbols (must precede signing) --------------------------------
find "$APP/Contents" -type f \( -name "*.so" -o -name "*.dylib" \) -print0 |
    xargs -0 -n1 -P4 strip -x 2>/dev/null || true
echo "stripped: $(du -sh "$APP" | awk '{print $1}')"
echo "STEP-strip-DONE"

# --- sign: every Mach-O, inside out, bundle last -------------------------------
DEV_ID="Developer ID Application: Richard Otto Raoul Bäcker (AGYVQ59A5S)"
while IFS= read -r -d '' file; do
    if file -b "$file" | grep -q 'Mach-O'; then
        codesign --force --timestamp --options runtime \
            --entitlements /tmp/wd_entitlements.plist --sign "$DEV_ID" "$file" || FAIL "sign $file"
    fi
done < <(find "$APP/Contents" -depth -type f -print0)
while IFS= read -r -d '' file; do
    codesign --force --timestamp --options runtime \
        --entitlements /tmp/wd_entitlements.plist --sign "$DEV_ID" "$file" || FAIL "sign $file"
done < <(find "$APP/Contents" -depth -type d \( -name '*.framework' -o -name '*.app' -o -name '*.xpc' \) -print0)
codesign --force --timestamp --options runtime \
    --entitlements /tmp/wd_entitlements.plist \
    --identifier "com.beckerhub.whisperdictate" --sign "$DEV_ID" "$APP" || FAIL "sign bundle"
codesign --verify --deep --strict "$APP" || FAIL "signature invalid"
echo "STEP-sign-DONE"

# --- notarize + staple ----------------------------------------------------------
# notarytool requires a zip; the ASC API key avoids any keychain dependency.
ISSUER=$(/usr/bin/python3 -c "import json;print(json.load(open('$HOME/.secrets/asc_key.json'))['issuer_id'])")
KEYPATH=$HOME/.appstoreconnect/private_keys/AuthKey_BP3N265886.p8
UPLOAD=/tmp/wd_notarize_upload.zip
ditto -c -k --sequesterRsrc --keepParent "$APP" "$UPLOAD" || FAIL "zip for upload"
xcrun notarytool submit "$UPLOAD" \
    --key "$KEYPATH" --key-id BP3N265886 --issuer "$ISSUER" \
    --wait 2>&1 | tail -4 || FAIL "notarization"
xcrun stapler staple "$APP" || FAIL "staple"
echo "=== spctl verdict:"
spctl -a -vv -t exec "$APP" 2>&1 | head -2
xcrun stapler validate "$APP" || FAIL "staple validate"
echo "STEP-notarize-DONE"

# --- archive --------------------------------------------------------------------
ditto -c -k --sequesterRsrc --keepParent "$APP" ~/target/WhisperDictate-v1.0.2-macos-arm64-notarized.zip || FAIL "zip"
shasum -a 256 ~/target/WhisperDictate-v1.0.2-macos-arm64-notarized.zip
echo "STEP-zip-DONE"
echo "ALL-DONE"
