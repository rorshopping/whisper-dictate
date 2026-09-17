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
from datetime import datetime, timezone

import history_store
import main as app

HISTORY_FILE = app.HISTORY_PATH


def _history_hotkey():
    return set(app.cfg.get("history_hotkey", ["ctrl", "shift", "f11"]))


def _history_enabled():
    return bool(app.cfg.get("history_enabled", True))


def save_history(profile, text, duration_s):
    """Text listener: append a finished transcription to the JSONL history."""
    if not _history_enabled() or not text:
        return
    try:
        # append_record serializes on the shared per-path lock in
        # history_store, the same lock the history window's edits hold.
        history_store.append_record(
            HISTORY_FILE,
            profile_name=profile.name,
            language=profile.language,
            model=profile.model,
            text=text,
            duration_s=duration_s,
        )
    except Exception as exc:
        app.log(f"History write failed: {exc}")


def open_history():
    """Open the Tk history browser, falling back to the raw file.

    The browser is the useful view (search, copy, re-paste, delete); opening
    the JSONL in an editor stays as the fallback for a headless or broken UI.
    """
    browser = getattr(app, "open_history_browser", None)
    if browser is not None:
        try:
            browser()
            app.log("Opened transcription history browser")
            return
        except Exception as exc:
            app.log(f"History browser unavailable ({exc}); opening the file")
    if not os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "a", encoding="utf-8"):
            pass
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
