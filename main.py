import ctypes
import json
import logging
import os
import queue
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
    names = {
        "models--Systran--faster-whisper-" + p["model"]
        for p in cfg.get("profiles") or []
        if p.get("model")
    }
    if not names:
        return False
    return all(os.path.isdir(os.path.join(cache, n)) for n in names)


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

if sys.platform == "win32":
    MUTEX_NAME = APP_NAME.replace(" ", "")
    _mutex = ctypes.windll.kernel32.CreateMutexW(None, False, MUTEX_NAME)
    if ctypes.windll.kernel32.GetLastError() in (183, 5):
        print("Another Whisper Dictate instance is already running - exiting.")
        sys.exit(0)
else:
    _LOCK_FILE = os.path.join(BASE_DIR, ".app.lock")
    try:
        _lf = os.open(_LOCK_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(_lf, str(os.getpid()).encode())
    except FileExistsError:
        print("Another Whisper Dictate instance is already running - exiting.")
        sys.exit(0)

logging.basicConfig(
    filename=os.path.join(BASE_DIR, "dictate.log"),
    level=logging.INFO,
    format="%(asctime)s %(message)s",
)

DEFAULTS = {
    "offline": True,
    "device": "auto",
    "compute_type": "auto",
    "audio_device": None,
    "samplerate": 16000,
    "beam_size": 2,
    "type_newline": True,
    "sound": True,
    "paste_last_hotkey": ["ctrl", "shift", "f12"],
    "profiles": [
        {
            "name": "EN",
            "hotkey": ["ctrl", "shift", "space"],
            "model": "small.en",
            "language": "en",
            "hotwords_file": "hotwords-en.txt",
            "prompt_prefix": (
                "Transcribe the following technical dictation. "
                "The terms below are expected and important:"
            ),
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
            "prompt_prefix": (
                "Transkribiere die folgende technische Diktation. "
                "Folgende Begriffe sind wichtig und werden erwartet:"
            ),
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
        self.hotwords_file = p.get("hotwords_file", "hotwords.txt")
        self.hotwords = load_hotwords(self.hotwords_file)
        self.prompt_prefix = p.get(
            "prompt_prefix",
            "Transcribe the following technical dictation. "
            "The terms below are expected and important:",
        )
        self.initial_prompt = (self.prompt_prefix + " " + self.hotwords).strip()
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
    print(f"[dictate] {msg}", flush=True)


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

    def _refresh_paste_button(self, pill_x, pill_y, pill_w, pill_h):
        if last_text is None:
            self.pb_win.withdraw()
            return
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
        try:
            GWL_EXSTYLE = -20
            hwnd = self.root.winfo_id()
            styles = ctypes.windll.user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
            styles |= 0x20 | 0x80000 | 0x08000000 | 0x80
            ctypes.windll.user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, styles)
            LWA_ALPHA = 0x2
            ctypes.windll.user32.SetLayeredWindowAttributes(hwnd, 0, 255, LWA_ALPHA)
        except Exception:
            pass

    def _poll(self):
        try:
            while True:
                item = STATUS_QUEUE.get_nowait()
                if item[0] == "show":
                    self._show(*item[1:])
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
            own = {self.root.winfo_id(), self.pb_win.winfo_id()}
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
        return profile.model_obj


def transcribe_thread(profile, buf):
    global last_text, last_profile
    try:
        audio = np.concatenate(buf) if buf else np.zeros(0, dtype=np.float32)
        audio = np.ascontiguousarray(audio, dtype=np.float32)
        if audio.size == 0:
            show_state("ready")
            return
        m = get_model(profile)
        done = threading.Event()

        def watchdog():
            t0 = time.time()
            while not done.wait(5):
                log(f"[{profile.name}] STALL WATCH: transcribing for {time.time()-t0:.0f}s so far")

        threading.Thread(target=watchdog, daemon=True).start()
        t0 = time.time()
        show_state("transcribing", profile)
        segments, _info = m.transcribe(
            audio,
            language=profile.language,
            beam_size=cfg.get("beam_size", 2),
            initial_prompt=profile.initial_prompt,
            hotwords=profile.hotwords,
            vad_filter=True,
        )
        parts = [seg.text.strip() for seg in segments]
        text = " ".join(parts).strip()
        done.set()
        log(
            f"[{profile.name}] Transcribed {audio.size/cfg['samplerate']:.1f}s audio in {time.time()-t0:.1f}s"
        )
        if not text:
            return
        last_text = text
        last_profile = profile
        show_state("typing", profile)
        type_text(text)
        beep(1320)
    except Exception as e:
        done.set()
        show_state("error", profile)
        log(f"[{profile.name}] Error: {e}")
        import traceback

        traceback.print_exc()
    finally:
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
        p.initial_prompt = (p.prompt_prefix + " " + p.hotwords).strip()
    log("Hotwords reloaded")
    if icon:
        icon.notify("Hotwords reloaded", APP_NAME)


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
    log(f"{APP_NAME} - device={DEVICE} compute={COMPUTE}")
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

    threading.Thread(target=get_model, args=(profiles[0],), daemon=True).start()

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
