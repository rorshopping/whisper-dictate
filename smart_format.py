"""Wispr-Flow-style auto-edits, applied to every final transcription.

All passes are deterministic string rewrites - no model cost, fully offline:

- Backtrack / self-correction: saying "scratch that" (or German "vergiss
  das") drops everything dictated before it, in-speech, like Wispr Flow's
  backtrack. Complements the Ctrl+Shift+F13 scratch hotkey, which undoes a
  transcription after it was already typed.
- Filler-word removal ("um", "uh", "ähm", ...) - text that reads like you
  wrote it, not like you spoke it.
- Spoken punctuation and structure commands ("comma", "period", "new line",
  "new paragraph", "bullet point", ...) so output is copy-ready on every
  engine, including ones without built-in punctuation.
- Spacing tidy-up and sentence capitalization.

The public entry point is `apply()`. Every pass is switched from config.json
(smart_format / smart_fillers / smart_spoken_punctuation / smart_capitalize -
see main.DEFAULTS); the caller wraps `apply()` in a fail-safe so a problem
here can never lose a transcription.
"""

import re

# Longer phrases first everywhere so longer commands win over overlapping
# shorter ones.
BACKTRACK_PHRASES = {
    "en": ["scratch that", "scratch this", "strike that"],
    "de": ["vergiss das", "vergiss es"],
}

# Standalone filler tokens (case-insensitive, whole words only). Deliberately
# conservative: real words like "like" or German "Punkt" are never touched.
FILLERS = {
    "en": ["um", "uh", "uhm", "umm", "uhh", "uhmm", "erm", "hmm"],
    "de": ["äh", "ähm", "öh", "öhm", "hmm"],
}

# Spoken punctuation: phrase -> replacement. Lists stay longest-first.
SPOKEN_PUNCTUATION = {
    "en": [
        ("new paragraph", "\n\n"),
        ("new line", "\n"),
        ("newline", "\n"),
        ("exclamation point", "!"),
        ("exclamation mark", "!"),
        ("question mark", "?"),
        ("open parenthesis", "("),
        ("close parenthesis", ")"),
        ("open paren", "("),
        ("close paren", ")"),
        ("full stop", "."),
        ("semicolon", ";"),
        ("period", "."),
        ("colon", ":"),
        ("comma", ","),
    ],
    "de": [
        ("neuer absatz", "\n\n"),
        ("neue zeile", "\n"),
        ("ausrufezeichen", "!"),
        ("fragezeichen", "?"),
        ("klammer auf", "("),
        ("klammer zu", ")"),
        ("doppelpunkt", ":"),
        ("semikolon", ";"),
        ("komma", ","),
    ],
}

# Structured lists: a bullet always starts on its own line.
BULLET_PHRASES = {
    "en": [("bullet point", "\n• "), ("new bullet", "\n• ")],
    "de": [("aufzählungspunkt", "\n• ")],
}


def _compile(phrases):
    return [
        (re.compile(r"\b" + re.escape(phrase) + r"\b", re.IGNORECASE), repl)
        for phrase, repl in phrases
    ]


def _compile_words(phrases):
    return [re.compile(r"\b" + re.escape(p) + r"\b", re.IGNORECASE) for p in phrases]


_BACKTRACK = {lang: _compile_words(v) for lang, v in BACKTRACK_PHRASES.items()}
_PUNCT = {lang: _compile(v) for lang, v in SPOKEN_PUNCTUATION.items()}
_BULLET = {lang: _compile(v) for lang, v in BULLET_PHRASES.items()}


def _normalize_lang(language):
    return "de" if str(language or "").lower().startswith("de") else "en"


def _backtrack(text, lang, log=None):
    """Drop everything up to and including the last backtrack phrase."""
    best = None
    for rx in _BACKTRACK[lang]:
        for m in rx.finditer(text):
            if best is None or m.end() > best[1]:
                best = (m.start(), m.end())
    if best is None:
        return text
    if log:
        log(f"Backtrack: dropping {best[0]} chars before self-correction")
    return text[best[1]:]


def _remove_fillers(text, lang):
    filler_rx = re.compile(
        r"\b(" + "|".join(sorted(map(re.escape, FILLERS[lang]), key=len, reverse=True)) + r")\b",
        re.IGNORECASE,
    )
    return filler_rx.sub("", text)


def _replace_phrases(text, compiled):
    for rx, repl in compiled:
        text = rx.sub(repl, text)
    return text


def _tidy(text):
    """Repair the spacing left behind by word removal and phrase replacement."""
    text = re.sub(r"[ \t]{2,}", " ", text)      # gaps where fillers were
    text = re.sub(r" +([,.;:!?])", r"\1", text)  # no space before punctuation
    text = re.sub(r"\( +", "(", text)
    text = re.sub(r"^[\s,;:]+", "", text)        # junk never starts a sentence
    text = re.sub(r"[ \t]\n", "\n", text)        # no trailing spaces on a line
    text = re.sub(r"\n[ \t]+", "\n", text)       # none at the start of one
    text = re.sub(r"\n{3,}", "\n\n", text)       # at most one blank line
    return text.strip()


def _capitalize(text, lang):
    if lang == "en":
        text = re.sub(r"\bi\b", "I", text)
    # Start of text, after sentence punctuation, after each line break, and
    # after a list bullet. Only matches lowercase, so acronyms survive and
    # "example.com" or "3.5" are never touched (no whitespace after the dot).
    return re.sub(
        r"(^|[.!?]\s+|\n\s*|• )([a-zäöüß])",
        lambda m: m.group(1) + m.group(2).upper(),
        text,
    )


def apply(text, language="en", fillers=True, spoken_punctuation=True,
          capitalize=True, log=None):
    """Run every enabled Wispr-Flow-style pass over a final transcription."""
    if not text:
        return text
    lang = _normalize_lang(language)
    text = _backtrack(text, lang, log)
    if not text:
        return ""
    if fillers:
        text = _remove_fillers(text, lang)
    if spoken_punctuation:
        text = _replace_phrases(text, _PUNCT[lang])
        text = _replace_phrases(text, _BULLET[lang])
    text = _tidy(text)
    if capitalize:
        text = _capitalize(text, lang)
    return text
