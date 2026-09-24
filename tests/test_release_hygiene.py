import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

from scripts.release_guard import (
    find_forbidden_paths,
    forbidden_reason,
    inspect_archive,
    inspect_package,
)
from scripts.release_manifest import (
    MANIFEST_SCHEMA,
    build_manifest,
    write_release_files,
)

ROOT = Path(__file__).resolve().parents[1]


class ArchiveDenylistTests(unittest.TestCase):
    def test_private_runtime_and_generated_names_are_denied(self):
        denied = [
            "WhisperDictate/dictate.log",
            "WhisperDictate/logs/worker.log",
            "WhisperDictate/worker.log.1",
            "WhisperDictate/transcription-history.jsonl",
            "WhisperDictate/history.jsonl.1",
            "WhisperDictate/config.local.json",
            "WhisperDictate/corrections-en.local.txt",
            "WhisperDictate/.env",
            "WhisperDictate/.env.production",
            "WhisperDictate/app.env",
            "WhisperDictate/lost_audio/clip.wav",
            "WhisperDictate/.venv/lib/python3.12/site-packages/thing.py",
            "WhisperDictate/venv/lib/python3.12/site-packages/thing.py",
            "WhisperDictate/__pycache__/thing.cpython-312.pyc",
            "WhisperDictate/Thumbs.db",
            "WhisperDictate/notes.tmp",
            "WhisperDictate/signing-key.pem",
            "WhisperDictate/model.safetensors",
            "WhisperDictate/model.gguf",
            "WhisperDictate/model.ckpt",
            "WhisperDictate/model.onnx",
            "WhisperDictate/model.pt",
            "WhisperDictate/model.pth",
            "WhisperDictate/model.bin",
            "WhisperDictate/models--nvidia--nemotron/snapshots/revision/config.json",
            "WhisperDictate/huggingface/hub/model/config.json",
        ]
        violations = find_forbidden_paths(denied)
        self.assertEqual(len(violations), len(denied))
        self.assertTrue(all(reason for _, reason in violations))

    def test_normal_release_names_are_allowed(self):
        allowed = [
            "WhisperDictate/WhisperDictate.exe",
            "WhisperDictate/_internal/README.md",
            "WhisperDictate/_internal/assets/sounds/message-chime-done.wav",
            "WhisperDictate/_internal/certifi/cacert.pem",
            "WhisperDictate/_internal/transformers/models/bert/configuration_bert.py",
            "WhisperDictate/config.json",
            "WhisperDictate/LICENSE",
        ]
        self.assertEqual(find_forbidden_paths(allowed), [])

    def test_path_traversal_and_windows_absolute_paths_are_denied(self):
        self.assertIn("path traversal", forbidden_reason("WhisperDictate/../secret.txt"))
        self.assertIn("absolute archive path", forbidden_reason("C:/Users/test/.env"))

    def test_zip_guard_reports_members_without_extracting_them(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive_path = Path(tmp) / "WhisperDictate-test.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("WhisperDictate/WhisperDictate.exe", b"binary")
                archive.writestr("WhisperDictate/dictate.log", b"private log")
            violations = inspect_archive(archive_path)
            self.assertEqual(
                violations,
                [("WhisperDictate/dictate.log", "forbidden filename: dictate.log")],
            )

    def test_package_directory_guard_checks_relative_member_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            package = Path(tmp) / "WhisperDictate"
            (package / ".venv" / "lib").mkdir(parents=True)
            (package / ".venv" / "lib" / "private.py").write_text("private", encoding="utf-8")
            (package / "config.local.json").write_text("{}", encoding="utf-8")
            (package / "README.md").write_text("allowed", encoding="utf-8")
            violations = inspect_package(package)
            self.assertEqual(
                [name for name, _ in violations],
                [".venv", ".venv/lib", ".venv/lib/private.py", "config.local.json"],
            )
            forbidden_root = Path(tmp) / "lost_audio"
            forbidden_root.mkdir()
            self.assertEqual(inspect_package(forbidden_root), [("lost_audio", "forbidden path component: lost_audio")])

    def test_guard_cli_fails_for_a_private_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive_path = Path(tmp) / "unsafe.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr(".env", b"TOKEN=do-not-ship")
            result = subprocess.run(
                [sys.executable, str(ROOT / "scripts/release_guard.py"), str(archive_path)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("environment file", result.stderr)


class ChecksumManifestTests(unittest.TestCase):
    def test_manifest_has_stable_sorted_asset_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            windows = root / "WhisperDictate-v9.9.9-windows-x64.zip"
            macos = root / "WhisperDictate-v9.9.9-macos-arm64.zip"
            windows.write_bytes(b"windows payload")
            macos.write_bytes(b"macos payload")

            manifest = build_manifest(
                [macos, windows],
                release="v9.9.9",
                download_base_url="https://downloads.example/releases/v9.9.9",
            )

            self.assertEqual(manifest["schema"], MANIFEST_SCHEMA)
            self.assertEqual(manifest["release"], "v9.9.9")
            self.assertEqual(
                [entry["name"] for entry in manifest["assets"]],
                [macos.name, windows.name],
            )
            windows_entry = manifest["assets"][1]
            self.assertEqual(windows_entry["sha256"], hashlib.sha256(b"windows payload").hexdigest())
            self.assertEqual(windows_entry["size_bytes"], len(b"windows payload"))
            self.assertEqual(windows_entry["platform"], "windows")
            self.assertEqual(windows_entry["architecture"], "x64")
            self.assertEqual(
                windows_entry["url"],
                "https://downloads.example/releases/v9.9.9/WhisperDictate-v9.9.9-windows-x64.zip",
            )

    def test_manifest_rejects_insecure_or_credentialed_download_base(self):
        with tempfile.TemporaryDirectory() as tmp:
            asset = Path(tmp) / "WhisperDictate-v1.0.0-windows-x64.zip"
            asset.write_bytes(b"payload")
            for base in (
                "http://downloads.example/release",
                "https://user:password@downloads.example/release",
            ):
                with self.subTest(base=base):
                    with self.assertRaises(ValueError):
                        build_manifest([asset], download_base_url=base)

    def test_manifest_and_sha256sums_are_written_as_machine_readable_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            asset = root / "WhisperDictate-v1.0.0-macos-arm64.zip"
            asset.write_bytes(b"signed archive")
            manifest_path = root / "release-manifest.json"
            checksums_path = root / "SHA256SUMS"
            digest = hashlib.sha256(b"signed archive").hexdigest()

            write_release_files(
                [asset],
                manifest_path=manifest_path,
                checksums_path=checksums_path,
                release="v1.0.0",
            )

            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["assets"][0]["sha256"], digest)
            self.assertEqual(checksums_path.read_text(encoding="utf-8"), f"{digest}  {asset.name}\n")


class WorkflowSanityTests(unittest.TestCase):
    def test_release_workflow_uses_declared_dependencies_and_new_gates(self):
        workflow = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
        self.assertIn("requirements-release.txt", workflow)
        self.assertIn("requirements.txt", workflow)
        self.assertIn("python -m unittest discover", workflow)
        self.assertIn("scripts/release_guard.py", workflow)
        self.assertIn("scripts/release_manifest.py", workflow)
        self.assertNotIn(
            "pip install faster-whisper sounddevice",
            workflow,
            "release jobs must not maintain a hand-copied package list",
        )
        self.assertEqual(workflow.count("contents: write"), 1)
        self.assertIn("draft: true", workflow)
        self.assertIn("NOTES_release-hygiene.md", workflow)

    def test_release_dependency_file_reuses_runtime_requirements(self):
        requirements = (ROOT / "requirements-release.txt").read_text(encoding="utf-8")
        self.assertIn("-r requirements.txt", requirements)
        self.assertIn("pyinstaller", requirements)
        self.assertIn("rapidfuzz", requirements)

    def test_gitignore_covers_private_release_inputs(self):
        ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
        for pattern in ("*.log", "*.jsonl", "*.local.*", ".env*", "lost_audio/", ".venv/"):
            self.assertIn(pattern, ignore)


if __name__ == "__main__":
    unittest.main()
