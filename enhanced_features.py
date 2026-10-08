"""Optional add-on features for Whisper Dictate.

The existing main.py remains the core app. This module adds local
transcription history (global hotkey, JSONL file) on top of it. main.py now
provides a small hook layer (add_text_listener / add_key_press_listener /
add_key_release_listener), so history subscribes to the one real
implementation of the keyboard/transcription flow instead of duplicating and
runtime-swapping on_press/on_release/stop_recording/transcribe_thread -
transcription fixes only need to be made once, in main.py.

Run through launcher.py so the existing implementation stays easy to audit.
"""

import json
import os
import threading
from datetime import datetime, timezone

import app_paths
import main as app

HISTORY_FILE = app_paths.history_path()
_HISTORY_LOCK = threading.Lock()
# The history directory is created once at startup rather than on every
# append: os.makedirs(exist_ok=True) still costs a syscall per utterance.
_HISTORY_DIR = os.path.dirname(HISTORY_FILE) or "."
# Same rotation policy as dictate.log (_RotatingLog in main.py): the history
# file used to grow without bound.
HISTORY_MAX_BYTES = 2 * 1024 * 1024
HISTORY_BACKUPS = 2
try:
    os.makedirs(_HISTORY_DIR, exist_ok=True)
except Exception as _exc:  # pragma: no cover - read-only data dir
    pass


def _history_hotkey():
    return set(app.cfg.get("history_hotkey", ["ctrl", "shift", "f11"]))


def _history_enabled():
    return bool(app.cfg.get("history_enabled", True))


def _rotate_if_oversized():
    """Keep one .1 backup when the history file grows past the cap.

    Plain rename, not a live file handle: the file is opened per append so the
    next append simply creates a fresh one.
    """
    try:
        if not os.path.exists(HISTORY_FILE):
            return
        if os.path.getsize(HISTORY_FILE) < HISTORY_MAX_BYTES:
            return
        oldest = f"{HISTORY_FILE}.{HISTORY_BACKUPS}"
        if os.path.exists(oldest):
            os.remove(oldest)
        for i in range(HISTORY_BACKUPS - 1, 0, -1):
            src = f"{HISTORY_FILE}.{i}"
            if os.path.exists(src):
                os.replace(src, f"{HISTORY_FILE}.{i + 1}")
        os.replace(HISTORY_FILE, f"{HISTORY_FILE}.1")
    except Exception as exc:
        app.log(f"History rotation failed: {exc}")


def save_history(profile, text, duration_s):
    """Text listener: append a finished transcription to the JSONL history."""
    if not _history_enabled() or not text:
        return
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "profile": profile.name,
        "language": profile.language,
        "model": profile.model,
        "duration_seconds": round(float(duration_s), 2),
        "text": text,
    }
    try:
        with _HISTORY_LOCK:
            _rotate_if_oversized()
            # Directory already exists (made at import), so this is a single
            # append instead of a makedirs syscall per utterance.
            with open(HISTORY_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as exc:
        app.log(f"History write failed: {exc}")


def open_history():
    try:
        os.makedirs(_HISTORY_DIR, exist_ok=True)
        if not os.path.exists(HISTORY_FILE):
            with open(HISTORY_FILE, "a", encoding="utf-8"):
                pass
    except Exception as exc:
        app.log(f"History file could not be created: {exc}")
        return
    try:
        if os.name == "nt":
            os.startfile(HISTORY_FILE)
        elif app.sys.platform == "darwin":
            import subprocess
            subprocess.Popen(["open", HISTORY_FILE])
        else:
            import subprocess
            subprocess.Popen(["xdg-open", HISTORY_FILE])
        app.log(f"Opened transcription history: {HISTORY_FILE}")
    except Exception as exc:
        app.log(f"Could not open transcription history: {exc}")


def _history_key_pressed():
    hk = _history_hotkey()
    return bool(hk) and hk <= app.pressed


def _on_press_history(name):
    """Key press listener: consume the history hotkey and open the file."""
    if not _history_enabled():
        return False
    if _history_key_pressed():
        if not getattr(_on_press_history, "fired", False):
            _on_press_history.fired = True
            open_history()
        return True
    return False


def _on_release_history(name):
    # Reset the open-once latch as soon as the hotkey is no longer held.
    if not _history_key_pressed():
        _on_press_history.fired = False


def install():
    """Register history with main's hook layer (no function swapping)."""
    app.add_text_listener(save_history)
    app.add_key_press_listener(_on_press_history)
    app.add_key_release_listener(_on_release_history)
