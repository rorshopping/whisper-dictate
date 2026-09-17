"""Transcription history: read, search, delete, and stats.

The history file is the JSONL that ``enhanced_features`` appends to - one
object per line, written by the live dictation path. This module is the
read/query side plus a small amount of editing, so the UI (``desktop_ui`` and
the CLI) never has to parse the format itself.

Design notes:

* Reading is tolerant: a truncated final line (a crash mid-write, a disk that
  filled up) is skipped, not an error. Losing one record must never make the
  history window fail to open.
* All access to a given history file - appends from the dictation path,
  delete/clear/prune edits from the UI - shares one per-path re-entrant lock,
  so every read-modify-write is atomic within the process (the app runs as a
  single instance; no cross-process locking is attempted).
* Writes go through a temp file + atomic replace, and only when the record set
  actually changed, so a read-only or full disk cannot corrupt the history.
* Nothing here imports tkinter or the app: pure stdlib, importable from a
  packaged build's CLI, from the UI, and from tests.
"""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timezone

_MAX_BYTES = 5_000_000

# Keep locks for the lifetime of the process so existing stores and new
# writers always agree. RLock allows a transaction to call load/_write.
_PATH_LOCKS_GUARD = threading.Lock()
_PATH_LOCKS = {}


def _lock_for(path):
    key = os.path.normcase(os.path.abspath(path)) if path else ""
    with _PATH_LOCKS_GUARD:
        lock = _PATH_LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _PATH_LOCKS[key] = lock
        return lock


class HistoryRecord:
    """One dictation, as stored in the JSONL file."""

    __slots__ = ("timestamp", "profile", "language", "model", "duration", "text")

    def __init__(self, timestamp="", profile="", language="", model="", duration=0.0, text=""):
        self.timestamp = timestamp
        self.profile = profile
        self.language = language
        self.model = model
        self.duration = duration
        self.text = text

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict):
            return None
        text = data.get("text") or ""
        if not isinstance(text, str) or not text.strip():
            # Nothing was dictated, or the row is not one of ours: a history
            # entry with no text is noise in the browser.
            return None
        try:
            duration = float(data.get("duration_seconds") or 0.0)
        except (TypeError, ValueError):
            duration = 0.0
        return cls(
            timestamp=str(data.get("timestamp") or ""),
            profile=str(data.get("profile") or ""),
            language=str(data.get("language") or ""),
            model=str(data.get("model") or ""),
            duration=duration,
            text=text,
        )

    def to_dict(self):
        return {
            "timestamp": self.timestamp,
            "profile": self.profile,
            "language": self.language,
            "model": self.model,
            "duration_seconds": round(self.duration, 2),
            "text": self.text,
        }

    def when_text(self):
        """Human-readable local time, best effort."""
        raw = self.timestamp
        if not raw:
            return ""
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone().strftime("%Y-%m-%d %H:%M")
        except Exception:
            return raw

    def preview(self, width=90):
        flat = " ".join(self.text.split())
        return flat if len(flat) <= width else flat[: width - 1] + "\u2026"


class HistoryStore:
    """Reads the JSONL file on demand; the app owns appending.

    Every read-modify-write (delete, clear, prune) and the appends from
    ``append_record`` share one per-path lock, so a concurrent dictation
    append is never lost while the history window edits the file.
    """

    def __init__(self, path):
        self.path = path
        self._lock = _lock_for(path)

    # --- reading ----------------------------------------------------------

    def load(self, limit=None):
        """All records, newest first. Tolerates a torn final line."""
        records = []
        if not self.path or not os.path.exists(self.path):
            return records
        try:
            with self._lock:
                with open(self.path, "r", encoding="utf-8", errors="replace") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            data = json.loads(line)
                        except ValueError:
                            continue  # torn line from a crash mid-write
                        record = HistoryRecord.from_dict(data)
                        if record is not None:
                            records.append(record)
        except OSError:
            return records
        records.reverse()
        if limit is not None:
            return records[:limit]
        return records

    def search(self, query, limit=None):
        """Case-insensitive substring search over the transcriptions."""
        records = self.load()
        needle = (query or "").strip().casefold()
        if not needle:
            if limit is not None:
                return records[:limit]
            return records

        def matches(record):
            haystacks = (record.text, record.profile, record.language, record.when_text())
            return any(needle in (field or "").casefold() for field in haystacks)

        hits = [r for r in records if matches(r)]
        if limit is not None:
            return hits[:limit]
        return hits

    def stats(self):
        """Totals for the history window header."""
        records = self.load()
        words = 0
        seconds = 0.0
        for record in records:
            words += len(record.text.split())
            seconds += record.duration or 0.0
        return {
            "count": len(records),
            "words": words,
            "seconds": seconds,
            "session": records[0].when_text() if records else "",
        }

    # --- editing ----------------------------------------------------------

    def delete(self, record):
        """Remove one record (matched by identity of its stored fields)."""
        target = record.to_dict()
        return self.delete_where(lambda r: r.to_dict() == target)

    def delete_where(self, predicate):
        """Drop every record the predicate accepts. Returns how many went.

        The whole read-filter-write cycle holds the per-path lock, so an
        append that lands mid-delete is either fully included in the rewrite
        or fully applied after it - never dropped.
        """
        with self._lock:
            keep = []
            removed = 0
            for record in self.load():
                if predicate(record):
                    removed += 1
                else:
                    keep.append(record)
            if not removed:
                return 0
            # Written back oldest-first, the order the app appends in.
            keep.reverse()
            self._write([r.to_dict() for r in keep])
            return removed

    def clear(self):
        with self._lock:
            records = self.load()
            if not records:
                return 0
            self._write([])
            return len(records)

    def _write(self, rows):
        if not self.path:
            return
        directory = os.path.dirname(self.path) or "."
        try:
            os.makedirs(directory, exist_ok=True)
        except OSError:
            pass
        temp = f"{self.path}.tmp"
        with self._lock:
            with open(temp, "w", encoding="utf-8") as f:
                for row in rows:
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")
            os.replace(temp, self.path)

    # --- exporting --------------------------------------------------------

    def export_text(self, records=None, query=None):
        if query is not None:
            rows = self.search(query)
        else:
            rows = self.load() if records is None else records
        blocks = []
        for record in rows:
            header = " - ".join(
                part for part in (record.when_text(), record.profile) if part
            )
            blocks.append(f"# {header}\n{record.text}" if header else record.text)
        return "\n\n".join(blocks)

    def export_markdown(self, records=None):
        rows = records if records is not None else self.load()
        lines = ["# Whisper Dictate transcriptions", ""]
        for record in rows:
            when = record.when_text()
            meta = " \u00b7 ".join(p for p in (when, record.profile) if p)
            lines.append(f"## {meta}" if meta else "##")
            lines.append("")
            lines.append(record.text)
            lines.append("")
        return "\n".join(lines)


def append_record(path, profile_name, language, model, text, duration_s):
    """Append one dictation. Shared by the app and any future CLI capture."""
    record = HistoryRecord(
        timestamp=datetime.now(timezone.utc).isoformat(),
        profile=profile_name,
        language=language,
        model=model,
        duration=float(duration_s or 0.0),
        text=text,
    )
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
    except OSError:
        pass
    # Hold the same per-path lock the readers/editors use: an append either
    # happens entirely before a delete/clear/prune rewrite or entirely after
    # it, never in between (which would lose the record).
    with _lock_for(path):
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record.to_dict(), ensure_ascii=False) + "\n")
    return record


def prune(path, keep=5000, max_bytes=_MAX_BYTES):
    """Bound the file: keep the newest ``keep`` records when it grows past size.

    The whole size-check, read, and rewrite holds the per-path lock, so
    records appended while pruning are kept.
    """
    if not path:
        return 0
    store = HistoryStore(path)
    with store._lock:
        try:
            if os.path.getsize(path) < max_bytes:
                return 0
        except OSError:
            return 0
        records = store.load()
        if len(records) <= keep:
            return 0
        trimmed = records[:keep]
        trimmed.reverse()
        store._write([r.to_dict() for r in trimmed])
        return len(records) - keep


def human_duration(seconds):
    try:
        seconds = float(seconds)
    except (TypeError, ValueError):
        return "0s"
    if seconds < 60:
        return f"{seconds:.0f}s"
    minutes = seconds / 60.0
    if minutes < 60:
        return f"{minutes:.0f}m"
    return f"{minutes / 60.0:.1f}h"


def human_age(timestamp):
    """'3 min ago' style string for a record timestamp."""
    if not timestamp:
        return ""
    try:
        parsed = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        seconds = time.time() - parsed.timestamp()
    except Exception:
        return ""
    if seconds < 0:
        return "just now"
    if seconds < 90:
        return "just now"
    if seconds < 3600:
        return f"{seconds / 60.0:.0f} min ago"
    if seconds < 86400:
        return f"{seconds / 3600.0:.0f} h ago"
    return f"{seconds / 86400.0:.0f} d ago"
