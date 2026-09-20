import unittest

from smart_format import apply


class SmartFormatTests(unittest.TestCase):
    def test_filler_removal_en(self):
        out = apply("um hello uh world period", "en")
        self.assertEqual(out, "Hello world.")

    def test_filler_removal_de(self):
        out = apply("äh hallo ähm welt", "de")
        self.assertEqual(out, "Hallo welt")

    def test_spoken_punctuation(self):
        out = apply("hello comma world period", "en")
        self.assertEqual(out, "Hello, world.")

    def test_question_and_exclamation(self):
        out = apply("are you there question mark wow exclamation point", "en")
        self.assertEqual(out, "Are you there? Wow!")

    def test_new_line_and_paragraph(self):
        out = apply("first line new line second line new paragraph third", "en")
        self.assertEqual(out, "First line\nSecond line\n\nThird")

    def test_bullets(self):
        out = apply("bullet point buy milk bullet point walk dog", "en")
        self.assertEqual(out, "• Buy milk\n• Walk dog")

    def test_backtrack_keeps_only_text_after_the_phrase(self):
        out = apply("the deploy is broken scratch that we should ship", "en")
        self.assertEqual(out, "We should ship")

    def test_backtrack_to_empty_types_nothing(self):
        self.assertEqual(apply("this is wrong scratch that", "en"), "")

    def test_backtrack_de(self):
        out = apply("das ist falsch vergiss das wir sollten shippen", "de")
        self.assertEqual(out, "Wir sollten shippen")

    def test_backtrack_word_boundary(self):
        # "vergisst" (real word) must not trigger the "vergiss" backtrack.
        out = apply("er vergisst das papier", "de")
        self.assertEqual(out, "Er vergisst das papier")

    def test_capitalize_sentences_and_i(self):
        out = apply("i think it works period it really does", "en")
        self.assertEqual(out, "I think it works. It really does")

    def test_decimals_and_domains_untouched(self):
        out = apply("version 3.5 works on example.com right question mark", "en")
        self.assertEqual(out, "Version 3.5 works on example.com right?")

    def test_tidy_spacing(self):
        out = apply("word , word ; word", "en", spoken_punctuation=False)
        self.assertEqual(out, "Word, word; word")

    def test_greedy_leading_punctuation_after_filler(self):
        out = apply("um , hello there", "en")
        self.assertEqual(out, "Hello there")

    def test_german_punctuation(self):
        out = apply("hallo komma welt fragezeichen", "de")
        self.assertEqual(out, "Hallo, welt?")

    def test_german_real_word_punkt_untouched(self):
        out = apply("ein wichtiger punkt fehlt noch", "de")
        self.assertEqual(out, "Ein wichtiger punkt fehlt noch")

    def test_empty_and_disabled(self):
        self.assertEqual(apply("", "en"), "")
        self.assertEqual(
            apply("um hello", "en", fillers=False, capitalize=False), "um hello"
        )
        self.assertEqual(
            apply("hello comma world", "en", spoken_punctuation=False,
                  capitalize=False),
            "hello comma world",
        )
        self.assertEqual(
            apply("um hello", "en", capitalize=False), "hello"
        )


if __name__ == "__main__":
    unittest.main()
