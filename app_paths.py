"""Resource and writable-data locations for Whisper Dictate.

PyInstaller resources and runtime state must not share a location.  This module
keeps that boundary in one place:

* source runs use the checkout for both roles, preserving the existing workflow;
* frozen runs read resources from ``sys._MEIPASS`` and write state per user; and
* ``--portable``, ``WHISPER_DICTATE_PORTABLE=1``, or a ``PortableData``
  directory opts into an application-adjacent data directory when it is
  writable.

The public path functions return strings, which are accepted directly by the
standard-library filesystem APIs and safely handle spaces and Unicode.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from collections.abc import Callable
from typing import Any

APP_NAME = "Whisper Dictate"
APP_DIRNAME = "Whisper Dictate"
APP_DIRNAME_LINUX = "whisper-dictate"
PORTABLE_DIRNAME = "PortableData"
PORTABLE_ENV = "WHISPER_DICTATE_PORTABLE"
PORTABLE_DIR_ENV = "WHISPER_DICTATE_PORTABLE_DIR"
DATA_DIR_ENV = "WHISPER_DICTATE_DATA_DIR"
PORTABLE_FLAG = "--portable"
# Kept small deliberately: text resources stay in the bundle; only the
# configuration is seeded into a writable data root.
DEFAULT_FILES = ("config.json",)
_FALSE_VALUES = {"", "0", "false", "no", "off"}


def is_frozen() -> bool:
    """Whether the process is running from a PyInstaller bundle."""
    return bool(getattr(sys, "frozen", False))


def _source_dir() -> str:
    return os.path.dirname(os.path.abspath(__file__))


def install_dir() -> str:
    """Directory containing the executable (or the checkout in source mode)."""
    if is_frozen():
        executable = getattr(sys, "executable", "") or ""
        return (
            os.path.dirname(os.path.abspath(os.fspath(executable)))
            if executable
            else _source_dir()
        )
    return resource_dir()


def resource_dir() -> str:
    """Read-only bundled resource root, including PyInstaller's ``_MEIPASS``."""
    meipass = getattr(sys, "_MEIPASS", None)
    if is_frozen() and meipass:
        return os.path.abspath(os.fspath(meipass))
    return install_dir() if is_frozen() else _source_dir()


def bundled_defaults_dir() -> str:
    """Return the bundled defaults directory when a packaging layout uses one."""
    candidate = os.path.join(resource_dir(), "defaults")
    return candidate if os.path.isdir(candidate) else resource_dir()


def _home() -> str:
    return os.path.abspath(os.path.expanduser("~"))


def user_data_dir() -> str:
    """Per-user writable data directory for an installed application."""
    override = os.environ.get(DATA_DIR_ENV)
    if override:
        return os.path.abspath(os.path.expandvars(os.path.expanduser(override)))
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.path.join(_home(), "AppData", "Local")
        return os.path.abspath(os.path.join(os.path.expandvars(base), APP_DIRNAME))
    if sys.platform == "darwin":
        return os.path.abspath(
            os.path.join(_home(), "Library", "Application Support", APP_DIRNAME)
        )
    base = os.environ.get("XDG_DATA_HOME") or os.path.join(_home(), ".local", "share")
    return os.path.abspath(
        os.path.join(os.path.expandvars(os.path.expanduser(base)), APP_DIRNAME_LINUX)
    )


def portable_requested() -> bool:
    """Whether portable mode was explicitly requested or marked."""
    if PORTABLE_FLAG in sys.argv:  # command line wins over an env override
        return True
    if PORTABLE_ENV in os.environ:
        return os.environ[PORTABLE_ENV].strip().lower() not in _FALSE_VALUES
    if PORTABLE_DIR_ENV in os.environ:
        return True
    return os.path.isdir(os.path.join(install_dir(), PORTABLE_DIRNAME))


# Friendly aliases for callers that use either spelling.
is_portable = portable_requested
portable_enabled = portable_requested


def _portable_candidate() -> str:
    override = os.environ.get(PORTABLE_DIR_ENV)
    if not override:
        value = os.environ.get(PORTABLE_ENV, "").strip()
        true_values = {"1", "true", "yes", "on", "portable"}
        if value and value.lower() not in _FALSE_VALUES | true_values:
            override = value
    if override:
        return os.path.abspath(os.path.expandvars(os.path.expanduser(override)))
    return os.path.join(install_dir(), PORTABLE_DIRNAME)


def portable_data_dir() -> str:
    """Return the requested PortableData path without creating it."""
    return _portable_candidate()


def _directory_is_writable(path: str) -> bool:
    """Create a short-lived probe so ACLs, spaces, and Unicode are tested."""
    directory = os.path.abspath(os.fspath(path))
    try:
        os.makedirs(directory, exist_ok=True)
        if not os.path.isdir(directory) or not os.access(directory, os.W_OK):
            return False
    except (OSError, UnicodeError):
        return False

    probe = None
    try:
        fd, probe = tempfile.mkstemp(
            prefix=".whisper-dictate-write-", suffix=".tmp", dir=directory
        )
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write("ok")
    except (OSError, UnicodeError):
        if probe:
            try:
                os.remove(probe)
            except OSError:
                pass
        return False
    try:
        os.remove(probe)
    except OSError:
        pass
    return True


is_writable_dir = _directory_is_writable


def data_dir() -> str:
    """Writable runtime-data root, with safe portable-mode fallback."""
    override = os.environ.get(DATA_DIR_ENV)
    if override:
        return os.path.abspath(os.path.expandvars(os.path.expanduser(override)))
    if portable_requested():
        candidate = _portable_candidate()
        return candidate if _directory_is_writable(candidate) else user_data_dir()
    return user_data_dir() if is_frozen() else _source_dir()


def ensure_data_dir() -> str:
    """Create and return the selected data directory without masking errors."""
    target = data_dir()
    try:
        os.makedirs(target, exist_ok=True)
    except (OSError, UnicodeError):
        pass
    return target


def resource_path(path: str) -> str:
    """Resolve a relative filename against the read-only resource root."""
    if not path:
        return resource_dir()
    path = os.fspath(path)
    return (
        os.path.abspath(path)
        if os.path.isabs(path)
        else os.path.abspath(os.path.join(resource_dir(), path))
    )


def data_path(path: str) -> str:
    """Resolve a relative filename against the writable data root."""
    if not path:
        return data_dir()
    path = os.fspath(path)
    return (
        os.path.abspath(path)
        if os.path.isabs(path)
        else os.path.abspath(os.path.join(data_dir(), path))
    )


def resolve_data_file(path: str) -> str:
    """Backward-compatible data-relative resolver; preserve empty input."""
    if not path:
        return ""
    return data_path(path)


def _safe_relative_name(path: str) -> str:
    """Prevent an absolute/traversal resource name escaping the data root."""
    raw = os.fspath(path)
    if os.path.isabs(raw):
        raw = os.path.basename(raw)
    parts = [part for part in raw.replace("\\", "/").split("/") if part not in ("", ".", "..")]
    return os.path.join(*parts) if parts else ""


def local_path(path: str) -> str:
    """Return the writable ``*.local.txt`` companion for a resource path."""
    relative = _safe_relative_name(path) if path else ""
    if not relative:
        return data_dir()
    root, ext = os.path.splitext(relative)
    return data_path(root + ".local" + (ext or ".txt"))


def config_path() -> str:
    return data_path("config.json")


def log_path() -> str:
    return data_path("dictate.log")


def history_path() -> str:
    return data_path("transcription-history.jsonl")


def model_cache_dir() -> str:
    """Return the model cache, retaining the legacy source-mode location."""
    if (
        not is_frozen()
        and not portable_requested()
        and os.path.abspath(data_dir()) == os.path.abspath(_source_dir())
    ):
        return os.path.join(_home(), ".cache", "huggingface", "hub")
    return data_path("models")


def lock_path() -> str:
    """The shared cross-platform single-instance lock path."""
    return data_path(".app.lock")


def _read_json(path: str) -> tuple[Any | None, str | None]:
    try:
        with open(path, "r", encoding="utf-8") as stream:
            return json.load(stream), None
    except FileNotFoundError:
        return None, "missing"
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return None, str(exc)


def _merge_missing(target: dict, defaults: dict) -> bool:
    """Add absent defaults recursively while retaining every user choice."""
    changed = False
    for key, value in defaults.items():
        if key not in target:
            target[key] = value
            changed = True
        elif isinstance(target[key], dict) and isinstance(value, dict):
            changed = _merge_missing(target[key], value) or changed
    return changed


def _atomic_json_write(path: str, value: Any) -> None:
    parent = os.path.dirname(path) or "."
    os.makedirs(parent, exist_ok=True)
    temporary = None
    try:
        fd, temporary = tempfile.mkstemp(
            prefix=f".{os.path.basename(path)}.", suffix=".tmp", dir=parent
        )
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
            stream.flush()
            try:
                os.fsync(stream.fileno())
            except OSError:
                pass
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary:
            try:
                os.remove(temporary)
            except OSError:
                pass


def save_config(data: dict, path: str | None = None) -> str:
    """Atomically save a configuration dictionary."""
    target = path or config_path()
    _atomic_json_write(target, data)
    return target


def _copy_json_if_valid(source: str, target: str) -> bool:
    value, _error = _read_json(source)
    if not isinstance(value, dict):
        return False
    try:
        _atomic_json_write(target, value)
    except (OSError, UnicodeError, TypeError, ValueError):
        return False
    return True


def _copy_file_if_absent(source: str, target: str) -> bool:
    if os.path.exists(target) or not os.path.isfile(source):
        return False
    temporary = None
    try:
        parent = os.path.dirname(target) or "."
        os.makedirs(parent, exist_ok=True)
        fd, temporary = tempfile.mkstemp(
            prefix=f".{os.path.basename(target)}.", suffix=".tmp", dir=parent
        )
        with os.fdopen(fd, "wb") as destination, open(source, "rb") as origin:
            shutil.copyfileobj(origin, destination)
            destination.flush()
            try:
                os.fsync(destination.fileno())
            except OSError:
                pass
        os.replace(temporary, target)
        temporary = None
    except (OSError, UnicodeError):
        return False
    finally:
        if temporary:
            try:
                os.remove(temporary)
            except OSError:
                pass
    return True


def _migrate_legacy_files(target: str, legacy: str, report: Callable[[str], None]) -> None:
    if not legacy or os.path.abspath(legacy) == os.path.abspath(target):
        return
    try:
        names = os.listdir(legacy)
    except OSError:
        return
    for name in names:
        if not (name.endswith(".local.txt") or name == "config.local.json"):
            continue
        source, destination = os.path.join(legacy, name), os.path.join(target, name)
        copied = (
            _copy_json_if_valid(source, destination)
            if name.endswith(".json")
            else _copy_file_if_absent(source, destination)
        )
        if copied:
            report(f"Migrated personal file from {source}")


def ensure_config(
    defaults: dict | None = None,
    *,
    merge: bool = True,
    log: Callable[[str], None] | None = None,
) -> bool:
    """Create a user config and merge only newly introduced default keys."""
    def report(message: str) -> None:
        if log is not None:
            try:
                log(message)
            except Exception:  # noqa: BLE001
                return

    target = config_path()
    try:
        os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
    except (OSError, UnicodeError) as exc:
        report(f"Could not create config directory: {exc}")
        return False

    if not os.path.exists(target):
        source = resource_path("config.json")
        if os.path.abspath(source) != os.path.abspath(target) and os.path.isfile(source):
            if not _copy_json_if_valid(source, target) and defaults is None:
                report(f"Could not create user config from {source}")
                return False
        elif defaults is None:
            return False
        if not os.path.exists(target) and defaults is not None:
            try:
                _atomic_json_write(target, defaults)
            except (OSError, UnicodeError, TypeError, ValueError) as exc:
                report(f"Could not create user config: {exc}")
                return False

    if defaults is None or not merge:
        return os.path.exists(target)
    value, error = _read_json(target)
    if not isinstance(value, dict):
        if error != "missing":
            report(f"User config was not changed because it is not valid JSON: {target}")
        return False
    try:
        if _merge_missing(value, defaults):
            _atomic_json_write(target, value)
            report(f"Merged new configuration defaults into {target}")
    except (OSError, UnicodeError, TypeError, ValueError) as exc:
        report(f"Could not merge configuration defaults: {exc}")
        return False
    return True


def ensure_initialized(log: Callable[[str], None] | None = None) -> str:
    """Create the data root and safely seed a missing user configuration."""
    def report(message: str) -> None:
        if log is not None:
            try:
                log(message)
            except Exception:  # noqa: BLE001
                return

    target = ensure_data_dir()
    config = config_path()
    migrating = is_frozen() or portable_requested() or bool(os.environ.get(DATA_DIR_ENV))
    if not os.path.exists(config):
        if migrating:
            legacy = os.path.join(install_dir(), "config.json")
            if os.path.isfile(legacy) and _copy_json_if_valid(legacy, config):
                report(f"Migrated existing user config from {legacy}")
        if not os.path.exists(config):
            bundled = resource_path("config.json")
            if (
                os.path.isfile(bundled)
                and os.path.abspath(bundled) != os.path.abspath(config)
                and _copy_json_if_valid(bundled, config)
            ):
                report(f"Created user config from bundled defaults: {config}")
    if migrating:
        _migrate_legacy_files(target, install_dir(), report)
    return target


__all__ = [
    "APP_DIRNAME",
    "APP_DIRNAME_LINUX",
    "APP_NAME",
    "DATA_DIR_ENV",
    "DEFAULT_FILES",
    "PORTABLE_DIRNAME",
    "PORTABLE_DIR_ENV",
    "PORTABLE_ENV",
    "PORTABLE_FLAG",
    "bundled_defaults_dir",
    "config_path",
    "data_dir",
    "data_path",
    "ensure_config",
    "ensure_data_dir",
    "ensure_initialized",
    "history_path",
    "install_dir",
    "is_frozen",
    "is_portable",
    "is_writable_dir",
    "local_path",
    "lock_path",
    "log_path",
    "model_cache_dir",
    "portable_data_dir",
    "portable_enabled",
    "portable_requested",
    "resolve_data_file",
    "resource_dir",
    "resource_path",
    "save_config",
    "user_data_dir",
]
