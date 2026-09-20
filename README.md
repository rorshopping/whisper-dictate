# Whisper Dictate

Local, offline push-to-talk dictation for programming and AI terms. Press and
hold a hotkey, speak, release — the text is transcribed on your own machine
(with your own GPU) and pasted at the cursor.

Supports **two profiles** in one app:

| Profile | Hotkey | Engine | Model | Language |
|---------|--------|--------|-------|----------|
| EN      | Ctrl + Shift + Space | NVIDIA Nemotron (transformers) | `nvidia/nemotron-speech-streaming-en-0.6b` | English |
| DE      | Ctrl + Alt + Space   | NVIDIA Nemotron (transformers) | `nvidia/nemotron-3.5-asr-streaming-0.6b` (language prompt `de` → de-DE) | German |

The status indicator sits at the bottom-center of the screen and always shows
the current state and both hotkeys, so you never forget them.

## Features

- 100% local / offline — no audio ever leaves your machine
- NVIDIA CUDA acceleration on Windows, Apple GPU (MPS) on macOS — both fall
  back to the CPU automatically
- English: NVIDIA Nemotron Speech Streaming 0.6B — punctuation and
  capitalization are built in (no Whisper-style "sentences without casing")
- German: NVIDIA Nemotron 3.5 ASR Streaming 0.6B with an explicit `de-DE`
  language prompt (the multilingual model never auto-detects the language)
- Hotwords per language: customize `hotwords-en.txt` / `hotwords-de.txt`
  (faster-whisper profiles only — see "Nemotron models" below)
- Personal vocabulary stays personal: a gitignored `*.local.txt` file next to
  any corrections/hotword file (e.g. `corrections-en.local.txt`) is merged at
  runtime, so private terms work locally but never end up in a published repo
- **Paste last transcription**: if you forget to click into a text field before
  dictating, select the field afterwards and press `Ctrl+Shift+F12` (or use the
  tray menu "Paste last transcription") to insert the most recent recording
  there.
- **Wispr Flow–style auto-edits**: filler words ("um", "ähm") are removed,
  spoken punctuation and structure commands ("comma", "new line",
  "bullet point", …) become real formatting, and saying "scratch that"
  mid-dictation drops everything before it — see
  [Auto-edits and voice shortcuts](#auto-edits-and-voice-shortcuts). All
  deterministic string rewrites, fully offline, no model cost.
- **Voice shortcuts**: `snippets-en.txt` / `snippets-de.txt` map spoken
  triggers to full-text expansions (`my email => richard@example.com`), with a
  gitignored `*.local.txt` next to each for private snippets.
- **Voice commands (Command Mode)**: hold `Ctrl+Shift+F10`, say one command
  ("press enter", "select all", "undo that", …), release — the keystrokes run
  in the focused window instead of the words being typed. See
  [Voice commands](#voice-commands-command-mode).
- **Changeable keyboard shortcuts**: tray menu → "Hotkeys…" rebinds every
  shortcut (both dictate profiles, Command Mode, paste-last, scratch-that,
  history) live — click Change, press the new combination, Save. Conflicts
  are rejected and the bindings persist in `config.json`.
- Status pill that only appears while something is happening (loading /
  listening / transcribing / typing / error) and hides itself when idle —
  every hotkey is listed in the tray menu instead
- Auto-starts with Windows (Startup shortcut)
- System tray icon with menu (hotkey reference, reload hotwords, unload
  models, quit)

## Feedback sounds

Right-click the tray icon → **Sounds** for five quieter, sample-based choices.
**Message chime** replaces the old system beep as the default. Selecting a
sound previews it immediately and saves it to `config.json`; **Off** mutes all
cues, and **Preview selected sound** replays the completion cue.

Choices are ordered by **Freesound source-file downloads** (snapshot:
September 17, 2026), among our curated shortlist—not a global popularity chart:

1. Message chime — 3,639 downloads (**default**)
2. Message tone — 1,785
3. Soft high bell — 1,441
4. Soft double bell — 1,090
5. Soft low bell — 709

Each has distinct short start, stop, completion, and undo variants. Playback
is non-blocking and fully offline. All source samples are CC0; see
[`assets/sounds/SOURCES.md`](assets/sounds/SOURCES.md) for links, licensing,
ranking methodology and adaptations. A restart is needed after installing
this code update; subsequent menu changes take effect immediately.

Config keys: `sound` (boolean, default `true`) and `sound_theme` (default
`"message-chime"`; alternatives `"message-tone"`, `"high-bell"`,
`"double-bell"`, `"low-bell"`). Existing `sound: false` preferences are honored.

## Auto-edits and voice shortcuts

After each transcription — corrections, fuzzy hotwords, then smart formatting —
a deterministic post-processing pass (`smart_format.py`) runs, so the text you
get reads like something you wrote, not like something you said:

- **Filler removal**: standalone "um / uh / uhm / erm / hmm" (EN) and
  "äh / ähm / öh / öhm" (DE) tokens are dropped.
- **Spoken punctuation and structure**: whole-word commands become real
  formatting on every engine:

  | Say (EN) | Say (DE) | Result |
  |---|---|---|
  | comma / period / full stop | Komma | `,` / `.` |
  | question mark / exclamation mark, point | Fragezeichen / Ausrufezeichen | `?` / `!` |
  | colon / semicolon | Doppelpunkt / Semikolon | `:` / `;` |
  | open / close paren(thesis) | Klammer auf / Klammer zu | `(` / `)` |
  | new line | neue Zeile | line break |
  | new paragraph | neuer Absatz | blank line |
  | bullet point / new bullet | Aufzählungspunkt | a `•` item on its own line |

- **Backtrack (self-correction)**: saying "scratch that" / "strike that"
  (EN) or "vergiss das" / "vergiss es" (DE) inside a dictation drops
  everything dictated before it — restate and keep going. (The
  `Ctrl+Shift+F13` scratch hotkey complements this by undoing a
  transcription *after* it was typed.)
- **Sentence casing**: sentences, lines and bullets start capitalized;
  standalone "i" becomes "I" (EN). Words like "example.com", "3.5" or German
  "Punkt" are never touched.

Every pass is conservative (whole words only, no real words rewritten) and can
be switched in `config.json`: `smart_format`, `smart_fillers`,
`smart_spoken_punctuation`, `smart_capitalize` (all default `true`).

**Voice shortcuts** are separate `trigger => expansion` files
(`snippets-en.txt` / `snippets-de.txt`) applied before smart formatting: say
the trigger, the full expansion is typed instead. Personal snippets (emails,
addresses, boilerplate) belong in a gitignored `snippets-*.local.txt` next to
the tracked file — both are merged. Edit either file and use the tray menu
"Reload hotwords & snippets" — no restart needed.

## Voice commands (Command Mode)

Wispr Flow's Command Mode, fully offline: hold the command hotkey (default
`Ctrl+Shift+F10`, config `command_hotkey`), speak one phrase, release. The
transcript is matched exactly against the table below — no model, no cloud —
and the keystrokes run in whatever window is focused. It uses the engine of
your last dictation, so the German phrases work after dictating in German.

| Say (EN) | Say (DE) | Effect |
|---|---|---|
| press enter / press tab / press escape / press backspace | Enter/Tab/Escape drücken | taps the key |
| select all | alles auswählen, alles markieren | Ctrl+A |
| copy that / cut that / paste | kopieren / ausschneiden / einfügen | Ctrl+C / Ctrl+X / Ctrl+V |
| undo that / redo that | rückgängig / wiederholen | Ctrl+Z / Ctrl+Y |
| delete last word | letztes Wort löschen | Ctrl+Backspace |

Anything that matches no phrase is typed as normal dictation, so a misheard
command never loses the words. Config: `voice_commands` (default `true`) and
`command_hotkey` (default `["ctrl", "shift", "f10"]`; `[]` disables it).

## Requirements

- Python 3.12+ (3.12 recommended on Windows: 3.13+ may be too new for the CUDA
  bridge, ctranslate2)
- Windows or macOS — see the platform setup below

## Install

One installer covers both platforms:

```bash
python install.py                     # auto-detect this machine
python install.py --platform macos    # macOS setup
python install.py --platform windows  # Windows setup
python install.py --platform windows --cuda   # + CUDA torch build (nvidia GPU)
```

It creates `.venv`, installs `requirements.txt` (the CUDA math libraries are
Windows-only and are skipped automatically by the environment markers), and
finishes with the `--doctor` self-check. The platforms differ in exactly two
places: the optional CUDA torch build (Windows) and `platform_mac.py`, which
owns all macOS behaviour (see below).

## Setup (Windows)

```powershell
cd C:\Users\Richard\Documents\Projects\whisper-dictate
python install.py --platform windows --cuda
```

Run once to download the models (offline mode only kicks in once the models
are cached locally, so first run downloads automatically). Each Nemotron model
is ~2.4 GB and is fetched by the profile's first use:

```powershell
.venv\Scripts\python main.py
```

Then either run `run.bat` or use the existing Start Menu / Startup shortcuts.

Headless (no terminal window): the app always starts via `pythonw.exe`
(windowless) with `--headless`, which also hides the console if one exists
(e.g. launched from `cmd.exe`). `run.bat` starts it minimized; double-click
`run_hidden.vbs` for a start with zero console flash. All output goes to
`dictate.log` next to `main.py`, so closing any terminal never stops the app
— quit via the tray icon menu. Pass `--console` to keep a console for
debugging. The log is size-capped (~1 MB plus two rotated backups).

Self-check: run `.venv\Scripts\python main.py --doctor` for a pass/fail
summary of config parsing, dependencies, CUDA/microphone access, model cache
presence, hotkey conflicts, and the hotword/correction files. It starts no
listener, GUI, audio stream, or model load, and can run while the app is
dictating. Exit code is `1` when any check fails.

## Setup (macOS)

macOS runtime support lives in `platform_mac.py` ("a platform module"), so
platform-specific fixes stay separate from the shared `main.py`.
`launcher.py` wires it up: `prepare()` runs before main is imported (stale
lock recovery), `install()` afterwards (the patches). Shared feedback sounds
are handled by `sound_cues.py`, using `afplay` on macOS.
Always start through `run_mac.sh` / `launcher.py` — starting `main.py`
directly skips the macOS support.

```bash
./run_mac.sh
```

macOS notes:
- The first run downloads the models from Hugging Face (~2.4 GB for each of
  the English and German Nemotron models) — keep internet on for that one run.
- The installer (`python install.py --platform macos`) is used automatically
  on the first `./run_mac.sh`; re-run it any time to update dependencies.
- GPU: `"device": "auto"` uses the Apple GPU (MPS) via `platform_mac.py` and
  falls back to the CPU automatically if a model cannot be loaded there
  (a `device` set in `config.json` always wins — e.g. `"cpu"`).
- What `platform_mac.py` provides on top of upstream `main.py`:
  - Tk is created before pystray/AppKit (otherwise Tk crashes with
    `-[NSApplication macOSVersion]: unrecognized selector`).
  - Paste and backspaces run on the Tk main thread (`CGEventPost` from worker
    threads can segfault), and the text is pasted with Cmd+V via System Events
    after re-activating the app that was focused when dictation started.
  - A stale `.app.lock` from a force-quit is reclaimed on the next start.
  - The pill warns when Accessibility / Input Monitoring is not granted.
- The bottom-center overlay uses Tk, which works on macOS; the click-through
  flag is Windows-only, so the pill may intercept clicks on a Mac.
- Microphone + keyboard capture on macOS requires granting the terminal app
  **Microphone** and **Accessibility / Input Monitoring** permissions in
  System Settings → Privacy & Security. Pasting is done with a System Events
  keystroke, so the launcher also needs **Automation → System Events**
  (macOS asks for this on the first paste). Without it, dictation still works
  but the text cannot be inserted.

## Configuration

`config.json` is created/merged over the built-in defaults. The `profiles`
array defines each profile (hotkey, `engine`, model, language, hotwords file,
status labels). `engine` is `"faster-whisper"` (default) or `"nemotron"`; a
model id containing `/` implies `"nemotron"` automatically. Hotwords are one
term per line in the per-language text files and are passed to Whisper as
`hotwords` (vocabulary hints) — the Nemotron engines have no vocabulary biasing
and ignore them. On the multilingual Nemotron checkpoint the profile's
`language` doubles as the model's language prompt (`de` → `de-DE`), so
changing it changes what language the model is conditioned on. No
`initial_prompt` is sent: Whisper's prompt slot means
"already transcribed text", not instructions, and instruction-style prompts
made the model echo prompt words instead of transcribing.

- `beam_size` — beam search width for the final transcription. Default `5`.
- `paste_last_hotkey` — global hotkey to re-insert the most recent
  transcription into the currently focused field. Default `["ctrl", "shift",
  "f12"]`; set to `[]` to disable (the tray menu item still works).
- `history_hotkey` — global hotkey that opens the transcription history file
  (`transcription-history.jsonl`, one JSON record per transcription: timestamp,
  profile, language, model, duration, text). Default `["ctrl", "shift", "f11"]`;
  `history_enabled` (default `true`) turns the add-on off entirely.
- `scratch_hotkey` — global hotkey that erases the most recent dictation by
  sending backspaces for the exact number of typed characters. Default
  `["ctrl", "shift", "f13"]`; set to `[]` to disable.
- `fuzzy_hotwords` — after transcription, transcript tokens are fuzzy matched
  against the profile's `hotwords-*.txt` entries and close misses are
  rewritten to the canonical spelling ("pie coding agent" → "Pi coding
  agent"). This makes the hotword files effective on engines without
  vocabulary biasing (Nemotron). Default `true`; `fuzzy_hotword_min_score`
  tunes the strictness (0-100, default `85`; raise it to only accept very
  close matches). Uses rapidfuzz when installed, otherwise the stdlib's
  `difflib` — no extra dependency required. Every replacement is logged to
  `dictate.log`.
- `paste_button_linger` — seconds the on-screen "Paste last" button stays up
  after a transcription before it fades out (hovering it pauses the fade; the
  hotkey works regardless). Default `10`; the status pill itself is fully
  click-through and translucent, so it never blocks what's behind it.
- `pill_alpha` — status pill opacity, 0 (invisible) to 255 (solid).
  Default `150`.
- `error_visible_s` — seconds an error pill stays readable before the idle
  hide takes effect. Default `6`.
- `model_idle_unload_minutes` — minutes of inactivity after which loaded
  models are dropped from RAM/VRAM to keep idle usage low. The model starts
  reloading from the local cache the moment a dictation hotkey is pressed
  (while you keep speaking), so releasing the hotkey only has to decode the
  audio. Default `10`; set to `0` to keep models loaded forever. The tray menu
  also has an "Unload models now" item.
- `capture_latency_s` — size of the audio device's capture buffer, in seconds.
  The sounddevice default works out to only ~26 ms, which silently drops the
  first words of a dictation whenever the process stalls briefly (model
  reload, CPU waking from idle, a background scan). The default `1.0` gives
  the stream roughly a second of stall headroom at the cost of ~64 KB of RAM;
  audio captured during a stall is delivered in a catch-up burst and kept.
  Set to `0` to restore the sounddevice default. Overflow drops are always
  logged to `dictate.log`, and a recording that came out shorter than its
  hotkey hold logs a warning.

### Nemotron models

Both profiles transcribe with NVIDIA Nemotron streaming models through Hugging
Face Transformers (not faster-whisper), at the widest right context the
checkpoints support (1.12 s) for maximum offline accuracy:

- **EN** — [`nemotron-speech-streaming-en-0.6b`](https://huggingface.co/nvidia/nemotron-speech-streaming-en-0.6b):
  English-only, 600M parameters, trained on ~530k hours.
- **DE** — [`nemotron-3.5-asr-streaming-0.6b`](https://huggingface.co/nvidia/nemotron-3.5-asr-streaming-0.6b):
  multilingual (40 locales) conditioned on an explicit language prompt. The
  profile's `language` (`de`) is resolved to the German prompt ID (`de-DE`)
  and always passed to the model, so it never auto-detects the language. Other
  locales work the same way (`fr`, `it`, `es`, ... — full list on the model
  card).

Common notes:

- Requirements: `torch` (CUDA build for GPU) and `transformers>=5.13`.
- Each checkpoint is ~2.4 GB and is downloaded on first use (or by running the
  app once with internet on).
- `hotwords-*.txt` is not used by these engines; put deterministic fixes in
  `corrections-*.txt` instead (applied to every transcription).
- To go back to faster-whisper for a profile, set
  `"engine": "faster-whisper"` and a faster-whisper `"model"` (e.g. `small.en`
  for English, `large-v3-turbo` for German) in `config.json`.

## Troubleshooting

- Log file: `dictate.log` next to `main.py`.
- CUDA: `device`/`compute_type` `"auto"` picks CUDA+float16 when available,
  CPU+int8 otherwise (faster-whisper); the Nemotron engines run fp16 on CUDA
  and fp32 on CPU, and log a warning when they fall back to CPU.
- Apple GPU: on macOS `"auto"` means the Apple GPU (MPS) — `platform_mac.py`
  switches the device once torch reports MPS support and falls back to the
  CPU (logged in `dictate.log`) if a model cannot be loaded; set
  `"device": "cpu"` in `config.json` to opt out.
- Language prompt: on the multilingual (DE) checkpoint the profile's
  `language` must be one the model supports (e.g. `de`, `de-DE`); an
  unsupported value fails with an error that lists the valid options.
- Nemotron import errors: install `transformers>=5.13`; for GPU transcription
  install torch from the CUDA index (see Setup), otherwise transcription still
  works but runs on the CPU.
- Offline: once models are downloaded, `"offline": true` (the default) skips
  the network check. Offline is only enforced when the models are already in
  the local cache, so first-time setup still downloads.

## License, buying, and releases

- **Try it**: free 14-day trial — sign up inside the app with an email, no
  card needed.
- **License**: €40 per user per year, for all use, at
  [whisperdictate.vercel.app](https://whisperdictate.vercel.app). Includes
  ready-to-run Windows & macOS builds from
  [GitHub Releases](https://github.com/rorshopping/whisper-dictate/releases/latest),
  a year of updates, and a 14-day money-back guarantee. Payments are
  processed by Stripe (setup documented in [STRIPE.md](STRIPE.md)).
- **License terms**: [PolyForm Free Trial 1.0.0](LICENSE) — evaluation is
  free for up to 31 days; continued use requires the paid license for
  everyone except the copyright holder. Versions published before
  2026-09-20 were MIT. Third-party packages and model
  weights keep their own licenses, documented in
  [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md).
- **Packaged builds**: tag a `v*` release and GitHub Actions builds
  Windows/macOS bundles via `WhisperDictate.spec` (PyInstaller) and attaches
  them to a draft release. Locally:
  `pyinstaller --noconfirm --clean WhisperDictate.spec`.

Bugs and pull requests are welcome right here on GitHub.
