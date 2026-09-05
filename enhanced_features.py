"""Optional OpenWhisper-inspired features for Whisper Dictate.

The existing main.py remains the core app. This module adds two high-value
features without replacing that small architecture:

1. Live streaming preview using a dedicated tiny Whisper model.
2. Local transcription history with a global history hotkey.

Run through launcher.py so the existing implementation stays easy to audit.
"""

import json
import os
import threading
import time
from datetime import datetime, timezone

import numpy as np

import main as app

HISTORY_FILE = os.path.join(app.BASE_DIR, "transcription-history.jsonl")
_HISTORY_LOCK = threading.Lock()
_STREAM_LOCK = threading.Lock()
_STREAM_STOP = threading.Event()
_STREAM_THREAD = None
_STREAM_MODEL = None
_STREAM_MODEL_NAME = None


def _history_hotkey():
    return set(app.cfg.get("history_hotkey", ["ctrl", "shift", "f11"]))


def _cache_has_model(model_name):
    cache = os.path.join(os.path.expanduser("~"), ".cache", "huggingface", "hub")
    path = os.path.join(cache, "models--Systran--faster-whisper-" + model_name)
    return os.path.isdir(path)


def _history_enabled():
    return bool(app.cfg.get("history_enabled", True))


def save_history(profile, text, duration_s):
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
            with open(HISTORY_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as exc:
        app.log(f"History write failed: {exc}")


def open_history():
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
    return bool(app.pressed & _history_hotkey())


def on_press(key):
    name = app.key_name(key)
    if name is None:
        return
    app.pressed.add(name)
    if _history_key_pressed():
        if not getattr(on_press, "fired", False):
            on_press.fired = True
            open_history()
        return
    if app.recording["active"]:
        return
    for profile in app.profiles:
        if set(profile.hotkey) <= app.pressed:
            start_recording(profile)
            return
    if (
        app.PASTE_LAST_HOTKEY
        and not app.paste_last_fired
        and set(app.PASTE_LAST_HOTKEY) <= app.pressed
    ):
        app.paste_last_fired = True
        app.paste_last()


def on_release(key):
    name = app.key_name(key)
    if name is None:
        return
    app.pressed.discard(name)
    if not _history_key_pressed():
        on_press.fired = False
    if app.recording["active"] and not (
        set(app.recording["profile"].hotkey) <= app.pressed
    ):
        stop_recording()
    if not set(app.PASTE_LAST_HOTKEY) <= app.pressed:
        app.paste_last_fired = False


def _get_stream_model(profile):
    global _STREAM_MODEL, _STREAM_MODEL_NAME
    model_name = app.cfg.get("streaming_model", "tiny")
    if not model_name or model_name == profile.model:
        return app.get_model(profile)
    with _STREAM_LOCK:
        if _STREAM_MODEL is None or _STREAM_MODEL_NAME != model_name:
            from faster_whisper import WhisperModel
            if app.cfg.get("offline", True) and not _cache_has_model(model_name):
                app.log(
                    f"[stream] Preview model '{model_name}' is not cached; "
                    f"falling back to {profile.model} for live preview"
                )
                return app.get_model(profile)
            app.log(f"[stream] Loading preview model '{model_name}'...")
            _STREAM_MODEL = WhisperModel(
                model_name, device=app.DEVICE, compute_type=app.COMPUTE
            )
            _STREAM_MODEL_NAME = model_name
            app.log(f"[stream] Preview model '{model_name}' ready")
        return _STREAM_MODEL


def _snapshot_audio():
    with app.frames_lock:
        buf = list(app.frames)
    if not buf:
        return np.zeros(0, dtype=np.float32)
    return np.ascontiguousarray(np.concatenate(buf), dtype=np.float32)


def _preview_text(model, audio, profile):
    if audio.size < int(app.cfg["samplerate"] * 0.65):
        return ""
    with _STREAM_LOCK:
        segments, _info = model.transcribe(
            audio,
            language=profile.language,
            beam_size=1,
            initial_prompt=profile.initial_prompt,
            hotwords=profile.hotwords,
            vad_filter=True,
            condition_on_previous_text=False,
        )
        return " ".join(seg.text.strip() for seg in segments).strip()


def _stream_worker(profile):
    global _STREAM_THREAD
    try:
        model = _get_stream_model(profile)
    except Exception as exc:
        app.log(f"[stream] Preview unavailable: {exc}")
        return
    last_preview = ""
    while not _STREAM_STOP.wait(float(app.cfg.get("streaming_interval", 1.25))):
        if not app.recording["active"] or app.recording["profile"] is not profile:
            continue
        try:
            audio = _snapshot_audio()
            preview = _preview_text(model, audio, profile)
            if preview and preview != last_preview:
                last_preview = preview
                app.show_state("listening", profile, preview[-180:])
        except Exception as exc:
            app.log(f"[stream] Preview error: {exc}")
            return
    _STREAM_THREAD = None


def start_streaming(profile):
    global _STREAM_THREAD
    if not app.cfg.get("streaming_enabled", True):
        return
    _STREAM_STOP.clear()
    if _STREAM_THREAD and _STREAM_THREAD.is_alive():
        return
    _STREAM_THREAD = threading.Thread(
        target=_stream_worker, args=(profile,), daemon=True, name="whisper-preview"
    )
    _STREAM_THREAD.start()


def stop_streaming():
    _STREAM_STOP.set()


def start_recording(profile):
    app.start_recording_original(profile)
    start_streaming(profile)


def stop_recording():
    profile = app.recording["profile"]
    app.recording["active"] = False
    stop_streaming()
    app.beep(440)
    with app.frames_lock:
        buf = list(app.frames)
    app.log(f"[{profile.name}] Recording stopped, {len(buf)} chunks captured")
    if not buf:
        app.show_state("ready")
        return
    threading.Thread(
        target=transcribe_thread, args=(profile, buf), daemon=True, name="whisper-final"
    ).start()


def transcribe_thread(profile, buf):
    done = threading.Event()
    try:
        audio = np.concatenate(buf) if buf else np.zeros(0, dtype=np.float32)
        audio = np.ascontiguousarray(audio, dtype=np.float32)
        if audio.size == 0:
            app.show_state("ready")
            return
        model = app.get_model(profile)
        t0 = time.time()
        app.show_state("transcribing", profile)

        def watchdog():
            while not done.wait(5):
                app.log(
                    f"[{profile.name}] STALL WATCH: transcribing for "
                    f"{time.time() - t0:.0f}s so far"
                )

        threading.Thread(target=watchdog, daemon=True).start()
        segments, _info = model.transcribe(
            audio,
            language=profile.language,
            beam_size=app.cfg.get("beam_size", 2),
            initial_prompt=profile.initial_prompt,
            hotwords=profile.hotwords,
            vad_filter=True,
        )
        text = " ".join(seg.text.strip() for seg in segments).strip()
        done.set()
        duration = audio.size / app.cfg["samplerate"]
        app.log(
            f"[{profile.name}] Transcribed {duration:.1f}s audio in "
            f"{time.time() - t0:.1f}s"
        )
        if not text:
            return
        app.last_text = text
        app.last_profile = profile
        save_history(profile, text, duration)
        app.show_state("typing", profile)
        app.type_text(text)
        app.beep(1320)
    except Exception as exc:
        done.set()
        app.show_state("error", profile)
        app.log(f"[{profile.name}] Error: {exc}")
        import traceback
        traceback.print_exc()
    finally:
        app.show_state("ready")


def install():
    app.start_recording_original = app.start_recording
    app.start_recording = start_recording
    app.stop_recording = stop_recording
    app.transcribe_thread = transcribe_thread
    app.on_press = on_press
    app.on_release = on_release
