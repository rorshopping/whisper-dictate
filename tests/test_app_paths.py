"""Tests for app_paths: data vs resource locations and first-run seeding."""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app_paths  # noqa: E402


class LocationTests(unittest.TestCase):

    def test_checkout_mode_uses_the_repo(self):
        # Not frozen: both roles point at the checkout so an existing install
        # keeps using its own config.json.
        self.assertFalse(app_paths.is_frozen())
        self.assertEqual(app_paths.data_dir(), os.path.dirname(os.path.abspath(app_paths.__file__)))
        self.assertEqual(app_paths.resource_dir(), os.path.dirname(os.path.abspath(app_paths.__file__)))

    def test_resolve_data_file(self):
        relative = app_paths.resolve_data_file("hotwords-en.txt")
        self.assertEqual(os.path.dirname(relative), app_paths.data_dir())
        absolute = os.path.join(tempfile.gettempdir(), "x.txt")
        self.assertEqual(app_paths.resolve_data_file(absolute), absolute)
        self.assertEqual(app_paths.resolve_data_file(""), "")

    def test_user_data_dir_is_per_platform_and_not_the_repo(self):
        target = app_paths.user_data_dir()
        self.assertTrue(os.path.isabs(target))
        self.assertIn("Whisper Dictate", target.replace("whisper-dictate", "Whisper Dictate"))
        self.assertNotEqual(target, app_paths.resource_dir())


class SeedingTests(unittest.TestCase):

    def test_seed_list_covers_every_default_file_in_the_repo(self):
        # Guards the bug where a new defaults file (snippets-*.txt) shipped in
        # the bundle but was never copied into the data folder, so the feature
        # looked broken in a packaged build.
        defaults = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "packaging",
            "defaults",
        )
        if not os.path.isdir(defaults):
            self.skipTest("packaging/defaults not present")
        present = {
            name
            for name in os.listdir(defaults)
            if name.endswith((".txt", ".json"))
        }
        missing = present - set(app_paths.DEFAULT_FILES)
        self.assertEqual(
            missing,
            set(),
            f"packaging/defaults ships {sorted(missing)} but DEFAULT_FILES omits them",
        )

    def test_ensure_initialized_is_idempotent_and_never_overwrites(self):
        directory = tempfile.mkdtemp()
        target = os.path.join(directory, "data")
        original = app_paths.data_dir
        try:
            app_paths.data_dir = lambda: target
            self.assertEqual(app_paths.ensure_initialized(), target)
            self.assertTrue(os.path.isdir(target))
            marker = os.path.join(target, "config.json")
            with open(marker, "w", encoding="utf-8") as f:
                f.write('{"user": true}')
            app_paths.ensure_initialized()
            with open(marker, "r", encoding="utf-8") as f:
                self.assertEqual(f.read(), '{"user": true}')
        finally:
            app_paths.data_dir = original


if __name__ == "__main__":
    unittest.main()
