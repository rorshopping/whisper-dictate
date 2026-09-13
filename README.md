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
- NVIDIA CUDA acceleration (falls back to CPU automatically)
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
- Auto-starts with Windows (Startup shortcut)
- System tray icon with menu (hotkey reference, reload hotwords, unload
  models, quit)

## Requirements

- Python 3.12 (3.13+ may be too new for the CUDA bridge, ctranslate2)
- Windows (macOS compatible code paths included — see below)

## Setup (Windows)

```powershell
cd C:\Users\Richard\Documents\Projects\whisper-dictate
py -3.12 -m venv .venv
# GPU transcription for the English Nemotron engine (PyPI's torch is CPU-only):
.venv\Scripts\pip install torch --index-url https://download.pytorch.org/whl/cu126
.venv\Scripts\pip install -r requirements.txt
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

The app has non-Windows code paths (file lock instead of mutex, beep via
terminal bell, no taskbar/toolwindow attributes). To run on a Mac:

```bash
chmod +x run_mac.sh
./run_mac.sh
```

macOS notes:
- The first run downloads the models from Hugging Face (~2.4 GB for each of
  the English and German Nemotron models) — keep internet on for that one run.
- GPU: add your MPS/GPU compute settings in `config.json` (`device` /
  `compute_type`) — e.g. `"device": "cpu"` is the safest default on Apple
  Silicon without CUDA. The Nemotron engine currently runs on CUDA or CPU
  only (no MPS path), so on a Mac the English profile uses the CPU.
- The bottom-center overlay uses Tk, which works on macOS; the click-through
  flag is Windows-only, so the pill may intercept clicks on a Mac.
- Microphone + keyboard capture on macOS requires granting the terminal app
  **Microphone** and **Accessibility / Input Monitoring** permissions in
  System Settings → Privacy & Security.

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
- Language prompt: on the multilingual (DE) checkpoint the profile's
  `language` must be one the model supports (e.g. `de`, `de-DE`); an
  unsupported value fails with an error that lists the valid options.
- Nemotron import errors: install `transformers>=5.13`; for GPU transcription
  install torch from the CUDA index (see Setup), otherwise transcription still
  works but runs on the CPU.
- Offline: once models are downloaded, `"offline": true` (the default) skips
  the network check. Offline is only enforced when the models are already in
  the local cache, so first-time setup still downloads.
