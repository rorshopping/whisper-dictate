"""Tests for the parakeet-gguf engine (parakeet.cpp via ctypes)."""

import hashlib
import os
import sys
import tempfile
import threading
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from model_manager import DEFAULT_MANIFESTS, ModelManager, ModelManifest, ResolvedModel
from parakeet_engine import ParakeetModel, _find_library


class ShellParakeet(ParakeetModel):
    """Construct the resolver path without loading the DLL or weights."""

    def _load(self, device, compute_type):
        self.load_args = (device, compute_type)


class ParakeetResolutionTests(unittest.TestCase):
    def make_manifest(self, model_id="fixture/gguf"):
        data = b"gguf-bytes"
        return data, ModelManifest.from_mapping(
            {
                "id": model_id,
                "revision": "test-revision",
                "repository": "fixture/collection",
                "language": "en",
                "required_files": [
                    {"name": "model-f16.gguf", "size": len(data), "sha256": hashlib.sha256(data).hexdigest()},
                ],
            }
        )

    def test_local_path_uses_resolver_and_preserves_profile_id(self):
        data, manifest = self.make_manifest()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "model-f16.gguf").write_bytes(data)
            model = ShellParakeet(
                "fixture/gguf",
                device="cpu",
                local_model_path=root,
                manifest=manifest,
                offline=True,
            )
            self.assertEqual(model.model_id, "fixture/gguf")
            self.assertEqual(model.model_path, root)
            self.assertEqual(model.model_revision, "test-revision")
            self.assertEqual(model.model_source, "local")
            self.assertEqual(model.load_args, ("cpu", "auto"))

    def test_gguf_file_path_pins_the_single_required_file(self):
        data, manifest = self.make_manifest()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "model-f16.gguf").write_bytes(data)
            model = ShellParakeet(
                "fixture/gguf",
                device="cpu",
                local_model_path=root,
                manifest=manifest,
                offline=True,
            )
            resolved = model._gguf_file_path()
            self.assertEqual(Path(resolved).name, "model-f16.gguf")
            self.assertEqual(Path(resolved).read_bytes(), data)

    def test_legacy_direct_id_signature_still_constructs(self):
        _data, manifest = self.make_manifest()
        calls = []

        class FakeManager:
            def __init__(self, **kwargs):
                calls.append(("manager", kwargs))

            def resolve(self, model_id, **kwargs):
                calls.append((model_id, kwargs))
                return ResolvedModel(manifest, Path("C:/models/gguf"), "cache")

        with patch("model_manager.ModelManager", FakeManager):
            model = ShellParakeet("fixture/gguf", "cpu", "auto", None)

        self.assertEqual(model.model_id, "fixture/gguf")
        self.assertEqual(calls[1][0], "fixture/gguf")
        self.assertEqual(model.load_args, ("cpu", "auto"))

    def test_library_not_found_message_lists_candidates(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("PARAKEET_GGUF_DLL", None)
            # Point the search at a name that cannot exist so the test does
            # not depend on a staged runtime.
            with patch("parakeet_engine._DLL_NAME", "parakeet-missing.dll"):
                with self.assertRaises(FileNotFoundError):
                    _find_library(lambda *_: None)


class FakeParakeetLib:
    """In-memory stand-in for the parakeet C API surface the engine uses."""

    def __init__(self, transcript="hello world"):
        self.transcript = transcript
        self.freed = []
        self.errors = []
        self.calls = []

    def parakeet_capi_abi_version(self):
        return 6

    def parakeet_capi_load(self, path):
        self.calls.append(("load", path))
        return 4242

    def parakeet_capi_free(self, ctx):
        self.freed.append(ctx)

    def parakeet_capi_transcribe_pcm_lang(self, ctx, samples, n, sr, decoder, lang):
        self.calls.append(("pcm", ctx, n, sr, decoder, lang))
        buf = (ctypes_char_buffer(self.transcript))
        return buf

    def parakeet_capi_free_string(self, ptr):
        self.freed.append(("string", ptr))

    def parakeet_capi_last_error(self, ctx):
        return b""


def ctypes_char_buffer(text):
    import ctypes

    return ctypes.create_string_buffer(text.encode("utf-8"))


def make_instantiated(transcript="hello world", languages=("en", "de")):
    """A ParakeetModel bypassing __init__, wired to the fake library."""
    model = object.__new__(ParakeetModel)
    model.model_id = "fixture/gguf"
    model._manifest_languages = languages
    model._log = lambda *_: None
    model._lock = threading.Lock()
    model._ctx = types.SimpleNamespace()
    model._lib = FakeParakeetLib(transcript)
    return model


class ParakeetInferenceTests(unittest.TestCase):
    def test_transcribe_returns_segments_and_info(self):
        model = make_instantiated("And so, my fellow Americans.")
        segments, info = model.transcribe(np.zeros(16000, dtype=np.float32), language="en")
        self.assertEqual(len(segments), 1)
        self.assertEqual(segments[0].text, "And so, my fellow Americans.")
        self.assertEqual(info["language"], "en")
        self.assertAlmostEqual(info["duration"], 1.0)

    def test_transcribe_passes_language_to_the_c_api(self):
        model = make_instantiated("Guten Tag")
        model.transcribe(np.zeros(8000, dtype=np.float32), language="de")
        pcm_call = model._lib.calls[-1]
        self.assertEqual(pcm_call[0], "pcm")
        self.assertEqual(pcm_call[5], b"de")

    def test_empty_audio_returns_no_segments(self):
        model = make_instantiated()
        segments, info = model.transcribe(np.zeros(0, dtype=np.float32), language="en")
        self.assertEqual(segments, [])
        self.assertEqual(info["duration"], 0.0)

    def test_language_mismatch_is_rejected_before_inference(self):
        model = make_instantiated(languages=("en",))
        with self.assertRaises(ValueError):
            model.transcribe(np.zeros(1600, dtype=np.float32), language="de")

    def test_close_frees_the_context_once(self):
        model = make_instantiated()
        ctx = model._ctx
        model.close()
        self.assertEqual(model._lib.freed, [ctx])
        self.assertIsNone(model._ctx)
        model.close()  # idempotent
        self.assertEqual(len(model._lib.freed), 1)


class ChunkingTests(unittest.TestCase):
    def test_long_audio_chunks_within_limit(self):
        model = make_instantiated()
        audio = np.zeros(int(400 * 16000), dtype=np.float32)
        chunks = model._split_for_limit(audio)
        limit = int(330 * 16000)
        self.assertGreater(len(chunks), 1)
        for chunk in chunks:
            self.assertLessEqual(chunk.size, limit)
        self.assertEqual(sum(c.size for c in chunks), audio.size)

    def test_short_audio_untouched(self):
        model = make_instantiated()
        audio = np.ones(16000, dtype=np.float32)
        self.assertEqual(len(model._split_for_limit(audio)), 1)


class GgufManifestCatalogTests(unittest.TestCase):
    def test_default_catalog_contains_pinned_ggufs(self):
        for model_id in ("mudler/parakeet-tdt-0.6b-v3-GGUF", "mudler/nemotron-3.5-asr-streaming-0.6b-GGUF"):
            manifest = DEFAULT_MANIFESTS.get(model_id)
            self.assertEqual(len(manifest.required_files), 1)
            self.assertTrue(manifest.required_files[0].name.endswith(".gguf"))
            self.assertEqual(manifest.repository, "mudler/parakeet-cpp-gguf")

    def test_download_url_uses_the_collection_repository(self):
        manager = ModelManager()
        manifest = DEFAULT_MANIFESTS.get("mudler/parakeet-tdt-0.6b-v3-GGUF")
        url = manager._url_for_file(manifest, "https://huggingface.co", manifest.required_files[0].name)
        self.assertEqual(
            url,
            "https://huggingface.co/mudler/parakeet-cpp-gguf/resolve/"
            f"{manifest.revision}/{manifest.required_files[0].name}",
        )

    def test_gguf_manifests_support_en_and_de(self):
        en = DEFAULT_MANIFESTS.get("mudler/parakeet-tdt-0.6b-v3-GGUF")
        de = DEFAULT_MANIFESTS.get("mudler/nemotron-3.5-asr-streaming-0.6b-GGUF")
        self.assertTrue(en.supports_language("en"))
        self.assertTrue(en.supports_language("de"))
        self.assertTrue(de.supports_language("de"))
        self.assertFalse(de.supports_language("eo"))


if __name__ == "__main__":
    unittest.main()
