"""Tests for history_store: reading, searching, editing, and tolerance.

Run: .venv/bin/python -m unittest discover -s tests -v
"""

import json
import os
import sys
import tempfile
import unittest

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


if __name__ == "__main__":
    unittest.main()
