"""Tests for history_store: reading, searching, editing, and tolerance.

Run: .venv/bin/python -m unittest discover -s tests -v
"""

import importlib.util
import json
import os
import sys
import tempfile
import threading
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import history_store  # noqa: E402


def write_lines(path, rows):
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def record(text, **kwargs):
    row = {
        "timestamp": kwargs.pop("timestamp", "2026-09-16T10:00:00+00:00"),
        "profile": kwargs.pop("profile", "EN"),
        "language": kwargs.pop("language", "en"),
        "model": kwargs.pop("model", "test-model"),
        "duration_seconds": kwargs.pop("duration_seconds", 2.5),
        "text": text,
    }
    row.update(kwargs)
    return row


class LoadTests(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "history.jsonl")

    def test_missing_file_is_empty(self):
        store = history_store.HistoryStore(self.path)
        self.assertEqual(store.load(), [])
        self.assertEqual(store.stats()["count"], 0)

    def test_loads_newest_first(self):
        write_lines(
            self.path,
            [record("first", timestamp="2026-09-16T10:00:00+00:00"),
             record("second", timestamp="2026-09-16T11:00:00+00:00")],
        )
        store = history_store.HistoryStore(self.path)
        texts = [r.text for r in store.load()]
        self.assertEqual(texts, ["second", "first"])

    def test_torn_trailing_line_is_skipped(self):
        write_lines(self.path, [record("good")])
        with open(self.path, "a", encoding="utf-8") as f:
            f.write('{"timestamp": "2026-09-16T12:00:00+00:00", "text": "trunca')
        store = history_store.HistoryStore(self.path)
        self.assertEqual([r.text for r in store.load()], ["good"])

    def test_unknown_and_missing_fields_are_tolerated(self):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write('{"text": "only text", "surprise": 1}\n')
            f.write('{"no": "text field"}\n')
            f.write("[]\n")
            f.write("\n")
        store = history_store.HistoryStore(self.path)
        records = store.load()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].text, "only text")
        self.assertEqual(records[0].duration, 0.0)

    def test_limit(self):
        write_lines(
            self.path,
            [record(f"line {i}", timestamp=f"2026-09-16T10:0{i}:00+00:00")
             for i in range(5)],
        )
        store = history_store.HistoryStore(self.path)
        self.assertEqual(len(store.load(limit=2)), 2)


class SearchTests(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "history.jsonl")
        write_lines(
            self.path,
            [
                record("Deploy the backend repository"),
                record("Backup performance is slow", profile="NORDIC"),
                record("unrelated words"),
            ],
        )
        self.store = history_store.HistoryStore(self.path)

    def test_substring_case_insensitive(self):
        hits = self.store.search("BACKEND")
        self.assertEqual([r.text for r in hits], ["Deploy the backend repository"])

    def test_matches_profile_field(self):
        hits = self.store.search("nordic")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].profile, "NORDIC")

    def test_empty_query_returns_everything(self):
        self.assertEqual(len(self.store.search("")), 3)

    def test_no_match(self):
        self.assertEqual(self.store.search("zzz"), [])


class EditTests(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "history.jsonl")
        write_lines(self.path, [record("keep"), record("drop")])
        self.store = history_store.HistoryStore(self.path)

    def test_delete_one_record(self):
        target = [r for r in self.store.load() if r.text == "drop"][0]
        self.assertEqual(self.store.delete(target), 1)
        self.assertEqual([r.text for r in self.store.load()], ["keep"])

    def test_delete_is_noop_for_unknown_record(self):
        ghost = history_store.HistoryRecord(
            timestamp="1999-01-01T00:00:00+00:00", text="ghost"
        )
        self.assertEqual(self.store.delete(ghost), 0)
        self.assertEqual(len(self.store.load()), 2)

    def test_clear_and_file_is_valid_jsonl(self):
        self.assertEqual(self.store.clear(), 2)
        self.assertEqual(self.store.load(), [])
        self.assertTrue(os.path.exists(self.path))
        with open(self.path, "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), "")

    def test_delete_where(self):
        removed = self.store.delete_where(lambda r: r.text == "keep")
        self.assertEqual(removed, 1)
        self.assertEqual([r.text for r in self.store.load()], ["drop"])

    def test_append_record_round_trip(self):
        history_store.append_record(
            self.path, "EN", "en", "model", "appended text", 1.25
        )
        newest = self.store.load()[0]
        self.assertEqual(newest.text, "appended text")
        self.assertEqual(newest.duration, 1.25)
        self.assertEqual(newest.profile, "EN")


class ExportTests(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "history.jsonl")
        write_lines(self.path, [record("hello world")])
        self.store = history_store.HistoryStore(self.path)

    def test_export_text_contains_transcription(self):
        self.assertIn("hello world", self.store.export_text())

    def test_export_markdown_has_heading(self):
        output = self.store.export_markdown()
        self.assertIn("# Whisper Dictate transcriptions", output)
        self.assertIn("hello world", output)


class StatsTests(unittest.TestCase):

    def test_counts_words_and_seconds(self):
        directory = tempfile.mkdtemp()
        path = os.path.join(directory, "history.jsonl")
        write_lines(
            path,
            [record("one two three"), record("four", duration_seconds=1.0)],
        )
        stats = history_store.HistoryStore(path).stats()
        self.assertEqual(stats["count"], 2)
        self.assertEqual(stats["words"], 4)
        self.assertAlmostEqual(stats["seconds"], 3.5)

    def test_human_duration(self):
        self.assertEqual(history_store.human_duration(45), "45s")
        self.assertEqual(history_store.human_duration(120), "2m")
        self.assertEqual(history_store.human_duration(7200), "2.0h")
        self.assertEqual(history_store.human_duration("nonsense"), "0s")


class PruneTests(unittest.TestCase):

    def test_prune_keeps_newest_when_file_is_large(self):
        directory = tempfile.mkdtemp()
        path = os.path.join(directory, "history.jsonl")
        write_lines(
            path,
            [record(f"line {i}", timestamp=f"2026-09-16T10:00:0{i % 10}+00:00")
             for i in range(30)],
        )
        removed = history_store.prune(path, keep=10, max_bytes=1)
        self.assertEqual(removed, 20)
        self.assertEqual(len(history_store.HistoryStore(path).load()), 10)

    def test_prune_small_file_is_noop(self):
        directory = tempfile.mkdtemp()
        path = os.path.join(directory, "history.jsonl")
        write_lines(path, [record("only")])
        self.assertEqual(history_store.prune(path, keep=1), 0)


class ConcurrencyTests(unittest.TestCase):
    """Pause after a snapshot and prove the writer actually meets a held lock.

    Events control ordering; nonblocking acquisition observes contention
    without timing assumptions or sleeps. Timeouts only prevent hung tests.
    """

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = os.path.join(directory.name, "history.jsonl")
        write_lines(self.path, [record("drop"), record("keep")])

    def test_stores_share_lock_for_equivalent_paths(self):
        first = history_store.HistoryStore(self.path)
        second = history_store.HistoryStore(os.path.relpath(self.path))
        self.assertIs(first._lock, second._lock)
        self.assertIsNot(first._lock, history_store.HistoryStore(self.path + "other")._lock)

    def _assert_append_survives(self, operation, expected, removed, append_action=None):
        snapshot_ready = threading.Event()
        resume_edit = threading.Event()
        writer_attempted = threading.Event()
        blocked = []
        errors = []
        results = []
        real_lock = history_store._lock_for(self.path)
        original_load = history_store.HistoryStore.load

        class ObservedLock:
            def __enter__(self):
                if threading.current_thread() is writer:
                    acquired = real_lock.acquire(blocking=False)
                    blocked.append(not acquired)
                    writer_attempted.set()
                    if not acquired:
                        real_lock.acquire()
                else:
                    real_lock.acquire()
                return self

            def __exit__(self, *args):
                real_lock.release()

        def paused_load(store, limit=None):
            rows = original_load(store, limit)
            if threading.current_thread() is editor:
                snapshot_ready.set()
                if not resume_edit.wait(5):
                    raise AssertionError("edit was not released")
            return rows

        def edit():
            try:
                results.append(operation(history_store.HistoryStore(self.path)))
            except BaseException as exc:
                errors.append(exc)

        def append():
            try:
                if append_action is None:
                    history_store.append_record(self.path, "EN", "en", "m", "new", 1.0)
                else:
                    append_action()
            except BaseException as exc:
                errors.append(exc)
            finally:
                # Also wake the test if a broken append bypasses the lock.
                writer_attempted.set()

        editor = threading.Thread(target=edit, daemon=True)
        writer = threading.Thread(target=append, daemon=True)
        with mock.patch.object(history_store, "_lock_for", return_value=ObservedLock()), \
                mock.patch.object(history_store.HistoryStore, "load", paused_load):
            editor.start()
            try:
                self.assertTrue(snapshot_ready.wait(5), "editor did not read snapshot")
                writer.start()
                self.assertTrue(writer_attempted.wait(5), "writer did not attempt append")
                self.assertEqual(blocked, [True], "append must wait for the whole edit")
            finally:
                resume_edit.set()
                editor.join(5)
                if writer.ident is not None:
                    writer.join(5)
            self.assertFalse(editor.is_alive())
            self.assertFalse(writer.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(results, [removed])
        self.assertEqual([r.text for r in history_store.HistoryStore(self.path).load()], expected)

    def test_concurrent_append_survives_delete(self):
        self._assert_append_survives(
            lambda store: store.delete_where(lambda row: row.text == "drop"),
            ["new", "keep"], 1,
        )

    def test_app_writer_shares_delete_lock(self):
        # Load the real listener without importing main's audio/UI dependencies.
        app = types.ModuleType("main")
        app.HISTORY_PATH = self.path
        app.cfg = {"history_enabled": True}
        app.log = mock.Mock()
        spec = importlib.util.spec_from_file_location(
            "history_listener_under_test",
            os.path.join(os.path.dirname(history_store.__file__), "enhanced_features.py"),
        )
        listener = importlib.util.module_from_spec(spec)
        with mock.patch.dict(sys.modules, {"main": app}):
            spec.loader.exec_module(listener)
        profile = types.SimpleNamespace(name="EN", language="en", model="m")
        self._assert_append_survives(
            lambda store: store.delete_where(lambda row: row.text == "drop"),
            ["new", "keep"], 1,
            append_action=lambda: listener.save_history(profile, "new", 1.0),
        )
        app.log.assert_not_called()

    def test_concurrent_append_survives_clear(self):
        self._assert_append_survives(lambda store: store.clear(), ["new"], 2)

    def test_concurrent_append_survives_prune(self):
        self._assert_append_survives(
            lambda store: history_store.prune(store.path, keep=1, max_bytes=1),
            ["new", "keep"], 1,
        )


class ExportEmptyTests(unittest.TestCase):
    """An explicit empty record list must not silently export everything."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "history.jsonl")
        write_lines(self.path, [record("hello world")])
        self.store = history_store.HistoryStore(self.path)

    def test_export_markdown_with_empty_list_is_empty_body(self):
        output = self.store.export_markdown(records=[])
        self.assertNotIn("hello world", output)

    def test_export_text_with_empty_list_is_empty(self):
        self.assertEqual(self.store.export_text(records=[]), "")

    def test_export_text_with_empty_query_still_exports_all(self):
        self.assertIn("hello world", self.store.export_text(query=""))


if __name__ == "__main__":
    unittest.main()
