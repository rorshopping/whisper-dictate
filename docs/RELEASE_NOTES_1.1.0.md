# Whisper Dictate 1.1.0 — macOS, Windows and Linux

Standalone local push-to-talk dictation for Apple Silicon macOS (signed and
notarized) plus unsigned Windows and Linux builds. Bundles include Python and
dependencies; models download separately from Hugging Face.

## macOS download

`WhisperDictate-1.1.0-macos-arm64.zip` — Apple Silicon macOS.
Developer ID signed, notarized and stapled; Gatekeeper accepted a fresh ZIP
extraction. SHA-256:

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

## Windows and Linux (unsigned)

Unsigned builds are also published in this release for users who accept the
missing signature. Windows: SmartScreen warns on first launch. Linux: requires
an X11 session; some distributions need `libportaudio2` and a PulseAudio or
ALSA backend.

- `WhisperDictate-1.1.0-win64-unsigned.zip` (SHA-256
  `53f2e1933081ef378f1aae0845620411dd4668e049f9fc13a2a548dae8c09d40`): built on
  Windows with CPU-only torch, Authenticode status NotSigned. Fresh-extracted
  doctor 21/21, both Nemotron models loaded from cache on CPU, frozen GUI and
  tray windows created, 69 native tests passed, embedded modules matched source.
- `WhisperDictate-1.1.0-linux-x86_64-unsigned.tar.gz` (SHA-256
  `7c91c6fe12a2a34f1ea96488a96f0b78a41fd39c74775ec3dac250777fc68dbb`): built on
  Debian 12 with CPU-only torch. Fresh-extraction doctor 21/21 (22/22 with an
  explicit virtual device), both models loaded offline, and an English
  synthetic-speech run was captured, transcribed and pasted end to end.

Each artifact has a `-unsigned-validation.md` next to it with scope and limits.
These builds are not code-signed: SmartScreen/Gatekeeper equivalent warnings
are expected. Not verified: microphone speech on physical hardware, interactive
hotkeys in a real desktop session, or Windows paste-at-cursor. On Linux the
English synthetic dictation passed end-to-end; the German run loaded the model
and completed inference but produced no output, so **German transcription is
not verified on Linux**. Windows validation loaded the multilingual model,
but a successful German dictation was not demonstrated on any platform in
these checks.

The application source repository is currently private. No subscription or
account is required by the desktop app.
