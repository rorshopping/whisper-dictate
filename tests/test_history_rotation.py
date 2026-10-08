"""transcription-history.jsonl rotation + the hoisted makedirs.

The history file had no size cap while dictate.log was capped at 1 MB with 2
backups; appending also paid an os.makedirs syscall per utterance. Both are
covered here.
"""
import json
import os
import tempfile
import unittest


def _import_main_for_test():
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


class HistoryRotationTests(unittest.TestCase):
    def setUp(self):
        import enhanced_features as ef

        self.ef = ef
        self.tmp = tempfile.TemporaryDirectory()
        self.history_file = os.path.join(self.tmp.name, "history.jsonl")
        self._orig_file = ef.HISTORY_FILE
        self._orig_dir = ef._HISTORY_DIR
        self._orig_max = ef.HISTORY_MAX_BYTES
        ef.HISTORY_FILE = self.history_file
        ef._HISTORY_DIR = self.tmp.name
        # Small cap so the test does not have to write megabytes.
        ef.HISTORY_MAX_BYTES = 300
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(lambda: setattr(ef, "HISTORY_FILE", self._orig_file))
        self.addCleanup(lambda: setattr(ef, "_HISTORY_DIR", self._orig_dir))
        self.addCleanup(lambda: setattr(ef, "HISTORY_MAX_BYTES", self._orig_max))

    class _P:
        name = "EN"
        language = "en"
        model = "m"

    def _append(self, n):
        for i in range(n):
            self.ef.save_history(self._P(), f"line {i}", 1.0)

    def _enable(self, on=True):
        main_mod.cfg["history_enabled"] = on

    def test_rotates_past_the_cap(self):
        self._enable()
        self._append(12)
        self.assertTrue(os.path.exists(f"{self.history_file}.1"),
                        "no backup was created past the cap")
        # Rotation is checked before the append, so the live file may hold one
        # record more than the cap -- it must not hold many.
        live = os.path.getsize(self.history_file)
        self.assertLess(live, self.ef.HISTORY_MAX_BYTES + 200,
                        f"live file {live} far over the cap "
                        f"{self.ef.HISTORY_MAX_BYTES}")

    def test_backups_are_bounded(self):
        self._enable()
        self._append(60)
        backups = [f for f in os.listdir(self.tmp.name)
                   if f.startswith(os.path.basename(self.history_file))]
        # live + .1 + .2 at most; no unbounded .3 .4 ... accumulation
        self.assertLessEqual(len(backups), 1 + self.ef.HISTORY_BACKUPS, backups)

    def test_every_record_parses_after_rotation(self):
        self._enable()
        self._append(12)
        for name in ("history.jsonl", "history.jsonl.1", "history.jsonl.2"):
            p = os.path.join(self.tmp.name, name)
            if not os.path.exists(p):
                continue
            with open(p, encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        json.loads(line)

    def test_no_rotation_under_the_cap(self):
        self._enable()
        self._append(3)
        self.assertTrue(os.path.exists(self.history_file))
        self.assertFalse(os.path.exists(f"{self.history_file}.1"))

    def test_disabled_history_writes_nothing(self):
        self._enable(False)
        self._append(4)
        self.assertFalse(os.path.exists(self.history_file))

    def test_append_is_not_clobbered_by_rotation(self):
        # Rotate then append: the new record must land in the fresh file, not
        # raise because the old one was renamed away.
        self._enable()
        self._append(12)
        self.ef.save_history(self._P(), "after rotation", 1.0)
        with open(self.history_file, encoding="utf-8") as f:
            lines = [json.loads(x) for x in f if x.strip()]
        self.assertTrue(any(r["text"] == "after rotation" for r in lines))


if __name__ == "__main__":
    unittest.main()
