"""Filesystem locations for Whisper Dictate, packaged or from a checkout.

Two different questions are answered here, and mixing them up is what breaks a
packaged build:

* :func:`resource_dir` - read-only files that ship *with* the app (default
  config templates, hotword seeds, the icon). Inside a frozen bundle this is
  PyInstaller's extraction directory, which is writable only until the process
  exits and is replaced on every launch.
* :func:`data_dir` - everything the app writes at runtime: ``config.json``,
  ``dictate.log``, the lock file, ``transcription-history.jsonl``, and the
  user's own hotword/correction files.

In a checkout (not frozen) both point at the repository, so an existing
development install keeps behaving exactly as before - no migration, no
surprise second copy of the config. When frozen, ``data_dir`` is the
platform's per-user data folder and :func:`ensure_initialized` seeds it from
``resource_dir()/defaults`` on first run.

The legacy checkout migration exists because the previous releases stored
everything next to the sources: if a frozen build would start with an empty
data folder while a populated checkout config is sitting in the same place the
user ran the app from, copying it once is strictly friendlier than asking them
to re-enter their hotkeys.
"""

from __future__ import annotations

import os
import shutil
import sys

APP_NAME = "Whisper Dictate"
APP_DIRNAME = "Whisper Dictate"
# Linux convention: lowercase, no spaces.
APP_DIRNAME_LINUX = "whisper-dictate"

# Files seeded into the data folder on first run.
DEFAULT_FILES = (
    "config.json",
    "hotwords-en.txt",
    "hotwords-de.txt",
    "corrections-en.txt",
    "corrections-de.txt",
    "snippets-en.txt",
    "snippets-de.txt",
)


def is_frozen() -> bool:
    """True inside a PyInstaller/standalone bundle."""
    return bool(getattr(sys, "frozen", False))


def _checkout_dir() -> str:
    return os.path.dirname(os.path.abspath(__file__))


def resource_dir() -> str:
    """Read-only bundled resources (PyInstaller extract dir when frozen)."""
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return meipass
    return _checkout_dir()


def bundled_defaults_dir() -> str:
    """Folder holding the release default config and seed text files."""
    return os.path.join(resource_dir(), "defaults")


def user_data_dir() -> str:
    """Per-user writable data folder for a packaged build."""
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        return os.path.join(base, APP_DIRNAME)
    if sys.platform == "darwin":
        return os.path.join(
            os.path.expanduser("~"), "Library", "Application Support", APP_DIRNAME
        )
    base = os.environ.get("XDG_DATA_HOME") or os.path.join(
        os.path.expanduser("~"), ".local", "share"
    )
    return os.path.join(base, APP_DIRNAME_LINUX)


def data_dir() -> str:
    """Where runtime state lives: the checkout when running from sources."""
    if is_frozen():
        return user_data_dir()
    return _checkout_dir()


def _legacy_checkout_candidates() -> list:
    """Checkouts that may hold a config worth migrating into the data folder."""
    candidates = []
    # Running the packaged binary from inside a developer checkout is the case
    # this exists for.
    candidates.append(os.getcwd())
    exe_dir = os.path.dirname(os.path.abspath(sys.executable))
    candidates.append(exe_dir)
    return candidates


def ensure_initialized(log=None) -> str:
    """Create the data folder, seeding defaults on first run. Returns its path.

    Safe to call more than once; existing files are never overwritten.
    """

    def _log(message):
        if log is not None:
            try:
                log(message)
            except Exception:
                pass

    target = data_dir()
    try:
        os.makedirs(target, exist_ok=True)
    except OSError as exc:
        # A read-only checkout in dev mode is still usable (writes will fail
        # loudly later); do not turn it into a startup crash.
        _log(f"Could not create data folder {target}: {exc}")
        return target

    defaults = bundled_defaults_dir()
    seeded = []
    for name in DEFAULT_FILES:
        dest = os.path.join(target, name)
        if os.path.exists(dest):
            continue
        source = os.path.join(defaults, name)
        if os.path.exists(source):
            try:
                shutil.copyfile(source, dest)
                seeded.append(name)
            except OSError as exc:
                _log(f"Could not seed {name}: {exc}")
    if seeded:
        _log(f"Initialized data folder {target} with {', '.join(seeded)}")

    # One-time migration from a legacy checkout config (packaged runs only).
    if is_frozen():
        config_path = os.path.join(target, "config.json")
        if not seeded and not any(
            os.path.exists(config_path) for _ in (0,)
        ):
            pass
        if not os.path.exists(config_path):
            for candidate in _legacy_checkout_candidates():
                legacy = os.path.join(candidate, "config.json")
                if candidate == target or not os.path.exists(legacy):
                    continue
                try:
                    shutil.copyfile(legacy, config_path)
                    _log(f"Migrated existing config from {legacy}")
                    break
                except OSError as exc:
                    _log(f"Could not migrate {legacy}: {exc}")
    return target


def resolve_data_file(path: str) -> str:
    """Resolve a config-relative filename against the data folder."""
    if not path:
        return path
    if os.path.isabs(path):
        return path
    return os.path.join(data_dir(), path)


def install_dir() -> str:
    """Folder the running executable lives in (for uninstall hints/logs)."""
    if is_frozen():
        return os.path.dirname(os.path.abspath(sys.executable))
    return _checkout_dir()
