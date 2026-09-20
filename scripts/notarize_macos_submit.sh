#!/bin/bash
# Resume: the signed dist/WhisperDictate.app already exists - zip it,
# submit for notarization, staple, verify, produce the release archive.
set -uo pipefail
export LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8

FAIL() { echo "JOB-FAILED: $1"; exit 1; }

cd ~/target/whisperdictate-rel || FAIL "no build tree"
APP=dist/WhisperDictate.app
[ -d "$APP" ] || FAIL "app missing"

codesign --verify --deep --strict "$APP" || FAIL "signature invalid before submit"

UPLOAD=/tmp/wd_notarize_upload.zip
ditto -c -k --sequesterRsrc --keepParent "$APP" "$UPLOAD" || FAIL "zip for upload"

echo "SUBMITTING (notarytool, ASC API key BP3N265886)..."
ISSUER=$(/usr/bin/python3 -c "import json;print(json.load(open('$HOME/.secrets/asc_key.json'))['issuer_id'])")
KEYPATH=$HOME/.appstoreconnect/private_keys/AuthKey_BP3N265886.p8
xcrun notarytool submit "$UPLOAD" \
    --key "$KEYPATH" --key-id BP3N265886 --issuer "$ISSUER" \
    --wait 2>&1 | tail -4 || FAIL "notarization"

xcrun stapler staple "$APP" || FAIL "staple"
echo "=== spctl verdict:"
spctl -a -vv -t exec "$APP" 2>&1 | head -2
xcrun stapler validate "$APP" || FAIL "staple validate"

ditto -c -k --sequesterRsrc --keepParent "$APP" \
    ~/target/WhisperDictate-v1.0.1-macos-arm64-notarized.zip || FAIL "final zip"
shasum -a 256 ~/target/WhisperDictate-v1.0.1-macos-arm64-notarized.zip
echo "ALL-DONE"
