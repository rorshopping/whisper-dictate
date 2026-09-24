"""Focused tests for the application Profile -> NemotronModel bridge."""

import importlib.util
import logging
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import app_paths


ROOT = Path(__file__).resolve().parents[1]


class _MainImport:
    """Load main.py without requiring the optional desktop/audio packages."""

    @classmethod
    def load(cls):
        keyboard = types.ModuleType("pynput.keyboard")
        keyboard.Key = types.SimpleNamespace()
        pynput = types.ModuleType("pynput")
        pynput.__path__ = []
        pynput.keyboard = keyboard
        pyperclip = types.ModuleType("pyperclip")
        pystray = types.ModuleType("pystray")
        sounddevice = types.ModuleType("sounddevice")
        tkinter = types.ModuleType("tkinter")
        replacements = {
            "pynput": pynput,
            "pynput.keyboard": keyboard,
            "pyperclip": pyperclip,
            "pystray": pystray,
            "sounddevice": sounddevice,
            "tkinter": tkinter,
        }

        with tempfile.TemporaryDirectory(prefix="whisper wiring ") as tmp:
            data = Path(tmp)
            # Keep import-time initialization away from the checkout and avoid
            # the platform single-instance guard in this headless test.
            with patch.object(app_paths, "data_dir", return_value=str(data)), patch.object(
                sys, "argv", ["main.py", "--doctor"]
            ), patch.dict(sys.modules, replacements):
                spec = importlib.util.spec_from_file_location(
                    "resolver_wiring_main", str(ROOT / "main.py")
                )
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                # main installs a file handler at import time.  Close it before
                # the temporary data directory is removed (required on Windows).
                handler = getattr(module, "_log_handler", None)
                if handler is not None:
                    logging.getLogger().removeHandler(handler)
                    handler.close()
        return module


class ProfileModelWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.main = _MainImport.load()

    def setUp(self):
        self.main.cfg = {
            "offline": True,
            "model_resolver": {
                "source_order": ["local", "cache", "mirror", "huggingface"],
                "cache_dir": "~/.cache/huggingface/hub",
                "mirror_url": "https://top-level.example",
                "hf_endpoint": "https://top-level-hf.example",
            },
        }
        self.profile = self.main.Profile(
            0,
            {
                "name": "EN",
                "engine": "nemotron",
                "model": "fixture/nemotron",
                "model_revision": "test-revision",
                "model_source_order": ["cache", "huggingface"],
                "model_mirror_url": "https://profile-mirror.example",
                "huggingface_endpoint": "https://profile-hf.example",
                "language": "en",
                "local_model_path": "local/snapshot",
            },
        )

    def test_profile_resolver_settings_and_app_cache_reach_options(self):
        reference, options = self.main._nemotron_model_options(self.profile)

        self.assertEqual(reference, "fixture/nemotron")
        self.assertEqual(options["revision"], "test-revision")
        self.assertEqual(options["source_order"], ("cache", "huggingface"))
        self.assertEqual(options["mirror_url"], "https://profile-mirror.example")
        self.assertEqual(
            options["huggingface_endpoint"], "https://profile-hf.example"
        )
        self.assertTrue(options["offline"])
        self.assertEqual(options["cache_dir"], self.main.MODEL_CACHE_DIR)
        self.assertEqual(options["local_model_path"], Path("local/snapshot"))
        self.assertEqual(options["language"], "en")

    def test_explicit_nondefault_cache_remains_configurable(self):
        custom = Path(self.main.MODEL_CACHE_DIR) / "operator-cache"
        self.main.cfg["model_resolver"]["cache_dir"] = str(custom)

        _reference, options = self.main._nemotron_model_options(self.profile)

        self.assertEqual(options["cache_dir"], custom)

    def test_get_model_passes_resolver_options_to_mocked_engine(self):
        calls = []

        class FakeNemotronModel:
            def __init__(self, model_id, **kwargs):
                calls.append((model_id, kwargs))
                self.model_id = model_id

        fake_engine = types.ModuleType("nemotron_engine")
        fake_engine.NemotronModel = FakeNemotronModel
        self.profile.model_obj = None
        with patch.dict(sys.modules, {"nemotron_engine": fake_engine}), patch.object(
            self.main, "show_state"
        ), patch.object(self.main, "log", lambda _message: None):
            loaded = self.main.get_model(self.profile)

        self.assertIsInstance(loaded, FakeNemotronModel)
        self.assertEqual(len(calls), 1)
        model_id, kwargs = calls[0]
        self.assertEqual(model_id, "fixture/nemotron")
        self.assertEqual(kwargs["revision"], "test-revision")
        self.assertEqual(kwargs["source_order"], ("cache", "huggingface"))
        self.assertEqual(kwargs["mirror_url"], "https://profile-mirror.example")
        self.assertEqual(kwargs["huggingface_endpoint"], "https://profile-hf.example")
        self.assertTrue(kwargs["offline"])
        self.assertEqual(kwargs["cache_dir"], self.main.MODEL_CACHE_DIR)
        self.assertEqual(kwargs["local_model_path"], Path("local/snapshot"))

    def test_resolver_failure_is_logged_and_re_raised_without_fallback(self):
        class BrokenNemotronModel:
            def __init__(self, *_args, **_kwargs):
                raise RuntimeError("pinned snapshot is missing or corrupt")

        fake_engine = types.ModuleType("nemotron_engine")
        fake_engine.NemotronModel = BrokenNemotronModel
        logs = []
        self.profile.model_obj = None
        with patch.dict(sys.modules, {"nemotron_engine": fake_engine}), patch.object(
            self.main, "show_state"
        ), patch.object(self.main, "log", logs.append):
            with self.assertRaisesRegex(RuntimeError, "missing or corrupt"):
                self.main.get_model(self.profile)

        self.assertTrue(any("missing or corrupt" in message for message in logs))
        self.assertIsNone(self.profile.model_obj)

    def test_faster_whisper_constructor_remains_unchanged(self):
        calls = []

        class FakeWhisperModel:
            def __init__(self, model_id, **kwargs):
                calls.append((model_id, kwargs))

        fake_engine = types.ModuleType("faster_whisper")
        fake_engine.WhisperModel = FakeWhisperModel
        profile = self.main.Profile(
            0,
            {"name": "small", "engine": "faster-whisper", "model": "small.en"},
        )
        profile.model_obj = None
        with patch.dict(sys.modules, {"faster_whisper": fake_engine}), patch.object(
            self.main, "show_state"
        ), patch.object(self.main, "log", lambda _message: None):
            self.main.get_model(profile)

        self.assertEqual(
            calls,
            [
                (
                    "small.en",
                    {"device": self.main.DEVICE, "compute_type": self.main.COMPUTE},
                )
            ],
        )


if __name__ == "__main__":
    unittest.main()
