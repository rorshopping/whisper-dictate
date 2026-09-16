#!/usr/bin/env bash
# Publish a built artifact to the public releases repo.
#
#   scripts/publish_release.sh dist/WhisperDictate-1.1.0-macos-arm64.zip [more.zip ...]
#
# Why this is not a GitHub workflow: the builds are signed on the machine that
# owns the certificate, and one of the three platforms is a Windows box reached
# over SSH. A workflow would have to hold the macOS Developer ID key and the
# Windows certificate as repository secrets, and neither certificate exists yet.
#
# The artifacts go to a dedicated PUBLIC repo because the source repo is private:
# an anonymous visitor to /whisper-dictate must not hit a GitHub 404 when they
# click Download.
set -euo pipefail

RELEASES_REPO="rorshopping/whisper-dictate-releases"
TAG="${TAG:-v1.1.0}"

if [ "$#" -lt 1 ]; then
    echo "usage: publish_release.sh <artifact> [artifact ...]" >&2
    echo "       TAG=v1.2.0 publish_release.sh ...   # to publish a new version" >&2
    exit 2
fi

for file in "$@"; do
    if [ ! -f "$file" ]; then
        echo "missing artifact: $file" >&2
        exit 2
    fi
done

echo "==> Checking gh auth"
if ! gh auth status >/dev/null 2>&1; then
    echo "gh is not authenticated; run: gh auth login" >&2
    exit 3
fi

echo "==> Ensuring the $TAG release exists in $RELEASES_REPO"
if gh release view "$TAG" --repo "$RELEASES_REPO" >/dev/null 2>&1; then
    echo "    release exists"
else
    NOTES_FILE="$(dirname "$0")/../docs/RELEASE_NOTES_${TAG#v}.md"
    if [ -f "$NOTES_FILE" ]; then
        gh release create "$TAG" --repo "$RELEASES_REPO" --title "Whisper Dictate ${TAG#v}" --notes-file "$NOTES_FILE"
    else
        gh release create "$TAG" --repo "$RELEASES_REPO" --title "Whisper Dictate ${TAG#v}" --notes "See the release notes in the repository."
    fi
fi

# curl, not `gh release upload`: gh has been unreliable with large assets and
# re-uploads (documented in the sibling project's AGENTS.md).
TOKEN="$(gh auth token)"
RELEASE_ID="$(gh api "repos/$RELEASES_REPO/releases/tags/$TAG" --jq .id)"
echo "==> Release id: $RELEASE_ID"

for file in "$@"; do
    name="$(basename "$file")"
    sha_file="$file.sha256"
    upload_list="$file"
    if [ -f "$sha_file" ]; then
        upload_list="$file $sha_file"
    fi
    for target in $upload_list; do
        target_name="$(basename "$target")"
        echo "==> Uploading $target_name"
        # Delete an existing asset of the same name so a re-upload replaces it
        # instead of creating "name-1".
        existing="$(gh api "repos/$RELEASES_REPO/releases/$RELEASE_ID/assets" \
            --jq ".[] | select(.name==\"$target_name\") | .id" 2>/dev/null || true)"
        if [ -n "$existing" ]; then
            gh api -X DELETE "repos/$RELEASES_REPO/releases/assets/$existing" >/dev/null
        fi
        curl -sS -X POST \
            -H "Authorization: token $TOKEN" \
            -H "Content-Type: application/octet-stream" \
            --data-binary "@$target" \
            "https://uploads.github.com/repos/$RELEASES_REPO/releases/$RELEASE_ID/assets?name=$(python3 -c "import urllib.parse,sys;print(urllib.parse.quote(sys.argv[1]))" "$target_name")" \
            -o /dev/null -w "    HTTP %{http_code}\n"
    done
done

echo "==> Verifying anonymous download (a private repo would 404 here)"
URL="$(gh api "repos/$RELEASES_REPO/releases/tags/$TAG" --jq '.assets[0].browser_download_url' 2>/dev/null || true)"
if [ -n "$URL" ]; then
    code="$(curl -s -o /dev/null -w "%{http_code}" -I "$URL")"
    echo "    $code  $URL"
    if [ "$code" != "200" ]; then
        echo "ERROR: the asset is not publicly downloadable ($code)." >&2
        exit 4
    fi
fi

echo
echo "Published $TAG to https://github.com/$RELEASES_REPO/releases/tag/$TAG"
echo "The website reads this repo directly (src/lib/whisperReleases.ts)."
