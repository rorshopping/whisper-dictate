"""End-to-end release->text latency trace (main._log_latency).

The trace exists so every future perf change is measured against an observed
budget rather than a sum of microbenchmarks. These tests pin its semantics:
cumulative offsets from release, graceful degradation when a stage was never
reached, and an inject stamp on every exit path of type_text.
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


main = _import_main_for_test()


class FakeProfile:
    name = "EN"


class LatencyTraceTests(unittest.TestCase):
    def setUp(self):
        self.lines = []
        self._orig_log = main.log
        main.log = self.lines.append
        self.addCleanup(lambda: setattr(main, "log", self._orig_log))

    def _set_latency(self, **stamps):
        base = 1000.0
        main._LAT.clear()
        for i, key in enumerate(("press", "release", "finalize", "asr",
                                 "inject_start", "inject")):
            if key in stamps:
                main._LAT[key] = base + stamps[key]
        return main._LAT

    def test_full_path_reports_every_stage(self):
        self._set_latency(press=0.0, release=1.5, finalize=1.55, asr=1.56,
                          inject_start=1.56, inject=1.57)
        main._log_latency(FakeProfile())
        self.assertEqual(len(self.lines), 1)
        line = self.lines[0]
        self.assertIn("LATENCY [EN]", line)
        self.assertIn("release2typed 70ms", line)
        self.assertIn("drain 50ms", line)   # cumulative from release
        self.assertIn("asr 60ms", line)
        self.assertIn("inject 70ms", line)
        self.assertIn("hold 1500ms", line)

    def test_offsets_are_cumulative_from_release(self):
        # finalize 47.6 ms after release -> drain stage must read 48 ms, not 0.
        self._set_latency(release=100.0, finalize=100.0476, asr=100.06,
                          inject=100.067)
        main._log_latency(FakeProfile())
        self.assertIn("drain 48ms", self.lines[0])
        self.assertIn("asr 60ms", self.lines[0])
        self.assertIn("inject 67ms", self.lines[0])

    def test_command_mode_success_falls_back_to_asr_total(self):
        self._set_latency(release=5.0, asr=5.01)
        main._log_latency(FakeProfile())
        self.assertEqual(len(self.lines), 1)
        self.assertIn("release2typed 10ms", self.lines[0])
        self.assertIn("asr 10ms", self.lines[0])
        self.assertNotIn("inject", self.lines[0])

    def test_empty_trace_logs_nothing(self):
        main._LAT.clear()
        main._log_latency(FakeProfile())
        self.assertEqual(self.lines, [])

    def test_release_without_any_later_stage_logs_nothing(self):
        main._LAT.clear()
        main._LAT["release"] = 1.0
        main._log_latency(FakeProfile())
        self.assertEqual(self.lines, [])

    def test_zero_offset_inject_is_not_swallowed(self):
        # A falsy-coalescing bug would drop an inject stamp of exactly 0 ms.
        self._set_latency(release=10.0, asr=10.005, inject=10.0)
        main._log_latency(FakeProfile())
        self.assertIn("release2typed 0ms", self.lines[0])
        self.assertIn("inject 0ms", self.lines[0])


class TypeTextStampTests(unittest.TestCase):
    def setUp(self):
        self._orig_keystrokes = main._type_keystrokes
        self._orig_clip = main.pyperclip
        self._orig_cfg = main.cfg
        main._type_keystrokes = lambda text: None
        self.addCleanup(lambda: setattr(main, "_type_keystrokes", self._orig_keystrokes))
        self.addCleanup(lambda: setattr(main, "pyperclip", self._orig_clip))
        self.addCleanup(lambda: setattr(main, "cfg", self._orig_cfg))
        main.cfg = dict(main.cfg)
        main.cfg["type_newline"] = False

    def test_happy_path_stamps_inject(self):
        class GoodClip:
            def paste(self):
                return "OLD"

            def copy(self, text):
                pass

        main.pyperclip = GoodClip()
        main._LAT.clear()
        main._LAT["release"] = 1.0
        main._LAT["inject_start"] = None
        del main._LAT["inject_start"]
        main._LAT.pop("inject", None)
        main.type_text("hello")
        self.assertIn("inject", main._LAT)
        self.assertIn("inject_start", main._LAT)

    def test_clipboard_failure_path_still_stamps_inject(self):
        """The keystroke fallback used to return before any stamp was set."""
        class BadClip:
            def paste(self):
                return "OLD"

            def copy(self, text):
                raise OSError("clipboard locked")

        main.pyperclip = BadClip()
        main._LAT.clear()
        main._LAT["release"] = 1.0
        main._LAT.pop("inject", None)
        main.type_text("hello")
        self.assertIn("inject", main._LAT)


if __name__ == "__main__":
    unittest.main()
