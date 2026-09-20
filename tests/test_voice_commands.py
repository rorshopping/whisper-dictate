import unittest

from voice_commands import COMMANDS, KNOWN_KEYS, match, normalize, validate


class VoiceCommandTests(unittest.TestCase):
    def test_exact_match_after_normalization(self):
        self.assertEqual(match("Press enter.", "en"), "enter")
        self.assertEqual(match("  PASTE  ", "en"), ("ctrl", "v"))
        self.assertEqual(match("select all", "en"), ("ctrl", "a"))

    def test_filler_and_punctuation_variants(self):
        # A misheard or noisy transcript still matches once normalized.
        self.assertEqual(match("press enter!", "en"), "enter")
        self.assertEqual(match("press   tab", "en"), "tab")

    def test_german_commands(self):
        self.assertEqual(match("Alles auswählen", "de"), ("ctrl", "a"))
        self.assertEqual(match("einfügen", "de"), ("ctrl", "v"))
        self.assertEqual(match("enter drücken", "de"), "enter")
        self.assertEqual(match("letztes Wort löschen.", "de"), ("ctrl", "backspace"))

    def test_english_table_for_unknown_language(self):
        self.assertEqual(match("press enter", "fr"), "enter")

    def test_normal_dictation_is_not_a_command(self):
        self.assertIsNone(match("hello world how are you", "en"))
        self.assertIsNone(match("please paste this for me", "en"))
        self.assertIsNone(match("", "en"))
        self.assertIsNone(match(None, "en"))

    def test_normalize(self):
        self.assertEqual(normalize("  Select   All.! "), "select all")
        self.assertEqual(normalize("Select All."), "select all")

    def test_every_spec_is_valid(self):
        self.assertEqual(validate(), [])
        for table in COMMANDS.values():
            for action in table.values():
                keys = (action,) if isinstance(action, str) else action
                for k in keys:
                    self.assertIn(k, KNOWN_KEYS)

    def test_modifiers_are_never_tapped_last(self):
        for table in COMMANDS.values():
            for action in table.values():
                keys = (action,) if isinstance(action, str) else action
                self.assertNotIn(keys[-1], ("ctrl", "alt", "shift"))


if __name__ == "__main__":
    unittest.main()
