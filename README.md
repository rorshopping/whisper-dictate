# Whisper Dictate

Local, offline push-to-talk dictation for programming and AI terms. Press and
hold a hotkey, speak, release — the text is transcribed on your own machine
(with your own GPU) and pasted at the cursor.

Supports **two profiles** in one app:

| Profile | Hotkey | Model | Language |
|---------|--------|-------|----------|
| EN      | Ctrl + Shift + Space | `small.en` | English |
| DE      | Ctrl + Alt + Space   | `medium`   | German   |

The status indicator sits at the bottom-center of the screen and always shows
the current state and both hotkeys, so you never forget them.

## Features

- 100% local / offline — no audio ever leaves your machine
- NVIDIA CUDA acceleration (falls back to CPU automatically)
- Hotwords per language: customize `hotwords-en.txt` / `hotwords-de.txt`
- **Paste last transcription**: if you forget to click into a text field before
  dictating, select the field afterwards and press `Ctrl+Shift+F12` (or use the
  tray menu "Paste last transcription") to insert the most recent recording
  there.
- Subtle always-on status pill (listening / transcribing / typing / ready)
- Auto-starts with Windows (Startup shortcut)
- System tray icon with menu (reload hotwords, quit)

## Requirements

- Python 3.12 (3.13+ may be too new for the CUDA bridge, ctranslate2)
- Windows (macOS compatible code paths included — see below)

## Setup (Windows)

```powershell
cd C:\Users\Richard\Documents\Projects\whisper-dictate
py -3.12 -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

Run once to download the models (offline mode only kicks in once the models
are cached locally, so first run downloads automatically):

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
debugging.

## Setup (macOS)

The app has non-Windows code paths (file lock instead of mutex, beep via
terminal bell, no taskbar/toolwindow attributes). To run on a Mac:

```bash
chmod +x run_mac.sh
./run_mac.sh
```

macOS notes:
- The first run downloads the models (~460 MB for `small.en`, ~1.5 GB for
  `medium`) from Hugging Face — keep internet on for that one run.
- GPU: add your MPS/GPU compute settings in `config.json` (`device` /
  `compute_type`) — e.g. `"device": "cpu"` is the safest default on Apple
  Silicon without CUDA.
- The bottom-center overlay uses Tk, which works on macOS; the click-through
  flag is Windows-only, so the pill may intercept clicks on a Mac.
- Microphone + keyboard capture on macOS requires granting the terminal app
  **Microphone** and **Accessibility / Input Monitoring** permissions in
  System Settings → Privacy & Security.

## Configuration

`config.json` is created/merged over the built-in defaults. The `profiles`
array defines each profile (hotkey, model, language, hotwords file, status
labels). Hotwords are one term per line in the per-language text files and are
passed to Whisper as `hotwords` (vocabulary hints). No `initial_prompt` is
sent: Whisper's prompt slot means "already transcribed text", not
instructions, and instruction-style prompts made the model echo prompt words
instead of transcribing.

- `beam_size` — beam search width for the final transcription. Default `5`.
- `streaming_model` — preview model for the live pill text while recording,
  global default `tiny`. A profile can override it via `"streaming_model"` in
  the profile (the DE profile uses `large-v3-turbo`: tiny/base are far too
  weak for German). Setting it to the profile's own `model` reuses that
  instance instead of loading a second one.
- `paste_last_hotkey` — global hotkey to re-insert the most recent
  transcription into the currently focused field. Default `["ctrl", "shift",
  "f12"]`; set to `[]` to disable (the tray menu item still works).
- `paste_button_linger` — seconds the on-screen "Paste last" button stays up
  after a transcription before it fades out (hovering it pauses the fade; the
  hotkey works regardless). Default `10`; the status pill itself is fully
  click-through and translucent, so it never blocks what's behind it.
- `pill_alpha` — status pill opacity, 0 (invisible) to 255 (solid).
  Default `150`.
- `model_idle_unload_minutes` — minutes of inactivity after which loaded
  Whisper models are dropped from RAM to keep idle usage low (a few seconds
  later, the next dictation reloads the model from the local cache). Default
  `10`; set to `0` to keep models loaded forever. The tray menu also has an
  "Unload models now" item.

### German models

The DE profile transcribes with `medium` (best punctuation/accuracy/speed
balance on an 8 GB GPU in benchmarks) and previews live with
`large-v3-turbo` (near-perfect German, ~3x faster than medium). To try a
different model, set `"model"` in the DE profile: `large-v3` scores similar
to `medium` but decodes ~2x slower; `large-v3-turbo` decodes fastest but can
drop sentence periods when given long hotword lists. The first run downloads
the model automatically (~1.6 GB for turbo).

## Troubleshooting

- Log file: `dictate.log` next to `main.py`.
- CUDA: `device`/`compute_type` `"auto"` picks CUDA+float16 when available,
  CPU+int8 otherwise.
- Offline: once models are downloaded, `"offline": true` (the default) skips
  the network check. Offline is only enforced when the models are already in
  the local cache, so first-time setup still downloads.
