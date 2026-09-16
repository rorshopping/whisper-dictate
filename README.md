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
- **Paste last transcription**: if you forget to click into a text field before
  dictating, select the field afterwards and press `Ctrl+Shift+F12` (or use the
  tray menu "Paste last transcription") to insert the most recent recording
  there.
- Status pill that only appears while something is happening (loading /
  listening / transcribing / typing / error) and hides itself when idle —
  every hotkey is listed in the tray menu instead
- **Transcription history window** (tray → "Transcription history…", or the
  history hotkey): search every past dictation, copy it, re-paste it at the
  cursor, delete single entries, export Markdown. Backed by the same JSONL file
  that is written next to the config.
- **Settings window** (tray → "Settings…"): edit the device, sound, capture
  buffer, model idle-unload, fuzzy-hotword and text-tool options and the
  per-profile name/hotkey/language, and open the hotword, correction and
  snippet files — without hand-editing `config.json`.
- **Spoken punctuation** (opt-in, `"spoken_punctuation": true`): say "comma",
  "period", "new line" — or "komma", "punkt", "neue zeile" — and get the
  character. Off by default because it rewrites ordinary words.
- **Voice snippets** (`snippets-<lang>.txt`): say a trigger on its own
  ("my signature") and a stored block is inserted verbatim. See the file for
  the `trigger => text` format; line breaks are written as `\n`.
- Auto-starts with Windows (Startup shortcut)
- System tray icon with menu (hotkey reference, reload hotwords, unload
  models, quit)
- **Standalone downloads** for Windows, macOS and Linux — no Python needed; see
  `docs/RELEASE.md` for how each platform is built and signed

## Requirements

- Python 3.12+ (3.12 recommended on Windows: 3.13+ may be too new for the CUDA
  bridge, ctranslate2) — only for running from source; the release builds are
  self-contained
- Windows, macOS or Linux — see the platform setup below (Linux needs an X11
  session; see `packaging/README-linux.md`)

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

All macOS behaviour lives in `platform_mac.py` ("a platform module"), so
upstream `main.py` stays untouched and macOS fixes never need to be re-applied
by hand after an update. `launcher.py` wires it up: `prepare()` runs before
main is imported (stale lock recovery), `install()` afterwards (the patches).
Always start through `run_mac.sh` / `launcher.py` — starting `main.py`
directly skips the macOS support.

```bash
./run_mac.sh
```

### Desktop app (.app bundle)

`./build_macos_app.sh --install` builds a signed `Whisper Dictate.app` and
copies it to `/Applications`. The bundle is a launcher for this checkout and
its `.venv` — the same entry point as `run_mac.sh` — so rebuilding it after
pulling changes (and re-running `install.py`) keeps the installed app current,
and the Microphone / Accessibility grants stick to the signed app identity.
Running from the bundle, macOS attributes those grants to the app itself, and
the Microphone and Automation usage strings macOS requires are part of it.

The app starts detached (the launcher exits right away). macOS 26 renders
status items as FrontBoard scenes, and a process launched by LaunchServices as
an app never has its scene granted - its menu-bar item stays parked off-screen.
A detached process is not part of that launch context, so the icon shows
whether the app is opened from Finder, the Dock or the shell. Starting it
twice is harmless: `main.py`'s single-instance guard makes the second start
exit. There is no Dock icon (the app is an agent / `LSUIElement` app): quit it
from its menu-bar menu, "Quit".

Start at login: `./build_macos_app.sh --login-item` writes a LaunchAgent
(`~/Library/LaunchAgents/com.beckerhub.whisperdictate.plist`) that opens the
installed app once per login - covered by the single-instance guard, so an app
that is already running is unaffected. There is no `KeepAlive`: quitting from
the menu bar stays quit until the next login.
`./build_macos_app.sh --remove-login-item` turns it off again. The LaunchAgent
logs to `~/Library/Logs/whisper-dictate-launch.log`; a log path inside
`~/Documents` would make launchd fail the job with exit code 78 (EX_CONFIG),
because that folder is TCC-protected and launchd opens the file before starting
the job.

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
- `history_hotkey` — global hotkey that opens the transcription history window
  (search, copy, re-paste at the cursor, delete, export Markdown). The data is
  `transcription-history.jsonl`, one JSON record per transcription: timestamp,
  profile, language, model, duration, text. Default `["ctrl", "shift", "f11"]`;
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
- `spoken_punctuation` — say "comma", "period", "new line", "question mark"
  (or "komma", "punkt", "neue zeile", "fragezeichen") and the real character is
  inserted, with the next word capitalized after a sentence mark. Off by
  default: it rewrites ordinary words, so enable it only if you do not dictate
  sentences that contain those words literally. English and German tables live
  in `text_tools.py`.
- `snippets_enabled` — whole-utterance voice snippets (default `true`). A
  trigger said on its own expands to a stored block, e.g. "my signature" →
  an address block. Define them in `snippets-<language>.txt`, one
  `trigger => text` rule per line; `\n` becomes a line break. Matching is
  exact (case-insensitive, optional trailing full stop), so a snippet can never
  fire in the middle of a sentence, and its content is inserted verbatim.

### Data folder

Runtime state (`config.json`, `dictate.log`, `.app.lock`,
`transcription-history.jsonl`, the hotword/correction/snippet files) lives next
to the sources when you run from a checkout, and in the per-user data folder in
a packaged build:

| Platform | Data folder |
|---|---|
| Windows | `%APPDATA%\Whisper Dictate` |
| macOS | `~/Library/Application Support/Whisper Dictate` |
| Linux | `~/.local/share/whisper-dictate` |

A packaged build seeds that folder from the bundled `defaults/` on first run and
never overwrites an existing file, so an upgrade keeps your config, hotwords,
corrections, snippets and history.

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
