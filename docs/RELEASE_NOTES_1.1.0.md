# Whisper Dictate 1.1.0

Local, offline push-to-talk dictation for Windows, macOS and Linux. Hold a
hotkey, speak, release — the transcription is typed at your cursor. No account,
no word limit, no audio leaving the machine.

## Downloads

| Platform | Artifact | Status |
|---|---|---|
| macOS (Apple Silicon) | `WhisperDictate-1.1.0-macos-arm64.zip` | unsigned preview |
| Windows (x64) | `WhisperDictate-1.1.0-win64-unsigned.zip` | unsigned preview |
| Linux (x86_64) | `WhisperDictate-1.1.0-linux-x86_64.tar.gz` | tarball |

**These previews are not code-signed.** macOS needs a right-click → Open on the
first launch, Windows shows SmartScreen's "More info → Run anyway". Signing
requires a Developer ID certificate (macOS) and a trusted Authenticode
certificate (Windows), neither of which is available yet — see
`docs/RELEASE.md`. The `.sha256` next to each artifact is the checksum of what
was uploaded.

## What is new in this release

**Standalone builds.** Every platform now ships a frozen bundle: the Python
interpreter and every dependency are inside the artifact, so there is no venv,
no `pip install`, and no Python requirement on the user's machine. Model weights
are still downloaded on first use (a few hundred MB per language profile) into
the normal Hugging Face cache; after that the app runs offline.

**A per-user data folder.** A packaged build keeps `config.json`, the log, the
lock file, the hotwords/corrections/snippets and the transcription history in
the platform's user data directory instead of next to the sources:

| Platform | Folder |
|---|---|
| Windows | `%APPDATA%\Whisper Dictate` |
| macOS | `~/Library/Application Support/Whisper Dictate` |
| Linux | `~/.local/share/whisper-dictate` |

It is seeded from the bundled defaults on first run and never overwritten, so
upgrading keeps your settings. Running from a checkout is unchanged — the files
stay in the repository.

**Transcription history window.** Tray → "Transcription history…" (or the
history hotkey) opens a searchable list of every dictation with copy,
re-paste-at-cursor, delete, clear, a Markdown export, and a header with your
totals. It replaces "open the JSONL file in a text editor".

**Settings window.** Tray → "Settings…" edits the device, sound, capture
buffer, model idle-unload, fuzzy-hotword and text-tool options plus each
profile's name, hotkey and language, and opens the hotword, correction and
snippet files. No more hand-editing JSON for everyday changes.

**Spoken punctuation** (opt-in, `"spoken_punctuation": true`). Say "comma",
"period", "new line", "question mark" — or the German "komma", "punkt", "neue
zeile", "fragezeichen" — and the real character is inserted, with the next word
capitalised after a sentence mark. Off by default because it rewrites ordinary
words. A command that would duplicate punctuation the model already emitted is
dropped, never doubled.

**Voice snippets** (`snippets-<language>.txt`, on by default). Say a trigger on
its own — "my signature" — and a stored block is typed verbatim, line breaks
included. Matching is whole-utterance and case-insensitive, so a snippet can
never fire in the middle of a sentence, and its content is inserted exactly as
written.

**Release tooling.** `scripts/build_release.sh` (macOS),
`scripts/build_release.ps1` (Windows) and `scripts/build_release_linux.sh`
(Linux) build each platform's artifact on that platform, with macOS signing
inside-out before notarization and Windows signing that refuses to label a
self-signed or unsigned build as a release. The macOS script verifies the frozen
app by actually loading a model, because a build that imports cleanly can still
fail at runtime (it did: `transformers` needs `librosa`, which no file in this
repository imports).

## Fixes

- **`--doctor` was ignored by `launcher.py`.** On macOS, `run_mac.sh` (and the
  `.app` bundle) started the full app even for one-shot flags, because the
  launcher always called `main.main()`. It now dispatches `--doctor` the same
  way `main.py` does.
- **`--doctor` output in a windowed build.** A frozen `.app` has no console, so
  the self-check now writes `doctor-report.txt` into the data folder instead of
  reporting into the void.
- **Fuzzy-hotword and text-tool stages ran in the wrong order.** Corrections,
  fuzzy hotwords, then snippets/spoken punctuation — so a snippet is never
  rewritten by the fuzzy pass.
- **Bundle size.** Stripping local symbols from the bundled Mach-O binaries
  removes ~107 MB (the app is 787 MB unpacked, from 894 MB) without touching
  behaviour; verified by loading a model from the frozen bundle afterwards.

## Known limitations

- **Windows and Linux artifacts are built on their own platforms.** There is no
  cross-compilation and no GitHub workflow by design; the Linux bundle must be
  built on the oldest distribution you intend to support, because it links the
  build machine's glibc.
- **Linux needs an X11 session.** Recording works under PipeWire or PulseAudio,
  but pasting and the global hotkeys use the X11 input API; on Wayland only the
  paste works, and only through XWayland.
- **macOS builds are Apple Silicon only** (`arm64`). An Intel build needs a
  build on an Intel Mac or a universal2 toolchain.
- The first dictation downloads the model; on a metered connection, copy the
  Hugging Face cache from another machine instead.
