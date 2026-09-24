"""Tests for the read-only resource / writable-data split."""

import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import app_paths


class AppPathTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="whisper paths ✓ ")
        self.root = Path(self.tmp.name)
        self.app = self.root / "Installed App"
        self.resources = self.root / "resource root"
        self.user = self.root / "user data"
        self.app.mkdir()
        self.resources.mkdir()
        self.user.mkdir()
        self.env_patch = patch.dict(os.environ, {}, clear=False)
        self.env_patch.start()
        for name in (
            app_paths.DATA_DIR_ENV,
            app_paths.PORTABLE_ENV,
            app_paths.PORTABLE_DIR_ENV,
        ):
            os.environ.pop(name, None)
        self.frozen_patch = patch.object(sys, "frozen", True, create=True)
        self.frozen_patch.start()
        self.meipass_patch = patch.object(sys, "_MEIPASS", str(self.resources), create=True)
        self.meipass_patch.start()
        self.exe_patch = patch.object(sys, "executable", str(self.app / "Whisper Dictate.exe"))
        self.exe_patch.start()
        self.user_patch = patch.object(app_paths, "user_data_dir", return_value=str(self.user))
        self.user_patch.start()

    def tearDown(self):
        self.user_patch.stop()
        self.exe_patch.stop()
        self.meipass_patch.stop()
        self.frozen_patch.stop()
        self.env_patch.stop()
        self.tmp.cleanup()

    def test_frozen_resources_are_meipass_and_data_is_separate(self):
        self.assertEqual(app_paths.resource_dir(), str(self.resources))
        self.assertEqual(app_paths.data_dir(), str(self.user))
        self.assertNotEqual(app_paths.resource_dir(), app_paths.data_dir())
        self.assertTrue(app_paths.config_path().startswith(str(self.user)))
        self.assertTrue(app_paths.log_path().startswith(str(self.user)))
        self.assertTrue(app_paths.history_path().startswith(str(self.user)))
        self.assertTrue(app_paths.model_cache_dir().startswith(str(self.user)))
        self.assertTrue(app_paths.lock_path().startswith(str(self.user)))

    def test_portable_flag_uses_space_and_unicode_safe_directory(self):
        os.environ[app_paths.PORTABLE_ENV] = "1"
        selected = Path(app_paths.data_dir())
        self.assertEqual(selected, self.app / app_paths.PORTABLE_DIRNAME)
        self.assertTrue(selected.is_dir())
        self.assertIn(" ", str(selected))
        self.assertTrue(app_paths.local_path("corrections-en.txt").startswith(str(selected)))

    def test_portable_marker_is_opt_in(self):
        marker = self.app / app_paths.PORTABLE_DIRNAME
        marker.mkdir()
        self.assertEqual(Path(app_paths.data_dir()), marker)
        self.assertTrue(app_paths.portable_requested())

    def test_unwritable_portable_location_falls_back_to_user_data(self):
        os.environ[app_paths.PORTABLE_ENV] = "1"
        with patch.object(app_paths, "_directory_is_writable", return_value=False):
            self.assertEqual(app_paths.data_dir(), str(self.user))
        self.assertFalse((self.app / app_paths.PORTABLE_DIRNAME).exists())

    def test_source_mode_keeps_checkout_data_behavior(self):
        with patch.object(sys, "frozen", False), patch.object(sys, "_MEIPASS", None), patch.object(sys, "argv", []):
            source = Path(app_paths.__file__).resolve().parent
            self.assertEqual(Path(app_paths.resource_dir()), source)
            self.assertEqual(Path(app_paths.data_dir()), source)
            self.assertTrue(app_paths.config_path().startswith(str(source)))

    def test_local_override_never_points_into_resource_root(self):
        override = Path(app_paths.local_path("private/corrections-en.txt"))
        self.assertEqual(
            override,
            self.user / "private" / "corrections-en.local.txt",
        )
        self.assertNotIn(str(self.resources), str(override))

    def test_data_resolver_preserves_empty_and_absolute_inputs(self):
        absolute = self.root / "already absolute.txt"
        self.assertEqual(app_paths.resolve_data_file(""), "")
        self.assertEqual(app_paths.resolve_data_file(str(absolute)), str(absolute))

    def test_lock_path_is_shared_name_for_every_platform(self):
        self.assertEqual(Path(app_paths.lock_path()).name, ".app.lock")
        self.assertEqual(Path(app_paths.lock_path()).parent, self.user)

    def test_frozen_sound_player_resolves_bundled_assets(self):
        from sound_cues import SoundPlayer

        player = SoundPlayer(self.app)
        self.assertEqual(
            player.directory,
            self.resources / "assets" / "sounds",
        )


class ConfigInitializationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="whisper config ")
        self.root = Path(self.tmp.name)
        self.resources = self.root / "resources"
        self.data = self.root / "data"
        self.resources.mkdir()
        self.data.mkdir()
        self.resource_patch = patch.object(
            app_paths, "resource_dir", return_value=str(self.resources)
        )
        self.data_patch = patch.object(app_paths, "data_dir", return_value=str(self.data))
        self.frozen_patch = patch.object(sys, "frozen", True, create=True)
        self.argv_patch = patch.object(sys, "argv", [])
        self.resource_patch.start()
        self.data_patch.start()
        self.frozen_patch.start()
        self.argv_patch.start()

    def tearDown(self):
        self.argv_patch.stop()
        self.frozen_patch.stop()
        self.data_patch.stop()
        self.resource_patch.stop()
        self.tmp.cleanup()

    def test_frozen_startup_copies_bundled_default_config(self):
        (self.resources / "config.json").write_text(
            json.dumps({"offline": True, "sound": True}), encoding="utf-8"
        )
        app_paths.ensure_initialized()
        user_config = self.data / "config.json"
        self.assertTrue(user_config.is_file())
        self.assertEqual(json.loads(user_config.read_text(encoding="utf-8"))["offline"], True)

    def test_builtin_defaults_can_create_a_config_without_a_resource_file(self):
        self.assertTrue(app_paths.ensure_config({"fallback": True}))
        self.assertEqual(
            json.loads((self.data / "config.json").read_text(encoding="utf-8")),
            {"fallback": True},
        )

    def test_existing_valid_config_is_preserved_and_merged(self):
        config = self.data / "config.json"
        config.write_text(
            json.dumps({"sound": False, "custom": "keep me"}), encoding="utf-8"
        )
        app_paths.ensure_config(
            {"sound": True, "new_option": 7, "nested": {"new": 1}},
            merge=True,
        )
        saved = json.loads(config.read_text(encoding="utf-8"))
        self.assertEqual(saved["custom"], "keep me")
        self.assertFalse(saved["sound"])
        self.assertEqual(saved["new_option"], 7)
        self.assertEqual(saved["nested"], {"new": 1})

    def test_atomic_config_save_creates_a_unicode_path(self):
        target = self.root / "配置 with spaces.json"
        app_paths.save_config({"text": "Grüße"}, str(target))
        self.assertEqual(json.loads(target.read_text(encoding="utf-8"))["text"], "Grüße")

    def test_invalid_existing_config_is_not_overwritten(self):
        config = self.data / "config.json"
        config.write_text("{not valid", encoding="utf-8")
        self.assertFalse(app_paths.ensure_config({"safe": True}, merge=True))
        self.assertEqual(config.read_text(encoding="utf-8"), "{not valid")

    def test_legacy_personal_files_are_migrated_without_overwriting(self):
        legacy = self.root / "legacy"
        legacy.mkdir()
        (legacy / "corrections-en.local.txt").write_text(
            "private => local\n", encoding="utf-8"
        )
        with patch.object(app_paths, "install_dir", return_value=str(legacy)):
            app_paths.ensure_initialized()
            self.assertEqual(
                (self.data / "corrections-en.local.txt").read_text(encoding="utf-8"),
                "private => local\n",
            )
            replacement = self.data / "corrections-en.local.txt"
            replacement.write_text("mine => value\n", encoding="utf-8")
            app_paths.ensure_initialized()
            self.assertEqual(replacement.read_text(encoding="utf-8"), "mine => value\n")


if __name__ == "__main__":
    unittest.main()
