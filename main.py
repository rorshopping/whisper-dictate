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
from logging.handlers import RotatingFileHandler

import numpy as np
import pynput.keyboard as pkb
import pyperclip
import pystray
import sounddevice as sd
from PIL import Image, ImageDraw

import app_paths

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Runtime state (config.json, dictate.log, the lock file, hotwords, corrections,
# transcription history). In a checkout this is BASE_DIR, exactly as before; in
# a packaged build it is the per-user data folder, seeded from the bundled
# defaults on first run - see app_paths.
DATA_DIR = app_paths.ensure_initialized()

# The JSONL history file lives next to the config (see history_store).
HISTORY_PATH = os.path.join(DATA_DIR, "transcription-history.jsonl")

APP_NAME = "Whisper Dictate"

# Headless startup: hide any console window when launched with --headless
# (used by run.bat / run_hidden.vbs / Startup shortcut). pythonw.exe already
# has no console; this covers launches via python.exe or cmd.exe so no
# terminal window stays visible. Pass --console to keep the console.
HEADLESS = "--headless" in sys.argv or "--hide-console" in sys.argv

# Self-check mode: verifies the setup and exits before any listener, audio
# stream, GUI, or model load starts (see run_doctor).
DOCTOR = "--doctor" in sys.argv


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
    path = os.path.join(DATA_DIR, "config.json")
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception:
            cfg = {}
    return cfg


def _models_cached(cfg):
    cache = os.path.join(os.path.expanduser("~"), ".cache", "huggingface", "hub")
    # faster-whisper models live in "models--<org>--faster-whisper-<name>" (the
    # org differs per model: Systran, mobiuslabsgmbh, ...), so match on the repo
    # basename only. Full HF repo ids (containing "/") such as the Nemotron
    # engine use the plain "models--<org>--<repo>" directory.
    def _has(name):
        if not name:
            return True
        if "/" in name:
            pattern = os.path.join(cache, "models--" + name.replace("/", "--"))
        else:
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

# Size-capped so dictate.log cannot grow without bound (~1 MB after a week of
# dictation); two rotated backups are kept alongside it.
class _RotatingLog(RotatingFileHandler):
    """RotatingFileHandler that tolerates a locked log file.

    On Windows the rename in doRollover fails while another process holds
    dictate.log open (a --doctor run alongside a dictating instance, or an
    editor showing a rotated backup). Logging must never break dictation, so
    the rollover is skipped and retried on a later record instead.
    """

    def doRollover(self):
        try:
            super().doRollover()
        except OSError:
            pass


_log_handler = _RotatingLog(
    os.path.join(DATA_DIR, "dictate.log"),
    maxBytes=1_000_000,
    backupCount=2,
    encoding="utf-8",
)
_log_handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
logging.basicConfig(level=logging.INFO, handlers=[_log_handler])


def log(msg):
    """Log to the rotating file and, when a console exists, to stdout.

    Defined before any module-level work (the profile list is built at import
    time and can report a bad hotword/snippet file), so it must not depend on
    anything created further down this module.
    """
    logging.info(msg)
    try:
        # sys.stdout is None under pythonw.exe with no console - never crash there.
        if sys.stdout is not None:
            print(f"[dictate] {msg}", flush=True)
    except Exception:
        pass

# The single-instance guard is skipped for --doctor: the self-check must be
# runnable while another instance is dictating.
if not DOCTOR:
    if sys.platform == "win32":
        MUTEX_NAME = APP_NAME.replace(" ", "")
        _mutex = ctypes.windll.kernel32.CreateMutexW(None, False, MUTEX_NAME)
        if ctypes.windll.kernel32.GetLastError() in (183, 5):
            logging.info(
                "Another Whisper Dictate instance is already running - exiting."
            )
            try:
                if sys.stdout is not None:
                    print(
                        "Another Whisper Dictate instance is already running - exiting."
                    )
            except Exception:
                pass
            sys.exit(0)
    else:
        _LOCK_FILE = os.path.join(DATA_DIR, ".app.lock")
        try:
            _lf = os.open(_LOCK_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(_lf, str(os.getpid()).encode())
        except FileExistsError:
            logging.info(
                "Another Whisper Dictate instance is already running - exiting."
            )
            try:
                if sys.stdout is not None:
                    print(
                        "Another Whisper Dictate instance is already running - exiting."
                    )
            except Exception:
                pass
            sys.exit(0)

DEFAULTS = {
    "offline": True,
    "device": "auto",
    "compute_type": "auto",
    "audio_device": None,
    "samplerate": 16000,
    "capture_latency_s": 1.0,
    "beam_size": 5,
    "type_newline": True,
    "sound": True,
    "paste_last_hotkey": ["ctrl", "shift", "f12"],
    "scratch_hotkey": ["ctrl", "shift", "f13"],
    "fuzzy_hotwords": True,
    "fuzzy_hotword_min_score": 85,
    # Spoken punctuation ("comma", "new line", ...) and `snippets-*.txt` voice
    # expansions. Both rewrite ordinary words, so they stay off until asked for.
    "spoken_punctuation": False,
    "snippets_enabled": True,
    "paste_button_linger": 10,
    "model_idle_unload_minutes": 10,
    "profiles": [
        {
            "name": "EN",
            "hotkey": ["ctrl", "shift", "space"],
            "engine": "nemotron",
            "model": "nvidia/nemotron-speech-streaming-en-0.6b",
            "language": "en",
            "hotwords_file": "hotwords-en.txt",
            "snippets_file": "snippets-en.txt",
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
            "engine": "nemotron",
            "model": "nvidia/nemotron-3.5-asr-streaming-0.6b",
            "language": "de",
            "hotwords_file": "hotwords-de.txt",
            "snippets_file": "snippets-de.txt",
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
    path = os.path.join(DATA_DIR, "config.json")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            cfg.update(json.load(f))
    return cfg


def load_hotwords(path):
    full = app_paths.resolve_data_file(path)
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
    full = app_paths.resolve_data_file(path)
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


def load_snippets(path):
    """Load whole-utterance voice snippets ("trigger => expansion" lines)."""
    if not path:
        return {}
    full = app_paths.resolve_data_file(path)
    if not os.path.exists(full):
        return {}
    try:
        from text_tools import parse_snippets

        with open(full, "r", encoding="utf-8") as f:
            lines = [
                line.strip()
                for line in f
                if line.strip() and not line.strip().startswith("#")
            ]
        return parse_snippets(lines)
    except Exception as exc:
        log(f"Could not load snippets from {path}: {exc}")
        return {}


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


# --- Extension hooks --------------------------------------------------------
# Add-ons (transcription history) register callbacks here instead of
# duplicating and runtime-swapping on_press/on_release/transcribe_thread, so
# there is exactly one implementation of the keyboard/transcription flow.
# Every callback is invoked defensively: an exception in an add-on is logged
# and can never take down the keyboard hook or a transcription. A key press
# listener returns True to consume the event (later listeners and the
# built-in handling are skipped).
_press_listeners = []    # f(key_name) -> True if the press was consumed
_release_listeners = []  # f(key_name)
_text_listeners = []     # f(profile, text, duration_s) on a fresh transcription


def add_key_press_listener(fn):
    _press_listeners.append(fn)


def add_key_release_listener(fn):
    _release_listeners.append(fn)


def add_text_listener(fn):
    _text_listeners.append(fn)


def _reconcile_hotwords(text, profile):
    """Fuzzy hotword pass: rewrite near-misses to the canonical spellings.

    The Nemotron engines ignore hotwords-*.txt (no vocabulary biasing), so
    this makes the hotword files effective on every engine. Fail-safe: any
    problem in the pass is logged and the text returned unchanged.
    """
    if not text or not FUZZY_HOTWORDS or not profile.hotword_list:
        return text
    try:
        from hotword_fuzzy import reconcile

        return reconcile(
            text,
            profile.hotword_list,
            min_score=FUZZY_HOTWORD_MIN_SCORE,
            log=log,
        )
    except Exception as exc:
        log(f"[{profile.name}] Fuzzy hotword pass skipped: {exc}")
        return text


def _apply_text_tools(text, profile):
    """Voice snippets and spoken punctuation, straight after the hotwords.

    Runs last so a snippet or a spoken comma is never rewritten by the fuzzy
    hotword pass, and the fuzzy pass never fights a snippet's own spelling.
    Fail-safe: any problem here is logged and the text passes through.
    """
    if not text:
        return text
    snippets = profile.snippets if SNIPPETS_ENABLED else None
    if not SPOKEN_PUNCTUATION and not snippets:
        return text
    try:
        from text_tools import process_text

        return process_text(
            text,
            language=profile.language,
            spoken_punctuation=SPOKEN_PUNCTUATION,
            snippets=snippets,
        )
    except Exception as exc:
        log(f"[{profile.name}] Spoken punctuation/snippets skipped: {exc}")
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
        # "faster-whisper" (default) or "nemotron". A HF repo id (with "/")
        # implies the Nemotron engine even without an explicit "engine" key.
        self.engine = p.get("engine") or (
            "nemotron" if "/" in self.model else "faster-whisper"
        )
        self.language = p.get("language", "en")
        self.hotwords_file = p.get("hotwords_file", "hotwords.txt")
        self.hotwords = load_hotwords(self.hotwords_file)
        # Canonical spellings for the fuzzy hotword pass
        # (hotword_fuzzy.reconcile) so hotwords-*.txt also reaches engines
        # with no vocabulary biasing (Nemotron).
        self.hotword_list = self.hotwords.split()
        self.corrections_file = p.get("corrections_file") or f"corrections-{self.language}.txt"
        self.corrections = load_corrections(self.corrections_file)
        # Whole-utterance voice snippets ("insert signature" -> a stored block).
        # A profile without the key gets the conventional filename, so dropping
        # a snippets-<lang>.txt next to the config is enough to enable them.
        self.snippets_file = p.get("snippets_file") or f"snippets-{self.language}.txt"
        self.snippets = load_snippets(self.snippets_file)
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
recording = {
    "active": False,
    "profile": None,
    "until": 0.0,      # epoch time: keep capturing through the post-release drain
    "seq": 0,          # bumped on every start; aborts a stale drain finalizer
    "started": 0.0,    # epoch time of hotkey press (for stall accounting)
    "stopped": 0.0,    # epoch time of hotkey release
    "overflow_logged": False,
}
frames = []
frames_lock = threading.Lock()
# Seconds to keep capturing after the hotkey is released, so audio still
# sitting in the audio device's buffer reaches the transcript. With a big
# device buffer (capture_latency_s) this also lets a post-release catch-up
# burst deliver audio that was buffered during a callback stall.
CAPTURE_TAIL_DRAIN_S = 0.5
# Set while a recording waits for its drain; lets a fast re-press finalize the
# previous dictation immediately instead of losing it.
_pending = {"seq": None, "profile": None}
_finish_lock = threading.Lock()
pressed = set()
last_text = None
last_profile = None
last_typed_text = None  # exact string last typed, for the scratch hotkey
paste_last_fired = False
scratch_fired = False
PASTE_LAST_HOTKEY = list(cfg.get("paste_last_hotkey") or [])
# Erase-the-last-dictation hotkey ("scratch that").
SCRATCH_HOTKEY = list(cfg.get("scratch_hotkey") or [])
# Fuzzy hotword reconciliation after transcription (see hotword_fuzzy).
FUZZY_HOTWORDS = bool(cfg.get("fuzzy_hotwords", True))
FUZZY_HOTWORD_MIN_SCORE = int(cfg.get("fuzzy_hotword_min_score", 85))
# Spoken punctuation ("comma" -> ",") and voice snippets (see text_tools).
SPOKEN_PUNCTUATION = bool(cfg.get("spoken_punctuation", False))
SNIPPETS_ENABLED = bool(cfg.get("snippets_enabled", True))
# Seconds the paste button stays up after a fresh transcription before it
# fades out (the Ctrl+Shift+F12 hotkey keeps working either way).
PASTE_BUTTON_LINGER = float(cfg.get("paste_button_linger", 10))
# 0-255 pill opacity; it never intercepts clicks either way.
PILL_ALPHA = int(cfg.get("pill_alpha", 150))
# Seconds an error pill stays readable before the idle hide takes effect.
ERROR_VISIBLE_S = float(cfg.get("error_visible_s", 6))
# Minutes of inactivity after which loaded Whisper models are dropped from RAM
# (0 disables unloading). CTranslate2 keeps freed memory resident, so without
# this the process stays at its post-transcription high-water mark forever.
MODEL_IDLE_UNLOAD_S = float(cfg.get("model_idle_unload_minutes", 10)) * 60
model_use_time = time.time()

STATUS_QUEUE = queue.Queue()
OVERLAY_ROOT = None

STATE_COLORS = {
    "listening": "#ff4d4d",
    "transcribing": "#ffb340",
    "loading": "#7aa2ff",
    "typing": "#4dd07f",
    "error": "#ff5555",
}


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
        # Idle: show nothing. The hotkey reference lives in the tray menu.
        STATUS_QUEUE.put(("hide",))
        return
    text = f"{profile.name} {profile.label(state)}"
    if detail:
        text += f" {detail}"
    STATUS_QUEUE.put(("show", state, STATE_COLORS[state], text))


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
        self.error_until = 0.0  # epoch seconds the error pill stays readable
        self.hide_pending = False
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
                else:  # "hide"
                    self._hide()
        except queue.Empty:
            pass
        if self.hide_pending and time.time() >= self.error_until:
            self.hide_pending = False
            self.root.withdraw()
        self._track_target()
        self._refresh_paste_button_pos()
        self.root.after(120, self._poll)

    def _hide(self):
        """Idle: withdraw the pill, but keep a fresh error readable a moment."""
        if time.time() < self.error_until:
            self.hide_pending = True
        else:
            self.root.withdraw()

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

    def _show(self, state, color, text):
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        self.dot.config(fg=color)
        self.txt.config(text=text)
        self.hide_pending = False
        self.error_until = time.time() + ERROR_VISIBLE_S if state == "error" else 0.0
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
    global paste_last_fired, scratch_fired
    n = key_name(key)
    if n is None:
        return
    pressed.add(n)
    # Add-on hotkeys (e.g. transcription history) run before everything else
    # and may consume the press.
    for fn in _press_listeners:
        try:
            if fn(n):
                return
        except Exception as exc:
            log(f"Key press listener failed: {exc}")
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
        return
    if SCRATCH_HOTKEY and not scratch_fired and set(SCRATCH_HOTKEY) <= pressed:
        scratch_fired = True
        scratch_last()


def on_release(key):
    global paste_last_fired, scratch_fired
    n = key_name(key)
    if n is None:
        return
    pressed.discard(n)
    for fn in _release_listeners:
        try:
            fn(n)
        except Exception as exc:
            log(f"Key release listener failed: {exc}")
    if recording["active"] and not (set(recording["profile"].hotkey) <= pressed):
        stop_recording()
    if not set(PASTE_LAST_HOTKEY) <= pressed:
        paste_last_fired = False
    if not set(SCRATCH_HOTKEY) <= pressed:
        scratch_fired = False


def audio_callback(indata, frames_cnt, time_info, status):
    if status and recording["active"] and not recording["overflow_logged"]:
        # PortAudio had to drop or replace audio because this process could not
        # service the callback in time. Without this, the loss is invisible:
        # the recording just starts a word or two into the sentence.
        recording["overflow_logged"] = True
        log(
            f"[{recording['profile'].name}] Audio input overflow ({status}) - "
            "audio may be missing from this recording"
        )
    # Keep appending through the post-release drain so audio that was still in
    # the device's buffer when the hotkey went up is not thrown away.
    if recording["active"] or time.time() < recording["until"]:
        with frames_lock:
            frames.append(indata[:, 0].copy())


def start_recording(profile):
    _flush_pending()
    recording["seq"] += 1
    recording["until"] = 0.0
    recording["started"] = time.time()
    recording["overflow_logged"] = False
    with frames_lock:
        frames.clear()
    recording["active"] = True
    recording["profile"] = profile
    beep(880)
    show_state("listening", profile)
    log(f"[{profile.name}] Recording... release {profile.hotkey_str()} to transcribe")
    # The model may have been dropped after the idle timeout: start loading it
    # now, while the user is still speaking, so a release only has to decode
    # the audio instead of waiting for the load first.
    if profile.model_obj is None:
        threading.Thread(
            target=preload_model_during_recording,
            args=(profile,),
            daemon=True,
            name=f"preload-{profile.name}",
        ).start()


def stop_recording():
    profile = recording["profile"]
    recording["active"] = False
    recording["until"] = time.time() + CAPTURE_TAIL_DRAIN_S
    recording["stopped"] = time.time()
    _pending["seq"] = recording["seq"]
    _pending["profile"] = profile
    beep(440)
    log(f"[{profile.name}] Recording stopped")
    timer = threading.Timer(
        CAPTURE_TAIL_DRAIN_S, _finish_recording, args=(recording["seq"], profile)
    )
    timer.daemon = True
    timer.start()


def _finish_recording(seq, profile):
    with _finish_lock:
        if _pending["seq"] != seq:
            return  # already finalized early by a new hotkey press
        _pending["seq"] = None
        _pending["profile"] = None
        with frames_lock:
            buf = list(frames)
            frames.clear()
    _transcribe_captured(profile, buf)


def _flush_pending():
    """A new press during the drain window: finalize the last dictation now.

    Without this, re-pressing within CAPTURE_TAIL_DRAIN_S of a release would
    silently discard the previous dictation (the pending drain owns the frame
    buffer that start_recording is about to clear).
    """
    with _finish_lock:
        seq = _pending["seq"]
        profile = _pending["profile"]
        if seq is None:
            return
        _pending["seq"] = None
        _pending["profile"] = None
        with frames_lock:
            buf = list(frames)
            frames.clear()
    _transcribe_captured(profile, buf)


def _transcribe_captured(profile, buf):
    hold = recording.get("stopped", 0) - recording.get("started", 0)
    captured = sum(len(b) for b in buf) / cfg["samplerate"]
    if hold > 0 and hold - captured > 0.15:
        log(
            f"[{profile.name}] WARNING: {hold - captured:.2f}s of the {hold:.2f}s "
            "hold was lost to audio stalls (see overflow warnings above)"
        )
    log(f"[{profile.name}] Recording stopped, {len(buf)} chunks captured")
    if not buf:
        show_state("ready")
        return
    threading.Thread(target=transcribe_thread, args=(profile, buf), daemon=True).start()


def get_model(profile):
    with model_lock:
        if profile.model_obj is None:
            t0 = time.time()
            show_state("loading", profile)
            log(f"[{profile.name}] Loading model '{profile.model}' ({profile.engine})...")
            if profile.engine == "nemotron":
                # Imported lazily: torch/transformers take a while to import
                # and are only needed for Nemotron profiles.
                from nemotron_engine import NemotronModel

                profile.model_obj = NemotronModel(
                    profile.model, device=DEVICE, compute_type=COMPUTE, log=log
                )
            else:
                from faster_whisper import WhisperModel

                profile.model_obj = WhisperModel(
                    profile.model, device=DEVICE, compute_type=COMPUTE
                )
            log(f"[{profile.name}] Model loaded in {time.time()-t0:.1f}s")
        touch_model_use()
        return profile.model_obj


def preload_model_during_recording(profile):
    """Load the profile's model in the background as soon as the hotkey is held.

    Recording runs in parallel, so the load overlaps with speaking instead of
    delaying transcription after the release. ``get_model`` holds
    ``model_lock`` for the whole load, so a release that arrives first simply
    waits for this same in-flight load - it never starts a second one.
    """
    try:
        get_model(profile)
    except Exception as e:
        log(f"[{profile.name}] Model preload failed: {e}")
        logging.exception(f"[{profile.name}] Model preload failed")
    finally:
        # Loading set the pill to "Loading model…"; if the user is still
        # holding the hotkey, give the pill back to the recording state.
        if recording["active"] and recording["profile"] is profile:
            show_state("listening", profile)


def touch_model_use():
    global model_use_time
    model_use_time = time.time()


def unload_models():
    """Drop every loaded model so the OS/GPU reclaims the memory.

    In-flight transcriptions keep their own reference to the model object, so
    an unload during inference is safe - the memory is freed once it finishes.
    """
    unloaded = []
    with model_lock:
        for p in profiles:
            if p.model_obj is not None:
                p.model_obj = None
                unloaded.append(p.model)
        if unloaded:
            # Nemotron models hold VRAM; torch only returns it on request.
            torch = sys.modules.get("torch")
            if torch is not None:
                try:
                    if torch.cuda.is_available():
                        torch.cuda.empty_cache()
                except Exception:
                    pass
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
        text = _reconcile_hotwords(text, profile)
        text = _apply_text_tools(text, profile)
        done.set()
        duration = audio.size / cfg["samplerate"]
        log(
            f"[{profile.name}] Transcribed {duration:.1f}s audio in {time.time()-t0:.1f}s"
        )
        if not text:
            return
        last_text = text
        last_profile = profile
        # Add-ons (e.g. history) see the final text before it is typed.
        for fn in _text_listeners:
            try:
                fn(profile, text, duration)
            except Exception as exc:
                log(f"Transcription listener failed: {exc}")
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


def _type_keystrokes(text):
    """Type text as simulated keystrokes (fallback when pasting fails)."""
    ctrl = pkb.Controller()
    ctrl.typewrite(text, interval=0.005)


def type_text(text):
    global last_typed_text
    if cfg.get("type_newline"):
        text += "\n"
    # Tracked before typing starts so the scratch hotkey can undo this
    # dictation even if the paste only partially worked.
    last_typed_text = text
    old_clip = None
    try:
        old_clip = pyperclip.paste()
    except Exception:
        old_clip = None
    try:
        pyperclip.copy(text)
        # Clipboard managers or policies can silently drop synthetic writes;
        # detect that and fall back to typing instead of pasting nothing.
        if pyperclip.paste() != text:
            raise RuntimeError("clipboard did not accept the text")
    except Exception as exc:
        log(f"Clipboard paste failed ({exc}); falling back to simulated keystrokes")
        try:
            _type_keystrokes(text)
        except Exception as exc2:
            log(f"Keystroke fallback failed too: {exc2}")
        return
    time.sleep(0.05)
    try:
        ctrl = pkb.Controller()
        ctrl.press(pkb.Key.ctrl)
        ctrl.tap("v")
        ctrl.release(pkb.Key.ctrl)
    except Exception as exc:
        log(f"Ctrl+V failed ({exc}); trying simulated keystrokes")
        try:
            _type_keystrokes(text)
        except Exception as exc2:
            log(f"Keystroke fallback failed too: {exc2}")
            return
    # Restore the user's previous clipboard once the target app had a moment
    # to read the paste - but never clobber a newer copy they made themselves.
    if old_clip is not None:
        def _restore():
            time.sleep(0.4)
            try:
                if pyperclip.paste() == text:
                    pyperclip.copy(old_clip)
            except Exception:
                pass

        threading.Thread(target=_restore, daemon=True, name="clipboard-restore").start()


def _send_backspaces(count):
    ctrl = pkb.Controller()
    # One tap at a time, with short breaks so the OS event queue and the
    # target app can keep up even for long dictations.
    for i in range(count):
        ctrl.tap(pkb.Key.backspace)
        if i % 20 == 19:
            time.sleep(0.01)


def scratch_last():
    """Erase the most recently typed transcription with backspaces."""
    global last_typed_text
    if not last_typed_text:
        log("Scratch: nothing typed to erase yet")
        return
    count = len(last_typed_text)
    last_typed_text = None
    log(f"Scratching last transcription ({count} characters)")
    try:
        _send_backspaces(count)
        beep(220)
    except Exception as exc:
        log(f"Scratch failed: {exc}")


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
        p.hotword_list = p.hotwords.split()
        p.corrections = load_corrections(p.corrections_file)
        p.snippets = load_snippets(p.snippets_file)
    log("Hotwords, corrections and snippets reloaded")
    if icon:
        icon.notify("Hotwords, corrections and snippets reloaded", APP_NAME)


def _run_on_ui_thread(fn, why="UI action"):
    """Run a Tk call on the main thread.

    Hotkeys and the tray menu fire on other threads (pynput's listener, pystray's
    backend) and Tk only tolerates widget calls from the thread that created the
    root, so every window is opened through here.
    """
    root = OVERLAY_ROOT
    if root is None:
        log(f"{why} ignored: the UI is not up yet")
        return
    try:
        root.after(0, fn)
    except Exception as exc:
        log(f"Could not schedule {why}: {exc}")


def _ui_call(fn, why):
    def wrapped():
        try:
            fn()
        except Exception as exc:
            log(f"{why} failed: {exc}")

    _run_on_ui_thread(wrapped, why)


def open_history_browser(icon=None, item=None):
    """Tk history browser (search, copy, re-paste, delete)."""
    import desktop_ui

    _ui_call(
        lambda: desktop_ui.open_history_window(
            OVERLAY_ROOT, HISTORY_PATH, on_paste=type_text
        ),
        "Opening the history window",
    )


def open_settings(icon=None, item=None):
    """Tk settings window for the config keys that matter day to day."""
    import desktop_ui

    _ui_call(
        lambda: desktop_ui.open_settings_window(
            OVERLAY_ROOT,
            os.path.join(DATA_DIR, "config.json"),
            on_saved=reload_settings,
            on_reload_hotwords=reload_hotwords,
        ),
        "Opening the settings window",
    )


def reload_settings():
    """Re-read config.json after the settings window saved it.

    Only the keys that can change without restarting a model or the keyboard
    listener are applied; the window says as much in its status line.
    """
    global SPOKEN_PUNCTUATION, SNIPPETS_ENABLED, PASTE_BUTTON_LINGER
    try:
        with open(os.path.join(DATA_DIR, "config.json"), "r", encoding="utf-8") as f:
            fresh = json.load(f)
    except Exception as exc:
        log(f"Could not re-read config.json: {exc}")
        return
    cfg.update(fresh)
    SPOKEN_PUNCTUATION = bool(cfg.get("spoken_punctuation", False))
    SNIPPETS_ENABLED = bool(cfg.get("snippets_enabled", True))
    PASTE_BUTTON_LINGER = float(cfg.get("paste_button_linger", 10))
    reload_hotwords()
    log("Settings reloaded from config.json")


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


def run_doctor():
    """--doctor: verify the setup and print a pass/fail summary, then exit.

    Runs before the keyboard listener, audio stream, GUI, and any model load
    start, so it is safe to use while another instance is dictating. Nothing
    is downloaded and no model is loaded.
    """
    if sys.stdout is None and not app_paths.is_frozen():
        logging.info("doctor: no console attached - run with python.exe")
        sys.exit(2)
    results = []
    result_rows = []

    def _say(text):
        """print() that tolerates a frozen windowed build (stdout is None)."""
        try:
            if sys.stdout is not None:
                print(text)
        except Exception:
            pass

    def check(name, ok, detail=""):
        ok = bool(ok)
        results.append(ok)
        result_rows.append((ok, name, detail))
        line = f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" - {detail}" if detail else "")
        _say(line)
        logging.info("doctor: %s", line)

    _say(f"{APP_NAME} doctor - device={DEVICE} compute={COMPUTE}")

    # Config
    try:
        with open(os.path.join(DATA_DIR, "config.json"), "r", encoding="utf-8") as f:
            file_cfg = json.load(f)
        check("config.json parses", True, f"{len(file_cfg)} top-level keys")
    except FileNotFoundError:
        check("config.json parses", True, "missing - using built-in defaults")
    except Exception as exc:
        check("config.json parses", False, str(exc))

    # Dependencies
    for mod in ("faster_whisper", "sounddevice", "pynput", "pyperclip", "pystray"):
        try:
            __import__(mod)
            check(f"{mod} importable", True)
        except Exception as exc:
            check(f"{mod} importable", False, str(exc))
    try:
        import torch

        check(
            "torch importable (nemotron engine)",
            True,
            f"{torch.__version__}, CUDA available: {bool(torch.cuda.is_available())}",
        )
    except Exception as exc:
        check("torch importable (nemotron engine)", False, str(exc))

    # Microphone
    try:
        inputs = [
            d for d in sd.query_devices() if d.get("max_input_channels", 0) > 0
        ]
        check("microphone access", bool(inputs), f"{len(inputs)} input device(s)")
        configured = cfg.get("audio_device")
        if configured not in (None, ""):
            names = [str(d.get("name", "")) for d in inputs]
            ok = isinstance(configured, int) and configured < len(inputs) or any(
                str(configured) == n or str(configured) in n for n in names
            )
            check("configured audio_device exists", ok, f"audio_device={configured!r}")
    except Exception as exc:
        check("microphone access", False, str(exc))

    # Model caches (never downloads; only checks the HF cache directory)
    for p in profiles:
        cached = _models_cached({"profiles": [{"model": p.model}]})
        check(
            f"model cached: {p.model}",
            cached,
            "start once with internet access to download" if not cached else "",
        )

    # Hotkey conflicts across every registered global hotkey
    hotkeys = [(f"profile {p.name}", p.hotkey) for p in profiles]
    hotkeys.append(("paste last", PASTE_LAST_HOTKEY))
    hotkeys.append(("scratch that", SCRATCH_HOTKEY))
    hotkeys.append(("history", list(cfg.get("history_hotkey") or [])))
    seen, dups = {}, []
    for label, combo in hotkeys:
        if not combo:
            continue
        key = tuple(sorted(combo))
        if key in seen:
            dups.append(f"{label} shares {'+'.join(sorted(combo))} with {seen[key]}")
        else:
            seen[key] = label
    check("hotkey conflicts", not dups, "; ".join(dups) or "none")

    # Hotword / correction files
    raw_profiles = cfg.get("profiles") or []
    for i, p in enumerate(profiles):
        raw = raw_profiles[i] if i < len(raw_profiles) else {}
        hw_path = p.hotwords_file if os.path.isabs(p.hotwords_file) else app_paths.resolve_data_file(p.hotwords_file)
        if os.path.exists(hw_path):
            check(f"hotwords file ({p.name})", True, f"{len(p.hotword_list)} entries")
        elif raw.get("hotwords_file"):
            check(f"hotwords file ({p.name})", False, f"{p.hotwords_file} configured but missing")
        else:
            check(f"hotwords file ({p.name})", True, "not configured (optional)")
        corr_path = p.corrections_file if os.path.isabs(p.corrections_file) else app_paths.resolve_data_file(p.corrections_file)
        check(
            f"corrections file ({p.name})",
            True,
            f"{len(p.corrections)} rules"
            + ("" if os.path.exists(corr_path) else " (file missing - no rules)"),
        )
        snippets_path = (
            p.snippets_file
            if os.path.isabs(p.snippets_file)
            else app_paths.resolve_data_file(p.snippets_file)
        )
        check(
            f"snippets file ({p.name})",
            True,
            f"{len(p.snippets)} snippets"
            + ("" if os.path.exists(snippets_path) else " (file missing - no snippets)"),
        )
    check(
        "spoken punctuation",
        True,
        "enabled" if SPOKEN_PUNCTUATION else "off (say \"comma\" as a literal word)",
    )
    check("data folder", True, DATA_DIR)

    # Environment
    try:
        pyperclip.paste()
        check("clipboard access", True)
    except Exception as exc:
        check("clipboard access", False, str(exc))
    check("data folder writable", os.access(DATA_DIR, os.W_OK), DATA_DIR)

    failed = results.count(False)
    summary = f"\n{len(results) - failed}/{len(results)} checks passed."
    _say(summary)
    if failed:
        _say("Fix the FAIL items above, then start the app as usual.")

    # A frozen windowed build has no console: --doctor would report into the
    # void, so write the same summary where the user (and the release scripts)
    # can read it. Never fail the run over the report itself.
    if app_paths.is_frozen():
        try:
            report = os.path.join(DATA_DIR, "doctor-report.txt")
            with open(report, "w", encoding="utf-8") as f:
                f.write(f"{APP_NAME} doctor - device={DEVICE} compute={COMPUTE}\n")
                f.write(f"python={sys.version.split()[0]} frozen={app_paths.is_frozen()}\n")
                f.write(f"data folder={DATA_DIR}\n\n")
                for ok, name, detail in result_rows:
                    f.write(
                        f"[{'PASS' if ok else 'FAIL'}] {name}"
                        + (f" - {detail}" if detail else "")
                        + "\n"
                    )
                f.write(summary + "\n")
            _say(f"Report written to {report}")
        except Exception as exc:
            _say(f"Could not write the doctor report: {exc}")
    sys.exit(1 if failed else 0)


def _hotkey_menu_items():
    """Informational (disabled) menu lines listing every global hotkey.

    The status pill only shows during activity now, so the tray menu is the
    always-available reference for the keybinds.
    """
    items = [pystray.MenuItem("Hotkeys", None, enabled=False)]
    for p in profiles:
        items.append(
            pystray.MenuItem(
                lambda item, prof=p: f"   {prof.name} dictate  {prof.hotkey_str()}",
                None,
                enabled=False,
            )
        )
    extras = [("Paste last", PASTE_LAST_HOTKEY), ("Scratch that", SCRATCH_HOTKEY)]
    if cfg.get("history_enabled", True):
        extras.append(("History", list(cfg.get("history_hotkey") or [])))
    for label, keys in extras:
        if keys:
            items.append(
                pystray.MenuItem(
                    lambda item, label=label, keys=tuple(keys): "   "
                    + label
                    + "  "
                    + " + ".join(_display_key(k) for k in keys),
                    None,
                    enabled=False,
                )
            )
    return items


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
    # sounddevice's default maps to a ~26 ms device buffer: any callback stall
    # longer than that (model load, CPU wake-up from idle, background scan)
    # silently drops audio - the recorded clip then starts a word or two into
    # the sentence. A generous buffer absorbs such stalls instead. Measured on
    # WASAPI: the device buffers roughly the requested latency, so 1.0 s covers
    # twice the worst stall seen in dictate.log (0.54 s). Setting 0 or null
    # keeps the sounddevice default.
    capture_latency = cfg.get("capture_latency_s")
    if capture_latency:
        stream_kwargs["latency"] = float(capture_latency)
    if input_device not in (None, ""):
        stream_kwargs["device"] = input_device
        log(f"Using configured microphone device: {input_device}")

    # Degrade gracefully: prefer the configured device and the generous
    # latency, but fall back to defaults if a device rejects either.
    stream = None
    devices = [input_device, None] if input_device not in (None, "") else [None]
    latencies = [stream_kwargs.get("latency"), None]
    last_exc = None
    for dev in devices:
        for lat in latencies:
            kw = dict(stream_kwargs)
            if lat is not None:
                kw["latency"] = lat
            else:
                kw.pop("latency", None)
            if dev is not None:
                kw["device"] = dev
            else:
                kw.pop("device", None)
            try:
                stream = sd.InputStream(**kw)
                stream.start()
                break
            except Exception as exc:
                last_exc = exc
                log(f"Audio stream open failed (device={dev!r}, latency={lat!r}): {exc}")
        if stream is not None:
            break
    if stream is None:
        raise last_exc

    # Shorter GIL hand-off quantum: the audio callback shares the interpreter
    # with the Tk UI and the model-load threads, and every millisecond it waits
    # for the GIL comes straight out of the device buffer's stall headroom.
    sys.setswitchinterval(0.001)

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
        *_hotkey_menu_items(),
        pystray.MenuItem("Transcription history…", open_history_browser),
        pystray.MenuItem("Settings…", open_settings),
        pystray.Menu.SEPARATOR,
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
    if DOCTOR:
        run_doctor()
    else:
        main()
