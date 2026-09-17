# Whisper Dictate 1.1.0 — macOS Apple Silicon

Standalone local push-to-talk dictation. This release includes Python and the
application dependencies; installing Python is not required. Model weights are
downloaded separately from Hugging Face and can occupy several gigabytes.

## Available download

`WhisperDictate-1.1.0-macos-arm64.zip` — Apple Silicon macOS.

Signed with Developer ID Application (team AGYVQ59A5S), notarized by Apple,
and stapled. Gatekeeper accepted both the built app and a fresh extraction of
this ZIP. SHA-256:

```
a84368d7dbca12d993dfba6a9b2616b5a494643d04789527fb7ea86a31f7e15e
```

Notarization submission: `a2f0efdf-bd77-4e3b-a91d-136c0b627647` (Accepted).

## Getting started

Unzip and move Whisper Dictate.app to Applications. Open it and grant microphone
and accessibility/input permissions when requested. Hold the configured hotkey,
speak, and release to transcribe. The default English hotkey is Ctrl+Shift+Space.
The tray menu provides settings and transcription history.

The first use requires an internet connection to download a model unless it is
already cached. CPU/MPS performance depends on the model and hardware.

## Included improvements

- Searchable local transcription history: copy, delete and export.
- Settings UI, per-profile hotkeys and language settings.
- Opt-in English/German spoken punctuation and whole-utterance voice snippets.
- Packaged defaults separated from per-user settings and history.
- Shared history locking to prevent concurrent deletion from losing a new entry.

## Verification and limitations

73 source tests passed. Frozen doctor passed 21/21 checks with bundled defaults
and a copied model cache; default English model preload passed on MPS. Embedded
history_store, enhanced_features and main code match the current source. Fresh
ZIP extraction passed signature, notarization, Gatekeeper and doctor checks.

These checks do not constitute a full fresh-account microphone-to-cursor test,
a privacy audit, or a compatibility guarantee for every application/macOS
version. German model availability was checked, but full German transcription
was not exercised in these release checks. Local history contains dictated text;
use the history window to delete entries you do not want to retain.

## Other platforms

Windows and Linux are not included in this public release. Windows signing is
unavailable; an earlier unsigned Windows preview and Linux X11 preview remain
internal and need rebuilding with the latest history fix. Linux VM checks cannot
verify physical microphone capture or real-desktop tray/paste behavior.

The application source repository is currently private. No subscription or
account is required by the desktop app.
