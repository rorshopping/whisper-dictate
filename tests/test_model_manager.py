import hashlib
import tempfile
import unittest
from pathlib import Path

from model_manager import (
    IncompleteModelError,
    LanguageMismatchError,
    ManifestError,
    ModelFile,
    ModelIntegrityError,
    ModelManager,
    ModelManifest,
    ModelNotFoundError,
    OfflineModelUnavailableError,
    atomic_download,
    default_manifests,
    parse_model_config,
    resolve_model,
    validate_snapshot,
)


class ModelManagerTests(unittest.TestCase):
    def make_manifest(self, revision="test-revision"):
        contents = {
            "config.json": b'{"model_type": "fixture"}',
            "tokenizer.json": b"tokenizer",
        }
        return contents, ModelManifest.from_mapping(
            {
                "id": "fixture/nemotron",
                "revision": revision,
                "language": "en",
                "required_files": [
                    {
                        "name": name,
                        "size": len(data),
                        "sha256": hashlib.sha256(data).hexdigest(),
                    }
                    for name, data in contents.items()
                ],
            }
        )

    def write_snapshot(self, path, contents):
        path.mkdir(parents=True, exist_ok=True)
        for name, data in contents.items():
            (path / name).write_bytes(data)
        return path

    def test_defaults_are_pinned_and_optional_formats_are_not_required(self):
        catalog = default_manifests()
        self.assertEqual(len(catalog), 2)
        for manifest in catalog:
            self.assertRegex(manifest.revision, r"^[0-9a-f]{40}$")
            required = {entry.name for entry in manifest.required_files}
            self.assertIn("model.safetensors", required)
            self.assertNotIn("nemotron-speech-streaming-en-0.6b.nemo", required)
            self.assertNotIn("nemotron-3.5-asr-streaming-0.6b.nemo", required)
            self.assertNotIn("nemotron-speech-streaming-en-0.6b.q8_0.gguf", required)
            for entry in manifest.required_files:
                self.assertRegex(entry.sha256, r"^[0-9a-f]{64}$")

    def test_manifest_accepts_optional_flags_in_a_unified_files_list(self):
        manifest = ModelManifest.from_mapping(
            {
                "repo": "fixture/nemotron",
                "revision": "test-revision",
                "files": [
                    {
                        "filename": "config.json",
                        "size_bytes": 1,
                        "hash": "0" * 64,
                    },
                    {
                        "name": "model.gguf",
                        "size": 1,
                        "sha256": "1" * 64,
                        "required": False,
                    },
                ],
            }
        )
        self.assertEqual(manifest.model_id, "fixture/nemotron")
        self.assertEqual(manifest.required_files[0].name, "config.json")
        self.assertEqual(manifest.optional_files[0].name, "model.gguf")

    def test_insecure_mirror_is_rejected(self):
        with self.assertRaises(ManifestError):
            ModelManager(mirror_url="http://mirror.example")

    def test_manifest_rejects_floating_revision(self):
        with self.assertRaises(ManifestError):
            ModelManifest(
                model_id="fixture/model",
                revision="main",
                required_files=(ModelFile("config.json", 1, "0" * 64),),
            )

    def test_snapshot_validation_reports_missing_and_corrupt_files(self):
        contents, manifest = self.make_manifest()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaises(IncompleteModelError) as missing:
                validate_snapshot(root, manifest)
            self.assertIn("config.json", str(missing.exception))
            self.write_snapshot(root, {"config.json": contents["config.json"]})
            (root / "tokenizer.json").write_bytes(b"wrong-size")
            with self.assertRaises(ModelIntegrityError):
                validate_snapshot(root, manifest)

    def test_explicit_local_path_is_validated_and_trace_visible(self):
        contents, manifest = self.make_manifest()
        with tempfile.TemporaryDirectory() as tmp:
            root = self.write_snapshot(Path(tmp) / "model", contents)
            calls = []
            manager = ModelManager(
                manifest=manifest,
                source_order=["local", "cache", "huggingface"],
                downloader=lambda *args: calls.append(args),
                offline=False,
            )
            result = manager.resolve(
                "fixture/nemotron", local_path=root, language="en"
            )
            self.assertEqual(result.source, "local")
            self.assertEqual(result.path, root)
            self.assertEqual(result.source_order, ("local",))
            self.assertEqual(result.revision, manifest.revision)
            self.assertEqual(calls, [])
            self.assertIn("selected", [event.status for event in result.trace])
            self.assertEqual(manager.last_trace, result.trace)

    def test_explicit_local_path_does_not_fall_back_to_another_local_root(self):
        contents, manifest = self.make_manifest()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            configured = self.write_snapshot(root / "other", contents)
            missing = root / "requested"
            manager = ModelManager(
                manifest=manifest,
                local_model_dir=configured,
                source_order=["local"],
                offline=True,
            )
            with self.assertRaises(ModelNotFoundError):
                manager.resolve("fixture/nemotron", local_path=missing)

    def test_direct_complete_cache_path_is_supported(self):
        contents, manifest = self.make_manifest()
        with tempfile.TemporaryDirectory() as tmp:
            root = self.write_snapshot(Path(tmp) / "snapshot", contents)
            manager = ModelManager(
                manifest=manifest,
                cache_path=root,
                source_order=["cache"],
                offline=True,
            )
            result = manager.resolve("fixture/nemotron")
            self.assertEqual(result.source, "cache")
            self.assertEqual(result.path, root)
            self.assertTrue(manager.validate_cache(root, manifest=manifest).valid)
            standard_root = Path(tmp) / "standard"
            standard = standard_root / "models--fixture--nemotron" / "snapshots" / manifest.revision
            self.write_snapshot(standard, contents)
            self.assertTrue(manager.validate_cache(standard_root, manifest=manifest).valid)

    def test_fake_downloader_uses_mirror_then_publishes_atomically(self):
        contents, manifest = self.make_manifest()
        calls = []
        sleeps = []

        def download(url, destination):
            calls.append(url)
            name = url.rsplit("/", 1)[-1]
            Path(destination).write_bytes(contents[name])

        with tempfile.TemporaryDirectory() as tmp:
            manager = ModelManager(
                manifest=manifest,
                cache_dir=Path(tmp) / "cache",
                mirror_url="https://mirror.example/models",
                source_order=["local", "cache", "mirror", "huggingface"],
                downloader=download,
                sleep=sleeps.append,
                max_retries=2,
                backoff_factor=0.25,
            )
            result = manager.resolve("fixture/nemotron")
            self.assertEqual(result.source, "mirror")
            self.assertEqual(len(calls), 2)
            self.assertTrue(all(url.startswith("https://mirror.example/") for url in calls))
            self.assertEqual(len(list(result.path.iterdir())), 3)  # two files + marker
            self.assertEqual(sleeps, [])

            # A second resolve uses the complete cache and never calls the
            # network, even though remote sources remain in the order.
            result_again = manager.resolve("fixture/nemotron")
            self.assertEqual(result_again.source, "cache")
            self.assertEqual(len(calls), 2)

    def test_huggingface_fallback_uses_the_manifest_revision(self):
        contents, manifest = self.make_manifest()
        calls = []

        def download(url, destination):
            calls.append(url)
            Path(destination).write_bytes(contents[url.rsplit("/", 1)[-1]])

        with tempfile.TemporaryDirectory() as tmp:
            manager = ModelManager(
                manifest=manifest,
                cache_dir=Path(tmp),
                source_order=["huggingface"],
                downloader=download,
                sleep=lambda _: None,
            )
            result = manager.resolve("fixture/nemotron")
            self.assertEqual(result.source, "huggingface")
            self.assertTrue(
                all(url.startswith("https://huggingface.co/fixture/nemotron/test-revision/")
                    for url in calls)
            )

    def test_module_resolve_helper_accepts_manager_options(self):
        contents, manifest = self.make_manifest()

        def download(url, destination):
            Path(destination).write_bytes(contents[url.rsplit("/", 1)[-1]])

        with tempfile.TemporaryDirectory() as tmp:
            result = resolve_model(
                "fixture/nemotron",
                manifest=manifest,
                cache_dir=Path(tmp),
                source_order=["huggingface"],
                downloader=download,
                sleep=lambda _: None,
            )
            self.assertEqual(result.source, "huggingface")

    def test_retry_backoff_is_injectable(self):
        contents, manifest = self.make_manifest()
        attempts = []
        sleeps = []

        def download(url, destination):
            attempts.append(url)
            if len(attempts) < 3:
                raise OSError("temporary failure")
            Path(destination).write_bytes(contents[url.rsplit("/", 1)[-1]])

        with tempfile.TemporaryDirectory() as tmp:
            manager = ModelManager(
                manifest=manifest,
                cache_dir=Path(tmp),
                mirror_url="https://mirror.example",
                source_order=["mirror"],
                downloader=download,
                sleep=sleeps.append,
                max_retries=2,
                backoff_factor=0.5,
            )
            result = manager.resolve("fixture/nemotron")
            self.assertEqual(result.source, "mirror")
            self.assertEqual(len(attempts), 4)
            self.assertEqual(sleeps, [0.5, 1.0])

    def test_offline_never_invokes_network(self):
        _, manifest = self.make_manifest()
        calls = []
        with tempfile.TemporaryDirectory() as tmp:
            manager = ModelManager(
                manifest=manifest,
                cache_dir=Path(tmp),
                mirror_url="https://mirror.example",
                source_order=["mirror", "huggingface"],
                offline=True,
                downloader=lambda *args: calls.append(args),
            )
            with self.assertRaises(OfflineModelUnavailableError) as error:
                manager.resolve("fixture/nemotron")
            self.assertEqual(calls, [])
            self.assertIn("offline", str(error.exception).lower())
            self.assertEqual([event.status for event in error.exception.trace], ["order", "skipped", "skipped"])

    def test_config_parser_supports_profile_local_path_and_aliases(self):
        config = {
            "offline": True,
            "model_resolver": {
                "source_order": ["cache", "mirror", "huggingface"],
                "mirror_url": "https://mirror.example",
            },
        }
        profile = {
            "model": "./models/english",
            "model_id": "fixture/nemotron",
            "model_revision": "test-revision",
            "language": "en",
        }
        settings = parse_model_config(config, profile)
        self.assertEqual(settings.model_id, "fixture/nemotron")
        self.assertEqual(settings.local_path, Path("models/english"))
        self.assertEqual(settings.revision, "test-revision")
        self.assertEqual(settings.source_order, ("cache", "mirror", "huggingface"))
        self.assertTrue(settings.offline)
        self.assertEqual(settings.max_retries, 3)
        self.assertEqual(settings.mirror_url, "https://mirror.example")
        self.assertEqual(settings.huggingface_endpoint, "https://huggingface.co")
        flat = parse_model_config({"cache_dir": "C:/cache", "offline": True})
        self.assertEqual(flat.cache_dir, Path("C:/cache"))
        self.assertTrue(flat.offline)

    def test_language_mismatch_fails_closed(self):
        _, manifest = self.make_manifest()
        with tempfile.TemporaryDirectory() as tmp:
            manager = ModelManager(manifest=manifest, cache_dir=Path(tmp), offline=True)
            with self.assertRaises(LanguageMismatchError):
                manager.resolve("fixture/nemotron", language="de")

    def test_atomic_download_does_not_replace_destination_on_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "model.bin"
            destination.write_bytes(b"old")
            with self.assertRaises(RuntimeError):
                atomic_download(
                    "https://example.invalid/model.bin",
                    destination,
                    downloader=lambda *_: (_ for _ in ()).throw(RuntimeError("boom")),
                )
            self.assertEqual(destination.read_bytes(), b"old")
            self.assertEqual(list(destination.parent.glob("*.part")), [])


if __name__ == "__main__":
    unittest.main()
