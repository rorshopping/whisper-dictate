"""macOS platform support for Whisper Dictate.

Everything Darwin-specific lives in this module, so upstream's main.py can
stay untouched: ``launcher.py`` runs :func:`prepare` before importing main and
:func:`install` after, and the macOS behaviour is applied at runtime.

Each piece exists because of a concrete macOS problem:

* :func:`prepare` reclaims a stale ``.app.lock``. The single-instance guard is
  a bare lock file (macOS has no kernel mutex), so a force-quit leaves the file
  behind and would otherwise block every later start.
* pystray's Darwin backend creates ``NSApplication.sharedApplication()`` in
  ``Icon.__init__``. If that happens before Tk creates its application, Tk
  later crashes with ``-[NSApplication macOSVersion]: unrecognized selector``.
  The Tk root is therefore created (and then reused by the status overlay)
  before any ``pystray.Icon`` exists.
* pynput's Controller (CGEventPost) and pyperclip are not safe to call from the
  worker threads main.py transcribes on, so all synthetic input is dispatched
  to the Tk main loop.
* The always-on-top pill can be frontmost when the text is pasted and would
  swallow it, so the app that was focused when dictation started is
  re-activated first and Cmd+V is sent through System Events (macOS asks for
  the Automation -> System Events permission on the first paste).
* ``"device": "auto"`` resolves to the Apple GPU (MPS) when torch offers it,
  with a logged fallback to the CPU if a model cannot be loaded there.

Only imported on Darwin (see launcher.py); on Windows none of this runs.
"""

import atexit
import ctypes
import ctypes.util
import os
import queue
import subprocess
import sys
import threading
import time
import tkinter

import app_paths

BASE_DIR = app_paths.data_dir()
LOCK_FILE = app_paths.lock_path()

_installed = False
_main_thread = threading.main_thread()
_ui_queue = queue.Queue()
_state = {
    "root": None,         # the single Tk root, created before AppKit is touched
    "target_app": None,   # NSApplication focused when dictation started
}


def _log(message):
    """Log through main when it is imported, else straight to stderr."""
    main_mod = sys.modules.get("main")
    if main_mod is not None:
        try:
            main_mod.log(message)
            return
        except Exception:
            pass
    try:
        print(f"[dictate] {message}", file=sys.stderr, flush=True)
    except Exception:
        pass


# --- stale lock recovery ----------------------------------------------------


def _lock_is_stale():
    """True when .app.lock was left behind by a process that is gone.

    macOS has no kernel mutex, so a force-quit (or a crash, or SIGTERM - Python
    signal handlers cannot run while Tk is inside the Cocoa event loop) leaves
    the file behind; it must not block every later start.
    """
    try:
        age = time.time() - os.path.getmtime(LOCK_FILE)
    except OSError:
        return False
    try:
        with open(LOCK_FILE, "r", encoding="utf-8") as f:
            pid = int((f.read() or "0").strip())
    except (OSError, ValueError):
        # Garbled content: a crash while creating it. Only reclaim once it is
        # clearly not from a start happening right now.
        return age > 10.0
    if pid <= 0:
        return age > 10.0
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    except OSError:
        return False  # alive, owned by another user, or otherwise unclear
    return False


def _remove_own_lock():
    """atexit: remove .app.lock, but only while it is still ours."""
    try:
        with open(LOCK_FILE, "r", encoding="utf-8") as f:
            pid = int((f.read() or "0").strip())
    except (OSError, ValueError):
        return
    if pid != os.getpid():
        return  # another instance owns it (this process lost the race)
    try:
        os.remove(LOCK_FILE)
    except OSError:
        pass


def _install_signal_cleanup():
    """Best-effort cleanup for SIGTERM.

    NOTE: with Tk's Cocoa mainloop running, a Python signal handler cannot
    execute (the interpreter stays inside the run loop), so this is only a
    safety net for the pre-mainloop window. A hard kill after that is covered
    by :func:`_lock_is_stale` on the next start.
    """
    import signal

    def handler(signum, frame):
        _remove_own_lock()
        signal.signal(signum, signal.SIG_DFL)
        os.kill(os.getpid(), signum)  # die with the original signal

    try:
        signal.signal(signal.SIGTERM, handler)
    except (ValueError, OSError):
        pass


def prepare():
    """Reclaim a stale lock and remove ours on exit (call before importing main)."""
    atexit.register(_remove_own_lock)
    _install_signal_cleanup()
    if not os.path.exists(LOCK_FILE):
        return
    if not _lock_is_stale():
        return
    _log("macOS: reclaiming stale .app.lock from a previous run")
    try:
        os.remove(LOCK_FILE)
    except OSError as exc:
        _log(f"macOS: could not remove the stale lock: {exc}")


# --- Tk / AppKit ordering ---------------------------------------------------


def _reuse_root(*args, **kwargs):
    return _state["root"]


def _ensure_tk_root():
    """Create (or reuse) the Tk root before AppKit gets its NSApplication.

    Tk must be the process that creates the shared NSApplication: if pystray's
    Darwin backend calls ``NSApplication.sharedApplication()`` first, Tk later
    crashes with ``-[NSApplication macOSVersion]: unrecognized selector``.
    The root is handed to every later ``tk.Tk()`` call so the app keeps running
    on a single Tk application (main's StatusOverlay would otherwise create a
    second one).
    """
    if _state["root"] is not None:
        return _state["root"]
    root = getattr(tkinter, "_default_root", None)
    if root is None:
        root = tkinter.Tk()
        root.withdraw()
        tkinter.Tk = _reuse_root
        _log("macOS: created the Tk root before AppKit (startup order fix)")
    _state["root"] = root
    return root


def _wrap_icon_init(icon_cls):
    original = icon_cls.__init__

    def __init__(self, *args, **kwargs):
        _ensure_tk_root()  # must happen before NSApplication.sharedApplication()
        return original(self, *args, **kwargs)

    icon_cls.__init__ = __init__


# --- main-thread dispatch ---------------------------------------------------


def _drain_ui_queue():
    while True:
        try:
            action = _ui_queue.get_nowait()
        except queue.Empty:
            break
        try:
            action()
        except Exception as exc:
            _log(f"macOS: deferred action failed: {exc}")
    root = _state["root"]
    if root is not None:
        try:
            root.after(120, _drain_ui_queue)
        except Exception:
            pass  # Tk is shutting down


def _run_on_ui(fn):
    """Run fn on the Tk main thread; worker threads only queue it."""
    if threading.current_thread() is _main_thread:
        fn()
        return
    if _state["root"] is None:
        # No Tk yet (should not happen once the app runs): best effort.
        fn()
        return
    _ui_queue.put(fn)


def _wrap_status_overlay(overlay_cls):
    original = overlay_cls.__init__

    def __init__(self, *args, **kwargs):
        original(self, *args, **kwargs)
        _state["root"] = self.root
        self.root.after(120, _drain_ui_queue)
        _warn_if_input_blocked()

    overlay_cls.__init__ = __init__


def _wrap_type_text(main_mod):
    original = main_mod.type_text

    def type_text(text):
        """main.type_text, but always on the Tk main thread (see module doc)."""
        _run_on_ui(lambda: original(text))

    main_mod.type_text = type_text


def _wrap_scratch_last(main_mod):
    original = main_mod.scratch_last

    def scratch_last():
        """main.scratch_last, but always on the Tk main thread."""
        _run_on_ui(original)

    main_mod.scratch_last = scratch_last


def _wrap_tap_keys(main_mod):
    original = main_mod._tap_keys

    def _tap_keys(action):
        """main._tap_keys (voice-command keystrokes) on the Tk main thread."""
        _run_on_ui(lambda: original(action))

    main_mod._tap_keys = _tap_keys


# --- paste target and Cmd+V injection ---------------------------------------


def _input_trusted():
    """Whether this process may monitor global input; None when unknown."""
    try:
        path = ctypes.util.find_library("ApplicationServices")
        if not path:
            return None
        lib = ctypes.CDLL(path)
        trusted = lib.AXIsProcessTrusted
        trusted.restype = ctypes.c_bool
        return bool(trusted())
    except Exception:
        try:
            from ApplicationServices import AXIsProcessTrusted

            return bool(AXIsProcessTrusted())
        except Exception:
            return None


def _frontmost_app():
    """The frontmost NSRunningApplication, or None."""
    try:
        from AppKit import NSWorkspace

        return NSWorkspace.sharedWorkspace().frontmostApplication()
    except Exception:
        return None


def _is_own_app(app):
    try:
        return app is not None and app.processIdentifier() == os.getpid()
    except Exception:
        return False


def _activate_target():
    """Re-activate the app that was focused when dictation started."""
    app = _state["target_app"]
    if app is None or _is_own_app(app):
        return
    try:
        # NSApplicationActivateIgnoringOtherApps = 1: raise even if another app
        # is active, so the paste lands in the user's text field and not in our
        # own overlay.
        app.activateWithOptions_(1)
        time.sleep(0.05)
    except Exception:
        pass


def _send_cmd_v():
    """Inject Cmd+V via System Events; raises when it cannot be delivered."""
    script = 'tell application "System Events" to keystroke "v" using {command down}'
    try:
        proc = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception as exc:
        raise RuntimeError(f"osascript failed: {exc}") from exc
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "osascript error").strip()
        raise RuntimeError(detail[:200])


def _wrap_start_recording(main_mod):
    original = main_mod.start_recording

    def start_recording(profile):
        # Remember where the user is dictating: by the time the text is pasted
        # our pill may be frontmost instead.
        app = _frontmost_app()
        if app is not None and not _is_own_app(app):
            _state["target_app"] = app
        return original(profile)

    main_mod.start_recording = start_recording


def _patch_controller(main_mod):
    keyboard = main_mod.pkb
    real_controller = keyboard.Controller

    class MacController(real_controller):
        """pynput Controller that turns type_text's Ctrl+V into macOS Cmd+V.

        main.type_text injects a paste as ``ctrl.press(Key.ctrl)``,
        ``ctrl.tap("v")``, ``ctrl.release(Key.ctrl)``; on macOS that sequence is
        replaced by "activate the dictation target, then Cmd+V via System
        Events". Everything else - the typewrite fallback and the backspace
        bursts used by scratch-that - is posted unchanged. A failed injection
        raises, so main.type_text's existing keystroke fallback takes over.
        """

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._ctrl_held = False
            self._pasted = False

        def press(self, key):
            if key == keyboard.Key.ctrl:
                self._ctrl_held = True  # consumed: the Ctrl never reaches the app
                return
            if self._ctrl_held and key == "v":
                self._pasted = True  # swallow the matching release("v") too
                self._mac_paste()
                return
            super().press(key)

        def tap(self, key):
            if self._ctrl_held and key == "v":
                self._mac_paste()
                return
            super().tap(key)

        def release(self, key):
            if key == keyboard.Key.ctrl and self._ctrl_held:
                self._ctrl_held = False
                return
            if self._pasted and key == "v":
                self._pasted = False
                return
            super().release(key)

        def _mac_paste(self):
            _activate_target()
            _send_cmd_v()

    keyboard.Controller = MacController


# --- Apple GPU default ------------------------------------------------------


def _prefer_apple_gpu(main_mod):
    """Resolve ``"device": "auto"`` to the Apple GPU when torch offers MPS."""
    if str(main_mod.cfg.get("device", "auto")).lower() != "auto":
        return
    try:
        import torch

        if not torch.backends.mps.is_available():
            return
    except Exception:
        return
    main_mod.DEVICE, main_mod.COMPUTE = "mps", "float16"
    _log(
        'macOS: using the Apple GPU (device=mps); set "device": "cpu" in '
        "config.json to force the CPU"
    )


def _wrap_get_model(main_mod):
    original = main_mod.get_model
    lock = threading.Lock()

    def get_model(profile):
        try:
            return original(profile)
        except Exception as exc:
            with lock:
                if main_mod.DEVICE != "mps":
                    raise
                main_mod.DEVICE, main_mod.COMPUTE = "cpu", "int8"
            _log(f"macOS: MPS model load failed ({exc}); falling back to the CPU")
            return original(profile)

    main_mod.get_model = get_model


# --- input permission warning ------------------------------------------------


def _warn_if_input_blocked():
    if _input_trusted() is not False:
        return
    _log(
        "input blocked - grant Accessibility / Input Monitoring to the app that "
        "launches this (Terminal, iTerm2, ...) in System Settings -> Privacy & "
        "Security, then relaunch. See README 'Setup (macOS)'."
    )
    main_mod = sys.modules.get("main")
    if main_mod is None:
        return
    try:
        main_mod.STATUS_QUEUE.put(
            (
                "show",
                "error",
                main_mod.STATE_COLORS["error"],
                "⚠ Input blocked — grant Accessibility / Input Monitoring",
            )
        )
    except Exception as exc:
        _log(f"could not show the input-blocked warning: {exc}")


# --- installation ------------------------------------------------------------


def _apply(label, patch):
    try:
        patch()
    except Exception as exc:
        _log(f"macOS: could not apply the {label} patch: {exc}")


def install():
    """Apply the macOS patches to main (call after importing main)."""
    global _installed
    if _installed:
        return
    _installed = True
    import main as main_mod

    _apply("Tk/AppKit startup order", lambda: _wrap_icon_init(main_mod.pystray.Icon))
    _apply("status overlay", lambda: _wrap_status_overlay(main_mod.StatusOverlay))
    _apply("main-thread paste", lambda: _wrap_type_text(main_mod))
    _apply("Cmd+V injection", lambda: _patch_controller(main_mod))
    _apply("scratch-that", lambda: _wrap_scratch_last(main_mod))
    _apply("voice command keys", lambda: _wrap_tap_keys(main_mod))
    _apply("paste target tracking", lambda: _wrap_start_recording(main_mod))
    _apply("Apple GPU default", lambda: _prefer_apple_gpu(main_mod))
    _apply("Apple GPU fallback", lambda: _wrap_get_model(main_mod))
    _log("macOS platform support active")
