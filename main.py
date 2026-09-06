import ctypes
import glob
import json
import logging
import os
import queue
import re
import sys
import threading
import time
import tkinter as tk

import numpy as np
import pynput.keyboard as pkb
import pyperclip
import pystray
import sounddevice as sd
from PIL import Image, ImageDraw

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

APP_NAME = "Whisper Dictate"

# Headless startup: hide any console window when launched with --headless
# (used by run.bat / run_hidden.vbs / Startup shortcut). pythonw.exe already
# has no console; this covers launches via python.exe or cmd.exe so no
# terminal window stays visible. Pass --console to keep the console.
HEADLESS = "--headless" in sys.argv or "--hide-console" in sys.argv


def _hide_console():
    if sys.platform != "win32" or "--console" in sys.argv:
        return
    try:
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 0)  # SW_HIDE
    except Exception:
        pass


if HEADLESS:
    _hide_console()


def _read_cfg():
    cfg = {}
    path = os.path.join(BASE_DIR, "config.json")
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception:
            cfg = {}
    return cfg


def _models_cached(cfg):
    cache = os.path.join(os.path.expanduser("~"), ".cache", "huggingface", "hub")
    # The HF cache dir is "models--<org>--faster-whisper-<name>" and the org
    # differs per model (Systran for most, mobiuslabsgmbh for large-v3-turbo),
    # so match on the repo basename only.
    def _has(name):
        if not name:
            return True
        pattern = os.path.join(cache, "models--*--faster-whisper-" + name)
        return bool(glob.glob(pattern))

    names = [p["model"] for p in cfg.get("profiles") or [] if p.get("model")]
    return bool(names) and all(_has(n) for n in names)


_cfg_early = _read_cfg()
if _cfg_early.get("offline", True) and _models_cached(_cfg_early):
    os.environ["HF_HUB_OFFLINE"] = "1"


def _add_cuda_dlls_to_path():
    if sys.platform != "win32":
        return
    for sp in sys.path:
        base = os.path.join(sp, "nvidia")
        for sub in ("cublas", "cudnn", "cuda_runtime"):
            d = os.path.join(base, sub, "bin")
            if os.path.isdir(d):
                os.environ["PATH"] = d + os.pathsep + os.environ.get("PATH", "")


_add_cuda_dlls_to_path()

logging.basicConfig(
    filename=os.path.join(BASE_DIR, "dictate.log"),
    level=logging.INFO,
    format="%(asctime)s %(message)s",
)

if sys.platform == "win32":
    MUTEX_NAME = APP_NAME.replace(" ", "")
    _mutex = ctypes.windll.kernel32.CreateMutexW(None, False, MUTEX_NAME)
    if ctypes.windll.kernel32.GetLastError() in (183, 5):
        logging.info("Another Whisper Dictate instance is already running - exiting.")
        try:
            if sys.stdout is not None:
                print("Another Whisper Dictate instance is already running - exiting.")
        except Exception:
            pass
        sys.exit(0)
else:
    _LOCK_FILE = os.path.join(BASE_DIR, ".app.lock")
    try:
        _lf = os.open(_LOCK_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(_lf, str(os.getpid()).encode())
    except FileExistsError:
        logging.info("Another Whisper Dictate instance is already running - exiting.")
        try:
            if sys.stdout is not None:
                print("Another Whisper Dictate instance is already running - exiting.")
        except Exception:
            pass
        sys.exit(0)

DEFAULTS = {
    "offline": True,
    "device": "auto",
    "compute_type": "auto",
    "audio_device": None,
    "samplerate": 16000,
    "beam_size": 5,
    "type_newline": True,
    "sound": True,
    "paste_last_hotkey": ["ctrl", "shift", "f12"],
    "paste_button_linger": 10,
    "model_idle_unload_minutes": 10,
    "profiles": [
        {
            "name": "EN",
            "hotkey": ["ctrl", "shift", "space"],
            "model": "small.en",
            "language": "en",
            "hotwords_file": "hotwords-en.txt",
            "labels": {
                "listening": "Listening…",
                "transcribing": "Transcribing…",
                "loading": "Loading model…",
                "typing": "Typing…",
                "error": "Error",
            },
        },
        {
            "name": "DE",
            "hotkey": ["ctrl", "alt", "space"],
            "model": "medium",
            "language": "de",
            "hotwords_file": "hotwords-de.txt",
            # German live preview: tiny/base are far too weak for German; a
            # large-v3-turbo instance shows near-perfect text while recording.
            "streaming_model": "large-v3-turbo",
            "labels": {
                "listening": "Hören…",
                "transcribing": "Transkribieren…",
                "loading": "Lade Modell…",
                "typing": "Tippe…",
                "error": "Fehler",
            },
        },
    ],
}


def load_config():
    cfg = dict(DEFAULTS)
    path = os.path.join(BASE_DIR, "config.json")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            cfg.update(json.load(f))
    return cfg


def load_hotwords(path):
    full = path if os.path.isabs(path) else os.path.join(BASE_DIR, path)
    if not os.path.exists(full):
        return ""
    words = []
    with open(full, "r", encoding="utf-8") as f:
        for line in f:
            w = line.strip()
            if w and not w.startswith("#"):
                words.append(w)
    return " ".join(words)


def load_corrections(path):
    """Load deterministic wrong=>correct pairs. Missing/empty file -> []."""
    if not path:
        return []
    full = path if os.path.isabs(path) else os.path.join(BASE_DIR, path)
    if not os.path.exists(full):
        return []
    pairs = []
    with open(full, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=>" not in line:
                continue
            wrong, correct = line.split("=>", 1)
            wrong, correct = wrong.strip(), correct.strip()
            if wrong and correct:
                pairs.append((wrong, correct))
    # Longest first so longer phrases win over their substrings.
    pairs.sort(key=lambda p: len(p[0]), reverse=True)
    return pairs


def apply_corrections(text, corrections):
    """Deterministic replacement: case-insensitive, word-boundary aware."""
    for wrong, correct in corrections or []:
        def _repl(m, correct=correct):
            s = m.group(0)
            if s and s[0].isupper() and correct:
                return correct[0].upper() + correct[1:]
            return correct
        text = re.sub(
            r"\b" + re.escape(wrong) + r"\b", _repl, text, flags=re.IGNORECASE
        )
    return text


def _display_key(k):
    return {
        "ctrl": "Ctrl",
        "shift": "Shift",
        "alt": "Alt",
        "space": "Space",
    }.get(k, k.title())


class Profile:
    def __init__(self, idx, p):
        self.name = p.get("name", f"P{idx + 1}")
        self.hotkey = list(p.get("hotkey", ["ctrl", "shift", "space"]))
        self.model = p.get("model", "small.en")
        self.language = p.get("language", "en")
        # Optional per-profile preview model; falls back to the global
        # "streaming_model" setting (see enhanced_features._get_stream_model).
        self.streaming_model = p.get("streaming_model")
        self.hotwords_file = p.get("hotwords_file", "hotwords.txt")
        self.hotwords = load_hotwords(self.hotwords_file)
        self.corrections_file = p.get("corrections_file") or f"corrections-{self.language}.txt"
        self.corrections = load_corrections(self.corrections_file)
        # No initial_prompt on purpose: Whisper's prompt slot means "already
        # transcribed text", not instructions. An instruction prefix (plus the
        # hotword list) made the model echo prompt words instead of
        # transcribing - a 20s German dictation once decoded to just three
        # hotwords ("Backend Datenbank Repository"). The hotwords parameter
        # alone biases the vocabulary with a single, size-capped copy.
        self.labels = p.get("labels", {})
        self.model_obj = None

    def hotkey_str(self):
        return "+".join(_display_key(k) for k in self.hotkey)

    def label(self, key):
        return self.labels.get(key, key.title())


cfg = load_config()
profiles = [Profile(i, p) for i, p in enumerate(cfg.get("profiles") or DEFAULTS["profiles"])]


def _resolve_runtime():
    dev = cfg.get("device", "auto")
    ct = cfg.get("compute_type", "auto")
    if dev == "auto":
        try:
            import ctranslate2

            if ctranslate2.get_cuda_device_count() > 0:
                dev, ct = "cuda", "float16"
            else:
                dev, ct = "cpu", "int8"
        except Exception:
            dev, ct = "cpu", "int8"
    elif ct == "auto":
        ct = "float16" if dev == "cuda" else "int8"
    return dev, ct


DEVICE, COMPUTE = _resolve_runtime()

model_lock = threading.Lock()
recording = {"active": False, "profile": None}
frames = []
frames_lock = threading.Lock()
pressed = set()
last_text = None
last_profile = None
paste_last_fired = False
PASTE_LAST_HOTKEY = list(cfg.get("paste_last_hotkey") or [])
# Seconds the paste button stays up after a fresh transcription before it
# fades out (the Ctrl+Shift+F12 hotkey keeps working either way).
PASTE_BUTTON_LINGER = float(cfg.get("paste_button_linger", 10))
# 0-255 pill opacity; it never intercepts clicks either way.
PILL_ALPHA = int(cfg.get("pill_alpha", 150))
# Minutes of inactivity after which loaded Whisper models are dropped from RAM
# (0 disables unloading). CTranslate2 keeps freed memory resident, so without
# this the process stays at its post-transcription high-water mark forever.
MODEL_IDLE_UNLOAD_S = float(cfg.get("model_idle_unload_minutes", 10)) * 60
model_use_time = time.time()

STATUS_QUEUE = queue.Queue()
OVERLAY_ROOT = None

STATE_COLORS = {
    "ready": "#aeb4c9",
    "listening": "#ff4d4d",
    "transcribing": "#ffb340",
    "loading": "#7aa2ff",
    "typing": "#4dd07f",
    "error": "#ff5555",
}


def log(msg):
    logging.info(msg)
    try:
        # sys.stdout is None under pythonw.exe with no console - never crash there.
        if sys.stdout is not None:
            print(f"[dictate] {msg}", flush=True)
    except Exception:
        pass


def beep(freq, dur=90):
    if not cfg.get("sound"):
        return
    try:
        if sys.platform == "win32":
            import winsound

            winsound.Beep(freq, dur)
        elif OVERLAY_ROOT is not None:
            OVERLAY_ROOT.bell()
        else:
            sys.stdout.write("\a")
            sys.stdout.flush()
    except Exception:
        pass


def show_state(state, profile=None, detail=""):
    if state == "ready":
        text = "Ready to transcribe    " + "    │    ".join(
            f"{p.name} {p.hotkey_str()}" for p in profiles
        )
    else:
        text = f"{profile.name} {profile.label(state)}"
        if detail:
            text += f" {detail}"
    STATUS_QUEUE.put(("show", STATE_COLORS[state], text))


class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


def _top_hwnd(widget):
    """Return the real top-level HWND of a Tk widget (Windows only).

    winfo_id() returns the inner TkChild window; GetForegroundWindow() and
    mouse hit-tests see its TkTopLevel wrapper instead.
    """
    if sys.platform != "win32" or widget is None:
        return None
    try:
        return ctypes.windll.user32.GetAncestor(widget.winfo_id(), 2)  # GA_ROOT
    except Exception:
        return None


def _foreground_hwnd():
    """Return the HWND of the currently focused window (Windows only)."""
    if sys.platform != "win32":
        return None
    try:
        return ctypes.windll.user32.GetForegroundWindow()
    except Exception:
        return None


def _set_foreground(hwnd):
    """Bring the given HWND to the foreground (Windows only)."""
    if sys.platform != "win32" or not hwnd:
        return
    try:
        ctypes.windll.user32.SetForegroundWindow(hwnd)
        time.sleep(0.03)
    except Exception:
        pass


class StatusOverlay:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title(APP_NAME)
        self.root.withdraw()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        if sys.platform == "win32":
            try:
                self.root.attributes("-toolwindow", True)
            except Exception:
                pass
        self.frame = tk.Frame(
            self.root,
            bg="#3d3d54",
            highlightthickness=1,
            highlightbackground="#55556e",
            highlightcolor="#55556e",
        )
        self.dot = tk.Label(
            self.frame, text="●", fg="#aeb4c9", bg="#3d3d54", font=("Segoe UI", 10)
        )
        self.txt = tk.Label(
            self.frame, text="", fg="#ffffff", bg="#3d3d54", font=("Segoe UI", 9)
        )
        self.dot.pack(side="left", padx=(9, 4), pady=3)
        self.txt.pack(side="left", padx=(0, 9), pady=3)
        self.frame.pack()
        if sys.platform == "win32":
            self._click_through()
        self._make_paste_button()
        self.target_hwnd = None
        self.pb_until = 0.0  # epoch seconds the paste button stays visible
        self.pb_alpha = 1.0
        self.pb_alpha_shown = None
        self.root.after(120, self._poll)

    @staticmethod
    def _paste_button_label():
        if PASTE_LAST_HOTKEY:
            return "Paste last  (" + " + ".join(_display_key(k) for k in PASTE_LAST_HOTKEY) + ")"
        return "Paste last"

    def _make_paste_button(self):
        self.pb_win = tk.Toplevel(self.root)
        self.pb_win.withdraw()
        self.pb_win.overrideredirect(True)
        self.pb_win.attributes("-topmost", True)
        if sys.platform == "win32":
            try:
                self.pb_win.attributes("-toolwindow", True)
            except Exception:
                pass
        self.pb_btn = tk.Button(
            self.pb_win,
            text=self._paste_button_label(),
            command=self._on_paste_click,
            bg="#3d3d54",
            fg="#ffffff",
            activebackground="#4c4c6a",
            activeforeground="#ffffff",
            relief="flat",
            bd=0,
            highlightthickness=1,
            highlightbackground="#55556e",
            highlightcolor="#55556e",
            padx=10,
            pady=2,
            cursor="hand2",
            font=("Segoe UI", 9),
        )
        self.pb_btn.pack()

    def _on_new_text(self):
        """A fresh transcription arrived: keep the paste button up for a while."""
        self.pb_until = time.time() + PASTE_BUTTON_LINGER
        self.pb_alpha = 1.0

    def _cursor_on_paste_button(self):
        """True if the mouse cursor is over the paste button (Windows only)."""
        if sys.platform != "win32":
            return False
        try:
            pt = _POINT()
            if not ctypes.windll.user32.GetCursorPos(ctypes.byref(pt)):
                return False
            bx = self.pb_win.winfo_rootx()
            by = self.pb_win.winfo_rooty()
            bw = self.pb_win.winfo_width()
            bh = self.pb_win.winfo_height()
        except Exception:
            return False
        pad = 6
        return bx - pad <= pt.x <= bx + bw + pad and by - pad <= pt.y <= by + bh + pad

    def _refresh_paste_button(self, pill_x, pill_y, pill_w, pill_h):
        if last_text is None:
            self.pb_win.withdraw()
            return
        now = time.time()
        try:
            shown = self.pb_win.state() != "withdrawn"
        except Exception:
            shown = False
        if shown and self._cursor_on_paste_button():
            # Don't fade out while the user is aiming for the button.
            self.pb_until = max(self.pb_until, now + 1.0)
        if now < self.pb_until:
            self.pb_alpha = 1.0
        else:
            self.pb_alpha = max(0.0, self.pb_alpha - 0.25)
            if self.pb_alpha <= 0.0:
                self.pb_win.withdraw()
                return
        if self.pb_alpha != self.pb_alpha_shown:
            self.pb_win.attributes("-alpha", self.pb_alpha)
            self.pb_alpha_shown = self.pb_alpha
        sw = self.root.winfo_screenwidth()
        self.pb_win.update_idletasks()
        bw = self.pb_win.winfo_reqwidth()
        bh = self.pb_win.winfo_reqheight()
        x = pill_x + pill_w + 8
        if x + bw > sw - 4:
            x = max(4, pill_x - bw - 8)
        y = pill_y
        self.pb_win.geometry(f"{bw}x{bh}+{x}+{y}")
        self.pb_win.deiconify()
        self.pb_win.lift()

    def _click_through(self):
        """Make the pill window immune to mouse clicks and translucent.

        The styles must go on the top-level wrapper window: winfo_id() returns
        the inner TkChild, which never receives the hit-test, so styling it
        silently does nothing and the pill keeps swallowing clicks.
        """
        try:
            user32 = ctypes.windll.user32
            GWL_EXSTYLE = -20
            hwnd = _top_hwnd(self.root)
            styles = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
            styles |= 0x20 | 0x80000 | 0x08000000 | 0x80
            user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, styles)
            # A layered window is never painted until SetLayeredWindowAttributes
            # is called on it at least once.
            LWA_ALPHA = 0x2
            user32.SetLayeredWindowAttributes(hwnd, 0, PILL_ALPHA, LWA_ALPHA)
        except Exception:
            pass

    def _poll(self):
        try:
            while True:
                item = STATUS_QUEUE.get_nowait()
                if item[0] == "show":
                    self._show(*item[1:])
                elif item[0] == "new_text":
                    self._on_new_text()
                else:
                    self.root.withdraw()
        except queue.Empty:
            pass
        self._track_target()
        self._refresh_paste_button_pos()
        self.root.after(120, self._poll)

    def _track_target(self):
        """Remember the last focused window that isn't one of our overlays."""
        cur = _foreground_hwnd()
        if not cur:
            return
        try:
            own = {_top_hwnd(self.root), _top_hwnd(self.pb_win)}
        except Exception:
            own = set()
        if cur not in own:
            self.target_hwnd = cur

    def _on_paste_click(self):
        _set_foreground(self.target_hwnd)
        paste_last()

    def _refresh_paste_button_pos(self):
        try:
            self.root.update_idletasks()
            x = self.root.winfo_x()
            y = self.root.winfo_y()
            w = self.root.winfo_reqwidth()
            h = self.root.winfo_reqheight()
            self._refresh_paste_button(x, y, w, h)
        except Exception:
            pass

    def _show(self, color, text):
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        self.dot.config(fg=color)
        self.txt.config(text=text)
        self.root.update_idletasks()
        w = self.root.winfo_reqwidth()
        h = self.root.winfo_reqheight()
        px = (sw - w) // 2
        py = sh - h - 64
        self.root.geometry(f"{w}x{h}+{px}+{py}")
        self.root.deiconify()
        self.root.lift()
        # Re-assert click-through after mapping: the wrapper window the styles
        # need only exists (or sticks) once the window has been shown.
        self._click_through()
        self._refresh_paste_button(px, py, w, h)


def key_name(key):
    if isinstance(key, pkb.KeyCode):
        ch = key.char
        if ch is None:
            return None
        ch = ch.lower()
        if ch == " ":
            return "space"
        return ch
    n = getattr(key, "name", None)
    if n in ("ctrl_l", "ctrl_r"):
        return "ctrl"
    if n in ("shift_l", "shift_r"):
        return "shift"
    if n in ("alt_l", "alt_r"):
        return "alt"
    return n


def on_press(key):
    global paste_last_fired
    n = key_name(key)
    if n is None:
        return
    pressed.add(n)
    if recording["active"]:
        return
    for p in profiles:
        if set(p.hotkey) <= pressed:
            start_recording(p)
            return
    if (
        PASTE_LAST_HOTKEY
        and not paste_last_fired
        and set(PASTE_LAST_HOTKEY) <= pressed
    ):
        paste_last_fired = True
        paste_last()


def on_release(key):
    global paste_last_fired
    n = key_name(key)
    if n is None:
        return
    pressed.discard(n)
    if recording["active"] and not (set(recording["profile"].hotkey) <= pressed):
        stop_recording()
    if not set(PASTE_LAST_HOTKEY) <= pressed:
        paste_last_fired = False


def audio_callback(indata, frames_cnt, time_info, status):
    if recording["active"]:
        with frames_lock:
            frames.append(indata[:, 0].copy())


def start_recording(profile):
    with frames_lock:
        frames.clear()
    recording["active"] = True
    recording["profile"] = profile
    beep(880)
    show_state("listening", profile)
    log(f"[{profile.name}] Recording... release {profile.hotkey_str()} to transcribe")


def stop_recording():
    profile = recording["profile"]
    recording["active"] = False
    beep(440)
    with frames_lock:
        buf = list(frames)
    log(f"[{profile.name}] Recording stopped, {len(buf)} chunks captured")
    if not buf:
        show_state("ready")
        return
    threading.Thread(target=transcribe_thread, args=(profile, buf), daemon=True).start()


def get_model(profile):
    with model_lock:
        if profile.model_obj is None:
            from faster_whisper import WhisperModel

            t0 = time.time()
            show_state("loading", profile)
            log(f"[{profile.name}] Loading model '{profile.model}'...")
            profile.model_obj = WhisperModel(
                profile.model, device=DEVICE, compute_type=COMPUTE
            )
            log(f"[{profile.name}] Model loaded in {time.time()-t0:.1f}s")
        touch_model_use()
        return profile.model_obj


def touch_model_use():
    global model_use_time
    model_use_time = time.time()


def unload_models():
    """Drop every loaded Whisper model so the OS reclaims the RAM.

    In-flight transcriptions keep their own reference to the model object, so
    an unload during inference is safe - the memory is freed once it finishes.
    """
    unloaded = []
    try:
        import enhanced_features

        if enhanced_features.unload_stream_model():
            unloaded.append("streaming preview")
    except Exception:
        pass
    with model_lock:
        for p in profiles:
            if p.model_obj is not None:
                p.model_obj = None
                unloaded.append(p.model)
    return unloaded


def unload_models_now(icon=None, item=None):
    if recording["active"]:
        if icon:
            icon.notify("Finish the current recording first", APP_NAME)
        return
    unloaded = unload_models()
    if icon:
        icon.notify(
            "Models unloaded" if unloaded else "No models were loaded", APP_NAME
        )
    log("Unloaded models: " + (", ".join(unloaded) if unloaded else "none"))


def _model_idle_watchdog():
    while True:
        time.sleep(30)
        if MODEL_IDLE_UNLOAD_S <= 0 or recording["active"]:
            continue
        if time.time() - model_use_time < MODEL_IDLE_UNLOAD_S:
            continue
        unloaded = unload_models()
        if unloaded:
            log(
                f"Idle for {MODEL_IDLE_UNLOAD_S / 60:.0f} min - unloaded: "
                + ", ".join(unloaded)
            )


def transcribe_thread(profile, buf):
    global last_text, last_profile
    try:
        audio = np.concatenate(buf) if buf else np.zeros(0, dtype=np.float32)
        audio = np.ascontiguousarray(audio, dtype=np.float32)
        if audio.size == 0:
            show_state("ready")
            return
        done = threading.Event()

        def watchdog():
            t0 = time.time()
            while not done.wait(5):
                log(f"[{profile.name}] STALL WATCH: transcribing for {time.time()-t0:.0f}s so far")

        m = get_model(profile)

        threading.Thread(target=watchdog, daemon=True).start()
        t0 = time.time()
        show_state("transcribing", profile)
        segments, _info = m.transcribe(
            audio,
            language=profile.language,
            beam_size=cfg.get("beam_size", 5),
            hotwords=profile.hotwords,
            vad_filter=True,
            # Never condition on this recording's own earlier output: once a
            # segment goes wrong (echo, repetition), conditioning feeds the
            # garbage back in and the rest of the dictation is lost.
            condition_on_previous_text=False,
        )
        parts = [seg.text.strip() for seg in segments]
        text = apply_corrections(" ".join(parts).strip(), profile.corrections)
        done.set()
        log(
            f"[{profile.name}] Transcribed {audio.size/cfg['samplerate']:.1f}s audio in {time.time()-t0:.1f}s"
        )
        if not text:
            return
        last_text = text
        last_profile = profile
        STATUS_QUEUE.put(("new_text",))
        show_state("typing", profile)
        type_text(text)
        beep(1320)
    except Exception as e:
        done.set()
        show_state("error", profile)
        log(f"[{profile.name}] Error: {e}")
        logging.exception(f"[{profile.name}] Error")
        import traceback

        try:
            traceback.print_exc()
        except Exception:
            pass
    finally:
        touch_model_use()
        show_state("ready")


def type_text(text):
    if cfg.get("type_newline"):
        text += "\n"
    pyperclip.copy(text)
    time.sleep(0.05)
    ctrl = pkb.Controller()
    ctrl.press(pkb.Key.ctrl)
    ctrl.tap("v")
    ctrl.release(pkb.Key.ctrl)


def paste_last(icon=None, item=None):
    """Re-insert the most recent transcription into the currently focused field."""
    if not last_text:
        log("No transcription to re-paste yet")
        if icon:
            icon.notify("Nothing to re-paste yet", APP_NAME)
        return
    profile = last_profile if last_profile is not None else profiles[0]
    show_state("typing", profile)
    type_text(last_text)
    beep(1320)
    log("Re-pasted last transcription")


def reload_hotwords(icon=None):
    for p in profiles:
        p.hotwords = load_hotwords(p.hotwords_file)
        p.corrections = load_corrections(p.corrections_file)
    log("Hotwords and corrections reloaded")
    if icon:
        icon.notify("Hotwords and corrections reloaded", APP_NAME)


def make_icon_image():
    img = Image.new("RGB", (64, 64), (20, 20, 30))
    d = ImageDraw.Draw(img)
    d.ellipse((10, 18, 54, 42), outline="white", width=4)
    d.rectangle((26, 12, 38, 20), fill="white")
    d.rectangle((26, 44, 38, 52), fill="white")
    return img


def quit_app(icon, item):
    icon.stop()
    if OVERLAY_ROOT is not None:
        try:
            OVERLAY_ROOT.quit()
        except Exception:
            pass


def _open_audio_settings(icon=None, item=None):
    """Show available microphone inputs and the configured device."""
    try:
        devices = sd.query_devices()
        inputs = [
            f"{i}: {d['name']}"
            for i, d in enumerate(devices)
            if d.get("max_input_channels", 0) > 0
        ]
        configured = cfg.get("audio_device")
        selected = "default" if configured in (None, "") else str(configured)
        message = f"Configured input: {selected}\n\n" + "\n".join(inputs)
        log("Available input devices: " + " | ".join(inputs))
        if icon:
            icon.notify(f"Input device: {selected}. See dictate.log for available devices.", APP_NAME)
        return message
    except Exception as exc:
        log(f"Could not enumerate audio devices: {exc}")
        return ""


def main():
    log(f"{APP_NAME} pid={os.getpid()} exe={sys.executable} - device={DEVICE} compute={COMPUTE}")
    if MODEL_IDLE_UNLOAD_S > 0:
        log(f"Models unload after {MODEL_IDLE_UNLOAD_S / 60:.0f} min idle")
    for p in profiles:
        log(f"[{p.name}] {p.hotkey_str()} -> model {p.model}, language {p.language}")
    _open_audio_settings()
    log("Right-click tray icon for menu. Quit to exit.")

    input_device = cfg.get("audio_device")
    stream_kwargs = {
        "samplerate": cfg["samplerate"],
        "channels": 1,
        "dtype": "float32",
        "callback": audio_callback,
    }
    if input_device not in (None, ""):
        stream_kwargs["device"] = input_device
        log(f"Using configured microphone device: {input_device}")

    try:
        stream = sd.InputStream(**stream_kwargs)
        stream.start()
    except Exception as exc:
        if input_device not in (None, ""):
            log(f"Configured audio device failed ({exc}); retrying with system default")
            stream_kwargs.pop("device", None)
            stream = sd.InputStream(**stream_kwargs)
            stream.start()
        else:
            raise

    def preload():
        # Preload the default model; without the reset the pill would stay on
        # "Loading model…" until the first transcription (the initial
        # show_state("ready") races with the loading state).
        try:
            get_model(profiles[0])
        except Exception as e:
            log(f"Preload of default model failed: {e}")
        finally:
            if not recording["active"]:
                show_state("ready")

    threading.Thread(target=preload, daemon=True).start()
    threading.Thread(
        target=_model_idle_watchdog, daemon=True, name="model-idle-watchdog"
    ).start()

    listener = pkb.Listener(on_press=on_press, on_release=on_release)
    listener.daemon = True
    listener.start()

    menu = pystray.Menu(
        pystray.MenuItem(
            lambda item: " · ".join(f"{p.name} {p.hotkey_str()}" for p in profiles),
            None,
            enabled=False,
        ),
        pystray.MenuItem("Paste last transcription", paste_last),
        pystray.MenuItem("Show microphone devices", _open_audio_settings),
        pystray.MenuItem("Reload hotwords", reload_hotwords),
        pystray.MenuItem("Unload models now", unload_models_now),
        pystray.MenuItem("Quit", quit_app),
    )
    icon = pystray.Icon("whisper_dictate", make_icon_image(), APP_NAME, menu)

    overlay = StatusOverlay()
    global OVERLAY_ROOT
    OVERLAY_ROOT = overlay.root
    show_state("ready")
    try:
        icon.run_detached()
    except AttributeError:
        threading.Thread(target=icon.run, daemon=True).start()
    overlay.root.mainloop()


if __name__ == "__main__":
    main()
