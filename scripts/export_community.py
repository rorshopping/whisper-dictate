"""Export a deterministic, reviewable community source tree.

This tool is intentionally an allowlist exporter.  It is not a repository
mirror and it does not copy an untrusted directory wholesale.  A new source
file therefore stays out of a community export until somebody explicitly adds
it to ``ALLOWLIST_PATHS``.

The exporter is a release-preparation aid, not a license auditor.  It removes
the paid activation path from generated copies of the small set of files that
contain it, emits a first-party-only MIT license, preserves the existing
third-party/model notices, and writes a sorted SHA-256 manifest.  The source
checkout is read-only from this tool's point of view.
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_NAME = "COMMUNITY_EXPORT_MANIFEST.json"
MANIFEST_FILENAME = MANIFEST_NAME
GENERATED_LICENSE_NAME = "LICENSE"
MODEL_LICENSES_NAME = "MODEL_LICENSES.md"

# This is deliberately a tuple of exact paths, rather than "copy all source".
# Keep it small and reviewable; release tooling and the website are not source
# payload.  The exporter test is a maintainer test and is likewise not copied
# into the public application tree.
_ALLOWLIST_PATHS = (
    "COMMUNITY_RELEASE_DECISION.md",
    "NOTES_portable-paths.md",
    "README.md",
    "THIRD-PARTY-NOTICES.md",
    "WhisperDictate.spec",
    # main.py imports this path-layer runtime; it is required, not optional.
    "app_paths.py",
    "config.json",
    "corrections-en.txt",
    "enhanced_features.py",
    "hotkey_settings.py",
    "hotword_fuzzy.py",
    "hotwords-de.txt",
    "hotwords-en.txt",
    "icon.ico",
    "install.py",
    "launcher.py",
    "main.py",
    "nemotron_engine.py",
    "platform_mac.py",
    "requirements.txt",
    "run.bat",
    "run_hidden.vbs",
    "run_mac.sh",
    "smart_format.py",
    "snippets-de.txt",
    "snippets-en.txt",
    "sound_cues.py",
    "voice_commands.py",
    "assets/sounds/SOURCES.md",
    "assets/sounds/manifest.json",
    # The bundled cue set is an allowlisted set of tracked runtime assets.  Do
    # not replace this with a wildcard: that could copy a local or generated
    # recording into a public export.
    "assets/sounds/double-bell-done.wav",
    "assets/sounds/double-bell-start.wav",
    "assets/sounds/double-bell-stop.wav",
    "assets/sounds/double-bell-undo.wav",
    "assets/sounds/high-bell-done.wav",
    "assets/sounds/high-bell-start.wav",
    "assets/sounds/high-bell-stop.wav",
    "assets/sounds/high-bell-undo.wav",
    "assets/sounds/low-bell-done.wav",
    "assets/sounds/low-bell-start.wav",
    "assets/sounds/low-bell-stop.wav",
    "assets/sounds/low-bell-undo.wav",
    "assets/sounds/message-chime-done.wav",
    "assets/sounds/message-chime-start.wav",
    "assets/sounds/message-chime-stop.wav",
    "assets/sounds/message-chime-undo.wav",
    "assets/sounds/message-tone-done.wav",
    "assets/sounds/message-tone-start.wav",
    "assets/sounds/message-tone-stop.wav",
    "assets/sounds/message-tone-undo.wav",
    # Application tests only.  The paid activation test is excluded below.
    "tests/test_app_paths.py",
    "tests/test_hotkey_settings.py",
    "tests/test_nemotron_chunking.py",
    "tests/test_smart_format.py",
    "tests/test_sound_cues.py",
    "tests/test_voice_commands.py",
)
ALLOWLIST_PATHS = tuple(sorted(_ALLOWLIST_PATHS))
# A descriptive alias for callers/tests that prefer the term "allowlist".
SOURCE_ALLOWLIST = ALLOWLIST_PATHS

# These are documented as defense in depth.  The exact allowlist is the
# primary control; a newly created file is not exported just because it happens
# not to match one of these patterns.
_DENYLIST_PATHS = (
    ".git",
    ".github",
    "website",
    ".venv",
    "venv",
    "build",
    "dist",
    "__pycache__",
    "node_modules",
    "config.local.json",
    ".app.lock",
    ".venv-build",
    ".vercel",
    "lost_audio",
    "test.wav",
    "release",
    "LICENSE",
    "license_gate.py",
    "tests/test_license_gate.py",
    "STRIPE.md",
    "MARKETING-LAUNCH.md",
    "scripts/export_community.py",
    "tests/test_community_export.py",
    "NOTES_community-export.md",
)
DENYLIST_PATHS = frozenset(path.casefold() for path in _DENYLIST_PATHS)
# Public aliases make the policy easy to inspect from a small review script.
ALLOWLIST = ALLOWLIST_PATHS
DENYLIST = DENYLIST_PATHS

_DENYLIST_PATTERNS = (
    # Alternate site and release infrastructure.
    "website/**",
    ".github/**",
    "**/api/**",
    "**/site/**",
    "**/public/**",
    "**/release/**",
    "**/*.html",
    "**/*.css",
    "**/*.js",
    "**/*.svg",
    "**/*.png",
    "**/*.jpg",
    "**/*.jpeg",
    "**/*.webp",
    "**/notarize*",
    "**/*stripe*",
    "**/*payment*",
    "**/*billing*",
    "**/*pricing*",
    "**/*marketing*",
    "**/*-launch*",
    "**/*launch.md",
    "**/*license_gate*",
    # Local/generated/cache material.
    "**/.git/**",
    "**/.venv/**",
    "**/.venv-build/**",
    "**/venv/**",
    "**/build/**",
    "**/dist/**",
    "**/node_modules/**",
    "**/__pycache__/**",
    "**/.pytest_cache/**",
    "**/.mypy_cache/**",
    "**/.tox/**",
    "**/.playwright-cli/**",
    "**/.vercel/**",
    "**/.app.lock",
    "**/.venv-build/**",
    "**/lost_audio/**",
    "**/test.wav",
    "**/.idea/**",
    "**/.vscode/**",
    "**/htmlcov/**",
    "**/coverage/**",
    "**/*.egg-info/**",
    "**/model-cache/**",
    "**/models/**",
    "**/huggingface/**",
    "**/*.local.*",
    "**/*.local",
    "*.local.txt",
    "*.local.*",
    "**/*.private.*",
    "**/*.personal.*",
    "**/*.bak",
    "**/*.tmp",
    "**/*.swp",
    "**/*.orig",
    "**/*.rej",
    "**/*.pyc",
    "**/*.pyo",
    "**/*.log",
    "**/*.log.*",
    "**/dictate.log*",
    "**/transcription-history*",
    "**/*.jsonl",
    "**/*.env",
    "**/.env*",
    "**/*.pem",
    "**/*.key",
    "**/*.crt",
    "**/*.pfx",
    "**/*.p12",
    "**/*.keystore",
    "**/.netrc",
    "**/.npmrc",
    "**/.pypirc",
    "**/id_rsa*",
    "**/secrets*",
    "**/*secret*",
    "**/*token*",
    "**/*credential*",
    "**/*password*",
    "**/*api-key*",
    "**/*.secret",
    "**/*private*",
    "**/*personal*",
    "**/.DS_Store",
    "**/Thumbs.db",
    # Do not accidentally package model weights or build artifacts.
    "**/*.safetensors",
    "**/*.ckpt",
    "**/*.pth",
    "**/*.pt",
    "**/*.onnx",
    "**/*.gguf",
    "**/*.h5",
    "**/*.pkl",
    "**/*.bin",
    "**/*.dll",
    "**/*.dylib",
    "**/*.exe",
    "**/*.msi",
    "**/*.app",
    "**/*.zip",
    "**/*.tar",
    "**/*.tar.gz",
    "**/*.tgz",
    "**/*.7z",
)
DENYLIST_PATTERNS = tuple(_DENYLIST_PATTERNS)

GENERATED_PATHS = frozenset(
    {GENERATED_LICENSE_NAME, MODEL_LICENSES_NAME, MANIFEST_NAME}
)
REQUIRED_SOURCE_PATHS = frozenset({"app_paths.py"})
EXPORT_PATHS = tuple(sorted(set(ALLOWLIST_PATHS) | GENERATED_PATHS))
EXECUTABLE_PATHS = frozenset({"run_mac.sh"})
MANIFEST_SCHEMA = "whisper-dictate/community-source-export-v1"

# The model IDs below are documentation pointers, not an invitation to bundle
# or relicense weights.  The text is intentionally conservative and is also
# emitted as MODEL_LICENSES.md in every export.
MODEL_LICENSES_TEMPLATE = """# Model Licenses

**No speech-model weights are bundled in this source export.** Whisper Dictate
downloads the configured models separately at first use from the publisher.
Those files are not first-party source and are not covered by the first-party
MIT license in the community export. Review the model card and the linked terms
before downloading, using, or redistributing any model.

## NVIDIA model

- `nvidia/nemotron-speech-streaming-en-0.6b` (English profile) uses the
  **NVIDIA Open Model License**.
- Terms: <https://www.nvidia.com/en-us/agreements/enterprise-software/nvidia-open-model-license/>
- Required notice from the publisher's terms: \"Licensed by NVIDIA Corporation
  under the NVIDIA Open Model License.\"

## OpenMDW model

- `nvidia/nemotron-3.5-asr-streaming-0.6b` (German profile) uses **OpenMDW-1.1**.
- Terms: <https://openmdw.ai/license/1-1/>

The linked NVIDIA and OpenMDW terms are authoritative for their respective
models. This file is only a starting pointer; it does not reproduce or alter
those terms. Weights are downloaded separately and are never represented as
MIT-licensed material. `THIRD-PARTY-NOTICES.md` retains the broader dependency
and model notice record.
"""

MIT_LICENSE_TEXT = """MIT License

Copyright (c) 2026 Richard Bäcker

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the \"Software\"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED \"AS IS\", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

This license applies only to first-party source files in this community
source export. It does not relicense third-party dependencies, model weights,
or other third-party materials. See THIRD-PARTY-NOTICES.md and
MODEL_LICENSES.md for their separate notices and terms.
"""


class ExportError(RuntimeError):
    """Raised when an export would be unsafe or incomplete."""


@dataclass(frozen=True)
class SelectedFile:
    """A source file selected by the allowlist."""

    relative_path: str
    source_path: Path
    transform: str = "copy"


# The first-party README is copied with its commercial release section
# replaced.  The source README remains unchanged in the paid checkout.
COMMUNITY_README_SECTION = """## Community license and releases

This is the community source edition. The first-party source in this export is
made available under the MIT License in `LICENSE`.

Third-party dependencies retain their own licenses; see
`THIRD-PARTY-NOTICES.md`. Speech-model weights are not included: they are
downloaded separately under their own terms. See `MODEL_LICENSES.md` before
using or redistributing a model.

No account service or remote notice polling is part of this export. The
release boundaries and quality gate are recorded in
`COMMUNITY_RELEASE_DECISION.md`.
"""

_SENSITIVE_CONFIG_KEYS = frozenset(
    {
        "license",
        "licenserequired",
        "licenseapi",
        "activation",
        "activationurl",
        "stripe",
        "payment",
        "paymenturl",
        "webhook",
        "webhookurl",
        "secret",
        "secretkey",
        "accesstoken",
        "refreshtoken",
        "apikey",
        "privatekey",
        "password",
        "noticeurl",
    }
)
_SENSITIVE_VALUE_PATTERNS = (
    re.compile(r"whisperdictate\.vercel\.app/api", re.IGNORECASE),
    re.compile(r"\bsk_live_[A-Za-z0-9]+\b"),
    re.compile(r"\bwhsec_[A-Za-z0-9]+\b"),
    re.compile(
        r"\b(?:STRIPE_SECRET_KEY|LICENSE_HMAC_SECRET|GH_TOKEN)"
        r"[\"']?\s*[:=]",
        re.IGNORECASE,
    ),
)
_PRIVATE_KEY_MARKER = re.compile(
    r"-----BEGIN [^-]{0,80}PRIVATE KEY-----", re.IGNORECASE
)


def _norm_rel(value: str) -> str:
    """Return a checked, POSIX-style relative path."""

    text = str(value).replace("\\", "/")
    pure = PurePosixPath(text)
    if pure.is_absolute() or not text or any(part in ("", ".", "..") for part in pure.parts):
        raise ExportError(f"unsafe relative path in export policy: {value!r}")
    return pure.as_posix()


def _matches_any(path: str, patterns: Iterable[str]) -> bool:
    path = path.casefold()
    for pattern in patterns:
        pattern = pattern.casefold()
        if fnmatch.fnmatchcase(path, pattern):
            return True
        # fnmatch does not make a bare directory pattern match its contents on
        # every Python version; normalize that case explicitly.  Also try the
        # form without the recursive ``**/`` prefix so ``build/file`` is
        # denied just like ``src/build/file``.
        variants = (pattern, pattern.rstrip("/") + "/**")
        if pattern.startswith("**/"):
            variants += (pattern[3:], pattern[3:].rstrip("/") + "/**")
        if any(fnmatch.fnmatchcase(path, variant) for variant in variants):
            return True
    return False


def is_denied(relative_path: str) -> bool:
    """Return whether a source-relative path is on the explicit denylist."""

    try:
        rel = _norm_rel(relative_path)
    except ExportError:
        # An invalid policy/path is unsafe, so fail closed.
        return True
    if rel.casefold() in DENYLIST_PATHS:
        return True
    if _matches_any(rel, DENYLIST_PATTERNS):
        return True
    # ``fnmatch`` on some platforms does not let ``**/name`` match a name at
    # the repository root.  Apply the basename form explicitly for the
    # file-name patterns above.
    basename = rel.rsplit("/", 1)[-1]
    for pattern in DENYLIST_PATTERNS:
        if (
            pattern.startswith("**/")
            and "/" not in pattern[3:]
            and fnmatch.fnmatchcase(basename, pattern[3:].casefold())
        ):
            return True
    return False


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _absolute_path(path: Path | str) -> Path:
    return Path(os.path.abspath(os.path.expanduser(os.fspath(path))))


def _reject_symlink_components(path: Path, *, label: str) -> None:
    """Reject a caller path that would traverse an existing symlink."""

    current = Path(path.anchor) if path.anchor else Path()
    for part in path.parts:
        if not current or part == path.anchor:
            continue
        current /= part
        if current.is_symlink():
            raise ExportError(f"{label} traverses a symlink: {current}")


def _normalise_source_root(source_root: Path | str | None) -> Path:
    candidate = _absolute_path(ROOT if source_root is None else source_root)
    _reject_symlink_components(candidate, label="source root")
    if not candidate.exists():
        raise ExportError(f"source root does not exist: {candidate}")
    if candidate.is_symlink() or not candidate.is_dir():
        raise ExportError(f"source root is not a regular directory: {candidate}")
    try:
        return candidate.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ExportError(f"cannot resolve source root {candidate}: {exc}") from exc


def _normalise_output(output_dir: Path | str, source_root: Path) -> Path:
    output = _absolute_path(output_dir)
    # The output must not be a link, and an existing parent link must not be
    # followed.  This also prevents a caller from turning a link into a write
    # primitive for an unrelated directory.
    _reject_symlink_components(output, label="output directory")
    try:
        output_real = output.resolve(strict=False)
    except (OSError, RuntimeError) as exc:
        raise ExportError(f"cannot resolve output directory {output}: {exc}") from exc
    if output_real == source_root or _is_within(output_real, source_root) or _is_within(source_root, output_real):
        raise ExportError("output directory must not be the source root or be inside/above it")
    if output.exists():
        if output.is_symlink():
            raise ExportError(f"output directory is a symlink: {output}")
        if not output.is_dir():
            raise ExportError(f"output path exists and is not a directory: {output}")
    return output


def _check_nonempty_output(output: Path, force: bool) -> None:
    if not output.exists():
        return
    if output.is_symlink() or not output.is_dir():
        raise ExportError(f"output path is not a regular directory: {output}")
    if any(output.iterdir()) and not force:
        raise ExportError(
            f"output directory is not empty: {output}; pass --force to replace it"
        )


def _source_file(root: Path, relative_path: str) -> SelectedFile | None:
    rel = _norm_rel(relative_path)
    if rel in GENERATED_PATHS:
        raise ExportError(f"generated path cannot be sourced directly: {rel}")
    if is_denied(rel):
        raise ExportError(f"allowlist and denylist overlap: {rel}")
    parts = PurePosixPath(rel).parts
    candidate = root.joinpath(*parts)
    if candidate.is_symlink():
        raise ExportError(f"refusing symlink in source: {rel}")
    if not candidate.exists():
        # Optional files may be absent in a small review fixture.  Required
        # generated files (LICENSE, MODEL_LICENSES, manifest) do not use this
        # path and are always emitted.
        return None
    try:
        resolved = candidate.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ExportError(f"cannot resolve source file {rel}: {exc}") from exc
    if not _is_within(resolved, root):
        raise ExportError(f"source path escapes source root: {rel}")
    if not resolved.is_file():
        raise ExportError(f"allowlisted source path is not a regular file: {rel}")
    try:
        parent_resolved = candidate.parent.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ExportError(f"cannot resolve source parent for {rel}: {exc}") from exc
    if candidate.parent != root and not _is_within(parent_resolved, root):
        raise ExportError(f"source parent escapes source root: {rel}")
    transform = {
        "main.py": "community-runtime",
        "README.md": "community-license-section",
        "config.json": "community-config",
    }.get(rel, "copy")
    return SelectedFile(rel, candidate, transform)


def _read_source_bytes(selected: SelectedFile) -> bytes:
    try:
        return selected.source_path.read_bytes()
    except OSError as exc:
        raise ExportError(f"cannot read {selected.relative_path}: {exc}") from exc


def _normalise_text(data: bytes, relative_path: str) -> str:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ExportError(f"expected UTF-8 text in {relative_path}") from exc
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _without_paid_readme_section(text: str) -> str:
    """Return a community-safe README while preserving the source's docs."""

    # Do not publish a local developer path.
    text = re.sub(
        r"(?i)[A-Z]:\\Users\\[^\\\r\n]+\\Documents\\Projects\\whisper-dictate",
        "/path/to/whisper-dictate",
        text,
    )
    marker = re.search(
        r"(?m)^## License, buying, and releases[ \t]*$", text
    )
    if marker is not None:
        text = text[:marker.start()].rstrip() + "\n\n" + COMMUNITY_README_SECTION
    else:
        lower = text.casefold()
        paid_markers = (
            "polyform free trial",
            "whisperdictate.vercel.app",
            "stripe.md",
            "buy pro",
            "free 14-day trial",
            "pricing",
        )
        if any(marker in lower for marker in paid_markers):
            raise ExportError(
                "README has a paid section with an unknown heading; refusing export"
            )
        if "## community license and releases" not in lower:
            text = text.rstrip() + "\n\n" + COMMUNITY_README_SECTION
    lower = text.casefold()
    for marker in (
        "whisperdictate.vercel.app",
        "stripe.md",
        "stripe",
        "polyform free trial",
        "buy pro",
        "license_api",
        "license_required",
    ):
        if marker in lower:
            raise ExportError(f"README still contains excluded material: {marker}")
    return text


def _clean_config_value(value: object) -> object:
    if isinstance(value, dict):
        cleaned = {}
        for key, child in value.items():
            if not isinstance(key, str):
                raise ExportError("config.json contains a non-string object key")
            normalized = re.sub(r"[^a-z0-9]+", "", key.casefold())
            if normalized in _SENSITIVE_CONFIG_KEYS or any(
                marker in normalized
                for marker in (
                    "license",
                    "activation",
                    "stripe",
                    "payment",
                    "billing",
                    "pricing",
                    "webhook",
                    "secret",
                    "password",
                    "privatekey",
                    "token",
                )
            ):
                continue
            cleaned[key] = _clean_config_value(child)
        return cleaned
    if isinstance(value, list):
        return [_clean_config_value(item) for item in value]
    return value


def _community_config(data: bytes) -> bytes:
    try:
        parsed = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ExportError(f"config.json is not valid UTF-8 JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ExportError("config.json must contain a JSON object")
    cleaned = _clean_config_value(parsed)
    text = json.dumps(cleaned, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    encoded = text.encode("utf-8")
    _assert_no_secret_material("config.json", encoded)
    return encoded


def _community_main(data: bytes) -> bytes:
    """Remove only the paid activation integration from a generated main.py."""

    text = _normalise_text(data, "main.py")
    text = re.sub(r"(?m)^[ \t]*import[ \t]+license_gate[ \t]*\n", "", text)
    text = re.sub(
        r'''(?m)^[ \t]*['"]license_required['"]\s*:[^\n]*\n''', "", text
    )
    text = re.sub(
        r'''(?m)^[ \t]*['"]license_api['"]\s*:[^\n]*\n''', "", text
    )
    text = re.sub(
        r"(?m)^([ \t]*)# Untracked machine-specific overrides \(e\.g\. the copyright holder's own\n"
        r"\1# license_required:false\); never shipped or committed\.[^\n]*",
        r"\1# Untracked machine-specific overrides; never shipped or committed.",
        text,
    )

    guard = re.compile(
        r"(?m)^    if not DOCTOR and not license_gate\.ensure_licensed\(cfg, log\):\n"
        r"        log\(\"No license - exiting \(start again to activate, or see \"\n"
        r"            \"https://whisperdictate\.vercel\.app[^\n]*\n"
        r"        return\n"
    )
    text, guard_count = guard.subn("", text)
    if guard_count > 1:
        raise ExportError("main.py contains duplicate paid activation guards")

    notice = re.compile(
        r"(?m)^    # Broadcast message fetched during license revalidation \(notice\.json\)\.\n"
        r"    notice = license_gate\.pending_notice\(\)\n"
        r"    if notice:\n"
        r"        try:\n"
        r"            icon\.notify\(notice\[\"message\"\], APP_NAME\)\n"
        r"        except Exception:\n"
        r"            pass\n"
    )
    text, notice_count = notice.subn("", text)
    if notice_count > 1:
        raise ExportError("main.py contains duplicate paid notice blocks")

    # If a future edit changes the shape of those integrations, fail closed
    # instead of copying a half-sanitized runtime file.
    if re.search(r"\blicense_gate\b", text):
        raise ExportError("main.py still references license_gate after sanitization")
    if "whisperdictate.vercel.app" in text:
        raise ExportError("main.py still contains the paid API URL")
    if re.search(r"\blicense_(?:required|api)\b", text):
        raise ExportError("main.py still contains paid configuration keys")
    if not re.search(r"(?m)^[ \t]*import[ \t]+app_paths[ \t]*$", text):
        raise ExportError("main.py is missing the required app_paths import")
    encoded = text.encode("utf-8")
    _assert_no_secret_material("main.py", encoded)
    return encoded


def _assert_no_secret_material(relative_path: str, data: bytes) -> None:
    """Reject high-confidence secrets in text files before writing them."""

    # Binary application assets (icon/WAV) are not decoded or searched.
    if not relative_path.endswith((".py", ".md", ".json", ".txt", ".bat", ".sh", ".vbs", ".spec")):
        return
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return
    if _PRIVATE_KEY_MARKER.search(text):
        raise ExportError(f"possible private key in {relative_path}")
    for pattern in _SENSITIVE_VALUE_PATTERNS:
        if pattern.search(text):
            raise ExportError(f"possible secret or paid API value in {relative_path}")


def _transform_source(selected: SelectedFile) -> bytes:
    data = _read_source_bytes(selected)
    if selected.relative_path == "main.py":
        data = _community_main(data)
    elif selected.relative_path == "README.md":
        data = _without_paid_readme_section(
            _normalise_text(data, selected.relative_path)
        ).encode("utf-8")
    elif selected.relative_path == "config.json":
        data = _community_config(data)
    else:
        _assert_no_secret_material(selected.relative_path, data)
    return data


def select_source_files(source_root: Path | str | None = None) -> tuple[SelectedFile, ...]:
    """Return the allowlisted existing files in deterministic path order."""

    root = _normalise_source_root(source_root)
    selected: list[SelectedFile] = []
    seen: set[str] = set()
    for relative_path in ALLOWLIST_PATHS:
        item = _source_file(root, relative_path)
        if item is not None:
            selected.append(item)
            seen.add(item.relative_path)
    missing = sorted(REQUIRED_SOURCE_PATHS - seen)
    if missing:
        raise ExportError(
            "required runtime source file(s) missing from export source: "
            + ", ".join(missing)
        )
    return tuple(selected)


def _artifact_entries(artifacts: dict[str, bytes]) -> list[dict[str, object]]:
    entries = []
    for relative_path in sorted(artifacts):
        data = artifacts[relative_path]
        entry: dict[str, object] = {
            "path": relative_path,
            "size": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        }
        if relative_path == GENERATED_LICENSE_NAME:
            entry["origin"] = "generated-first-party-license"
        elif relative_path == MODEL_LICENSES_NAME:
            entry["origin"] = "generated-model-license-template"
        elif relative_path == "main.py":
            entry["transform"] = "community-runtime"
        elif relative_path == "README.md":
            entry["transform"] = "community-license-section"
        elif relative_path == "config.json":
            entry["transform"] = "community-config"
        if relative_path in EXECUTABLE_PATHS:
            entry["mode"] = "100755"
        entries.append(entry)
    return entries


def build_artifacts(source_root: Path | str | None = None) -> dict[str, bytes]:
    """Build the complete output payload without writing it to disk."""

    selected = select_source_files(source_root)
    artifacts: dict[str, bytes] = {
        GENERATED_LICENSE_NAME: MIT_LICENSE_TEXT.encode("utf-8"),
        MODEL_LICENSES_NAME: MODEL_LICENSES_TEMPLATE.encode("utf-8"),
    }
    for item in selected:
        if item.relative_path in artifacts:
            raise ExportError(f"generated and copied path collide: {item.relative_path}")
        artifacts[item.relative_path] = _transform_source(item)

    manifest = {
        "schema": MANIFEST_SCHEMA,
        "manifest": MANIFEST_NAME,
        "license": "MIT",
        "first_party_license": "MIT",
        "third_party_notices": "THIRD-PARTY-NOTICES.md",
        "model_licenses": MODEL_LICENSES_NAME,
        "files": _artifact_entries(artifacts),
    }
    # sort_keys makes object representation independent of construction order;
    # the files list itself is explicitly sorted above.
    artifacts[MANIFEST_NAME] = (
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    return dict(sorted(artifacts.items()))


def _safe_output_path(root: Path, relative_path: str) -> Path:
    rel = _norm_rel(relative_path)
    if is_denied(rel) and rel not in GENERATED_PATHS:
        raise ExportError(f"denied path reached output writer: {rel}")
    return root.joinpath(*PurePosixPath(rel).parts)


def _write_artifacts(stage: Path, artifacts: dict[str, bytes]) -> None:
    for relative_path in sorted(artifacts):
        destination = _safe_output_path(stage, relative_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            destination.write_bytes(artifacts[relative_path])
            if relative_path in EXECUTABLE_PATHS and os.name != "nt":
                destination.chmod(0o755)
        except OSError as exc:
            raise ExportError(f"cannot write {relative_path}: {exc}") from exc


def _validate_stage(stage: Path, artifacts: dict[str, bytes]) -> None:
    expected = set(artifacts)
    actual: set[str] = set()
    for path in stage.rglob("*"):
        rel = path.relative_to(stage).as_posix()
        if path.is_symlink():
            raise ExportError(f"symlink unexpectedly created in output: {rel}")
        if path.is_dir():
            continue
        actual.add(rel)
        if is_denied(rel) and rel not in GENERATED_PATHS:
            raise ExportError(f"denied path unexpectedly created in output: {rel}")
        if rel not in expected:
            raise ExportError(f"unexpected output file: {rel}")
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != hashlib.sha256(artifacts[rel]).hexdigest():
            raise ExportError(f"output bytes do not match planned file: {rel}")
    if actual != expected:
        missing = ", ".join(sorted(expected - actual))
        raise ExportError(f"output validation failed; missing files: {missing}")


def _reject_output_tree_symlinks(output: Path) -> None:
    if not output.exists() or output.is_symlink():
        return
    for child in output.rglob("*"):
        if child.is_symlink():
            raise ExportError(f"refusing symlink inside output directory: {child}")


def _remove_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.exists():
        shutil.rmtree(path)


def _install_stage(stage: Path, output: Path, force: bool) -> None:
    # Recheck immediately before replacement to avoid silently destroying a
    # file that appeared after the initial nonempty-output check.  Move an
    # existing destination to a temporary sibling first so an install failure
    # can restore it instead of leaving the caller with a half-replaced tree.
    backup: Path | None = None
    if output.exists():
        if output.is_symlink() or not output.is_dir():
            raise ExportError(f"output path is not a regular directory: {output}")
        _reject_output_tree_symlinks(output)
        if any(output.iterdir()) and not force:
            raise ExportError(
                f"output directory is not empty: {output}; pass --force to replace it"
            )
        backup = output.parent / f"{stage.name}.previous"
        if backup.exists() or backup.is_symlink():
            raise ExportError(f"temporary export backup already exists: {backup}")
        try:
            os.replace(output, backup)
        except OSError as exc:
            raise ExportError(f"cannot stage existing output {output}: {exc}") from exc
    try:
        os.replace(stage, output)
    except OSError as exc:
        if backup is not None and backup.exists() and not output.exists():
            try:
                os.replace(backup, output)
            except OSError as rollback_exc:
                raise ExportError(
                    f"cannot install export at {output}: {exc}; "
                    f"rollback also failed: {rollback_exc}"
                ) from rollback_exc
        raise ExportError(f"cannot install export at {output}: {exc}") from exc
    finally:
        if backup is not None and (backup.exists() or backup.is_symlink()):
            try:
                _remove_path(backup)
            except OSError:
                # The new export is already installed; do not turn a harmless
                # temporary cleanup problem into a false installation failure.
                pass


def export_community(
    source_root: Path | str | None = None,
    output_dir: Path | str | None = None,
    *,
    output: Path | str | None = None,
    force: bool = False,
) -> Path:
    """Export the community source and return the output directory.

    ``output`` is a keyword alias for ``output_dir`` for small integrations.
    ``force`` is deliberately a named, explicit argument.  It is only used to
    replace an existing nonempty directory; source files are never removed.
    """

    if output is not None:
        if output_dir is not None:
            raise ExportError("provide only one of output_dir and output")
        output_dir = output
    if output_dir is None:
        raise ExportError("an output directory is required")
    if not isinstance(force, bool):
        raise ExportError("force must be a boolean")
    root = _normalise_source_root(source_root)
    output = _normalise_output(output_dir, root)
    _check_nonempty_output(output, force)
    artifacts = build_artifacts(root)
    output.parent.mkdir(parents=True, exist_ok=True)
    stage: Path | None = None
    try:
        stage = Path(
            tempfile.mkdtemp(
                prefix=".community-export-stage-", dir=str(output.parent)
            )
        )
        _write_artifacts(stage, artifacts)
        _validate_stage(stage, artifacts)
        _install_stage(stage, output, force)
        stage = None
    finally:
        if stage is not None and stage.exists():
            shutil.rmtree(stage, ignore_errors=True)
    return output


# Compatibility/readability aliases for callers that prefer a longer name.
export_community_source = export_community
export_community_tree = export_community
build_community_export = build_artifacts


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Export a deterministic, allowlisted Whisper Dictate community source tree."
    )
    parser.add_argument(
        "output_dir",
        nargs="?",
        type=Path,
        help="destination directory (must be outside the source tree)",
    )
    parser.add_argument(
        "-o",
        "--output",
        "--output-dir",
        dest="output_option",
        type=Path,
        help="named alternative to the positional output directory",
    )
    parser.add_argument(
        "--source-root",
        "--source",
        dest="source_root",
        type=Path,
        default=None,
        help="source checkout (defaults to this script's repository root)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="replace a nonempty output directory",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.output_dir is None and args.output_option is None:
        parser.error("an output directory is required")
    if args.output_dir is not None and args.output_option is not None:
        parser.error("provide the output directory either positionally or with --output, not both")
    output = args.output_dir if args.output_dir is not None else args.output_option
    try:
        result = export_community(args.source_root, output, force=args.force)
    except (ExportError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"Community source export written to {result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
