"""Short, offline feedback cues. No synthesis or downloads at runtime."""
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading

DEFAULT_THEME = "message-chime"
# Descending source-file downloads on Freesound, observed 2026-09-17.
# This ranks our curated shortlist, not all notification sounds on the web.
THEMES = (
    ("message-chime", "Message chime", 3639),
    ("message-tone", "Message tone", 1785),
    ("high-bell", "Soft high bell", 1441),
    ("double-bell", "Soft double bell", 1090),
    ("low-bell", "Soft low bell", 709),
)
EVENTS = ("start", "stop", "done", "undo")


def selected_theme(cfg):
    theme = cfg.get("sound_theme", DEFAULT_THEME)
    return theme if theme in {t[0] for t in THEMES} else DEFAULT_THEME


def save_preferences(path, cfg, *, enabled, theme):
    """Update only sound keys, retaining edits made to other config settings."""
    if theme not in {t[0] for t in THEMES}:
        raise ValueError(f"Unknown sound theme: {theme}")
    path = Path(path)
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    data.update(sound=bool(enabled), sound_theme=theme)
    # Write then replace atomically; never truncate the user's configuration.
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         delete=False, suffix=".tmp") as out:
            temporary = Path(out.name)
            json.dump(data, out, indent=2, ensure_ascii=False)
            out.write("\n")
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    cfg.update(sound=bool(enabled), sound_theme=theme)


class SoundPlayer:
    def __init__(self, base_dir):
        self.directory = Path(base_dir) / "assets" / "sounds"
        self._lock = threading.Lock()
        self._process = None
        self._warned = set()

    def _stop_process(self):
        if self._process is not None:
            if self._process.poll() is None:
                self._process.terminate()
            self._process = None

    def stop(self):
        try:
            with self._lock:
                if sys.platform == "win32":
                    import winsound
                    winsound.PlaySound(None, 0)
                else:
                    self._stop_process()
        except Exception as exc:
            logging.warning("Could not stop sound: %s", exc)

    def play(self, cfg, event):
        if not cfg.get("sound", True) or event not in EVENTS:
            return
        path = self.directory / f"{selected_theme(cfg)}-{event}.wav"
        try:
            if not path.is_file():
                raise FileNotFoundError(path)
            with self._lock:
                if sys.platform == "win32":
                    import winsound
                    # Async file playback never holds up the keyboard listener.
                    # NODEFAULT prevents missing files triggering a harsh system beep.
                    winsound.PlaySound(str(path), winsound.SND_FILENAME |
                                       winsound.SND_ASYNC | winsound.SND_NODEFAULT)
                elif sys.platform == "darwin":
                    self._stop_process()
                    self._process = subprocess.Popen(
                        ["/usr/bin/afplay", str(path)], stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                else:
                    # Do not use sounddevice.play: it can interrupt capture streams.
                    self._stop_process()
                    self._process = subprocess.Popen(
                        ["aplay", "-q", str(path)], stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
        except Exception as exc:
            if str(path) not in self._warned:
                self._warned.add(str(path))
                logging.warning("Sound unavailable (%s): %s", path.name, exc)


def build_sound_menu(menu_type, item_type, cfg, config_path, player, notify):
    """Inject tray classes so menu behaviour can be tested without a GUI."""
    def apply(icon, *, enabled, theme):
        try:
            save_preferences(config_path, cfg, enabled=enabled, theme=theme)
        except Exception as exc:
            logging.exception("Could not save sound preferences")
            notify(icon, f"Could not save sound preference: {exc}")
            return
        if enabled:
            player.play(cfg, "done")
        else:
            player.stop()
        if icon:
            icon.update_menu()

    def choose(theme):
        def action(icon, item):
            apply(icon, enabled=True, theme=theme)
        return action

    def checked(theme):
        return lambda item: bool(cfg.get("sound", True)) and selected_theme(cfg) == theme

    def mute(icon, item):
        apply(icon, enabled=False, theme=selected_theme(cfg))

    def preview(icon, item):
        player.play(cfg, "done")

    items = [item_type("Ranked by source downloads (Sep 2026)", None, enabled=False)]
    for rank, (theme, label, downloads) in enumerate(THEMES, 1):
        suffix = " - default" if theme == DEFAULT_THEME else ""
        items.append(item_type(f"{rank}. {label} ({downloads:,}){suffix}", choose(theme),
                               checked=checked(theme), radio=True))
    items.extend([
        menu_type.SEPARATOR,
        item_type("Off", mute, checked=lambda item: not cfg.get("sound", True), radio=True),
        item_type("Preview selected sound", preview,
                  enabled=lambda item: bool(cfg.get("sound", True))),
    ])
    return menu_type(*items)
