# Portable/installed path notes

`app_paths.py` is the boundary between files shipped with Whisper Dictate and
files written while it runs.

## Runtime locations

* `resource_dir()` is the repository directory in source mode and PyInstaller's
  `sys._MEIPASS` resource root in a frozen build. Sounds, text resources, and
  the bundled default `config.json` are read from there.
* `data_dir()` is the repository directory in source mode, preserving the
  existing developer workflow. Frozen builds use a per-user directory by
  default: `%APPDATA%\\Whisper Dictate` on Windows,
  `~/Library/Application Support/Whisper Dictate` on macOS, and
  `$XDG_DATA_HOME/whisper-dictate` (or `~/.local/share/whisper-dictate`) on
  other systems.
* `config_path()`, `log_path()`, `history_path()`, `model_cache_dir()`, and
  `lock_path()` all resolve below that data root. The lock is the same
  `.app.lock` path used by the non-Windows single-instance guard and the macOS
  stale-lock recovery code. Windows continues to use its named mutex in
  addition to the shared path abstraction.
* In source mode the Hugging Face cache remains at the historical
  `~/.cache/huggingface/hub` location. Frozen and explicitly portable runs
  use `models/` below their data root, so a read-only bundle never receives
  model downloads.

`*.local.txt` companions are always addressed below `data_dir()`, even when
the corresponding tracked file is in `_MEIPASS`. A frozen app therefore never
tries to create a private correction or hotword file inside `_internal`.

## Enabling portable mode

Portable mode is opt-in. Any of the following enables it:

```text
WHISPER_DICTATE_PORTABLE=1
WhisperDictate.exe --portable
a `PortableData` directory beside the executable
```

`WHISPER_DICTATE_PORTABLE_DIR` can select a different portable directory. A
path supplied directly as the value of `WHISPER_DICTATE_PORTABLE` is also
accepted. `WHISPER_DICTATE_DATA_DIR` is an explicit per-user/data-root
override for deployments that already manage that location.

The application creates `PortableData` when the explicit switch or directory
override requests it. It performs a real write probe rather than relying only
on `os.access`; if the application directory is read-only (as a normal
Program Files installation or signed `.app` is), it falls back to the
per-user directory. Spaces and Unicode in all of these paths are supported.

## First run and migration

The PyInstaller spec packages the tracked `config.json` as a **default**, not as
the live configuration. On frozen startup:

1. the data directory is created;
2. a valid legacy `config.json` beside an older executable is copied once when
   no user config exists;
3. otherwise the bundled default is copied to the data root; and
4. newly introduced built-in keys are recursively merged into an existing
   valid user config.

Writes are atomic. Existing user values, including `false`, custom keys, and
licensing settings, win over defaults. Invalid existing JSON is reported and
left untouched rather than being silently replaced. `config.local.json` is
also read from the data root.

## Known gaps / migration notes

* The one-time migration covers the configuration only. Existing logs,
  transcription history, lost-audio files, and model caches are not moved;
  users can copy them manually to the reported data directory.
* A portable directory is used only when it is writable. A signed macOS app
  normally falls back to Application Support; copying a release to a writable
  folder and using the flag/marker enables genuinely portable operation.
* Changing between source, installed, and portable modes intentionally uses
  separate data roots. There is no background synchronisation between them.
* The bundled text files remain read-only resources. Only `*.local.txt` files
  are created in the writable data root.
