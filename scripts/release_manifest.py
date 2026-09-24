#!/usr/bin/env python3
"""Create deterministic SHA-256 release metadata.

The manifest is deliberately a small, dependency-free JSON document intended
for a download page (including a Vercel-hosted page):

    {
      "schema": "whisper-dictate.release-manifest.v1",
      "checksum": "sha256",
      "release": "v1.2.3",
      "assets": [
        {
          "name": "WhisperDictate-v1.2.3-macos-arm64.zip",
          "url": "https://.../WhisperDictate-v1.2.3-macos-arm64.zip",
          "sha256": "...",
          "size_bytes": 123,
          "platform": "macos",
          "architecture": "arm64"
        }
      ]
    }

The script also writes a conventional ``SHA256SUMS`` file.  It never includes
its own output in the input set, and the JSON is sorted and has no timestamp,
so identical signed assets produce identical metadata.

Examples
--------
    python scripts/release_manifest.py dist/*.zip \\
        --release v1.2.3 \\
        --output release-manifest.json \\
        --checksums SHA256SUMS

Run ``--help`` for the available options.  The command exits non-zero for a
missing/non-file input, duplicate asset name, or an output collision.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

MANIFEST_SCHEMA = "whisper-dictate.release-manifest.v1"
DEFAULT_MANIFEST = "release-manifest.json"
DEFAULT_CHECKSUMS = "SHA256SUMS"
_HASH_CHUNK_SIZE = 1024 * 1024


def sha256_file(path: str | Path, chunk_size: int = _HASH_CHUNK_SIZE) -> str:
    """Return the lowercase SHA-256 digest of a regular file."""

    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    file_path = Path(path)
    if not file_path.is_file():
        raise ValueError(f"asset is not a regular file: {file_path}")
    digest = hashlib.sha256()
    with file_path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


# Public alias for callers that use the conventional ``sha256`` spelling.
file_sha256 = sha256_file


def infer_platform(name: str) -> str | None:
    """Infer a stable platform label from a release asset filename."""

    lowered = name.casefold()
    if "windows" in lowered or re.search(r"(?:^|[-_.])win(?:dows)?(?:[-_.]|$)", lowered):
        return "windows"
    if "macos" in lowered or "darwin" in lowered:
        return "macos"
    return None


def infer_architecture(name: str) -> str | None:
    """Infer an architecture label from a release asset filename."""

    lowered = name.casefold()
    for architecture in ("arm64", "aarch64", "x64", "amd64", "x86_64", "universal"):
        if re.search(rf"(?:^|[-_.]){re.escape(architecture)}(?:[-_.]|$)", lowered):
            return "arm64" if architecture == "aarch64" else "x86_64" if architecture == "amd64" else architecture
    return None


def _asset_entry(path: Path, download_base_url: str | None) -> dict[str, Any]:
    name = path.name
    entry: dict[str, object] = {
        "name": name,
        "sha256": sha256_file(path),
        "size_bytes": path.stat().st_size,
        "platform": infer_platform(name),
        "architecture": infer_architecture(name),
    }
    if download_base_url:
        base = download_base_url.rstrip("/")
        entry["url"] = f"{base}/{quote(name, safe='')}"
    return entry


def build_manifest(
    assets: Sequence[str | Path],
    *,
    release: str | None = None,
    download_base_url: str | None = None,
) -> dict[str, Any]:
    """Build a sorted JSON-serializable manifest for *assets*.

    Asset names must be unique within one manifest.  Missing labels are kept as
    ``null`` rather than guessed from a machine-specific path, which makes the
    result safe for a generic download page.
    """

    if not assets:
        raise ValueError("at least one release asset is required")
    if download_base_url:
        parsed_base = urlparse(download_base_url)
        if (
            parsed_base.scheme.lower() != "https"
            or not parsed_base.netloc
            or parsed_base.username
            or parsed_base.password
        ):
            raise ValueError(
                "download_base_url must be an HTTPS URL without embedded credentials"
            )

    paths = [Path(asset) for asset in assets]
    names = [path.name for path in paths]
    folded_names = [name.casefold() for name in names]
    duplicates = sorted({name for name in folded_names if folded_names.count(name) > 1})
    if duplicates:
        raise ValueError("duplicate asset name(s): " + ", ".join(duplicates))

    entries = [_asset_entry(path, download_base_url) for path in paths]
    entries.sort(key=lambda entry: (str(entry["name"]).casefold(), str(entry["name"])))
    manifest: dict[str, object] = {
        "schema": MANIFEST_SCHEMA,
        "checksum": "sha256",
        "release": release,
        "assets": entries,
    }
    return manifest


def _serialized_json(value: object) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def checksum_lines(assets: Sequence[str | Path]) -> list[str]:
    """Return sorted conventional ``sha256  filename`` lines."""

    paths = [Path(asset) for asset in assets]
    lines = [f"{sha256_file(path)}  {path.name}" for path in paths]
    return sorted(lines, key=lambda line: (line.split("  ", 1)[1].casefold(), line.split("  ", 1)[1]))


def write_release_files(
    assets: Sequence[str | Path],
    *,
    manifest_path: str | Path = DEFAULT_MANIFEST,
    checksums_path: str | Path | None = DEFAULT_CHECKSUMS,
    release: str | None = None,
    download_base_url: str | None = None,
) -> dict[str, Any]:
    """Build and write the manifest and optional ``SHA256SUMS`` sidecar."""

    paths = [Path(asset) for asset in assets]
    manifest_file = Path(manifest_path)
    checksum_file = Path(checksums_path) if checksums_path is not None else None
    if checksum_file is not None and manifest_file.resolve() == checksum_file.resolve():
        raise ValueError("manifest and checksum outputs must be different files")
    output_paths = {manifest_file.resolve(), checksum_file.resolve() if checksum_file else None}
    for path in paths:
        if path.resolve() in output_paths:
            raise ValueError(f"asset cannot also be an output: {path}")

    manifest = build_manifest(paths, release=release, download_base_url=download_base_url)
    manifest_file.parent.mkdir(parents=True, exist_ok=True)
    manifest_file.write_text(_serialized_json(manifest), encoding="utf-8", newline="\n")

    if checksum_file is not None:
        checksum_file.parent.mkdir(parents=True, exist_ok=True)
        checksum_file.write_text("\n".join(checksum_lines(paths)) + "\n", encoding="utf-8", newline="\n")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("assets", nargs="+", type=Path, help="release assets to hash")
    parser.add_argument("--output", type=Path, default=Path(DEFAULT_MANIFEST), help="manifest JSON path")
    parser.add_argument(
        "--checksums",
        default=DEFAULT_CHECKSUMS,
        help="SHA256SUMS output path (use an empty string to omit it)",
    )
    parser.add_argument("--release", help="release tag recorded in the manifest")
    parser.add_argument(
        "--download-base-url",
        help="base URL for each asset's download URL (for example a GitHub release URL)",
    )
    args = parser.parse_args(argv)

    checksums: Path | None = Path(args.checksums) if args.checksums else None
    try:
        manifest = write_release_files(
            args.assets,
            manifest_path=args.output,
            checksums_path=checksums,
            release=args.release,
            download_base_url=args.download_base_url,
        )
    except (OSError, ValueError) as exc:
        print(f"Release manifest failed: {exc}", file=sys.stderr)
        return 1

    print(
        f"Wrote {args.output} and {args.checksums if checksums is not None else 'no checksum sidecar'} "
        f"for {len(manifest['assets'])} asset(s)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
