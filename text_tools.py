"""Local text post-processing: spoken punctuation and voice snippets.

Two opt-in, entirely local features that other dictation tools ship and this
one did not:

* **Spoken punctuation** - say "comma", "period", "new line" (or "komma",
  "punkt", "neue zeile") and the text gets the real character. Off by default:
  it rewrites ordinary words, so it must be a deliberate choice. Nothing here
  touches the model, the audio, or the network.
* **Voice snippets** - an exact utterance that expands into a stored block,
  e.g. saying "insert signature" pastes an address block. Whole-utterance
  matching only, so a snippet can never fire in the middle of a sentence by
  accident.

Design rules that the tests pin down:

* The default path returns the input unchanged, byte for byte.
* Commands match on word boundaries, case-insensitively, longest phrase first,
  so "question mark" beats a hypothetical "mark".
* Inline punctuation attaches to the previous word ("hello comma world" ->
  "hello, world") and a sentence mark capitalizes the next word; newline
  commands collapse the surrounding whitespace.
* A command that would duplicate punctuation the transcript already produced is
  dropped ("Ready. period" -> "Ready."), never doubled.
* Snippets are matched before punctuation and returned verbatim, so a snippet
  containing the word "period" is never rewritten by the punctuation pass.

No third-party imports, no configuration of its own: the caller (main.py)
decides which of the two features is enabled.
"""

from __future__ import annotations

import re

# --- spoken punctuation tables ------------------------------------------------
# Longest phrases win, so multi-word commands are listed alongside single words
# and sorted at match time. English and German are the two profiles this app
# ships; adding a language is adding a dict here.

EN_PUNCTUATION = {
    "full stop": ".",
    "period": ".",
    "comma": ",",
    "question mark": "?",
    "exclamation mark": "!",
    "exclamation point": "!",
    "semicolon": ";",
    "semi colon": ";",
    "colon": ":",
    "ellipsis": "\u2026",
    "hyphen": "-",
    "dash": "\u2014",
    "open parenthesis": "(",
    "close parenthesis": ")",
    "open bracket": "[",
    "close bracket": "]",
    "open quote": "\u201c",
    "close quote": "\u201d",
    "ampersand": "&",
    "percent sign": "%",
    "degree sign": "\u00b0",
    "asterisk": "*",
    "new line": "\n",
    "newline": "\n",
    "new paragraph": "\n\n",
}

DE_PUNCTUATION = {
    "punkt": ".",
    "komma": ",",
    "fragezeichen": "?",
    "ausrufezeichen": "!",
    "semikolon": ";",
    "doppelpunkt": ":",
    "auslassungspunkte": "\u2026",
    "gedankenstrich": "\u2013",
    "bindestrich": "-",
    "klammer auf": "(",
    "klammer zu": ")",
    "eckige klammer auf": "[",
    "eckige klammer zu": "]",
    "anfuehrungszeichen": "\u201c",
    "anführungszeichen": "\u201c",
    "prozentzeichen": "%",
    "prozent": "%",
    "gradzeichen": "\u00b0",
    "sternchen": "*",
    "neue zeile": "\n",
    "neuer absatz": "\n\n",
}

PUNCTUATION = {
    "en": EN_PUNCTUATION,
    "de": DE_PUNCTUATION,
}

_NEWLINE_COMMANDS = frozenset({"\n", "\n\n"})
# Marks that hug the following word instead of leaving a space.
_OPENERS = frozenset({"(", "[", "\u201c", "'", "{"})
_SENTENCE_END = frozenset({".", "!", "?"})


def _language_key(language):
    if not language:
        return "en"
    return str(language).strip().lower().split("-")[0]


def parse_snippets(snippets):
    """Accept a dict, "trigger => value" lines, or (trigger, value) pairs."""
    table = {}
    if not snippets:
        return table
    items = []
    if isinstance(snippets, dict):
        items = list(snippets.items())
    else:
        for entry in snippets:
            if isinstance(entry, (tuple, list)) and len(entry) == 2:
                items.append((entry[0], entry[1]))
            elif isinstance(entry, str) and "=>" in entry:
                # "trigger => value" lines: the space around the arrow is
                # formatting, not content.
                trigger, value = entry.split("=>", 1)
                items.append((trigger.strip(), value.strip()))
    for trigger, value in items:
        trigger = (trigger or "").strip()
        if not trigger or value is None:
            continue
        table[trigger.casefold()] = _unescape(str(value))
    return table


def _unescape(value):
    """Let one-line rule files express line breaks: ``\\n`` and ``\\t``."""
    return value.replace("\\n", "\n").replace("\\t", "\t")


def _normalize_utterance(text):
    """Drop surrounding space and trailing sentence punctuation."""
    stripped = (text or "").strip()
    return stripped.rstrip(" \t.!?,;:\u2026").strip()


def match_snippet(text, snippets):
    """Return the snippet for an exact whole-utterance match, else None."""
    table = parse_snippets(snippets)
    if not table or not text:
        return None
    key = _normalize_utterance(text).casefold()
    if not key:
        return None
    return table.get(key)


def _apply_command(text, start, end, symbol):
    """Replace text[start:end] with symbol, fixing the surrounding spacing."""
    before = text[:start]
    after = text[end:]

    if symbol in _NEWLINE_COMMANDS:
        before = before.rstrip(" \t")
        if before.endswith(symbol):
            # Already at a paragraph break: do not stack another one.
            return before + after.lstrip(" \t")
        rest = after.lstrip(" \t")
        result = before + symbol + rest
        offset = len(before) + len(symbol)
        match = re.search(r"[a-z]", result[offset:])
        if match:
            index = offset + match.start()
            result = result[:index] + result[index].upper() + result[index + 1:]
        return result

    if symbol == " ":
        return before.rstrip(" \t") + " " + after.lstrip(" \t")

    # Collapse the space the ASR put in front of the command word.
    before = before.rstrip(" \t")
    rest = after.lstrip(" \t")

    # Never double punctuation that is already in the transcript.
    if rest[:1] == symbol:
        rest = rest[1:].lstrip(" \t")

    if symbol in _SENTENCE_END and rest[:1].islower() and rest[:1].isalpha():
        rest = rest[0].upper() + rest[1:]

    if before.endswith(symbol):
        # The word was already punctuated; drop the command, keep the text.
        return before + rest

    if symbol in _OPENERS:
        return before + symbol + rest

    return before + symbol + (" " + rest if rest else "")


def apply_spoken_punctuation(text, language="en"):
    """Rewrite spoken command words into their characters."""
    if not text:
        return text
    table = PUNCTUATION.get(_language_key(language))
    if not table:
        return text

    # Longest command first so "question mark" is matched before "mark".
    commands = sorted(table.items(), key=lambda kv: len(kv[0]), reverse=True)
    pattern = "|".join(
        re.escape(word).replace(r"\ ", r"\s+") for word, _ in commands
    )
    regex = re.compile(r"(?<!\w)(" + pattern + r")(?!\w)", re.IGNORECASE)
    lookup = {word.casefold(): symbol for word, symbol in commands}

    # One pass per match, right to left, so earlier indices stay valid.
    result = text
    for match in reversed(list(regex.finditer(text))):
        symbol = lookup[match.group(1).casefold()]
        result = _apply_command(result, match.start(), match.end(), symbol)
    return result


def process_text(
    text,
    language="en",
    spoken_punctuation=False,
    snippets=None,
):
    """Final post-processing pass before the text is typed.

    Snippets win over punctuation: a whole-utterance match is returned
    verbatim. Otherwise the text is returned unchanged unless
    ``spoken_punctuation`` is on.
    """
    if not text:
        return text
    snippet = match_snippet(text, snippets)
    if snippet is not None:
        return snippet
    if not spoken_punctuation:
        return text
    return apply_spoken_punctuation(text, language=language)
