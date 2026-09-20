"""Changeable keyboard shortcuts - a Tk dialog plus pure helpers.

Reachable from the tray menu ("Hotkeys…"). Rows show every configurable
shortcut; "Change" captures the next key combination typed in the dialog;
saving live-rebinds the running app (via the apply callback) and persists
the new combos to config.json.

Capture runs at the Tk level (no second pynput listener): the capture
Toplevel takes keyboard focus, tracks held modifiers, and takes the first
non-modifier key as the final key of the combination.

The pure helpers (keysym mapping, combo formatting, conflict detection,
config transformation) are unit-tested in tests/test_hotkey_settings.py.
"""

import re
import tkinter as tk

_MODIFIER_ALIASES = {"control_l": "ctrl", "control_r": "ctrl", "control": "ctrl",
                     "shift_l": "shift", "shift_r": "shift", "shift": "shift",
                     "alt_l": "alt", "alt_r": "alt", "alt": "alt"}
_FINAL_ALIASES = {"escape": "escape", "return": "enter", "enter": "enter",
                  "backspace": "backspace", "tab": "tab", "space": "space",
                  "caps_lock": "capslock", "delete": "delete"}
_MODIFIERS = ("ctrl", "shift", "alt")
DISPLAY = {"ctrl": "Ctrl", "shift": "Shift", "alt": "Alt", "space": "Space",
           "enter": "Enter", "tab": "Tab", "escape": "Esc",
           "backspace": "Backspace", "delete": "Del", "capslock": "CapsLock"}


def keysym_to_name(keysym):
    """Map a Tk keysym to the app's key-name vocabulary (pynput-compatible)."""
    s = str(keysym).lower()
    if s in _MODIFIER_ALIASES:
        return _MODIFIER_ALIASES[s]
    if s in _FINAL_ALIASES:
        return _FINAL_ALIASES[s]
    if re.fullmatch(r"f[1-9]|f1[0-9]|f2[0-4]", s):
        return s
    if len(s) == 1:
        return s
    return None


def format_combo(combo):
    """['ctrl', 'shift', 'space'] -> 'Ctrl+Shift+Space'."""
    return "+".join(DISPLAY.get(k, k.upper() if len(k) == 1 else k.title())
                    for k in combo)


def combo_key(combo):
    return tuple(sorted(set(combo or [])))


def find_conflict(combo, others):
    """Return the label of the first entry in `others` with the same combo."""
    for label, other in others:
        if other and combo_key(combo) == combo_key(other):
            return label
    return None


def is_valid_combo(combo):
    """A combo needs at least one non-modifier key."""
    return bool(combo) and combo[-1] not in _MODIFIERS


def apply_changes_to_config(data, changes):
    """Pure: update a config dict with {row_id: combo}; returns a new dict.

    Row ids: 'profile:<index>' (dict under data['profiles'][idx]) and
    'paste_last' | 'scratch' | 'command' | 'history' (config keys
    'paste_last_hotkey', 'scratch_hotkey', 'command_hotkey',
    'history_hotkey').
    """
    data = dict(data)
    profiles = [dict(p) for p in (data.get("profiles") or [])]
    for row_id, combo in changes.items():
        combo = list(combo)
        if row_id.startswith("profile:"):
            idx = int(row_id.split(":", 1)[1])
            if 0 <= idx < len(profiles):
                profiles[idx]["hotkey"] = combo
        else:
            data[row_id + "_hotkey"] = combo
    if profiles:
        data["profiles"] = profiles
    return data


def open_dialog(root, rows, on_save):
    """Show the hotkeys dialog (call on the Tk main thread).

    rows: list of (label, current_combo, row_id). on_save receives
    {row_id: combo} for the changed rows only; raise to show an error.
    """
    state = {"changes": {}, "capturing": None, "held": set()}

    win = tk.Toplevel(root)
    win.title("Whisper Dictate — Keyboard shortcuts")
    win.resizable(False, False)
    win.transient(root)
    frm = tk.Frame(win, padx=16, pady=12)
    frm.pack()
    tk.Label(frm, text="Click Change, then press the new key combination.",
             fg="#666666").pack(anchor="w", pady=(0, 8))

    status = tk.Label(frm, text="", fg="#b45309", wraplength=360,
                      justify="left")
    status.pack(anchor="w", pady=(0, 4))
    buttons = {}

    def cancel_capture(event=None):
        if state["capturing"] is None:
            return
        row_id = state["capturing"]
        state["capturing"] = None
        state["held"] = set()
        for _label, get, _set, rid in row_specs:
            if rid == row_id:
                buttons[row_id].config(text=format_combo(get()))
        try:
            win.unbind("<KeyPress>")
        except Exception:
            pass
        status.config(text="")

    def begin_capture(row_id):
        cancel_capture()
        state["capturing"] = row_id
        buttons[row_id].config(text="press keys…")
        status.config(text="Press the new combination (needs a non-modifier "
                           "key). Esc cancels.")
        win.bind("<KeyPress>", on_key)
        win.bind("<Escape>", cancel_capture)

    def on_key(event):
        row_id = state["capturing"]
        if row_id is None:
            return
        if str(event.keysym).lower() == "escape":
            return  # the <Escape> binding cancels the capture
        name = keysym_to_name(event.keysym)
        if name is None:
            return
        held = state["held"]
        if name in _MODIFIERS:
            held.add(name)
            buttons[row_id].config(text=format_combo(sorted(held)) + " + …")
            return
        combo = sorted(held) + [name]
        others = [(get() and label, get()) for label, get, _s, rid in row_specs
                  if rid != row_id]
        clash = find_conflict(combo, others)
        if clash:
            status.config(text=f"Already used by: {clash}", fg="#b91c1c")
            return
        if not is_valid_combo(combo):
            status.config(text="Add a non-modifier key (a letter, F-key, "
                               "Space…).", fg="#b91c1c")
            return
        for label, get, set_, rid in row_specs:
            if rid == row_id:
                set_(combo)
        state["changes"][row_id] = combo
        buttons[row_id].config(text=format_combo(combo))
        state["capturing"] = None
        state["held"] = set()
        win.unbind("<KeyPress>")
        status.config(text="")

    def on_key_release(event):
        name = keysym_to_name(event.keysym)
        if name in _MODIFIERS:
            state["held"].discard(name)

    row_specs = []

    def make_row(label, combo, row_id):
        row = tk.Frame(frm)
        row.pack(fill="x", pady=3)
        tk.Label(row, text=label + ":", width=22, anchor="w").pack(side="left")
        holder = {"combo": list(combo)}

        def get():
            return holder["combo"]

        def set_(value):
            holder["combo"] = list(value)

        btn = tk.Button(row, text=format_combo(combo), width=22,
                        command=lambda: begin_capture(row_id))
        btn.pack(side="left")
        buttons[row_id] = btn
        row_specs.append((label, get, set_, row_id))

    for label, combo, row_id in rows:
        make_row(label, combo, row_id)

    def save():
        cancel_capture()
        try:
            on_save(state["changes"])
        except Exception as exc:
            status.config(text=f"Could not save: {exc}", fg="#b91c1c")
            return
        win.destroy()

    tk.Button(frm, text="Save", command=save).pack(anchor="e", pady=(8, 0))
    tk.Label(frm, text="Changes apply immediately and are saved to "
                       "config.json.", fg="#888888").pack(anchor="w",
                                                          pady=(4, 0))

    win.update_idletasks()
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    win.geometry(f"+{(sw - win.winfo_width()) // 2}+{(sh - win.winfo_height()) // 2}")
    win.focus_force()
