"""Tests for text_tools: spoken punctuation and voice snippets.

Run: .venv/bin/python -m unittest discover -s tests -v
No third-party test dependency; plain unittest so it runs anywhere.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import text_tools  # noqa: E402


class DefaultPathTests(unittest.TestCase):
    """With both features off the text must survive untouched."""

    def test_plain_text_unchanged(self):
        text = "Backup performance ist heute schlecht."
        self.assertEqual(text_tools.process_text(text), text)

    def test_command_words_unchanged_when_disabled(self):
        text = "The period of this comma separated list is short."
        self.assertEqual(text_tools.process_text(text, language="en"), text)

    def test_empty_input(self):
        self.assertEqual(text_tools.process_text(""), "")


class SpokenPunctuationEnglishTests(unittest.TestCase):

    def run_text(self, text):
        return text_tools.process_text(text, language="en", spoken_punctuation=True)

    def test_inline_comma(self):
        self.assertEqual(self.run_text("hello comma world"), "hello, world")

    def test_trailing_period(self):
        self.assertEqual(self.run_text("Ready period"), "Ready.")

    def test_sentence_mark_capitalizes_next_word(self):
        self.assertEqual(
            self.run_text("done period next sentence"), "done. Next sentence"
        )

    def test_question_mark(self):
        self.assertEqual(self.run_text("is this on question mark"), "is this on?")

    def test_exclamation_point(self):
        self.assertEqual(self.run_text("great exclamation point"), "great!")

    def test_new_line(self):
        self.assertEqual(self.run_text("first new line second"), "first\nSecond")

    def test_new_paragraph(self):
        self.assertEqual(
            self.run_text("first paragraph new paragraph second"),
            "first paragraph\n\nSecond",
        )

    def test_parentheses(self):
        self.assertEqual(
            self.run_text("open parenthesis aside close parenthesis done"),
            "(aside) done",
        )

    def test_colon(self):
        self.assertEqual(self.run_text("note colon here"), "note: here")

    def test_longest_phrase_wins(self):
        self.assertEqual(self.run_text("really question mark"), "really?")

    def test_word_boundary_protects_lookalikes(self):
        # "periodical" and "commas" must not be rewritten.
        text = "The periodical lists commas"
        self.assertEqual(self.run_text(text), text)

    def test_leading_command(self):
        self.assertEqual(self.run_text("comma hello"), ", hello")

    def test_already_punctuated_is_not_doubled(self):
        self.assertEqual(self.run_text("Ready. period"), "Ready.")

    def test_mixed_case_command(self):
        self.assertEqual(self.run_text("hello Comma world"), "hello, world")

    def test_unrelated_words_untouched(self):
        text = "the database migration finished"
        self.assertEqual(self.run_text(text), text)


class SpokenPunctuationGermanTests(unittest.TestCase):

    def run_text(self, text):
        return text_tools.process_text(text, language="de", spoken_punctuation=True)

    def test_komma(self):
        self.assertEqual(self.run_text("hallo komma welt"), "hallo, welt")

    def test_punkt(self):
        self.assertEqual(self.run_text("fertig punkt"), "fertig.")

    def test_fragezeichen(self):
        self.assertEqual(self.run_text("ist das an fragezeichen"), "ist das an?")

    def test_neue_zeile(self):
        self.assertEqual(
            self.run_text("erste zeile neue zeile zweite zeile"),
            "erste zeile\nZweite zeile",
        )

    def test_neuer_absatz(self):
        self.assertEqual(
            self.run_text("eins neuer absatz zwei"),
            "eins\n\nZwei",
        )

    def test_klammer(self):
        self.assertEqual(
            self.run_text("klammer auf einschluss klammer zu ende"),
            "(einschluss) ende",
        )

    def test_language_region_variant(self):
        self.assertEqual(
            text_tools.process_text(
                "hallo komma welt", language="de-DE", spoken_punctuation=True
            ),
            "hallo, welt",
        )


class SnippetTests(unittest.TestCase):

    SNIPPETS = {
        "insert signature": "Richard Bäcker\nBecker Hub",
        "my address": "Musterstraße 1",
    }

    def test_exact_utterance_expands(self):
        self.assertEqual(
            text_tools.process_text("insert signature", snippets=self.SNIPPETS),
            "Richard Bäcker\nBecker Hub",
        )

    def test_match_ignores_case_and_trailing_punctuation(self):
        self.assertEqual(
            text_tools.process_text("Insert signature.", snippets=self.SNIPPETS),
            "Richard Bäcker\nBecker Hub",
        )

    def test_no_partial_match_inside_a_sentence(self):
        text = "please insert signature below"
        self.assertEqual(
            text_tools.process_text(text, snippets=self.SNIPPETS), text
        )

    def test_unknown_utterance_unchanged(self):
        text = "insert nothing"
        self.assertEqual(text_tools.process_text(text, snippets=self.SNIPPETS), text)

    def test_snippet_content_is_verbatim_not_rewritten(self):
        snippets = {"say address": "Line one period Line two"}
        self.assertEqual(
            text_tools.process_text(
                "say address",
                snippets=snippets,
                spoken_punctuation=True,
            ),
            "Line one period Line two",
        )

    def test_snippets_accept_arrow_lines_and_pairs(self):
        self.assertEqual(
            match_arrow := text_tools.process_text(
                "sig", snippets=["sig => Best regards"]
            ),
            "Best regards",
        )
        self.assertEqual(match_arrow, "Best regards")
        self.assertEqual(
            text_tools.process_text("sig", snippets=[("sig", "Cheers")]), "Cheers"
        )

    def test_snippet_expansion_works_with_punctuation_enabled(self):
        snippets = {"insert date": "2026-09-16"}
        self.assertEqual(
            text_tools.process_text(
                "insert date", snippets=snippets, spoken_punctuation=True
            ),
            "2026-09-16",
        )


class ParseSnippetsTests(unittest.TestCase):

    def test_dict(self):
        self.assertEqual(
            text_tools.parse_snippets({"A": "b"}), {"a": "b"}
        )

    def test_arrow_lines(self):
        self.assertEqual(
            text_tools.parse_snippets(["A => b", "c=>d"]), {"a": "b", "c": "d"}
        )

    def test_empty_and_broken_entries(self):
        self.assertEqual(text_tools.parse_snippets(None), {})
        self.assertEqual(text_tools.parse_snippets([]), {})
        self.assertEqual(text_tools.parse_snippets(["no arrow"]), {})
        self.assertEqual(text_tools.parse_snippets([("only-one",)]), {})

    def test_escape_sequences_expand_to_whitespace(self):
        self.assertEqual(
            text_tools.parse_snippets(["sig => a\\nb"]), {"sig": "a\nb"}
        )
        self.assertEqual(
            text_tools.parse_snippets(["sig => a\\tb"]), {"sig": "a\tb"}
        )


if __name__ == "__main__":
    unittest.main()
