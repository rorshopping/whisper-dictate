import hashlib
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import Mock, patch
import wave

from sound_cues import (DEFAULT_THEME, EVENTS, THEMES, SoundPlayer,
                        build_sound_menu, save_preferences, selected_theme)

ROOT = Path(__file__).resolve().parents[1]


class SoundTests(unittest.TestCase):
    def test_default_and_unknown_theme(self):
        self.assertEqual(selected_theme({}), DEFAULT_THEME)
        self.assertEqual(selected_theme({"sound_theme": "bad"}), DEFAULT_THEME)

    def test_five_ranked_choices(self):
        self.assertEqual(len(THEMES), 5)
        self.assertEqual([t[2] for t in THEMES], sorted([t[2] for t in THEMES], reverse=True))

    def test_bundled_files(self):
        manifest = json.loads((ROOT / "assets/sounds/manifest.json").read_text())
        self.assertEqual([x["id"] for x in manifest], [t[0] for t in THEMES])
        for entry in manifest:
            self.assertEqual(entry["license"], "CC0-1.0")
            for event in EVENTS:
                name = f'{entry["id"]}-{event}.wav'
                path = ROOT / "assets/sounds" / name
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), entry["files"][name])
                with wave.open(str(path)) as wav:
                    self.assertEqual((wav.getnchannels(), wav.getsampwidth()), (1, 2))
                    self.assertGreater(wav.getnframes(), 0)
                    self.assertLessEqual(wav.getnframes() / wav.getframerate(), 0.45)
                    data = wav.readframes(wav.getnframes())
                    pcm = struct.unpack(f"<{len(data)//2}h", data)
                    self.assertGreater(max(abs(x) for x in pcm), 100)
                    self.assertLessEqual(max(abs(x) for x in pcm), 5243)
                    self.assertEqual(pcm[0], 0)
                    self.assertEqual(pcm[-1], 0)

    def test_persistence_preserves_other_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            data = {"profiles": [{"language": "de"}], "custom": "user edit"}
            path.write_text(json.dumps(data))
            cfg = {}
            save_preferences(path, cfg, enabled=True, theme="low-bell")
            saved = json.loads(path.read_text())
            self.assertEqual(saved["profiles"], data["profiles"])
            self.assertEqual(saved["custom"], "user edit")
            self.assertEqual(cfg, {"sound": True, "sound_theme": "low-bell"})
            save_preferences(path, cfg, enabled=False, theme="low-bell")
            self.assertFalse(json.loads(path.read_text())["sound"])

    def test_failed_save_does_not_change_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text("{invalid user config")
            cfg = {"sound": False}
            with self.assertRaises(ValueError):
                save_preferences(path, cfg, enabled=True, theme=DEFAULT_THEME)
            self.assertEqual(cfg, {"sound": False})
            self.assertEqual(path.read_text(), "{invalid user config")

    def test_atomic_replace_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text('{"sound": false}')
            cfg = {"sound": False}
            with patch("sound_cues.os.replace", side_effect=OSError("locked")):
                with self.assertRaises(OSError):
                    save_preferences(path, cfg, enabled=True, theme=DEFAULT_THEME)
            self.assertEqual(cfg, {"sound": False})
            self.assertEqual(json.loads(path.read_text()), cfg)
            self.assertEqual(list(Path(tmp).iterdir()), [path])

    def test_windows_playback_async_and_no_system_fallback(self):
        winsound = Mock(SND_FILENAME=1, SND_ASYNC=2, SND_NODEFAULT=4)
        with patch("sound_cues.sys.platform", "win32"), patch.dict("sys.modules", winsound=winsound):
            player = SoundPlayer(ROOT)
            player.play({}, "start")
            winsound.PlaySound.assert_called_once_with(
                str(ROOT / f"assets/sounds/{DEFAULT_THEME}-start.wav"), 7)
            winsound.PlaySound.reset_mock()
            player.play({"sound": False}, "done")
            player.play({}, "unknown")
            winsound.PlaySound.assert_not_called()
            with tempfile.TemporaryDirectory() as tmp, self.assertLogs(level="WARNING"):
                SoundPlayer(tmp).play({}, "done")
            winsound.PlaySound.assert_not_called()
            player.stop()
            winsound.PlaySound.assert_called_once_with(None, 0)

    def test_real_pystray_menu_callbacks(self):
        import pystray
        with tempfile.TemporaryDirectory() as tmp:
            cfg = {}
            player, notify, icon = Mock(), Mock(), Mock()
            path = Path(tmp) / "config.json"
            menu = build_sound_menu(pystray.Menu, pystray.MenuItem, cfg, path, player, notify)
            items = list(menu.items)
            self.assertEqual(len(items), 9)
            self.assertTrue(items[1].checked)
            for index, (theme, _, _) in enumerate(THEMES, 1):
                items[index](icon)
                self.assertEqual(cfg["sound_theme"], theme)
                self.assertEqual(sum(bool(i.checked) for i in items[1:6]), 1)
                player.play.assert_called_with(cfg, "done")
            items[7](icon)  # Off
            self.assertFalse(cfg["sound"])
            self.assertTrue(items[7].checked)
            self.assertFalse(items[8].enabled)
            player.stop.assert_called_once()
            items[1](icon)  # Selecting a theme re-enables audio.
            self.assertTrue(cfg["sound"])
            items[8](icon)
            player.play.assert_called_with(cfg, "done")
            notify.assert_not_called()


if __name__ == "__main__":
    unittest.main()
