import unittest

from hotkey_settings import (apply_changes_to_config, combo_key,
                             find_conflict, format_combo, is_valid_combo,
                             keysym_to_name)


class KeysymTests(unittest.TestCase):
    def test_modifiers(self):
        self.assertEqual(keysym_to_name("Control_L"), "ctrl")
        self.assertEqual(keysym_to_name("Alt_R"), "alt")
        self.assertEqual(keysym_to_name("shift"), "shift")

    def test_named_keys(self):
        self.assertEqual(keysym_to_name("space"), "space")
        self.assertEqual(keysym_to_name("Return"), "enter")
        self.assertEqual(keysym_to_name("F13"), "f13")

    def test_single_chars_and_unknown(self):
        self.assertEqual(keysym_to_name("a"), "a")
        self.assertEqual(keysym_to_name("A"), "a")
        self.assertIsNone(keysym_to_name("Caps_Lock"[:3] + "x" * 3))


class FormatTests(unittest.TestCase):
    def test_format_combo(self):
        self.assertEqual(format_combo(["ctrl", "shift", "space"]),
                         "Ctrl+Shift+Space")
        self.assertEqual(format_combo(["ctrl", "shift", "f10"]),
                         "Ctrl+Shift+F10")
        self.assertEqual(format_combo(["ctrl", "a"]), "Ctrl+A")


class ConflictTests(unittest.TestCase):
    def test_order_insensitive(self):
        others = [("EN", ["ctrl", "shift", "space"])]
        self.assertEqual(find_conflict(["space", "shift", "ctrl"], others), "EN")
        self.assertIsNone(find_conflict(["ctrl", "alt", "space"], others))

    def test_no_empty_match(self):
        self.assertIsNone(find_conflict([], [("EN", [])]))


class ValidityTests(unittest.TestCase):
    def test_needs_final_key(self):
        self.assertTrue(is_valid_combo(["ctrl", "shift", "f10"]))
        self.assertFalse(is_valid_combo(["ctrl", "shift"]))
        self.assertFalse(is_valid_combo([]))


class ConfigApplyTests(unittest.TestCase):
    CONFIG = {
        "profiles": [
            {"name": "EN", "hotkey": ["ctrl", "shift", "space"]},
            {"name": "DE", "hotkey": ["ctrl", "alt", "space"]},
        ],
        "paste_last_hotkey": ["ctrl", "shift", "f12"],
        "sound": True,
    }

    def test_profile_change_is_copy_safe(self):
        import copy
        original = copy.deepcopy(self.CONFIG)
        out = apply_changes_to_config(self.CONFIG,
                                      {"profile:0": ["ctrl", "alt", "f9"]})
        self.assertEqual(out["profiles"][0]["hotkey"], ["ctrl", "alt", "f9"])
        self.assertEqual(out["profiles"][1]["hotkey"],
                         original["profiles"][1]["hotkey"])
        # input dict untouched (deep)
        self.assertEqual(self.CONFIG["profiles"][0]["hotkey"],
                         ["ctrl", "shift", "space"])

    def test_simple_keys_and_unknown_rows(self):
        out = apply_changes_to_config(self.CONFIG, {
            "scratch": ["ctrl", "shift", "f13"],
            "profile:7": ["x"],  # out of range: ignored
        })
        self.assertEqual(out["scratch_hotkey"], ["ctrl", "shift", "f13"])
        self.assertEqual(len(out["profiles"]), 2)

    def test_all_row_ids_map_to_hotkey_keys(self):
        out = apply_changes_to_config(self.CONFIG, {
            "paste_last": ["p"], "scratch": ["s"], "command": ["c"],
            "history": ["h"],
        })
        self.assertEqual(out["paste_last_hotkey"], ["p"])
        self.assertEqual(out["scratch_hotkey"], ["s"])
        self.assertEqual(out["command_hotkey"], ["c"])
        self.assertEqual(out["history_hotkey"], ["h"])

    def test_combo_key(self):
        self.assertEqual(combo_key(["ctrl", "a"]), combo_key(["a", "ctrl"]))
        self.assertEqual(combo_key(None), ())


if __name__ == "__main__":
    unittest.main()
