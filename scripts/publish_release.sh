#!/usr/bin/env bash
# Stage artifacts in a draft prerelease only. Never publish or replace assets.
#   TAG=v1.1.0-preview.1 scripts/publish_release.sh "dist/my preview.zip"
# Signing and clean-machine validation are separate release gates; uploading is
# not evidence of trust. Do not promote a draft while this script is running.
set -euo pipefail

RELEASES_REPO="rorshopping/whisper-dictate-releases"
TAG="${TAG:-v1.1.0}"

if [ "$#" -lt 1 ]; then
    echo 'usage: publish_release.sh <artifact> [artifact ...] (draft-only)' >&2
    exit 2
fi
if [[ ! "$TAG" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]]; then
    echo "invalid release tag: $TAG" >&2
    exit 2
fi

# Arrays preserve spaces in artifact and checksum paths.
uploads=()
for file in "$@"; do
    if [ ! -f "$file" ] || [ ! -r "$file" ]; then
        echo "missing or unreadable artifact: $file" >&2
        exit 2
    fi
    uploads+=("$file")
    if [ -f "$file.sha256" ]; then
        uploads+=("$file.sha256")
    fi
done

# Reject duplicate destination names before contacting GitHub.
python3 - "${uploads[@]}" <<'PY'
import os
import sys
names = [os.path.basename(path) for path in sys.argv[1:]]
if len(names) != len(set(names)):
    sys.exit("duplicate upload filenames; no assets uploaded")
PY

gh auth status >/dev/null
TOKEN="$(gh auth token)"
[ -n "$TOKEN" ] || { echo 'empty GitHub token' >&2; exit 3; }
work="$(mktemp -d "${TMPDIR:-/tmp}/whisper-release.XXXXXX")"
trap 'rm -rf "$work"' EXIT

# A successful, fully paginated list distinguishes absence from auth/network
# failures. Never interpret a failed API request as permission to create.
gh api --paginate --slurp "repos/$RELEASES_REPO/releases" > "$work/releases.json"
RELEASE_ID="$(python3 - "$work/releases.json" "$TAG" <<'PY'
import json
import sys
with open(sys.argv[1]) as stream:
    releases = [release for page in json.load(stream) for release in page]
matches = [release for release in releases if release.get("tag_name") == sys.argv[2]]
if len(matches) > 1:
    sys.exit("ambiguous release tag; refusing upload")
if matches:
    release = matches[0]
    if release.get("draft") is not True:
        sys.exit("refusing to modify an existing public release (including prereleases)")
    release_id = release.get("id")
    if type(release_id) is not int or release_id <= 0:
        sys.exit("invalid release ID")
    print(release_id)
PY
)"

if [ -z "$RELEASE_ID" ]; then
    NOTES_FILE="$(dirname "$0")/../docs/RELEASE_NOTES_${TAG#v}.md"
    notes=(--notes 'Untrusted preview staged for review. Not approved for public distribution.')
    if [ -f "$NOTES_FILE" ]; then
        notes=(--notes-file "$NOTES_FILE")
    fi
    gh release create "$TAG" --repo "$RELEASES_REPO" --draft --prerelease \
        --title "Whisper Dictate ${TAG#v} — preview (not release-ready)" "${notes[@]}"
    RELEASE_ID="$(gh api "repos/$RELEASES_REPO/releases/tags/$TAG" --jq .id)"
    [[ "$RELEASE_ID" =~ ^[1-9][0-9]*$ ]] || { echo 'invalid release ID' >&2; exit 3; }
fi

check_draft_and_names() {
    gh api "repos/$RELEASES_REPO/releases/$RELEASE_ID" > "$work/release.json"
    # Paginate assets too: the embedded release asset list may be incomplete.
    gh api --paginate --slurp "repos/$RELEASES_REPO/releases/$RELEASE_ID/assets" > "$work/assets.json"
    python3 - "$work/release.json" "$work/assets.json" "$TAG" "$@" <<'PY'
import json
import os
import sys
with open(sys.argv[1]) as stream:
    release = json.load(stream)
if release.get("draft") is not True or release.get("tag_name") != sys.argv[3]:
    sys.exit("release is not the expected draft; refusing upload")
with open(sys.argv[2]) as stream:
    names = {asset["name"] for page in json.load(stream) for asset in page}
collisions = names.intersection(os.path.basename(path) for path in sys.argv[4:])
if collisions:
    sys.exit("existing assets will not be replaced: " + ", ".join(sorted(collisions)))
PY
}

# Preflight the whole batch, then recheck before each upload. GitHub rejects
# concurrent same-name uploads; we never delete assets or use --clobber.
check_draft_and_names "${uploads[@]}"
for target in "${uploads[@]}"; do
    check_draft_and_names "$target"
    target_name="$(basename "$target")"
    encoded_name="$(python3 -c 'import sys, urllib.parse; print(urllib.parse.quote(sys.argv[1], safe=""))' "$target_name")"
    echo "==> Staging $target_name in draft $TAG"
    code="$(curl --fail --silent --show-error --connect-timeout 30 --max-time 1800 \
        -X POST -H "Authorization: token $TOKEN" \
        -H 'Content-Type: application/octet-stream' \
        --data-binary "@$target" \
        "https://uploads.github.com/repos/$RELEASES_REPO/releases/$RELEASE_ID/assets?name=$encoded_name" \
        -o "$work/upload.json" -w '%{http_code}')"
    if [ "$code" != '201' ]; then
        echo "upload did not return HTTP 201 (got $code); stopping" >&2
        exit 4
    fi
done

echo "Staged $TAG as a draft in $RELEASES_REPO. Nothing was published."
echo 'Draft assets are not anonymous downloads. Trust and release approval remain outstanding.'
