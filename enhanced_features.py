"""Optional OpenWhisper-inspired features for Whisper Dictate.

The existing main.py remains the core app. This module adds high-value features
without replacing that small architecture:

1. Live streaming preview using a dedicated preview Whisper model (per
   profile, e.g. large-v3-turbo for German - tiny is too weak there).
2. Local transcription history with a global history hotkey.
3. Safe model coordination so preview and final transcription never compete for
   the same faster-whisper model instance.

Run through launcher.py so the existing implementation stays easy to audit.
"""

import glob
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
    # Org differs per model (Systran for most, mobiuslabsgmbh for
    # large-v3-turbo), so match on the repo basename only.
    pattern = os.path.join(cache, "models--*--faster-whisper-" + model_name)
    return bool(glob.glob(pattern))


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
    hk = _history_hotkey()
    return bool(hk) and hk <= app.pressed


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
    # Per-profile override first (tiny is far too weak for German preview);
    # an override equal to the profile model just shares that instance.
    model_name = profile.streaming_model or app.cfg.get("streaming_model", "tiny")
    if not model_name or model_name == profile.model:
        return app.get_model(profile), False
    with _STREAM_LOCK:
        if _STREAM_MODEL is None or _STREAM_MODEL_NAME != model_name:
            from faster_whisper import WhisperModel
            if app.cfg.get("offline", True) and not _cache_has_model(model_name):
                # No separate preview model available offline: fall back to the
                # already-loaded profile model so the pill still shows live
                # text instead of silently disabling the preview. The final
                # paste-at-end path is unchanged - the preview never types
                # into the document, it only updates the status pill.
                app.log(
                    f"[stream] Preview model '{model_name}' is not cached; "
                    f"falling back to profile model '{profile.model}' for preview"
                )
                return app.get_model(profile), False
            app.log(f"[stream] Loading preview model '{model_name}'...")
            _STREAM_MODEL = WhisperModel(
                model_name, device=app.DEVICE, compute_type=app.COMPUTE
            )
            _STREAM_MODEL_NAME = model_name
            app.log(f"[stream] Preview model '{model_name}' ready")
        return _STREAM_MODEL, True


def unload_stream_model():
    """Drop the dedicated streaming preview model; returns True if it was loaded."""
    global _STREAM_MODEL, _STREAM_MODEL_NAME
    with _STREAM_LOCK:
        if _STREAM_MODEL is None:
            return False
        _STREAM_MODEL = None
        _STREAM_MODEL_NAME = None
        return True


def _snapshot_audio():
    with app.frames_lock:
        buf = list(app.frames)
    if not buf:
        return np.zeros(0, dtype=np.float32)
    return np.ascontiguousarray(np.concatenate(buf), dtype=np.float32)


def _preview_text(model, audio, profile):
    app.touch_model_use()
    if audio.size < int(app.cfg["samplerate"] * 0.65):
        return ""
    with _STREAM_LOCK:
        segments, _info = model.transcribe(
            audio,
            language=profile.language,
            beam_size=1,
            hotwords=profile.hotwords,
            vad_filter=True,
            condition_on_previous_text=False,
        )
        preview = " ".join(seg.text.strip() for seg in segments).strip()
        return app.apply_corrections(preview, profile.corrections)


def _stream_worker(profile):
    global _STREAM_THREAD
    try:
        model, dedicated = _get_stream_model(profile)
        if model is None:
            return
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

        # Preview and final transcription may share CUDA memory and faster-whisper
        # model state. Serialize final inference with preview inference to avoid
        # intermittent GPU/CPU contention, especially when streaming falls back
        # to the profile model.
        with _STREAM_LOCK:
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
                beam_size=app.cfg.get("beam_size", 5),
                hotwords=profile.hotwords,
                vad_filter=True,
                # Same rationale as main.transcribe_thread: don't feed this
                # recording's own earlier output back as context.
                condition_on_previous_text=False,
            )
            text = app.apply_corrections(
                " ".join(seg.text.strip() for seg in segments).strip(),
                profile.corrections,
            )

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
        import logging as _logging

        _logging.exception(f"[{profile.name}] Error")
        import traceback
        try:
            traceback.print_exc()
        except Exception:
            pass
    finally:
        done.set()
        app.touch_model_use()
        app.show_state("ready")


def install():
    app.start_recording_original = app.start_recording
    app.start_recording = start_recording
    app.stop_recording = stop_recording
    app.transcribe_thread = transcribe_thread
    app.on_press = on_press
    app.on_release = on_release
