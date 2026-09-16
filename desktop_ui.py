"""Tk windows for history and settings.

Both windows are created *on the main thread*: Tk is not thread-safe, and the
global hotkey that opens history fires on pynput's listener thread. The app
therefore calls :func:`open_history_window` / :func:`open_settings_window`
through ``root.after(0, ...)`` - these functions never start their own threads
and never talk to the audio pipeline.

Scope, deliberately: this replaces "open the JSONL in a text editor" with a
usable window and makes the important config keys editable without hand-editing
JSON. It is not a full settings application - hotkey strings, devices, and the
text files are all reachable, and everything else stays in ``config.json``.

Colours follow the status pill's dark palette so the windows do not look like a
different product.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tkinter as tk
from tkinter import messagebox

import history_store

BG = "#1e1e28"
PANEL = "#26263a"
FIELD = "#15151f"
FG = "#f2f2f7"
MUTED = "#9a9ab0"
ACCENT = "#4dd07f"
DANGER = "#ff5555"
FONT = ("Segoe UI", 10)
FONT_BOLD = ("Segoe UI", 10, "bold")
FONT_MONO = ("Menlo", 11) if sys.platform == "darwin" else ("Consolas", 10)

# One window per kind, so a second hotkey press raises the open window instead
# of stacking duplicates.
_windows = {}


def _present(kind, build):
    """Raise the existing window for ``kind`` or build a new one."""
    existing = _windows.get(kind)
    if existing is not None:
        try:
            if existing.winfo_exists():
                existing.deiconify()
                existing.lift()
                existing.focus_force()
                return existing
        except Exception:
            pass
    window = build()
    _windows[kind] = window
    return window


def _style_window(window, title, size):
    window.title(title)
    window.configure(bg=BG)
    window.geometry(size)
    window.minsize(420, 300)


def _button(parent, text, command, bg=PANEL, fg=FG):
    return tk.Button(
        parent,
        text=text,
        command=command,
        bg=bg,
        fg=fg,
        activebackground=FIELD,
        activeforeground=FG,
        relief="flat",
        bd=0,
        highlightthickness=0,
        padx=10,
        pady=4,
        cursor="hand2",
        font=FONT,
    )


def _label(parent, text, muted=False, bold=False):
    return tk.Label(
        parent,
        text=text,
        bg=BG,
        fg=MUTED if muted else FG,
        font=FONT_BOLD if bold else FONT,
        anchor="w",
        justify="left",
    )


def _open_in_editor(path):
    try:
        if sys.platform == "win32":
            os.startfile(path)  # noqa: S606 - the user's own file
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
    except Exception:
        pass


# --- history ------------------------------------------------------------------


def open_history_window(root, history_path, on_paste=None, on_copy=None):
    """Browse, search, re-paste, and delete past transcriptions."""

    def build():
        store = history_store.HistoryStore(history_path)
        window = tk.Toplevel(root)
        _style_window(window, "Transcription history", "760x560")

        header = tk.Frame(window, bg=BG)
        header.pack(fill="x", padx=12, pady=(12, 6))
        _label(header, "History", bold=True).pack(side="left")
        stats = _label(header, "", muted=True)
        stats.pack(side="left", padx=(10, 0))

        search_row = tk.Frame(window, bg=BG)
        search_row.pack(fill="x", padx=12, pady=(0, 8))
        query = tk.StringVar()
        entry = tk.Entry(
            search_row,
            textvariable=query,
            bg=FIELD,
            fg=FG,
            insertbackground=FG,
            relief="flat",
            font=FONT,
        )
        entry.pack(side="left", fill="x", expand=True, ipady=5)

        body = tk.Frame(window, bg=BG)
        body.pack(fill="both", expand=True, padx=12, pady=(0, 8))

        listbox = tk.Listbox(
            body,
            bg=PANEL,
            fg=FG,
            selectbackground="#3d3d54",
            selectforeground=FG,
            relief="flat",
            highlightthickness=0,
            font=FONT,
            activestyle="none",
        )
        scroll = tk.Scrollbar(body, command=listbox.yview)
        listbox.configure(yscrollcommand=scroll.set)
        listbox.pack(side="left", fill="both", expand=False, ipadx=4)
        listbox.configure(width=38)
        scroll.pack(side="left", fill="y")

        detail_frame = tk.Frame(body, bg=BG)
        detail_frame.pack(side="left", fill="both", expand=True, padx=(10, 0))
        detail = tk.Text(
            detail_frame,
            bg=FIELD,
            fg=FG,
            insertbackground=FG,
            relief="flat",
            wrap="word",
            font=FONT_MONO,
            padx=8,
            pady=8,
            height=10,
        )
        detail.pack(fill="both", expand=True)

        actions = tk.Frame(window, bg=BG)
        actions.pack(fill="x", padx=12, pady=(0, 12))

        state = {"records": []}

        def current_record():
            selection = listbox.curselection()
            if not selection:
                return None
            index = selection[0]
            if 0 <= index < len(state["records"]):
                return state["records"][index]
            return None

        def render_detail(*_args):
            record = current_record()
            detail.configure(state="normal")
            detail.delete("1.0", "end")
            if record is not None:
                meta = " \u00b7 ".join(
                    part
                    for part in (
                        record.when_text(),
                        record.profile,
                        history_store.human_duration(record.duration),
                    )
                    if part
                )
                detail.insert("end", meta + "\n\n")
                detail.insert("end", record.text)
            detail.configure(state="disabled")

        def refresh(*_args):
            records = store.search(query.get())
            state["records"] = records
            listbox.delete(0, "end")
            for record in records:
                stamp = record.when_text() or "?"
                age = history_store.human_age(record.timestamp)
                label = f"{stamp}  {record.profile or ''}".rstrip()
                listbox.insert("end", f"{label}   {record.preview(52)}   {age}".rstrip())
            if records:
                listbox.selection_set(0)
            render_detail()
            summary = store.stats()
            stats.configure(
                text=(
                    f"{summary['count']} dictations \u00b7 {summary['words']} words "
                    f"\u00b7 {history_store.human_duration(summary['seconds'])} spoken"
                )
            )

        def copy_selected():
            record = current_record()
            if record is None:
                return
            try:
                window.clipboard_clear()
                window.clipboard_append(record.text)
                if on_copy is not None:
                    on_copy(record.text)
            except Exception:
                pass

        def paste_selected():
            record = current_record()
            if record is None:
                return
            if on_paste is None:
                copy_selected()
                return
            try:
                window.withdraw()
                on_paste(record.text)
            except Exception:
                pass
            finally:
                window.after(300, window.deiconify)

        def delete_selected():
            record = current_record()
            if record is None:
                return
            if not messagebox.askyesno(
                "Delete transcription",
                "Delete this transcription from the history file?",
                parent=window,
            ):
                return
            store.delete(record)
            refresh()

        def clear_all():
            if not messagebox.askyesno(
                "Clear history",
                "Delete every transcription in the history file?\n"
                "This cannot be undone.",
                parent=window,
            ):
                return
            store.clear()
            refresh()

        def export_markdown():
            target = os.path.join(os.path.dirname(history_path), "transcription-history.md")
            try:
                with open(target, "w", encoding="utf-8") as f:
                    f.write(store.export_markdown())
                _open_in_editor(target)
            except Exception as exc:
                messagebox.showerror("Export failed", str(exc), parent=window)

        listbox.bind("<<ListboxSelect>>", render_detail)
        listbox.bind("<Double-Button-1>", lambda _e: paste_selected())
        query.trace_add("write", refresh)
        entry.bind("<Escape>", lambda _e: query.set(""))
        window.bind("<Escape>", lambda _e: window.destroy())
        window.bind("<Command-a>" if sys.platform == "darwin" else "<Control-a>", lambda _e: None)

        _button(actions, "Copy", copy_selected).pack(side="left")
        _button(actions, "Paste at cursor", paste_selected).pack(side="left", padx=6)
        _button(actions, "Delete", delete_selected, bg="#3a2030", fg=FG).pack(side="left")
        _button(actions, "Export .md", export_markdown).pack(side="right")
        _button(actions, "Clear all", clear_all, bg="#3a2030", fg=DANGER).pack(
            side="right", padx=6
        )
        _button(actions, "Open file", lambda: _open_in_editor(history_path)).pack(
            side="right"
        )

        refresh()
        entry.focus_set()
        return window

    return _present("history", build)


# --- settings -----------------------------------------------------------------


def _hotkey_to_text(keys):
    return "+".join(str(k) for k in (keys or []))


def _text_to_hotkey(text):
    parts = [p.strip().lower() for p in (text or "").replace(" ", "+").split("+")]
    return [p for p in parts if p]


def open_settings_window(root, config_path, on_saved=None, on_reload_hotwords=None):
    """Edit the config keys that matter, plus open the text files."""

    def build():
        import json

        window = tk.Toplevel(root)
        _style_window(window, "Whisper Dictate settings", "620x640")

        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)

        header = tk.Frame(window, bg=BG)
        header.pack(fill="x", padx=14, pady=(12, 4))
        _label(header, "Settings", bold=True).pack(side="left")
        _label(header, f"  {config_path}", muted=True).pack(side="left")

        canvas_frame = tk.Frame(window, bg=BG)
        canvas_frame.pack(fill="both", expand=True, padx=14, pady=6)

        def section(title):
            box = tk.LabelFrame(
                canvas_frame,
                text=title,
                bg=BG,
                fg=MUTED,
                font=FONT,
                bd=1,
                relief="groove",
                labelanchor="nw",
            )
            box.pack(fill="x", pady=(0, 10), ipady=6)
            return box

        def row(parent, label):
            line = tk.Frame(parent, bg=BG)
            line.pack(fill="x", padx=8, pady=3)
            _label(line, label).pack(side="left")
            return line

        def entry_for(parent, label, value):
            line = row(parent, label)
            variable = tk.StringVar(value="" if value is None else str(value))
            field = tk.Entry(
                line,
                textvariable=variable,
                bg=FIELD,
                fg=FG,
                insertbackground=FG,
                relief="flat",
                font=FONT,
                width=28,
            )
            field.pack(side="right", ipady=3)
            return variable

        def check_for(parent, label, value):
            line = row(parent, label)
            variable = tk.BooleanVar(value=bool(value))
            tk.Checkbutton(
                line,
                variable=variable,
                bg=BG,
                fg=FG,
                activebackground=BG,
                activeforeground=FG,
                selectcolor=FIELD,
                highlightthickness=0,
                bd=0,
            ).pack(side="right")
            return variable

        # --- general
        general = section("General")
        device = entry_for(general, "Device (auto / cpu / cuda / mps)", config.get("device", "auto"))
        sound = check_for(general, "Sound feedback", config.get("sound", True))
        newline = check_for(general, "Trailing newline after dictation", config.get("type_newline", True))
        latency = entry_for(general, "Capture buffer (seconds)", config.get("capture_latency_s", 1.0))
        idle = entry_for(general, "Unload models after (minutes)", config.get("model_idle_unload_minutes", 10))

        # --- text processing
        text_box = section("Text (applies to every profile)")
        fuzzy = check_for(text_box, "Fuzzy hotword matching", config.get("fuzzy_hotwords", True))
        fuzzy_score = entry_for(text_box, "Fuzzy minimum score (0-100)", config.get("fuzzy_hotword_min_score", 85))
        spoken = check_for(text_box, 'Spoken punctuation ("comma", "new line")', config.get("spoken_punctuation", False))
        snippets_on = check_for(text_box, "Voice snippets", config.get("snippets_enabled", True))

        # --- profiles
        profiles = config.get("profiles") or []
        profile_vars = []
        for index, profile in enumerate(profiles):
            box = section(f"Profile {index + 1}: {profile.get('name', '?')}")
            profile_vars.append(
                {
                    "name": entry_for(box, "Name", profile.get("name", "")),
                    "hotkey": entry_for(
                        box, "Hotkey (ctrl+shift+space)", _hotkey_to_text(profile.get("hotkey"))
                    ),
                    "language": entry_for(box, "Language", profile.get("language", "")),
                }
            )
            _label(
                box,
                f"    model: {profile.get('model', '')}",
                muted=True,
            ).pack(fill="x", padx=8)

        # --- files
        files = section("Files")
        files_row = tk.Frame(files, bg=BG)
        files_row.pack(fill="x", padx=8, pady=4)

        data_dir = os.path.dirname(config_path)

        def open_file(name):
            _open_in_editor(os.path.join(data_dir, name))

        _button(files_row, "config.json", lambda: _open_in_editor(config_path)).pack(side="left")
        for name in ("hotwords-en.txt", "hotwords-de.txt", "corrections-en.txt", "snippets-en.txt"):
            _button(files_row, name, lambda n=name: open_file(n)).pack(side="left", padx=4)
        if on_reload_hotwords is not None:
            _button(files_row, "Reload hotwords", on_reload_hotwords).pack(side="left", padx=4)

        status = _label(window, "", muted=True)

        def save():
            def as_int(value, fallback):
                try:
                    return int(float(str(value).strip()))
                except (TypeError, ValueError):
                    return fallback

            def as_float(value, fallback):
                try:
                    return float(str(value).strip())
                except (TypeError, ValueError):
                    return fallback

            config["device"] = device.get().strip() or "auto"
            config["sound"] = bool(sound.get())
            config["type_newline"] = bool(newline.get())
            config["capture_latency_s"] = as_float(latency.get(), config.get("capture_latency_s", 1.0))
            config["model_idle_unload_minutes"] = as_int(idle.get(), config.get("model_idle_unload_minutes", 10))
            config["fuzzy_hotwords"] = bool(fuzzy.get())
            config["fuzzy_hotword_min_score"] = as_int(fuzzy_score.get(), config.get("fuzzy_hotword_min_score", 85))
            config["spoken_punctuation"] = bool(spoken.get())
            config["snippets_enabled"] = bool(snippets_on.get())

            for profile, variables in zip(profiles, profile_vars):
                name = variables["name"].get().strip()
                if name:
                    profile["name"] = name
                hotkey = _text_to_hotkey(variables["hotkey"].get())
                if hotkey:
                    profile["hotkey"] = hotkey
                language = variables["language"].get().strip()
                if language:
                    profile["language"] = language

            try:
                with open(config_path, "w", encoding="utf-8") as f:
                    json.dump(config, f, indent=2, ensure_ascii=False)
                    f.write("\n")
            except Exception as exc:
                messagebox.showerror("Could not save settings", str(exc), parent=window)
                return
            status.configure(
                text="Saved. Restart Whisper Dictate for device, hotkey and language changes.",
                fg=ACCENT,
            )
            if on_saved is not None:
                try:
                    on_saved()
                except Exception:
                    pass

        buttons = tk.Frame(window, bg=BG)
        buttons.pack(fill="x", padx=14, pady=(0, 6))
        _button(buttons, "Save", save, bg="#24402f", fg=ACCENT).pack(side="right")
        _button(buttons, "Close", window.destroy).pack(side="right", padx=6)
        status.pack(fill="x", padx=14, pady=(0, 12))
        return window

    return _present("settings", build)
