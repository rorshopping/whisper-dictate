import hashlib
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from model_manager import ModelManifest, ResolvedModel
from nemotron_engine import NemotronModel


class ShellNemotron(NemotronModel):
    """Construct the resolver path without importing torch or loading weights."""

    def _load(self, device, compute_type):
        self.load_args = (device, compute_type)


class NemotronModelResolutionTests(unittest.TestCase):
    def make_manifest(self):
        contents = {
            "config.json": b'{"model_type": "fixture"}',
            "tokenizer.json": b"tokenizer",
        }
        return contents, ModelManifest.from_mapping(
            {
                "id": "fixture/nemotron",
                "revision": "test-revision",
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

    def test_local_path_uses_resolver_and_preserves_profile_id(self):
        contents, manifest = self.make_manifest()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name, data in contents.items():
                (root / name).write_bytes(data)
            model = ShellNemotron(
                "fixture/nemotron",
                device="cpu",
                local_model_path=root,
                manifest=manifest,
                offline=True,
            )
            self.assertEqual(model.model_id, "fixture/nemotron")
            self.assertEqual(model.model_path, root)
            self.assertEqual(model.model_revision, "test-revision")
            self.assertEqual(model.model_source, "local")
            self.assertEqual(model.load_args, ("cpu", "auto"))

    def test_legacy_direct_id_signature_still_constructs(self):
        contents, manifest = self.make_manifest()
        calls = []

        class FakeManager:
            def __init__(self, **kwargs):
                calls.append(("manager", kwargs))

            def resolve(self, model_id, **kwargs):
                calls.append((model_id, kwargs))
                return ResolvedModel(
                    manifest,
                    Path("C:/models/fixture"),
                    "cache",
                )

        # This is the pre-resolver positional shape: model ID, device,
        # compute type, and logger remain valid with no new keyword arguments.
        with patch("model_manager.ModelManager", FakeManager):
            model = ShellNemotron(
                "fixture/nemotron",
                "cpu",
                "auto",
                None,
            )

        self.assertEqual(model.model_id, "fixture/nemotron")
        self.assertEqual(model.model_path, Path("C:/models/fixture"))
        self.assertEqual(model.model_revision, manifest.revision)
        self.assertEqual(calls[1][0], "fixture/nemotron")
        self.assertEqual(model.load_args, ("cpu", "auto"))

    def test_transformers_load_is_local_only_and_revision_pinned(self):
        calls = []

        class FakeProcessor:
            @classmethod
            def from_pretrained(cls, path, **kwargs):
                calls.append(("processor", path, kwargs))
                return types.SimpleNamespace(
                    supported_num_lookahead_tokens=[],
                )

        class FakeModel:
            def __init__(self):
                self.config = types.SimpleNamespace(model_type="nemotron_asr_streaming")

            def to(self, device):
                self.device = device
                return self

            def eval(self):
                return self

            @classmethod
            def from_pretrained(cls, path, **kwargs):
                calls.append(("model", path, kwargs))
                return cls()

        fake_torch = types.ModuleType("torch")
        fake_torch.float32 = object()
        fake_torch.float16 = object()
        fake_torch.device = lambda value: value
        fake_torch.cuda = types.SimpleNamespace(is_available=lambda: False)
        fake_transformers = types.ModuleType("transformers")
        fake_transformers.AutoProcessor = FakeProcessor
        fake_transformers.AutoModelForRNNT = FakeModel
        old_torch = sys.modules.get("torch")
        old_transformers = sys.modules.get("transformers")
        sys.modules["torch"] = fake_torch
        sys.modules["transformers"] = fake_transformers
        try:
            model = object.__new__(NemotronModel)
            model.model_id = "fixture/nemotron"
            model.model_path = Path("C:/models/fixture")
            model.model_revision = "test-revision"
            model._log = lambda *_: None
            model._load("cpu", "auto")
        finally:
            if old_torch is None:
                sys.modules.pop("torch", None)
            else:
                sys.modules["torch"] = old_torch
            if old_transformers is None:
                sys.modules.pop("transformers", None)
            else:
                sys.modules["transformers"] = old_transformers

        self.assertEqual(calls[0][0], "processor")
        self.assertEqual(calls[1][0], "model")
        for _, _, kwargs in calls:
            self.assertTrue(kwargs["local_files_only"])
            self.assertEqual(kwargs["revision"], "test-revision")
            self.assertFalse(kwargs["trust_remote_code"])
        self.assertTrue(calls[1][2]["use_safetensors"])

    def test_language_mismatch_is_rejected_before_inference(self):
        model = object.__new__(NemotronModel)
        model.model_id = "fixture/nemotron"
        model._manifest_languages = ("en",)
        with self.assertRaises(ValueError):
            model.transcribe(np.zeros(0, dtype=np.float32), language="de")


if __name__ == "__main__":
    unittest.main()
