#!/usr/bin/env python3
"""Fail-closed privacy guard for files and release archives.

The guard is intentionally dependency-free so it can run in a clean release
job before an artifact is uploaded.  It checks archive member names (and
package directory names) against a small, explicit denylist.  It does not
inspect or copy user data; a release job only needs to know whether a name is
safe to ship.

Examples
--------
    python scripts/release_guard.py dist/WhisperDictate-v1.2.3-windows-x64.zip
    python scripts/release_guard.py dist/WhisperDictate
    python scripts/release_guard.py --json artifact.zip

The command exits 0 when every checked path is allowed and 1 when a forbidden
path, unsafe archive path, missing input, or unsupported archive is found.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tarfile
import zipfile
from collections.abc import Iterable, Iterator
from pathlib import Path

# Keep these lists explicit.  A broad "private-looking file" heuristic is
# difficult to audit and tends to change from release to release.
FORBIDDEN_COMPONENTS = frozenset(
    {
        # Logs and generated/runtime state.
        "log",
        "logs",
        ".env",
        ".envrc",
        "lost_audio",
        "lost-audio",
        "lost audio",
        "transcription-history.jsonl",
        "history",
        # Virtual environments and dependency/build trees.
        ".venv",
        ".venv-build",
        "venv",
        "virtualenv",
        "virtualenvs",
        "env",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".tox",
        "node_modules",
        "build",
        "dist",
        ".eggs",
        "htmlcov",
        ".ipynb_checkpoints",
        # VCS/editor state.
        ".git",
        ".hg",
        ".svn",
        ".idea",
        ".vscode",
    }
)
FORBIDDEN_NAMES = frozenset(
    {
        ".env",
        ".envrc",
        ".netrc",
        ".npmrc",
        ".ds_store",
        "thumbs.db",
        "desktop.ini",
        "config.local",
        "config.local.json",
        "log",
        "logs",
        "dictate.log",
        "transcription-history.jsonl",
        "history.jsonl",
        "id_rsa",
        "id_dsa",
        "id_ecdsa",
        "id_ed25519",
        "credentials.json",
        "secrets.json",
        "license.json",
        "activation.json",
        ".coverage",
        "coverage.xml",
    }
)
# Public trust-store files are a normal runtime data dependency (for example
# certifi's CA bundle), not signing material.  Keep the narrow exception
# explicit so a future private certificate does not silently become allowed.
PUBLIC_CERTIFICATE_NAMES = frozenset({"cacert.pem", "ca-bundle.crt"})
FORBIDDEN_SUFFIXES = frozenset(
    {
        # Application logs and transcription/user history.
        ".log",
        ".jsonl",
        # Local overrides and environment files (the prefix check also covers
        # .env.local, .env.production, and similar names).
        ".local.json",
        ".local.yaml",
        ".local.yml",
        ".local.toml",
        ".local.ini",
        ".local.cfg",
        ".local.txt",
        ".local",
        ".env",
        # Compiler/cache/editor debris.
        ".pyc",
        ".pyo",
        ".bak",
        ".backup",
        ".orig",
        ".rej",
        ".tmp",
        ".temp",
        ".swp",
        ".swo",
        ".crdownload",
        ".download",
        ".part",
        # Credentials/signing material must never be shipped in a bundle.
        ".pem",
        ".key",
        ".p12",
        ".pfx",
        ".jks",
        ".keystore",
        ".egg-info",
        ".whl",
        # Speech-model weights are acquired at runtime, never bundled in a
        # release archive or onedir payload.
        ".safetensors",
        ".ckpt",
        ".pth",
        ".pt",
        ".onnx",
        ".gguf",
        ".h5",
        ".pkl",
        ".bin",
    }
)

# A path traversal is a packaging/safety failure even when its final basename
# is harmless.  This is kept separate from the privacy denylist so reports are
# actionable.
_DRIVE_RE = re.compile(r"^[A-Za-z]:")


def normalize_member_name(name: str) -> str:
    """Return an archive/package path in a stable slash-separated form."""

    if not isinstance(name, str):
        raise TypeError("archive member names must be strings")
    normalized = name.replace("\\", "/")
    # Remove only a leading ``./`` marker.  ``str.lstrip("./")`` would also
    # turn private names such as ``.env`` into ``env`` and hide a violation.
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def _parts(name: str) -> tuple[str, ...]:
    return tuple(part for part in normalize_member_name(name).split("/") if part not in ("", "."))


def forbidden_reason(name: str) -> str | None:
    """Return a stable reason when *name* must not be in a release package.

    Matching is case-insensitive because release artifacts move between
    case-sensitive macOS runners and case-insensitive Windows installations.
    ``None`` means the path is allowed by the denylist.  This function is
    path/name based only; it never reads the member contents.
    """

    if not isinstance(name, str) or not name:
        return "empty or non-string path"

    normalized = normalize_member_name(name)
    if "\x00" in normalized:
        return "NUL byte in path"
    if normalized.startswith("/") or _DRIVE_RE.match(normalized):
        return "absolute archive path"
    parts = _parts(normalized)
    if not parts:
        return "empty archive path"
    if any(part == ".." for part in parts):
        return "parent-directory path traversal"

    lowered_parts = tuple(part.casefold() for part in parts)
    basename = lowered_parts[-1]

    if (
        basename == ".env"
        or basename.startswith((".env.", ".env_"))
        or basename.endswith(".env")
    ):
        return "environment file"
    for component in lowered_parts:
        if component in FORBIDDEN_COMPONENTS:
            return f"forbidden path component: {component}"
        if component in {"model-cache", "huggingface"} or component.startswith("models--"):
            return "model cache path"
    if basename in FORBIDDEN_NAMES:
        return f"forbidden filename: {basename}"
    if basename not in PUBLIC_CERTIFICATE_NAMES:
        matching_suffixes = sorted(suffix for suffix in FORBIDDEN_SUFFIXES if basename.endswith(suffix))
        if matching_suffixes:
            return f"forbidden file suffix: {matching_suffixes[0]}"
    if ".local." in basename or basename.startswith("config.local"):
        return "local configuration file"
    if basename.startswith("dictate.log") or ".log." in basename:
        return "application log"
    if basename.startswith("transcription-history") or ".jsonl." in basename:
        return "transcription history"
    if basename.startswith(("lost_audio", "lost-audio", "lost audio")):
        return "lost audio directory or archive"
    if basename.startswith("id_rsa"):
        return "private key material"
    if basename.endswith("~"):
        return "editor backup file"
    return None


# Friendly aliases for callers/tests that prefer predicate/collection naming.
def is_forbidden_path(name: str) -> bool:
    """Return whether *name* matches the release denylist."""

    return forbidden_reason(name) is not None


def find_forbidden(names: Iterable[str]) -> list[tuple[str, str]]:
    """Return all violations in *names* (collection-friendly alias)."""

    return find_forbidden_paths(names)


def _unique_violations(violations: Iterable[tuple[str, str]]) -> list[tuple[str, str]]:
    """Deduplicate and sort violations so CI output is deterministic."""

    return sorted(set(violations), key=lambda item: (item[0].casefold(), item[0], item[1]))


def find_forbidden_paths(names: Iterable[str]) -> list[tuple[str, str]]:
    """Return ``(member_name, reason)`` pairs for all denied names."""

    violations: list[tuple[str, str]] = []
    for name in names:
        reason = forbidden_reason(name)
        if reason is not None:
            violations.append((str(name), reason))
    return _unique_violations(violations)


def _archive_names(path: Path) -> Iterator[str]:
    """Yield member names from a supported archive without extracting it."""

    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            for zip_info in archive.infolist():
                yield zip_info.filename
        return

    # tarfile.is_tarfile may inspect a small header only and works for gzip,
    # bzip2, and xz compressed tar files when the stdlib supports them.
    if tarfile.is_tarfile(path):
        with tarfile.open(path, mode="r:*") as archive:
            for tar_info in archive.getmembers():
                yield tar_info.name
        return

    raise ValueError(f"unsupported archive format: {path}")


def inspect_archive(path: str | os.PathLike[str]) -> list[tuple[str, str]]:
    """Inspect archive member names and return deterministic violations."""

    archive_path = Path(path)
    if not archive_path.is_file():
        return [(str(archive_path), "missing archive")]
    try:
        return find_forbidden_paths(_archive_names(archive_path))
    except (OSError, ValueError, zipfile.BadZipFile, tarfile.TarError) as exc:
        return [(str(archive_path), f"could not inspect archive: {exc}")]


def _package_names(root: Path) -> Iterator[str]:
    """Yield names below a package directory, including directory names."""

    def raise_walk_error(error: OSError) -> None:
        raise error

    # os.walk lets us sort each level and avoid following a symlinked directory.
    for current, dirs, files in os.walk(
        root, topdown=True, followlinks=False, onerror=raise_walk_error
    ):
        dirs.sort(key=str.casefold)
        files.sort(key=str.casefold)
        current_path = Path(current)
        for name in dirs:
            yield (current_path / name).relative_to(root).as_posix()
        for name in files:
            yield (current_path / name).relative_to(root).as_posix()


def inspect_package(path: str | os.PathLike[str]) -> list[tuple[str, str]]:
    """Inspect a directory/package tree and return deterministic violations."""

    package_path = Path(path)
    if not package_path.is_dir():
        return [(str(package_path), "missing package directory")]
    try:
        names = [package_path.name]
        names.extend(_package_names(package_path))
        return find_forbidden_paths(names)
    except OSError as exc:
        return [(str(package_path), f"could not inspect package: {exc}")]


def inspect(path: str | os.PathLike[str]) -> list[tuple[str, str]]:
    """Inspect either a release archive or a package directory."""

    target = Path(path)
    if target.is_dir():
        return inspect_package(target)
    return inspect_archive(target)


def _json_report(paths: list[Path], violations: list[tuple[str, str]]) -> dict[str, object]:
    return {
        "ok": not violations,
        "paths": [str(path) for path in paths],
        "violations": [
            {"path": name, "reason": reason}
            for name, reason in _unique_violations(violations)
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("paths", nargs="+", type=Path, help="archive or package directory to inspect")
    parser.add_argument(
        "--json",
        dest="as_json",
        action="store_true",
        help="emit a machine-readable report instead of human-readable failures",
    )
    args = parser.parse_args(argv)

    all_violations: list[tuple[str, str]] = []
    for path in args.paths:
        all_violations.extend(inspect(path))
    violations = _unique_violations(all_violations)
    report = _json_report(args.paths, violations)

    if args.as_json:
        print(json.dumps(report, indent=2, sort_keys=True))
    elif violations:
        print("Release package guard FAILED", file=sys.stderr)
        for name, reason in violations:
            print(f"- {name}: {reason}", file=sys.stderr)
    else:
        print(f"Release package guard passed ({len(args.paths)} path(s)).")

    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
