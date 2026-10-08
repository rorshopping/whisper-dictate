"""apply_corrections: compiled-cache output must equal the old per-call build.

The optimized path pre-compiles regexes once per profile; the old path rebuilt
them inside a re.sub() per pair per utterance. These tests pin that the two
produce byte-identical results, including the case-preservation branch, so
"cached" cannot silently mean "different".
"""
import unittest

def _import_main_for_test():
    """Import main under --doctor so the single-instance mutex is skipped."""
    import sys

    argv = list(sys.argv)
    if "--doctor" not in argv:
        sys.argv.append("--doctor")
    try:
        import main
    finally:
        sys.argv = argv
    return main


main_mod = _import_main_for_test()
m = main_mod


class CorrectionCompileTests(unittest.TestCase):
    def setUp(self):
        self.lines = []
        self._orig_log = m.log
        m.log = self.lines.append
        self.addCleanup(lambda: setattr(m, "log", self._orig_log))

    def test_compiled_equals_percall_reference(self):
        pairs = [
            ("llama cpp", "llama.cpp"),
            ("github", "GitHub"),
            ("ca nt", "can't"),
            ("postgress", "postgres"),
            ("sub agents", "subagents"),
        ]
        text = "I use llama cpp and github, and I ca nt spell postgress. " \
               "The sub agents fight."
        expected = m._compile_corrections(pairs)  # reference build
        got = m.apply_corrections(text, m._compile_corrections(pairs))
        self.assertEqual(got, m.apply_corrections(text, expected))

    def test_raw_pair_list_still_supported(self):
        # Embedders/tests that hold raw (wrong, correct) pairs keep working.
        pairs = [("github", "GitHub")]
        self.assertEqual(
            m.apply_corrections("push to github", pairs), "push to GitHub"
        )

    def test_case_preserved_from_sentence_start(self):
        compiled = m._compile_corrections([("llama cpp", "llama.cpp")])
        self.assertEqual(
            m.apply_corrections("Llama cpp is fast", compiled),
            "Llama.cpp is fast",
        )
        self.assertEqual(
            m.apply_corrections("llama cpp is fast", compiled),
            "llama.cpp is fast",
        )

    def test_each_pair_gets_its_own_replacement(self):
        # Late-binding closure bug guard: every pair must close over its own
        # `correct`, not the last one in the loop.
        compiled = m._compile_corrections([
            ("one", "1"), ("two", "2"), ("three", "3"),
        ])
        self.assertEqual(
            m.apply_corrections("one two three", compiled), "1 2 3"
        )

    def test_word_boundary_only(self):
        compiled = m._compile_corrections([("the", "a")])
        self.assertEqual(
            m.apply_corrections("the theatre theme", compiled), "a theatre theme"
        )

    def test_empty_pairs_is_identity(self):
        self.assertEqual(m.apply_corrections("hello", ()), "hello")
        self.assertEqual(m.apply_corrections("hello", None), "hello")

    def test_longest_first_ordering_respected(self):
        # load_corrections sorts longest-first, so the longer phrase must win
        # over its substring when both match.
        pairs = [("postgres database", "PostgreSQL"),
                 ("database", "DB")]
        pairs.sort(key=lambda p: len(p[0]), reverse=True)
        compiled = m._compile_corrections(pairs)
        self.assertEqual(
            m.apply_corrections("connect to postgres database", compiled),
            "connect to PostgreSQL",
        )


if __name__ == "__main__":
    unittest.main()
