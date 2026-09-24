"""Pinned, source-independent model resolution for Nemotron checkpoints.

The application deliberately does not make the model manager depend on a
particular downloader or on the Hugging Face cache layout.  A manifest names
an exact model revision and the files that the Transformers loader needs.  A
manager can then resolve that manifest from, in a configurable order:

* an explicitly supplied local directory;
* a complete local/Hugging Face cache;
* a configured HTTPS mirror; or
* the pinned Hugging Face snapshot.

Only files listed in ``required_files`` are requested.  In particular, the
NeMo ``.nemo`` and NeMo-Speech.cpp ``.gguf`` artifacts are not downloaded for
the current Transformers engine.

The module uses only the Python standard library.  Network access is isolated
behind ``downloader`` and the sleep/backoff hook so tests and alternative
integrations can provide their own implementations.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import shutil
import tempfile
import threading
import time
import uuid
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

MANIFEST_SCHEMA_VERSION = 1
DEFAULT_SOURCE_ORDER = ("local", "cache", "mirror", "huggingface")
_HF_ENDPOINT = "https://huggingface.co"
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_REVISION_NAME_RE = re.compile(r"^[A-Za-z0-9._/-]+$")
_FLOATING_REVISIONS = {"main", "master", "latest", "head"}
_SOURCE_ALIASES = {
    "local": "local",
    "path": "local",
    "directory": "local",
    "local_dir": "local",
    "cache": "cache",
    "cache_dir": "cache",
    "hf_cache": "cache",
    "huggingface-cache": "cache",
    "huggingface_cache": "cache",
    "mirror": "mirror",
    "https_mirror": "mirror",
    "https-mirror": "mirror",
    "https": "mirror",
    "huggingface": "huggingface",
    "hf": "huggingface",
    "remote": "huggingface",
}


# ---------------------------------------------------------------------------
# Errors


class ModelManagerError(Exception):
    """Base class for model resolution and integrity failures."""


class ManifestError(ModelManagerError):
    """The manifest is malformed or does not describe a usable model."""


class ModelResolutionError(ModelManagerError):
    """No configured source produced the requested pinned model."""

    def __init__(self, message: str, *, trace: Sequence[ResolutionEvent] = ()):
        super().__init__(message)
        self.trace = tuple(trace)
        self.failures = self.trace


class ModelNotFoundError(ModelResolutionError):
    """A configured local/cache directory does not exist."""


class IncompleteModelError(ModelResolutionError):
    """A snapshot exists but one or more required files are missing."""


class ModelIntegrityError(ModelResolutionError):
    """A file has the wrong size or SHA-256 digest."""


class ModelDownloadError(ModelResolutionError):
    """A remote source could not be fetched after the configured retries."""


class OfflineModelUnavailableError(ModelResolutionError):
    """Offline mode was requested but no complete local snapshot exists."""


class LanguageMismatchError(ModelResolutionError):
    """The requested profile language is not part of the pinned model."""


# Friendly aliases for callers that prefer the more explicit names.
ManifestValidationError = ManifestError
ModelCorruptError = ModelIntegrityError
PartialModelError = IncompleteModelError


# ---------------------------------------------------------------------------
# Manifest data types


@dataclass(frozen=True)
class ModelFile:
    """One immutable file entry in a model manifest."""

    name: str
    size: int
    sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ManifestError("model file name must be a non-empty string")
        name = self.name.replace("\\", "/")
        if name.startswith(("/", "../")) or "/../" in name or ":" in name:
            raise ManifestError(f"unsafe model file name in manifest: {self.name!r}")
        if any(part in {"", ".", ".."} for part in name.split("/")):
            raise ManifestError(f"unsafe model file name in manifest: {self.name!r}")
        if not isinstance(self.size, int) or isinstance(self.size, bool) or self.size < 0:
            raise ManifestError(f"invalid size for model file {self.name!r}")
        if not isinstance(self.sha256, str) or not _SHA256_RE.fullmatch(self.sha256):
            raise ManifestError(
                f"invalid SHA-256 for model file {self.name!r}; expected 64 hex characters"
            )
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "sha256", self.sha256.lower())

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> ModelFile:
        if isinstance(data, cls):
            return data
        if not isinstance(data, Mapping):
            raise ManifestError("a model file entry must be a JSON object")
        try:
            return cls(
                name=data.get("name", data.get("filename")),
                size=data.get("size", data.get("size_bytes")),
                sha256=data.get("sha256", data.get("sha256sum", data.get("hash"))),
            )
        except KeyError as exc:
            raise ManifestError(f"file entry is missing {exc.args[0]!r}") from exc

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "size": self.size, "sha256": self.sha256}


@dataclass(frozen=True)
class ModelManifest:
    """An exact model identity and the files needed to load it.

    ``required_files`` is intentionally explicit.  Optional files (for
    example ``.nemo`` or ``.gguf``) are never used by this Transformers
    integration and are therefore not required for a resolved snapshot.
    """

    model_id: str
    revision: str
    required_files: tuple[ModelFile, ...]
    optional_files: tuple[ModelFile, ...] = ()
    language: str | None = None
    languages: tuple[str, ...] = ()
    model_type: str | None = None
    architectures: tuple[str, ...] = ()
    license: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.model_id, str) or not self.model_id.strip():
            raise ManifestError("manifest model_id must be a non-empty string")
        model_id_parts = self.model_id.strip().split("/")
        if (
            model_id_parts[0] in {"", ".", ".."}
            or any(part in {"", ".", ".."} for part in model_id_parts)
        ):
            raise ManifestError(f"unsafe model_id in manifest: {self.model_id!r}")
        if (
            not isinstance(self.revision, str)
            or not self.revision.strip()
            or not _REVISION_NAME_RE.fullmatch(self.revision)
            or self.revision.startswith("/")
            or self.revision.endswith("/")
            or ".." in self.revision.split("/")
            or self.revision.lower() in _FLOATING_REVISIONS
        ):
            raise ManifestError(
                f"manifest for {self.model_id!r} needs an immutable revision, "
                "not a branch such as main"
            )
        required = tuple(self.required_files or ())
        optional = tuple(self.optional_files or ())
        if not required:
            raise ManifestError(f"manifest for {self.model_id!r} has no required files")
        for entry in (*required, *optional):
            if not isinstance(entry, ModelFile):
                raise ManifestError(
                    f"manifest files for {self.model_id!r} must be ModelFile objects"
                )
        names = [entry.name for entry in (*required, *optional)]
        if len(names) != len(set(names)):
            raise ManifestError(f"manifest for {self.model_id!r} lists a file twice")
        language_values = (
            (self.languages,)
            if isinstance(self.languages, str)
            else (self.languages or ())
        )
        languages = tuple(
            str(item).strip().lower().replace("_", "-")
            for item in language_values
            if str(item).strip()
        )
        if self.language:
            language = str(self.language).strip().lower().replace("_", "-")
            if language != "multilingual" and not languages:
                languages = (language,)
        architecture_values = (
            (self.architectures,)
            if isinstance(self.architectures, str)
            else (self.architectures or ())
        )
        object.__setattr__(self, "model_id", self.model_id.strip())
        object.__setattr__(self, "revision", self.revision.strip())
        object.__setattr__(self, "required_files", required)
        object.__setattr__(self, "optional_files", optional)
        object.__setattr__(self, "language", str(self.language).lower().replace("_", "-") if self.language else None)
        object.__setattr__(self, "languages", languages)
        object.__setattr__(self, "architectures", tuple(str(item) for item in architecture_values))

    @property
    def files(self) -> tuple[ModelFile, ...]:
        """All manifest files, required first."""

        return self.required_files + self.optional_files

    @property
    def allowed_languages(self) -> tuple[str, ...]:
        if self.languages:
            return self.languages
        if self.language and self.language != "multilingual":
            return (self.language,)
        return ()

    def supports_language(self, language: str | None) -> bool:
        if not language:
            return True
        if not self.allowed_languages:
            return True
        candidate = str(language).strip().lower().replace("_", "-")
        if candidate == "multilingual" or candidate in self.allowed_languages:
            return True
        base = candidate.split("-", 1)[0]
        return base in self.allowed_languages

    def fingerprint(self) -> str:
        """Stable digest of the manifest metadata (not of downloaded bytes)."""

        encoded = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> ModelManifest:
        if isinstance(data, cls):
            return data
        if not isinstance(data, Mapping):
            raise ManifestError("a model manifest must be a JSON object")
        schema_version = data.get("schema_version", MANIFEST_SCHEMA_VERSION)
        if schema_version != MANIFEST_SCHEMA_VERSION:
            raise ManifestError(
                f"unsupported model manifest schema version {schema_version!r}; "
                f"expected {MANIFEST_SCHEMA_VERSION}"
            )
        model_id = data.get(
            "model_id",
            data.get(
                "id",
                data.get("repo", data.get("repository", data.get("repo_id"))),
            ),
        )
        revision = data.get("revision")
        if not model_id or not revision:
            raise ManifestError("each model manifest needs model_id/id and revision")

        def files_from(value: Any) -> tuple[ModelFile, ...]:
            if value is None:
                return ()
            if isinstance(value, Mapping):
                value = [dict(spec, name=name) for name, spec in value.items()]
            if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
                raise ManifestError(f"file list for {model_id!r} must be an array")
            result = []
            for spec in value:
                if not isinstance(spec, Mapping):
                    raise ManifestError(f"file entries for {model_id!r} must be objects")
                result.append(ModelFile.from_mapping(spec))
            return tuple(result)

        raw_required = data.get("required_files")
        raw_optional: Any = data.get("optional_files")
        if raw_required is None and "files" in data:
            raw_files = data["files"]
            if isinstance(raw_files, Mapping):
                raw_files = [dict(spec, name=name) for name, spec in raw_files.items()]
            if not isinstance(raw_files, Sequence) or isinstance(raw_files, (str, bytes)):
                raise ManifestError(f"file list for {model_id!r} must be an array")
            raw_required = []
            embedded_optional = []
            for spec in raw_files:
                if isinstance(spec, Mapping) and spec.get("required") is False:
                    embedded_optional.append(spec)
                else:
                    raw_required.append(spec)
            if isinstance(raw_optional, Mapping):
                raw_optional = [
                    dict(spec, name=name) for name, spec in raw_optional.items()
                ]
            raw_optional = list(embedded_optional) + list(raw_optional or [])
        required = files_from(raw_required)
        optional = files_from(raw_optional)
        if not required:
            raise ManifestError(f"manifest for {model_id!r} has no required files")
        return cls(
            model_id=str(model_id),
            revision=str(revision),
            required_files=required,
            optional_files=optional,
            language=data.get("language", data.get("lang")),
            languages=tuple(data.get("languages", data.get("locales")) or ()),
            model_type=data.get("model_type"),
            architectures=tuple(data.get("architectures") or ()),
            license=data.get("license"),
        )

    from_dict = from_mapping

    @classmethod
    def from_json(cls, path: str | os.PathLike[str]) -> ModelManifest:
        return load_manifest(path)

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "schema_version": MANIFEST_SCHEMA_VERSION,
            "id": self.model_id,
            "revision": self.revision,
            "required_files": [entry.to_dict() for entry in self.required_files],
            "optional_files": [entry.to_dict() for entry in self.optional_files],
        }
        if self.language:
            result["language"] = self.language
        if self.languages:
            result["languages"] = list(self.languages)
        if self.model_type:
            result["model_type"] = self.model_type
        if self.architectures:
            result["architectures"] = list(self.architectures)
        if self.license:
            result["license"] = self.license
        return result


@dataclass(frozen=True)
class ModelManifestCatalog:
    """A set of manifests, normally the two documented defaults."""

    manifests: tuple[ModelManifest, ...]

    def __post_init__(self) -> None:
        values = tuple(self.manifests or ())
        if not values:
            raise ManifestError("a model manifest catalog cannot be empty")
        if any(not isinstance(item, ModelManifest) for item in values):
            raise ManifestError("catalog entries must be ModelManifest objects")
        object.__setattr__(self, "manifests", values)

    def __iter__(self):
        return iter(self.manifests)

    def __len__(self) -> int:
        return len(self.manifests)

    def __getitem__(self, key: str | int) -> ModelManifest:
        if isinstance(key, int):
            return self.manifests[key]
        return self.get(key)

    def __contains__(self, model_id: object) -> bool:
        return any(item.model_id == model_id for item in self.manifests)

    def get(self, model_id: str, revision: str | None = None) -> ModelManifest:
        matches = [item for item in self.manifests if item.model_id == model_id]
        if revision is not None:
            matches = [item for item in matches if item.revision == revision]
        if not matches:
            suffix = f" at revision {revision!r}" if revision else ""
            raise ManifestError(f"no manifest for model {model_id!r}{suffix}")
        if len(matches) > 1:
            revisions = ", ".join(sorted(item.revision for item in matches))
            raise ManifestError(
                f"multiple manifests exist for {model_id!r}; choose a pinned revision ({revisions})"
            )
        return matches[0]

    def for_language(self, language: str) -> ModelManifest:
        matches = [item for item in self.manifests if item.supports_language(language)]
        if len(matches) != 1:
            choices = ", ".join(item.model_id for item in self.manifests)
            raise ManifestError(
                f"language {language!r} does not identify one pinned model (choices: {choices})"
            )
        return matches[0]

    @classmethod
    def from_data(cls, data: Any) -> ModelManifestCatalog:
        if isinstance(data, cls):
            return data
        if isinstance(data, ModelManifest):
            return cls((data,))
        if isinstance(data, Mapping):
            schema_version = data.get("schema_version", MANIFEST_SCHEMA_VERSION)
            if schema_version != MANIFEST_SCHEMA_VERSION:
                raise ManifestError(
                    f"unsupported model manifest schema version {schema_version!r}; "
                    f"expected {MANIFEST_SCHEMA_VERSION}"
                )
            if "models" in data:
                values = data["models"]
                if isinstance(values, Mapping):
                    converted = []
                    for model_id, value in values.items():
                        if not isinstance(value, Mapping):
                            raise ManifestError(
                                f"manifest catalog entry {model_id!r} must be an object"
                            )
                        item = dict(value)
                        item.setdefault("model_id", model_id)
                        converted.append(item)
                    values = converted
            elif (
                "model_id" in data
                or "id" in data
                or "repo" in data
                or "repo_id" in data
            ):
                values = [data]
            else:
                values = []
                for model_id, value in data.items():
                    if model_id == "schema_version":
                        continue
                    if isinstance(value, Mapping):
                        item = dict(value)
                        item.setdefault("model_id", model_id)
                        values.append(item)
                    else:
                        raise ManifestError(
                            f"manifest catalog entry {model_id!r} must be an object"
                        )
        elif isinstance(data, Sequence) and not isinstance(data, (str, bytes)):
            values = data
        else:
            raise ManifestError("model manifest catalog must be an object or array")
        if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
            raise ManifestError("model manifest catalog 'models' must be an array")
        return cls(tuple(ModelManifest.from_mapping(item) for item in values))


# The metadata below was audited against the Hugging Face commits on
# 2026-09-24.  The six required files are exactly the files used by the
# current Transformers loader.  Optional NeMo/GGUF files are recorded for
# auditability but are never fetched by ModelManager.
DEFAULT_MANIFEST_DATA: dict[str, Any] = {
    "schema_version": MANIFEST_SCHEMA_VERSION,
    "models": [
        {
            "id": "nvidia/nemotron-speech-streaming-en-0.6b",
            "revision": "ebe59e5a817142986528bbbee5dba8db7b38ed50",
            "language": "en",
            "languages": ["en"],
            "model_type": "nemotron_asr_streaming",
            "architectures": ["NemotronAsrStreamingForRNNT"],
            "license": "NVIDIA Open Model License",
            "required_files": [
                {
                    "name": "config.json",
                    "size": 1284,
                    "sha256": "dffe850bc79ad2b0f8117804502b24d2c4a445aafbed4c1e40f8d78e0cb44065",
                },
                {
                    "name": "generation_config.json",
                    "size": 192,
                    "sha256": "6ce531b39df8046cc8dbbe29dc64458b72972011d4717e160e6efb2c1af198d1",
                },
                {
                    "name": "model.safetensors",
                    "size": 2472413604,
                    "sha256": "bddd8a7300826efd19cf7e01f1c7db8402bed6786fc4c7739632894f69c71473",
                },
                {
                    "name": "processor_config.json",
                    "size": 525,
                    "sha256": "cf35efc9abdd0963db7e96967f8a91d9c8243803b9f6bbd900aa936ee3ce42f3",
                },
                {
                    "name": "tokenizer.json",
                    "size": 400216,
                    "sha256": "60dc0361763fa3cd62df60f34fca3e61134676a939967853931db5f3869b2db2",
                },
                {
                    "name": "tokenizer_config.json",
                    "size": 270,
                    "sha256": "0665bee664daf39a155e5ee013bb1d885c58b4901994abc07b9a6b3904cce132",
                },
            ],
            "optional_files": [
                {
                    "name": "nemotron-speech-streaming-en-0.6b.nemo",
                    "size": 2473041920,
                    "sha256": "283638054c44f6794e74fe9af9048d78a6d9d6c058c12131856c7859a62ac9cd",
                },
                {
                    "name": "nemotron-speech-streaming-en-0.6b.q8_0.gguf",
                    "size": 699872960,
                    "sha256": "d9a01898d2a611c8764e23a1c2f45e70bbd5a425dc4de93692ac951dd603812d",
                },
            ],
        },
        {
            "id": "nvidia/nemotron-3.5-asr-streaming-0.6b",
            "revision": "ea30d66debe3740a08b573244286791d423d6b3e",
            "language": "multilingual",
            "languages": [
                "en",
                "es",
                "de",
                "fr",
                "it",
                "ar",
                "ja",
                "ko",
                "pt",
                "ru",
                "hi",
                "zh",
                "vi",
                "he",
                "nl",
                "cs",
                "da",
                "pl",
                "no",
                "sv",
                "th",
                "tr",
                "bg",
                "el",
                "et",
                "fi",
                "hr",
                "hu",
                "lt",
                "lv",
                "ro",
                "sk",
                "uk",
                "mt",
                "sl",
            ],
            "model_type": "nemotron3_5_asr",
            "architectures": ["Nemotron3_5AsrForRNNT"],
            "license": "OpenMDW-1.1",
            "required_files": [
                {
                    "name": "config.json",
                    "size": 1376,
                    "sha256": "62d186fd91f518e00e7867500f1f5819225e8ee95ea3e21b546514bf2048e845",
                },
                {
                    "name": "generation_config.json",
                    "size": 193,
                    "sha256": "993e5d4cb74a6fe9d6e7084a76b3313c1446740679be4676570c23b664fdc07e",
                },
                {
                    "name": "model.safetensors",
                    "size": 2552062944,
                    "sha256": "9eebdd6590289cb3030f310858f3df93256600a800a3e8200c5993d5f967e174",
                },
                {
                    "name": "processor_config.json",
                    "size": 2519,
                    "sha256": "ec47870f1091ea4f25539208387b45b902c92d0e3f997a30061ef88f73437ab0",
                },
                {
                    "name": "tokenizer.json",
                    "size": 752051,
                    "sha256": "3f3d481deb073b64c2082e8c7860d487a3a62774bf4e9e4faac83007e181f246",
                },
                {
                    "name": "tokenizer_config.json",
                    "size": 881,
                    "sha256": "5c641c5b3f50702a60082690d27c1ce7fcb5a92c4a624793bcae0f21eda3d6e0",
                },
            ],
            "optional_files": [
                {
                    "name": "nemotron-3.5-asr-streaming-0.6b.nemo",
                    "size": 2368284501,
                    "sha256": "210214ed94039bf6bfbb9a047c7fa289628db75b103e2bf6381fa78285436a74",
                },
                {
                    "name": "nemotron-3.5-asr-streaming-0.6b.q8_0.gguf",
                    "size": 742090464,
                    "sha256": "3fc991d3badad7277c11030a7519832cddaf2057aafed6d4b25147e953a070b1",
                },
            ],
        },
    ],
}


def default_manifest_data() -> dict[str, Any]:
    """Return a defensive copy suitable for editing or writing to disk."""

    return copy.deepcopy(DEFAULT_MANIFEST_DATA)


def default_manifests() -> ModelManifestCatalog:
    return ModelManifestCatalog.from_data(default_manifest_data())


# Public immutable convenience value for callers that do not need to reload
# the audited defaults from JSON.
DEFAULT_MANIFESTS = default_manifests()


def load_manifest(path: str | os.PathLike[str]) -> ModelManifest:
    """Load a single-model manifest JSON file."""

    data = _read_json(path)
    if isinstance(data, Mapping) and "models" in data:
        catalog = ModelManifestCatalog.from_data(data)
        if len(catalog) != 1:
            raise ManifestError(f"{path} must contain exactly one model")
        return catalog.manifests[0]
    return ModelManifest.from_mapping(data)


def load_manifest_catalog(path: str | os.PathLike[str]) -> ModelManifestCatalog:
    """Load a manifest file containing one or more models."""

    return ModelManifestCatalog.from_data(_read_json(path))


def _read_json(path: str | os.PathLike[str]) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except OSError as exc:
        raise ManifestError(f"cannot read model manifest {path!s}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ManifestError(f"invalid JSON in model manifest {path!s}: {exc}") from exc


# ---------------------------------------------------------------------------
# Snapshot validation and download primitives


@dataclass(frozen=True)
class SnapshotValidation:
    path: Path
    checked_files: tuple[str, ...]
    missing_files: tuple[str, ...]
    size_mismatches: tuple[tuple[str, int, int], ...]
    hash_mismatches: tuple[tuple[str, str], ...]

    @property
    def valid(self) -> bool:
        return not (self.missing_files or self.size_mismatches or self.hash_mismatches)

    @property
    def complete(self) -> bool:
        return not self.missing_files

    @property
    def missing(self) -> tuple[str, ...]:
        return self.missing_files

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "checked_files": list(self.checked_files),
            "missing_files": list(self.missing_files),
            "size_mismatches": [list(item) for item in self.size_mismatches],
            "hash_mismatches": [list(item) for item in self.hash_mismatches],
            "valid": self.valid,
        }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise ModelIntegrityError(f"cannot read {path}: {exc}") from exc
    return digest.hexdigest()


def verify_model_file(path: str | os.PathLike[str], expected: ModelFile | Mapping[str, Any]) -> None:
    """Verify one file's size and SHA-256, with an actionable error."""

    if not isinstance(expected, ModelFile):
        expected = ModelFile.from_mapping(expected)
    file_path = Path(path)
    if not file_path.exists():
        raise IncompleteModelError(f"required model file is missing: {file_path}")
    if not file_path.is_file():
        raise ModelIntegrityError(f"required model path is not a regular file: {file_path}")
    try:
        actual_size = file_path.stat().st_size
    except OSError as exc:
        raise ModelIntegrityError(f"cannot stat required model file {file_path}: {exc}") from exc
    if actual_size != expected.size:
        raise ModelIntegrityError(
            f"size mismatch for {file_path}: expected {expected.size} bytes, "
            f"found {actual_size}"
        )
    actual_hash = _sha256(file_path)
    if actual_hash != expected.sha256:
        raise ModelIntegrityError(
            f"SHA-256 mismatch for {file_path}: expected {expected.sha256}, "
            f"found {actual_hash}"
        )


def validate_snapshot(
    path: str | os.PathLike[str],
    manifest: ModelManifest | Mapping[str, Any],
    *,
    raise_on_error: bool = True,
) -> SnapshotValidation:
    """Validate all required files in a local snapshot.

    Optional ``.nemo``/``.gguf`` files are ignored.  A size mismatch is
    treated as corruption/partial transfer and is reported separately from a
    missing file so callers can show a useful repair instruction.
    """

    if not isinstance(manifest, ModelManifest):
        manifest = ModelManifest.from_mapping(manifest)
    root = Path(path)
    if not root.exists():
        report = SnapshotValidation(
            root,
            (),
            tuple(entry.name for entry in manifest.required_files),
            (),
            (),
        )
        if raise_on_error:
            raise ModelNotFoundError(
                f"model snapshot does not exist: {root}; expected revision "
                f"{manifest.revision!r} for {manifest.model_id}"
            )
        return report
    if not root.is_dir():
        report = SnapshotValidation(root, (), tuple(entry.name for entry in manifest.required_files), (), ())
        if raise_on_error:
            raise ModelNotFoundError(f"model snapshot is not a directory: {root}")
        return report

    missing: list[str] = []
    size_mismatches: list[tuple[str, int, int]] = []
    hash_mismatches: list[tuple[str, str]] = []
    checked: list[str] = []
    for entry in manifest.required_files:
        file_path = root / Path(entry.name)
        if not file_path.exists():
            missing.append(entry.name)
            continue
        checked.append(entry.name)
        if not file_path.is_file():
            size_mismatches.append((entry.name, entry.size, -1))
            continue
        try:
            actual_size = file_path.stat().st_size
        except OSError:
            size_mismatches.append((entry.name, entry.size, -1))
            continue
        if actual_size != entry.size:
            size_mismatches.append((entry.name, entry.size, actual_size))
            continue
        try:
            actual_hash = _sha256(file_path)
        except ModelIntegrityError:
            hash_mismatches.append((entry.name, "unreadable"))
            continue
        if actual_hash != entry.sha256:
            hash_mismatches.append((entry.name, actual_hash))
    report = SnapshotValidation(
        root,
        tuple(checked),
        tuple(missing),
        tuple(size_mismatches),
        tuple(hash_mismatches),
    )
    if raise_on_error and not report.valid:
        details = _format_validation_failure(report)
        if report.missing_files and not report.size_mismatches and not report.hash_mismatches:
            raise IncompleteModelError(
                f"model snapshot is incomplete at {root}: {details}. "
                "Restore the missing files or configure an allowed source."
            )
        raise ModelIntegrityError(
            f"model snapshot failed integrity checks at {root}: {details}. "
            "Delete/re-fetch the snapshot; do not load unverified weights."
        )
    return report


def _format_validation_failure(report: SnapshotValidation) -> str:
    parts: list[str] = []
    if report.missing_files:
        parts.append("missing " + ", ".join(report.missing_files))
    for name, expected, actual in report.size_mismatches:
        parts.append(f"size mismatch {name} (expected {expected}, found {actual})")
    for name, actual in report.hash_mismatches:
        parts.append(f"SHA-256 mismatch {name} ({actual})")
    return "; ".join(parts) or "unknown validation failure"


def _invoke_downloader(downloader: Callable[..., Any] | Any, url: str, destination: Path) -> Any:
    method = getattr(downloader, "download", None)
    if callable(method):
        return method(url, destination)
    return downloader(url, destination)


def _write_result_to_temp(result: Any, temporary: Path, destination: Path) -> None:
    if result is None:
        return
    if isinstance(result, (bytes, bytearray, memoryview)):
        temporary.write_bytes(bytes(result))
        return
    if isinstance(result, (str, os.PathLike)):
        result_path = Path(result)
        if result_path.exists() and result_path != temporary:
            shutil.copyfile(result_path, temporary)
        return
    if not temporary.exists():
        raise ModelDownloadError(
            f"downloader for {destination} returned {type(result).__name__} without writing a file"
        )


def _default_stream_to_file(
    url: str,
    destination: Path,
    timeout: float,
    require_https: bool = True,
) -> None:
    request = Request(
        url,
        headers={
            "User-Agent": "whisper-dictate-model-manager/1",
            "Accept-Encoding": "identity",
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            final_url = getattr(response, "geturl", lambda: url)() or url
            if require_https and urlparse(final_url).scheme.lower() != "https":
                raise ModelDownloadError(
                    f"model download redirected to a non-HTTPS URL: {final_url!r}"
                )
            with open(destination, "wb") as handle:
                shutil.copyfileobj(response, handle)
    except Exception:
        # The caller owns retry/error translation.  Remove a possibly partial
        # response before it can be mistaken for a completed file.
        try:
            destination.unlink()
        except OSError:
            pass
        raise


def atomic_download(
    url: str,
    destination: str | os.PathLike[str],
    *,
    downloader: Callable[..., Any] | Any | None = None,
    timeout: float = 60.0,
    download_hook: Callable[..., Any] | None = None,
    atomic_replace: Callable[[Path, Path], Any] | None = None,
    attempt: int = 0,
    require_https: bool = True,
) -> Path:
    """Download ``url`` to a temporary sibling and atomically publish it.

    ``downloader`` may be a callable ``(url, path)`` or an object with a
    ``download(url, path)`` method.  It may write the supplied path, return
    bytes, or return an already-written local path.  This makes the network
    seam easy to fake without a 2.5 GB test download.
    """

    if require_https:
        parsed = urlparse(url)
        if parsed.scheme.lower() != "https" or not parsed.netloc:
            raise ModelDownloadError(f"model download must use HTTPS: {url!r}")
    target = Path(destination)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".part", dir=str(target.parent)
    )
    os.close(fd)
    temporary = Path(temporary_name)
    try:
        if download_hook:
            try:
                download_hook("start", url, target, attempt)
            except Exception:  # noqa: BLE001,S110 - observer must not block download
                pass
        if downloader is None:
            _default_stream_to_file(url, temporary, timeout, require_https)
        else:
            result = _invoke_downloader(downloader, url, temporary)
            _write_result_to_temp(result, temporary, target)
        if not temporary.exists() or not temporary.is_file():
            raise ModelDownloadError(f"downloader did not produce a file for {url}")
        (atomic_replace or os.replace)(temporary, target)
        if download_hook:
            try:
                download_hook("complete", url, target, attempt)
            except Exception:  # noqa: BLE001,S110 - observer must not mask success
                pass
        return target
    except Exception as exc:
        if download_hook:
            try:
                download_hook("failed", url, target, attempt, exc)
            except Exception:  # noqa: BLE001,S110 - observer must not mask download errors
                pass
        raise
    finally:
        try:
            temporary.unlink()
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Resolver configuration and results


@dataclass(frozen=True)
class ResolutionEvent:
    source: str
    status: str
    detail: str
    path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        result = {"source": self.source, "status": self.status, "detail": self.detail}
        if self.path is not None:
            result["path"] = self.path
        return result


@dataclass(frozen=True)
class ResolvedModel:
    manifest: ModelManifest
    path: Path
    source: str
    trace: tuple[ResolutionEvent, ...] = ()

    @property
    def local_path(self) -> Path:
        return self.path

    @property
    def snapshot_path(self) -> Path:
        return self.path

    def __fspath__(self) -> str:
        return os.fspath(self.path)

    @property
    def model_id(self) -> str:
        return self.manifest.model_id

    @property
    def revision(self) -> str:
        return self.manifest.revision

    @property
    def source_order(self) -> tuple[str, ...]:
        """Sources actually attempted, in the configured order."""

        return tuple(
            dict.fromkeys(
                event.source for event in self.trace if event.source != "resolver"
            )
        )

    @property
    def resolution_trace(self) -> tuple[ResolutionEvent, ...]:
        return self.trace

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "revision": self.revision,
            "path": str(self.path),
            "source": self.source,
            "source_order": list(self.source_order),
            "trace": [event.to_dict() for event in self.trace],
        }


@dataclass(frozen=True)
class ModelResolverSettings:
    """Normalized resolver settings extracted from JSON configuration."""

    model_id: str | None = None
    local_path: Path | None = None
    revision: str | None = None
    language: str | None = None
    manifest: Any | None = None
    cache_dir: Path | None = None
    cache_path: Path | None = None
    local_model_dir: Path | None = None
    mirror_url: str | None = None
    huggingface_endpoint: str = _HF_ENDPOINT
    source_order: tuple[str, ...] = DEFAULT_SOURCE_ORDER
    offline: bool = False
    max_retries: int = 3
    backoff_factor: float = 1.0
    max_backoff: float = 30.0


def _pick(mapping: Mapping[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in mapping and mapping[key] is not None:
            return mapping[key]
    return default


def _optional_path(value: Any) -> Path | None:
    if value is None or value == "":
        return None
    return Path(os.path.expandvars(os.path.expanduser(os.fspath(value))))


def normalize_source_order(value: Sequence[str] | str | None) -> tuple[str, ...]:
    if value is None:
        return DEFAULT_SOURCE_ORDER
    if isinstance(value, str):
        values = [item.strip() for item in value.split(",") if item.strip()]
    else:
        values = [str(item).strip() for item in value if str(item).strip()]
    if not values:
        raise ManifestError("model source order cannot be empty")
    result: list[str] = []
    for value_name in values:
        source = _SOURCE_ALIASES.get(value_name.lower())
        if source is None:
            raise ManifestError(
                f"unknown model source {value_name!r}; choose from {DEFAULT_SOURCE_ORDER}"
            )
        if source not in result:
            result.append(source)
    return tuple(result)


def validate_https_url(value: str | None) -> str | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise ManifestError("model mirror URL must be a string")
    parsed = urlparse(value)
    if parsed.scheme.lower() != "https" or not parsed.netloc:
        raise ManifestError(
            f"model mirror must be an HTTPS URL (got {value!r}); refusing insecure fallback"
        )
    return value.rstrip("/")


def parse_model_config(
    config: Mapping[str, Any] | None,
    profile: Mapping[str, Any] | None = None,
) -> ModelResolverSettings:
    """Read resolver keys without importing or changing the main config path.

    Profile values override the top-level ``model_resolver`` block.  The
    existing profile ``model`` field remains the model ID unless it names an
    explicit local directory.  A separate ``model_id`` can accompany such a
    path for custom manifests.
    """

    config = config or {}
    profile = profile or {}
    resolver = config.get("model_resolver")
    if not isinstance(resolver, Mapping):
        resolver = {
            key: config[key]
            for key in (
                "model",
                "model_id",
                "local_model_path",
                "local_model_dir",
                "model_path",
                "model_dir",
                "local_dir",
                "model_revision",
                "revision",
                "model_manifest",
                "manifest",
                "manifest_path",
                "cache_dir",
                "model_cache_dir",
                "cache_path",
                "model_cache_path",
                "mirror_url",
                "model_mirror",
                "model_mirror_url",
                "hf_endpoint",
                "huggingface_endpoint",
                "source_order",
                "model_source_order",
                "offline",
                "max_retries",
                "model_max_retries",
                "backoff_factor",
                "model_backoff_factor",
                "max_backoff",
                "model_max_backoff",
            )
            if key in config
        }

    model_value = _pick(
        profile,
        "model",
        "model_id",
        default=_pick(resolver, "model", "model_id"),
    )
    local_value = _pick(
        profile,
        "local_model_path",
        "model_path",
        "model_dir",
        "local_dir",
        default=_pick(resolver, "local_model_path", "model_dir", "local_dir"),
    )
    if local_value is None and _looks_like_path(model_value):
        local_value = model_value
        model_value = _pick(profile, "model_id", "huggingface_model", default=None)
    model_id = _pick(profile, "model_id", "huggingface_model", default=model_value)
    if _looks_like_path(model_id):
        local_value = local_value or model_id
        model_id = None

    source_order = normalize_source_order(
        _pick(
            profile,
            "model_source_order",
            "source_order",
            default=_pick(resolver, "source_order", "model_source_order"),
        )
    )
    offline_value = _pick(
        profile,
        "offline",
        default=_pick(resolver, "offline", default=config.get("offline", False)),
    )
    max_retries = _pick(
        profile,
        "model_max_retries",
        "max_retries",
        default=_pick(resolver, "max_retries", "model_max_retries", default=3),
    )
    backoff_factor = _pick(
        profile,
        "model_backoff_factor",
        "backoff_factor",
        default=_pick(resolver, "backoff_factor", "model_backoff_factor", default=1.0),
    )
    max_backoff = _pick(
        profile,
        "model_max_backoff",
        "max_backoff",
        default=_pick(resolver, "max_backoff", "model_max_backoff", default=30.0),
    )
    return ModelResolverSettings(
        model_id=str(model_id) if model_id is not None else None,
        local_path=_optional_path(local_value),
        revision=_pick(profile, "model_revision", "revision", default=_pick(resolver, "revision")),
        language=_pick(profile, "language", default=_pick(resolver, "language")),
        manifest=_pick(
            profile,
            "model_manifest",
            "manifest",
            "manifest_path",
            default=_pick(resolver, "model_manifest", "manifest", "manifest_path"),
        ),
        cache_dir=_optional_path(
            _pick(profile, "model_cache_dir", "cache_dir", "hf_cache_dir", default=_pick(resolver, "cache_dir", "model_cache_dir"))
        ),
        cache_path=_optional_path(
            _pick(profile, "model_cache_path", "cache_path", default=_pick(resolver, "cache_path", "model_cache_path"))
        ),
        local_model_dir=_optional_path(
            _pick(profile, "local_model_dir", default=_pick(resolver, "local_model_dir"))
        ),
        mirror_url=validate_https_url(
            _pick(
                profile,
                "model_mirror",
                "model_mirror_url",
                "model_mirror_base",
                "mirror_url",
                default=_pick(
                    resolver,
                    "mirror_url",
                    "model_mirror",
                    "model_mirror_url",
                    "model_mirror_base",
                ),
            )
        ),
        huggingface_endpoint=validate_https_url(
            _pick(
                profile,
                "hf_endpoint",
                "huggingface_endpoint",
                default=_pick(resolver, "hf_endpoint", "huggingface_endpoint"),
            )
        )
        or _HF_ENDPOINT,
        source_order=source_order,
        offline=bool(offline_value),
        max_retries=int(max_retries),
        backoff_factor=float(backoff_factor),
        max_backoff=float(max_backoff),
    )


def load_resolver_config(path: str | os.PathLike[str]) -> ModelResolverSettings:
    """Load and normalize a JSON config file without importing application code."""

    return parse_model_config(_read_json(path))


def _looks_like_path(value: Any) -> bool:
    if isinstance(value, Path):
        return True
    if not isinstance(value, (str, os.PathLike)):
        return False
    text = os.fspath(value)
    if not text:
        return False
    expanded = os.path.expandvars(os.path.expanduser(text))
    if os.path.exists(expanded):
        return True
    if os.path.isabs(text) or os.path.splitdrive(text)[0]:
        return True
    return text.startswith(("~", "./", "../", ".\\", "..\\"))


def _default_cache_dir() -> Path:
    hf_cache = os.environ.get("HF_HUB_CACHE")
    if hf_cache:
        return Path(os.path.expandvars(os.path.expanduser(hf_cache)))
    hf_home = os.environ.get("HF_HOME")
    if hf_home:
        return Path(os.path.expandvars(os.path.expanduser(hf_home))) / "hub"
    return Path.home() / ".cache" / "huggingface" / "hub"


def _cache_name(model_id: str) -> str:
    return "models--" + re.sub(r"[^A-Za-z0-9_.-]+", "--", model_id.replace("/", "--"))


def _dedupe_paths(paths: Iterable[Path]) -> tuple[Path, ...]:
    result: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        text = os.path.normcase(os.path.abspath(os.fspath(path)))
        if text not in seen:
            seen.add(text)
            result.append(path)
    return tuple(result)


# ---------------------------------------------------------------------------
# The resolver


class ModelManager:
    """Resolve exact model manifests through local and remote sources."""

    def __init__(
        self,
        manifests: ModelManifestCatalog | ModelManifest | Mapping[str, Any] | Sequence[Any] | None = None,
        *,
        manifest: ModelManifest | Mapping[str, Any] | str | os.PathLike[str] | None = None,
        manifest_path: str | os.PathLike[str] | None = None,
        local_model_dir: str | os.PathLike[str] | None = None,
        cache_dir: str | os.PathLike[str] | None = None,
        cache_path: str | os.PathLike[str] | None = None,
        mirror_url: str | None = None,
        huggingface_endpoint: str | None = None,
        source_order: Sequence[str] | str | None = None,
        offline: bool = False,
        downloader: Callable[..., Any] | Any | None = None,
        max_retries: int = 3,
        retries: int | None = None,
        backoff_factor: float = 1.0,
        backoff: float | None = None,
        max_backoff: float = 30.0,
        sleep: Callable[[float], Any] = time.sleep,
        download_hook: Callable[..., Any] | None = None,
        atomic_replace: Callable[[Path, Path], Any] | None = None,
        request_timeout: float = 60.0,
        log: Callable[[str], Any] | None = None,
    ) -> None:
        if manifest is not None and manifest_path is not None:
            raise ManifestError("pass only one of manifest and manifest_path")
        if retries is not None:
            max_retries = retries
        if backoff is not None:
            backoff_factor = backoff
        selected_manifest = manifest_path or manifest
        if isinstance(selected_manifest, (str, os.PathLike)):
            catalog = load_manifest_catalog(selected_manifest)
        elif selected_manifest is not None:
            catalog = ModelManifestCatalog.from_data(selected_manifest)
        elif manifests is not None:
            catalog = ModelManifestCatalog.from_data(manifests)
        else:
            catalog = default_manifests()
        if not isinstance(max_retries, int) or isinstance(max_retries, bool) or max_retries < 0:
            raise ManifestError("max_retries must be a non-negative integer")
        if backoff_factor < 0 or max_backoff < 0 or request_timeout <= 0:
            raise ManifestError("backoff and timeout values must be non-negative")
        self.manifests = catalog
        self.local_model_dir = _optional_path(local_model_dir)
        self.cache_dir = _optional_path(cache_dir) or _default_cache_dir()
        self.cache_path = _optional_path(cache_path)
        self.mirror_url = validate_https_url(mirror_url)
        self.huggingface_endpoint = validate_https_url(huggingface_endpoint) or _HF_ENDPOINT
        self.source_order = normalize_source_order(source_order)
        self.offline = bool(offline)
        self.downloader = downloader
        self.max_retries = max_retries
        self.backoff_factor = float(backoff_factor)
        self.max_backoff = float(max_backoff)
        self.sleep = sleep
        self.download_hook = download_hook
        self.atomic_replace = atomic_replace or os.replace
        self.request_timeout = float(request_timeout)
        self.log = log
        self.last_trace: tuple[ResolutionEvent, ...] = ()
        self._trace_lock = threading.Lock()

    @classmethod
    def from_config(
        cls,
        config: Mapping[str, Any],
        profile: Mapping[str, Any] | None = None,
        **overrides: Any,
    ) -> ModelManager:
        """Build a manager from the app's JSON-shaped configuration."""

        settings = parse_model_config(config, profile)
        kwargs: dict[str, Any] = {
            "local_model_dir": settings.local_model_dir,
            "cache_dir": settings.cache_dir,
            "cache_path": settings.cache_path,
            "mirror_url": settings.mirror_url,
            "huggingface_endpoint": settings.huggingface_endpoint,
            "source_order": settings.source_order,
            "offline": settings.offline,
            "max_retries": settings.max_retries,
            "backoff_factor": settings.backoff_factor,
            "max_backoff": settings.max_backoff,
        }
        if settings.manifest is not None:
            kwargs["manifest"] = settings.manifest
        kwargs.update(overrides)
        return cls(**kwargs)

    def _emit(self, message: str) -> None:
        if self.log:
            try:
                self.log(message)
            except Exception:  # noqa: BLE001,S110 - logging must not break resolution
                pass

    def _set_trace(self, trace: Sequence[ResolutionEvent]) -> None:
        with self._trace_lock:
            self.last_trace = tuple(trace)

    def _select_manifest(
        self,
        model_id: str | None,
        *,
        manifest: ModelManifest | ModelManifestCatalog | Mapping[str, Any] | str | os.PathLike[str] | None,
        revision: str | None,
        language: str | None,
        local_path: Path | None,
    ) -> ModelManifest:
        if isinstance(manifest, (str, os.PathLike)):
            manifest = load_manifest(manifest)
        if isinstance(manifest, ModelManifestCatalog):
            if model_id and not _looks_like_path(model_id):
                selected = manifest.get(model_id, revision=revision)
            elif revision:
                matches = [item for item in manifest if item.revision == revision]
                if len(matches) != 1:
                    raise ManifestError(
                        "a multi-model manifest catalog needs a model ID or unique revision"
                    )
                selected = matches[0]
            elif len(manifest) == 1:
                selected = manifest.manifests[0]
            else:
                raise ManifestError("a multi-model manifest catalog needs a model ID")
        elif isinstance(manifest, Mapping) and "models" in manifest:
            catalog = ModelManifestCatalog.from_data(manifest)
            if model_id and not _looks_like_path(model_id):
                selected = catalog.get(model_id, revision=revision)
            elif revision:
                matches = [item for item in catalog if item.revision == revision]
                if len(matches) != 1:
                    raise ManifestError(
                        "a multi-model manifest catalog needs a model ID or unique revision"
                    )
                selected = matches[0]
            elif len(catalog) == 1:
                selected = catalog.manifests[0]
            else:
                raise ManifestError("a multi-model manifest catalog needs a model ID")
        elif manifest is not None:
            selected = manifest if isinstance(manifest, ModelManifest) else ModelManifest.from_mapping(manifest)
            if model_id and not _looks_like_path(model_id) and selected.model_id != model_id:
                raise ManifestError(
                    f"requested model {model_id!r} does not match manifest {selected.model_id!r}"
                )
        elif model_id and not _looks_like_path(model_id):
            selected = self.manifests.get(model_id, revision=revision)
        elif local_path is not None and local_path.exists():
            selected = self._infer_manifest_from_path(local_path)
        elif language:
            selected = self.manifests.for_language(language)
        else:
            raise ManifestError(
                "a model ID, manifest, local model path, or language is required"
            )
        if revision is not None and revision != selected.revision:
            raise ManifestError(
                f"revision {revision!r} was requested, but the immutable manifest is pinned to "
                f"{selected.revision!r}; provide a custom manifest for another revision"
            )
        if language and not selected.supports_language(language):
            raise LanguageMismatchError(
                f"model {selected.model_id!r} does not support requested language {language!r}; "
                f"supported: {', '.join(selected.allowed_languages)}"
            )
        return selected

    def _infer_manifest_from_path(self, path: Path) -> ModelManifest:
        config_path = path / "config.json"
        try:
            with open(config_path, "r", encoding="utf-8") as handle:
                config = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            raise ManifestError(
                f"cannot identify local model at {path}; provide an explicit manifest "
                f"(config.json could not be read: {exc})"
            ) from exc
        model_type = config.get("model_type") if isinstance(config, Mapping) else None
        architectures = tuple(config.get("architectures") or ()) if isinstance(config, Mapping) else ()
        matches = [
            item
            for item in self.manifests
            if (model_type and item.model_type == model_type)
            or (architectures and set(architectures).intersection(item.architectures))
        ]
        if len(matches) != 1:
            raise ManifestError(
                f"local model at {path} is not uniquely identified by config.json; "
                "pass an explicit manifest instead of silently selecting a checkpoint"
            )
        return matches[0]

    def resolve(
        self,
        model_id: str | os.PathLike[str] | None = None,
        *,
        manifest: ModelManifest | ModelManifestCatalog | Mapping[str, Any] | str | os.PathLike[str] | None = None,
        revision: str | None = None,
        language: str | None = None,
        local_path: str | os.PathLike[str] | None = None,
        local_model_path: str | os.PathLike[str] | None = None,
        source: str | None = None,
        source_order: Sequence[str] | str | None = None,
        cache_path: str | os.PathLike[str] | None = None,
        mirror_url: str | None = None,
        huggingface_endpoint: str | None = None,
        offline: bool | None = None,
    ) -> ResolvedModel:
        """Resolve one manifest, never falling back to a different identity.

        ``revision`` is an assertion against the selected manifest.  A custom
        revision is supported by supplying a custom manifest; this prevents a
        profile typo from silently turning into an unpinned ``main`` download.
        """

        explicit_local = local_model_path if local_model_path is not None else local_path
        explicit_local_path = _optional_path(explicit_local)
        if model_id is not None and _looks_like_path(model_id):
            if explicit_local_path is None:
                explicit_local_path = _optional_path(model_id)
            model_id = None
        selected = self._select_manifest(
            str(model_id) if model_id is not None else None,
            manifest=manifest,
            revision=revision,
            language=language,
            local_path=explicit_local_path,
        )
        if source_order is not None:
            order = normalize_source_order(source_order)
        elif source:
            order = normalize_source_order((source,))
        else:
            order = self.source_order
        effective_offline = self.offline if offline is None else bool(offline)
        effective_mirror = self.mirror_url if mirror_url is None else validate_https_url(mirror_url)
        effective_hf_endpoint = (
            self.huggingface_endpoint
            if huggingface_endpoint is None
            else validate_https_url(huggingface_endpoint) or _HF_ENDPOINT
        )
        effective_cache_path = _optional_path(cache_path) or self.cache_path
        trace: list[ResolutionEvent] = [
            ResolutionEvent(
                "resolver",
                "order",
                ", ".join(order) + (" (offline)" if effective_offline else ""),
            )
        ]
        if explicit_local_path is not None and "local" not in order:
            self._set_trace(trace)
            raise ManifestError(
                "an explicit local model path requires 'local' in model source order; "
                "refusing to silently use a different source"
            )

        try:
            for source_name in order:
                if source_name == "local":
                    result = self._resolve_local(
                        selected,
                        explicit_local_path,
                        self.local_model_dir,
                        trace,
                        strict=explicit_local_path is not None,
                    )
                    if result is not None:
                        return self._finish(selected, result, "local", trace)
                    continue
                if source_name == "cache":
                    result = self._resolve_cache(
                        selected,
                        self.cache_dir,
                        effective_cache_path,
                        trace,
                    )
                    if result is not None:
                        return self._finish(selected, result, "cache", trace)
                    continue
                if effective_offline:
                    trace.append(
                        ResolutionEvent(
                            source_name,
                            "skipped",
                            "offline mode forbids network sources",
                        )
                    )
                    continue
                if source_name == "mirror":
                    if not effective_mirror:
                        trace.append(
                            ResolutionEvent(
                                "mirror", "skipped", "no HTTPS mirror configured"
                            )
                        )
                        continue
                    result = self._download_remote(
                        selected,
                        effective_mirror,
                        "mirror",
                        trace,
                    )
                    if result is not None:
                        return self._finish(selected, result, "mirror", trace)
                    continue
                if source_name == "huggingface":
                    result = self._download_remote(
                        selected,
                        effective_hf_endpoint,
                        "huggingface",
                        trace,
                    )
                    if result is not None:
                        return self._finish(selected, result, "huggingface", trace)
                    continue
                # normalize_source_order makes this unreachable, but keeping the
                # guard makes a future source addition fail closed.
                raise ManifestError(f"unsupported model source {source_name!r}")
            self._set_trace(trace)
            failure_details = "; ".join(
                f"{event.source}: {event.detail}"
                for event in trace
                if event.status in {"failed", "invalid"}
            )
            message = (
                f"could not resolve pinned model {selected.model_id!r} at revision "
                f"{selected.revision!r}; tried {', '.join(order)}"
            )
            if failure_details:
                message += f". Last source result: {failure_details}"
            if effective_offline:
                raise OfflineModelUnavailableError(
                    message + ". Offline mode only accepts a complete local snapshot.",
                    trace=trace,
                )
            raise ModelResolutionError(message + ". Check the configured paths and network/mirror settings.", trace=trace)
        except ModelManagerError as exc:
            self._set_trace(trace)
            if not getattr(exc, "trace", ()):
                exc.trace = tuple(trace)
                exc.failures = exc.trace
            raise

    def resolve_model(self, *args: Any, **kwargs: Any) -> ResolvedModel:
        """Named alias for :meth:`resolve`."""

        return self.resolve(*args, **kwargs)

    def resolve_profile(
        self,
        config: Mapping[str, Any],
        profile: Mapping[str, Any],
        **overrides: Any,
    ) -> ResolvedModel:
        """Resolve one profile using the normalized JSON configuration."""

        settings = parse_model_config(config, profile)
        kwargs: dict[str, Any] = {
            "revision": settings.revision,
            "language": settings.language,
            "local_path": settings.local_path,
            "cache_path": settings.cache_path,
            "source_order": settings.source_order,
            "offline": settings.offline,
            "mirror_url": settings.mirror_url,
            "huggingface_endpoint": settings.huggingface_endpoint,
        }
        if settings.manifest is not None:
            kwargs["manifest"] = settings.manifest
        kwargs.update(overrides)
        return self.resolve(settings.model_id, **kwargs)

    def resolve_local(
        self,
        path: str | os.PathLike[str],
        *,
        manifest: ModelManifest | Mapping[str, Any],
        language: str | None = None,
        revision: str | None = None,
    ) -> ResolvedModel:
        """Resolve an explicit local snapshot with a required manifest.

        This convenience method makes the trust boundary explicit: a local
        directory is not treated as an anonymous model merely because it
        happens to contain a Transformers-looking file.
        """

        return self.resolve(
            manifest=manifest,
            revision=revision,
            language=language,
            local_path=path,
            source_order=("local",),
        )

    def validate_cache(
        self,
        path: str | os.PathLike[str],
        *,
        manifest: ModelManifest | Mapping[str, Any] | None = None,
    ) -> SnapshotValidation:
        """Validate a cache root or direct snapshot without downloading."""

        if manifest is None:
            raise ManifestError("validate_cache requires an explicit manifest")
        selected = manifest if isinstance(manifest, ModelManifest) else ModelManifest.from_mapping(manifest)
        root = Path(path)
        cache_name = _cache_name(selected.model_id)
        candidates = _dedupe_paths(
            (
                root,
                root / cache_name / "snapshots" / selected.revision,
                root / "snapshots" / selected.revision,
                root / selected.model_id.replace("/", os.sep) / selected.revision,
            )
        )
        first_report: SnapshotValidation | None = None
        for candidate in candidates:
            if candidate.exists():
                report = validate_snapshot(candidate, selected, raise_on_error=False)
                if first_report is None:
                    first_report = report
                if report.valid:
                    return report
        return first_report or validate_snapshot(root, selected, raise_on_error=False)

    def _finish(
        self,
        manifest: ModelManifest,
        path: Path,
        source: str,
        trace: list[ResolutionEvent],
    ) -> ResolvedModel:
        trace.append(
            ResolutionEvent(
                source,
                "selected",
                f"validated revision {manifest.revision}",
                str(path),
            )
        )
        self._set_trace(trace)
        self._emit(
            f"model {manifest.model_id}@{manifest.revision} selected from {source}: {path}"
        )
        return ResolvedModel(manifest, path, source, tuple(trace))

    def _resolve_local(
        self,
        manifest: ModelManifest,
        explicit_path: Path | None,
        configured_dir: Path | None,
        trace: list[ResolutionEvent],
        *,
        strict: bool,
    ) -> Path | None:
        candidates: list[Path] = []
        if explicit_path is not None:
            candidates.append(explicit_path)
        if not strict and configured_dir is not None:
            candidates.extend(
                (
                    configured_dir,
                    configured_dir / manifest.model_id.replace("/", os.sep),
                    configured_dir / manifest.model_id.split("/")[-1],
                )
            )
        if not candidates:
            trace.append(ResolutionEvent("local", "skipped", "no local directory configured"))
            return None
        for candidate in _dedupe_paths(candidates):
            if not candidate.exists():
                trace.append(ResolutionEvent("local", "missing", f"not found: {candidate}", str(candidate)))
                continue
            try:
                validate_snapshot(candidate, manifest)
            except ModelManagerError as exc:
                trace.append(ResolutionEvent("local", "invalid", str(exc), str(candidate)))
                if strict:
                    raise
                continue
            return candidate
        if strict:
            raise ModelNotFoundError(
                f"explicit local model directory is unavailable: {explicit_path}; "
                "restore the complete pinned snapshot or correct the path"
            )
        return None

    def _resolve_cache(
        self,
        manifest: ModelManifest,
        cache_dir: Path,
        direct_cache_path: Path | None,
        trace: list[ResolutionEvent],
    ) -> Path | None:
        if direct_cache_path is not None:
            candidates = (direct_cache_path,)
        else:
            cache_name = _cache_name(manifest.model_id)
            candidates_list: list[Path] = [
                cache_dir / cache_name / "snapshots" / manifest.revision,
                cache_dir / "snapshots" / manifest.revision,
                cache_dir / manifest.model_id.replace("/", os.sep) / manifest.revision,
                cache_dir / manifest.model_id.split("/")[-1] / manifest.revision,
                cache_dir / manifest.revision,
            ]
            # A caller may point cache_dir at a model-specific HF cache folder
            # or directly at a snapshots directory.
            candidates_list.extend(
                (
                    cache_dir / cache_name / "snapshots" / manifest.revision,
                    cache_dir / cache_name / manifest.revision,
                    cache_dir,
                )
            )
            candidates = _dedupe_paths(candidates_list)
        found_candidate = False
        for candidate in candidates:
            if not candidate.exists():
                continue
            found_candidate = True
            try:
                validate_snapshot(candidate, manifest)
            except ModelManagerError as exc:
                trace.append(ResolutionEvent("cache", "invalid", str(exc), str(candidate)))
                continue
            return candidate
        if found_candidate:
            trace.append(ResolutionEvent("cache", "invalid", "no candidate passed completeness/integrity checks"))
        else:
            trace.append(ResolutionEvent("cache", "missing", f"no snapshot for revision {manifest.revision} under {cache_dir}"))
        return None

    def _snapshot_target(self, manifest: ModelManifest, cache_dir: Path) -> Path:
        cache_name = _cache_name(manifest.model_id)
        if cache_dir.name == "snapshots":
            return cache_dir / manifest.revision
        if cache_dir.name.startswith("models--"):
            return cache_dir / "snapshots" / manifest.revision
        return cache_dir / cache_name / "snapshots" / manifest.revision

    def _download_remote(
        self,
        manifest: ModelManifest,
        base_url: str,
        source_name: str,
        trace: list[ResolutionEvent],
    ) -> Path | None:
        target = self._snapshot_target(manifest, self.cache_dir)
        if target.exists():
            try:
                validate_snapshot(target, manifest)
            except ModelManagerError as exc:
                trace.append(ResolutionEvent(source_name, "invalid", str(exc), str(target)))
            else:
                trace.append(ResolutionEvent(source_name, "cached", f"using validated cache at {target}", str(target)))
                return target
        try:
            path = self._download_snapshot(manifest, base_url, source_name, target)
        except (ModelManagerError, OSError) as exc:
            trace.append(ResolutionEvent(source_name, "failed", str(exc)))
            return None
        trace.append(ResolutionEvent(source_name, "downloaded", f"published snapshot at {path}", str(path)))
        return path

    def _url_for_file(self, manifest: ModelManifest, base_url: str, filename: str) -> str:
        model_path = quote(manifest.model_id, safe="/")
        revision = quote(manifest.revision, safe="")
        file_path = quote(filename, safe="/")
        if any(token in base_url for token in ("{model_id}", "{revision}", "{filename}")):
            return base_url.format(
                model_id=model_path,
                revision=revision,
                filename=file_path,
            )
        base = base_url.rstrip("/")
        if "/resolve/" in base:
            return f"{base}/{revision}/{file_path}"
        return f"{base}/{model_path}/resolve/{revision}/{file_path}"

    def _download_snapshot(
        self,
        manifest: ModelManifest,
        base_url: str,
        source_name: str,
        target: Path,
    ) -> Path:
        target.parent.mkdir(parents=True, exist_ok=True)
        stage = Path(tempfile.mkdtemp(prefix=f".{target.name}.", dir=str(target.parent)))
        try:
            for entry in manifest.required_files:
                url = self._url_for_file(manifest, base_url, entry.name)
                destination = stage / Path(entry.name)
                destination.parent.mkdir(parents=True, exist_ok=True)
                self._download_file(manifest, url, destination, entry.name, source_name)
            validate_snapshot(stage, manifest)
            marker = stage / ".whisper-dictate-manifest.json"
            marker.write_text(
                json.dumps(
                    {
                        "model_id": manifest.model_id,
                        "revision": manifest.revision,
                        "fingerprint": manifest.fingerprint(),
                    },
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            self._commit_stage(stage, target)
            return target
        finally:
            if stage.exists():
                shutil.rmtree(stage, ignore_errors=True)

    def _commit_stage(self, stage: Path, target: Path) -> None:
        backup: Path | None = None
        if target.exists():
            backup = target.with_name(f".{target.name}.corrupt-{uuid.uuid4().hex}")
            self.atomic_replace(target, backup)
        try:
            self.atomic_replace(stage, target)
        except Exception:
            if backup is not None and not target.exists():
                try:
                    self.atomic_replace(backup, target)
                except OSError:
                    pass
            raise
        if backup is not None:
            if backup.is_dir():
                shutil.rmtree(backup, ignore_errors=True)
            else:
                try:
                    backup.unlink()
                except OSError:
                    pass

    def _download_file(
        self,
        manifest: ModelManifest,
        url: str,
        destination: Path,
        filename: str,
        source_name: str,
    ) -> None:
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                atomic_download(
                    url,
                    destination,
                    downloader=self.downloader,
                    timeout=self.request_timeout,
                    download_hook=self._download_event_hook,
                    atomic_replace=self.atomic_replace,
                    attempt=attempt,
                )
                verify_model_file(destination, next(
                    entry for entry in manifest.required_files if entry.name == filename
                ))
                return
            except Exception as exc:  # noqa: BLE001 - retry all downloader failures
                last_error = exc
                try:
                    destination.unlink()
                except OSError:
                    pass
                if attempt >= self.max_retries:
                    break
                delay = min(self.max_backoff, self.backoff_factor * (2**attempt))
                self._emit(
                    f"model {source_name} download failed for {manifest.model_id} "
                    f"({exc}); retrying in {delay:.1f}s"
                )
                if delay:
                    self.sleep(delay)
        if isinstance(last_error, ModelIntegrityError):
            raise ModelIntegrityError(
                f"downloaded {manifest.model_id} file {destination.name} from {source_name} "
                f"({url}) failed integrity checks after {self.max_retries + 1} attempt(s): {last_error}"
            ) from last_error
        raise ModelDownloadError(
            f"could not download {manifest.model_id}@{manifest.revision} from {source_name} "
            f"({url}) after {self.max_retries + 1} attempt(s): {last_error}"
        ) from last_error

    def _download_event_hook(self, event: str, url: str, path: Path, attempt: int, *args: Any) -> None:
        if not self.download_hook:
            return
        try:
            self.download_hook(event, url, path, attempt, *args)
        except Exception:  # noqa: BLE001,S110 - observer must not break resolution
            pass

    def validate(self, path: str | os.PathLike[str], manifest: ModelManifest | Mapping[str, Any]) -> SnapshotValidation:
        """Public completeness/integrity check for a resolved snapshot."""

        return validate_snapshot(path, manifest, raise_on_error=False)


# ---------------------------------------------------------------------------
# Convenience functions


def resolve_model(
    model_id: str | os.PathLike[str] | None = None,
    *,
    manager: ModelManager | None = None,
    manager_kwargs: Mapping[str, Any] | None = None,
    **kwargs: Any,
) -> ResolvedModel:
    """Resolve with a supplied manager or a short-lived default manager.

    Constructor settings such as ``cache_dir`` and ``downloader`` may be
    supplied in ``manager_kwargs`` (or directly as a small convenience when
    using this function).
    """

    if manager is None:
        constructor_names = {
            "manifests",
            "manifest",
            "manifest_path",
            "local_model_dir",
            "cache_dir",
            "cache_path",
            "mirror_url",
            "huggingface_endpoint",
            "source_order",
            "offline",
            "downloader",
            "max_retries",
            "retries",
            "backoff_factor",
            "backoff",
            "max_backoff",
            "sleep",
            "download_hook",
            "atomic_replace",
            "request_timeout",
            "log",
        }
        options = dict(manager_kwargs or {})
        for name in tuple(kwargs):
            if name in constructor_names:
                options[name] = kwargs.pop(name)
        manager = ModelManager(**options)
    return manager.resolve(model_id, **kwargs)


__all__ = [
    "DEFAULT_MANIFESTS",
    "DEFAULT_MANIFEST_DATA",
    "DEFAULT_SOURCE_ORDER",
    "MANIFEST_SCHEMA_VERSION",
    "IncompleteModelError",
    "LanguageMismatchError",
    "ManifestError",
    "ManifestValidationError",
    "ModelCorruptError",
    "ModelDownloadError",
    "ModelFile",
    "ModelIntegrityError",
    "ModelManager",
    "ModelManagerError",
    "ModelManifest",
    "ModelManifestCatalog",
    "ModelNotFoundError",
    "ModelResolutionError",
    "ModelResolverSettings",
    "OfflineModelUnavailableError",
    "PartialModelError",
    "ResolutionEvent",
    "ResolvedModel",
    "SnapshotValidation",
    "atomic_download",
    "default_manifest_data",
    "default_manifests",
    "load_manifest",
    "load_manifest_catalog",
    "load_resolver_config",
    "normalize_source_order",
    "parse_model_config",
    "resolve_model",
    "validate_https_url",
    "validate_snapshot",
    "verify_model_file",
]
