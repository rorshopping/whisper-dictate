"""Deterministic voice commands - the offline subset of Wispr Flow's
Command Mode.

Hold the command hotkey (config `command_hotkey`), speak one phrase, release:
if the transcript matches an entry below, the matching key sequence is
executed in the focused app instead of typing the words. Anything else is
typed as normal dictation, so a misheard command never loses the text.

Matching is exact after normalization (whitespace collapsed, case and
trailing punctuation stripped) - no model, no fuzz, fully offline. Actions
are key names understood by `main._tap_keys`: a string taps one key, a tuple
presses modifier(s) (ctrl/alt/shift) and taps the last key.
"""

COMMANDS = {
    "en": {
        "press enter": "enter",
        "press tab": "tab",
        "press escape": "escape",
        "press backspace": "backspace",
        "select all": ("ctrl", "a"),
        "copy that": ("ctrl", "c"),
        "cut that": ("ctrl", "x"),
        "paste": ("ctrl", "v"),
        "undo that": ("ctrl", "z"),
        "redo that": ("ctrl", "y"),
        "delete last word": ("ctrl", "backspace"),
    },
    "de": {
        "enter drücken": "enter",
        "enter druecken": "enter",
        "tab drücken": "tab",
        "tab druecken": "tab",
        "escape drücken": "escape",
        "esc drücken": "escape",
        "alles auswählen": ("ctrl", "a"),
        "alles markieren": ("ctrl", "a"),
        "kopieren": ("ctrl", "c"),
        "ausschneiden": ("ctrl", "x"),
        "einfügen": ("ctrl", "v"),
        "einfuegen": ("ctrl", "v"),
        "rückgängig": ("ctrl", "z"),
        "rueckgaengig": ("ctrl", "z"),
        "wiederholen": ("ctrl", "y"),
        "letztes wort löschen": ("ctrl", "backspace"),
        "letztes wort loeschen": ("ctrl", "backspace"),
    },
}

# Key names the action specs may use; everything else must be a single
# character (typed as such).
KNOWN_KEYS = {
    "enter", "tab", "escape", "esc", "backspace", "delete", "space",
    "ctrl", "alt", "shift",
    "a", "c", "v", "x", "z", "y",
}


def normalize(text):
    """Collapse whitespace, lowercase, drop trailing punctuation."""
    t = " ".join(str(text or "").split()).lower()
    return t.rstrip(".,!?;: ")


def match(text, language="en"):
    """Return the action spec for a command phrase, else None."""
    lang = "de" if str(language or "").lower().startswith("de") else "en"
    return COMMANDS[lang].get(normalize(text))


def validate():
    """Sanity-check every action spec; returns a list of problems (empty = ok)."""
    problems = []
    for lang, table in COMMANDS.items():
        for phrase, action in table.items():
            if phrase != normalize(phrase):
                problems.append(f"{lang}: phrase '{phrase}' is not normalized")
            keys = (action,) if isinstance(action, str) else action
            for k in keys:
                if k not in KNOWN_KEYS:
                    problems.append(f"{lang}: '{phrase}' uses unknown key '{k}'")
    return problems
