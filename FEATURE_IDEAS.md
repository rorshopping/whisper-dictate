# Feature Ideas

Whisper Dictate is a local, offline push-to-talk dictation tool for Windows (with partial macOS support): hold a hotkey, speak, release, and the recording is transcribed on your own GPU and pasted at the cursor. It runs two language profiles (EN/DE) on NVIDIA Nemotron streaming RNNT models via `transformers` (with faster-whisper as an alternative engine), shows a click-through Tk status pill, and supports per-language hotwords, deterministic `corrections-*.txt` fixes, `snippets-*.txt` voice shortcuts, Wispr-Flow-style smart formatting (`smart_format.py`), a "paste last transcription" hotkey, and JSONL transcription history. The codebase is intentionally small (`main.py` plus `nemotron_engine.py` and the small add-on modules `enhanced_features.py`, `hotword_fuzzy.py`, `smart_format.py`), configured entirely through `config.json`.

Ideas below build on what actually exists in the code today.

## Core Dictation Features

- **Scratch-that (undo last dictation)** — `Quick Win`
  A global hotkey (e.g. `Ctrl+Shift+F13`) that sends enough backspaces to erase the last typed transcription, tracked by storing the typed text length alongside `last_text`. Fixes the most common dictation mistake without touching the mouse.

- **Toggle and hands-free recording modes**
  Besides hold-to-talk, support a toggle mode (hotkey starts/stops) and a VAD-gated hands-free mode that stops on silence, reusing the energy gate already in `nemotron_engine._trim_silence` or Silero VAD from faster-whisper. Useful for long-form dictation where holding a key gets tiring.

- **More language profiles from the multilingual checkpoint**
  The DE profile already runs `nemotron-3.5-asr-streaming-0.6b` (40 locales) with an explicit language prompt, so adding FR/ES/IT profiles is mostly a `config.json` profiles entry plus handling more tray-menu/pill hotkey labels. Instant value for multilingual users at near-zero engineering cost.

## Accuracy and Post-Processing

- **Fuzzy hotword reconciliation for Nemotron**
  `hotwords-*.txt` is ignored by the Nemotron engines (no vocabulary biasing), so domain terms only work if manually added to `corrections-en.txt`. Add a post-transcription pass that fuzzy-matches transcript tokens against the hotword list (e.g. `rapidfuzz` token similarity) and swaps in the canonical spelling, making the existing hotword files effective on every engine.

- **Spoken punctuation and smart-formatting pass**
  Extend the `apply_corrections` layer with a formatting stage: map spoken "comma"/"period"/"new paragraph" to real punctuation, capitalize sentences, and format numbers/URLs — mainly for faster-whisper profiles that lack Nemotron's built-in punctuation and capitalization. Keeps dictation output copy-ready instead of requiring manual cleanup.

- **Correction miner from transcription history**
  `transcription-history.jsonl` already stores every result; add a tray-menu action that diffs history text against what the user typed afterwards (or surfaces frequent near-duplicate phrases like "backup performance" → "Becker-performant") and proposes new `corrections-*.txt` rules. Turns the manual correction-file chore into a guided workflow.

## UX Improvements

- **In-app history browser**
  Replace "open the JSONL in the default editor" (`enhanced_features.open_history`) with a small Tk window listing past transcriptions with search, copy, re-paste, and delete, backed by the same JSONL file. History is currently write-only; this makes it actually usable for recovering an earlier dictation.

- **Clipboard preservation and paste fallback** — `Quick Win`
  `type_text()` permanently overwrites the user's clipboard with the transcription; save and restore the previous clipboard after the Ctrl+V paste, and fall back to simulated keystrokes (`pynput` typewrite) for apps that reject synthetic paste. Low effort, removes a daily papercut.

- **Per-app dictation profiles** — `Big Bet`
  Use the existing Win32 foreground-window helpers (`_foreground_hwnd`) to detect the focused app and adapt behavior: no trailing newline in chat apps, identifier-safe casing (`snake_case`) in editors/terminals, plain prose in mail. Makes dictation feel native in every target instead of one-size-fits-all.

## Performance and Reliability

- **Live streaming preview on the Nemotron decoder** — `Big Bet`
  The old partial-preview (re-transcribing the growing buffer every ~1.25 s) was removed because it doubled VRAM use; the Nemotron checkpoints are cache-aware *streaming* RNNT models, so run them incrementally during recording and show partial text in the pill. Real-time feedback would let users stop and re-dictate early instead of waiting for a wrong final result.

- **`--doctor` self-check and log rotation** — `Quick Win`
  A startup flag that verifies CUDA availability, microphone access, model cache presence, and hotkey conflicts, printing a pass/fail summary; plus size-capped rotation for `dictate.log` (already ~1 MB after a week). Cuts troubleshooting time for the most common setup issues documented in the README.

- **Typing guard for overlapping transcriptions**
  A new recording can start and finish while the previous `transcribe_thread` is still typing, so the delayed Ctrl+V can land in the wrong place or interleave with the new recording. Queue or defer `type_text()` while `recording["active"]` is true, and serialize transcriptions in a single worker.

## Integrations and Automation

- **Voice command grammar for app control** — `Big Bet`
  A small phrase grammar ("open terminal", "press enter", "insert snippet X") recognized in the transcription pipeline before text is typed, executed via `pynput`/`os.startfile`. Turns the tool from pure dictation into a hands-free productivity layer, building on the correction-matching infrastructure that already rewrites phrases.

- **Local CLI/HTTP trigger interface**
  A tiny localhost HTTP endpoint or `--dictate-once` CLI mode so other tools (scripts, editors, stream decks) can trigger a dictation and receive the text. Reuses the whole capture/transcribe stack and opens the tool up to automation beyond global hotkeys.

## Technical Debt and Infrastructure

- **Unify the `enhanced_features` monkey-patch**
  `enhanced_features.py` duplicates `on_press`/`on_release`/`stop_recording`/`transcribe_thread` and swaps them at runtime via `install()`, so every transcription fix must be made twice. Introduce a small hook/event layer in `main.py` (post-transcribe, on-hotkey) and fold history in as a plain subscriber.

- **Packaged build and single-instance guard**
  Ship a PyInstaller-based Windows build (the README's venv + `run_hidden.vbs` dance is fragile across machines) and enforce single-instance via the existing mutex/file-lock path so launching `run.bat` twice can't create two keyboard listeners.

## Implemented

Implemented 2026-09-12 (restart the app to pick the changes up):

- **Fuzzy hotword reconciliation for Nemotron** — new `hotword_fuzzy.py`, wired into `main.transcribe_thread` via `_reconcile_hotwords()` (`main.py`), with the canonical spellings exposed as `Profile.hotword_list` and refreshed by the tray's "Reload hotwords". Tokens are fuzzy matched against `hotwords-*.txt` (single words, phrases, and split compounds like "daten bank") and rewritten to the canonical spelling. Uses `rapidfuzz` when installed, falls back to stdlib `difflib` (equivalent indel scoring), so no new dependency is required. Conservative guards: tokens < 4 chars or containing digits are never touched, exact hotword spellings are left alone, overlap resolution keeps the best match, and every replacement is logged. Config: `fuzzy_hotwords` (default on), `fuzzy_hotword_min_score` (default 85).
- **Unify the `enhanced_features` monkey-patch** — `main.py` now has a small hook layer (`add_key_press_listener` / `add_key_release_listener` / `add_text_listener`); press listeners return `True` to consume a key. `enhanced_features.py` shrank from a duplicated `on_press`/`on_release`/`stop_recording`/`transcribe_thread` set to a plain subscriber (`install()` swaps nothing), so transcription-flow fixes only exist in one place now. `launcher.py` unchanged.
- **Scratch-that (undo last dictation)** — `main.py`: `scratch_hotkey` config (default `Ctrl+Shift+F13`, disable with `[]`), `type_text()` records the exact typed string in `last_typed_text`, and `scratch_last()` sends that many backspaces (`_send_backspaces`, chunked with short sleeps). Same latch/reset semantics as the paste-last hotkey.
- **Clipboard preservation and paste fallback** — `main.type_text()` saves the previous clipboard, verifies the clipboard actually accepted the synthetic write, falls back to simulated keystrokes (`_type_keystrokes`) when the copy or the Ctrl+V fails, and restores the user's previous clipboard ~0.4 s after the paste — unless the user copied something newer in the meantime.
- **`--doctor` self-check and log rotation** — `python main.py --doctor` (`run_doctor()` in `main.py`) prints a pass/fail summary for config parsing, dependency imports (incl. torch/CUDA), microphone access and the configured device, per-profile model cache presence, hotkey conflicts across all global hotkeys, hotword/correction files, clipboard, and folder writability; exit code 1 on any FAIL. It bypasses the single-instance guard, starts no listener/GUI/audio stream/model load, and is safe to run while dictating. `dictate.log` is now size-capped (1 MB + 2 backups, `_RotatingLog`) with rollover that tolerates the file being locked by another process.

Implemented 2026-09-16:

- **macOS as a platform module** — new `platform_mac.py` owns every Darwin-specific piece, so `main.py` matches upstream again and macOS fixes no longer have to be re-applied by hand after an update: stale `.app.lock` recovery (`prepare()`, plus atexit), Tk-before-AppKit start-up order (pystray's `Icon.__init__` creates the shared `NSApplication`; if that happens first, Tk crashes with `-[NSApplication macOSVersion]: unrecognized selector` — the root is created in the wrapper and handed to every later `tk.Tk()` call), main-thread dispatch for paste and scratch-that (`CGEventPost` from worker threads can segfault), the Ctrl+V→Cmd+V swap inside `type_text` (a `pynput` Controller subclass re-activates the app that was focused when dictation started, tracked by a `start_recording` wrapper, then injects Cmd+V through System Events, raising so the existing keystroke fallback still works), the Accessibility / Input Monitoring warning in the pill, `"device": "auto"`→Apple GPU (MPS) with a logged CPU fallback, and per-patch failure logging so an upstream rename only disables that one patch. `launcher.py` calls `prepare()` before importing main and `install()` after; each patch is wrapped in `_apply()` and logged.
- **Platform-aware installer** — `install.py` with `--platform {auto,macos,windows}` (plus `--cuda` for the Windows CUDA torch build and `--no-doctor`): creates the venv, installs `requirements.txt` (CUDA libs are skipped on macOS by the existing environment markers), finishes with the `--doctor` self-check, and prints the platform's start command and permission notes. `run_mac.sh` uses it on first run, forwards `--doctor` to `main.py`, and always starts `launcher.py`.

Implemented 2026-09-20 (Wispr Flow parity pass; restart the app to pick the changes up):

- **Wispr-Flow-style smart formatting** — new `smart_format.py`, run in `transcribe_thread` via `_smart_format()` (`main.py`) after corrections and fuzzy hotwords. Four deterministic passes on the final text, EN and DE: filler-word removal ("um"/"uh"/"erm"/"hmm", "äh"/"ähm"/"öh"/"öhm" as standalone tokens), spoken punctuation and structure commands ("comma", "period", "question mark", "colon", "new line", "new paragraph", "open/close paren"; DE "Komma", "Fragezeichen", "neue Zeile", "neuer Absatz", "Klammer auf/zu"), list bullets ("bullet point"/"new bullet"/"Aufzählungspunkt" → a `•` item on its own line), and spacing tidy-up plus sentence/line/bullet capitalization with standalone-"i" fixing (EN). Whole-word matches only; real words like "example.com", "3.5" or German "Punkt" are never touched. This supersedes the old faster-whisper-only "spoken punctuation" idea — the commands now work on every engine, Nemotron included. Config: `smart_format`, `smart_fillers`, `smart_spoken_punctuation`, `smart_capitalize` (all default on).
- **Backtrack / in-speech self-correction** — part of the same pass: saying "scratch that"/"scratch this"/"strike that" (EN) or "vergiss das"/"vergiss es" (DE) inside a dictation drops everything dictated before it (last occurrence wins; the remainder is tidy-capped). Empty remainder types nothing. Complements the existing `Ctrl+Shift+F13` scratch hotkey, which undoes a transcription after typing.
- **Voice shortcuts (custom text snippets)** — `snippets-en.txt` / `snippets-de.txt` (starter files with commented examples) hold `trigger => expansion` pairs in the corrections file format, loaded per profile (`Profile.snippets`, `snippets_file` config key) and applied via `_expand_snippets()` after corrections, before smart formatting. Gitignored `snippets-*.local.txt` merged like every vocabulary file. Reloaded by the tray menu item, renamed to "Reload hotwords & snippets". `--doctor` reports per-profile snippet counts. Config: `voice_shortcuts` (default on).

Skipped (with reasons):

- **Live streaming preview** (`Big Bet`) — needs the actual Nemotron checkpoints and a GPU to validate incremental decoding; enabling it code-only could not be verified safe.
- **Toggle and hands-free recording modes** — changes the live capture/hotkey state machine; should be built and tested against a real microphone.
- **Typing guard for overlapping transcriptions** — serializes worker threads in the live typing path; a subtle race fix that needs real end-to-end testing.
- **Per-app dictation profiles** (`Big Bet`) — behavior changes per focused app; needs interactive testing across real targets.
- **Voice command grammar** (`Big Bet`) — new recognition/execution surface; beyond this pass.
- **More language profiles** — config-only (add a `profiles` entry + labels); nothing to implement in code.
- **Correction miner, in-app history browser** — UI/UX work (tray flow, Tk window) that needs interactive testing.
- **Local CLI/HTTP trigger** — new automation surface (and a localhost endpoint is a security-sensitive addition).
- **Packaged build** — PyInstaller packaging is a build-infra project; note the single-instance guard (mutex/file lock) already exists in `main.py`.
