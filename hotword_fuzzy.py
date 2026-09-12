"""Fuzzy hotword reconciliation for finished transcripts.

The Nemotron engines accept no vocabulary biasing (``hotwords`` is accepted
and ignored in nemotron_engine.py), so ``hotwords-*.txt`` only ever reached
the faster-whisper profiles. This pass closes the gap for every engine: after
the deterministic corrections are applied, transcript tokens are fuzzy
matched against the profile's hotword list and close misses are rewritten to
the canonical spelling ("pie coding agent" -> "Pi coding agent").

Design notes:

* Uses rapidfuzz when it is installed; without it the module falls back to
  ``difflib.SequenceMatcher``, whose ratio is the same normalized indel
  similarity on a 0-100 scale. The feature therefore degrades gracefully to
  the standard library and never requires the extra dependency.
* Conservative by default: tokens shorter than ``min_len`` characters and
  tokens containing digits are never touched, spellings that already match a
  hotword (case-insensitively) are left alone, and only matches scoring at
  least ``min_score`` (0-100) are replaced. Tune ``fuzzy_hotword_min_score``
  or set ``"fuzzy_hotwords": false`` in config.json.
* Multi-word hotwords ("Pi coding agent") are matched against consecutive
  token windows of the same word count, keeping the surrounding punctuation.
  Single-word hotwords also match token pairs/triples so split compounds and
  CamelCase names ("daten bank", "deep seek") are found as well.
"""

import difflib
import re
import string

try:
    from rapidfuzz import fuzz as _fuzz
except Exception:  # rapidfuzz is optional - stdlib fallback below
    _fuzz = None

_TOKEN_RE = re.compile(r"\S+")
_PUNCT = string.punctuation + "…—–«»„“”‚‘’¡¿§°"


def _score(a, b):
    """Similarity of two strings on a 0-100 scale."""
    if _fuzz is not None:
        return _fuzz.ratio(a, b)
    return difflib.SequenceMatcher(None, a, b, autojunk=False).ratio() * 100.0


def _split_token(token):
    """Split a raw token into (leading punctuation, core, trailing punctuation)."""
    core = token.strip(_PUNCT)
    if not core:
        return token, "", ""
    start = token.index(core)
    return token[:start], core, token[start + len(core):]


def reconcile(text, hotwords, min_score=85, min_len=4, log=None):
    """Rewrite near-misses of the hotword list in ``text``.

    ``hotwords`` is the list of canonical spellings (multi-word phrases
    allowed). Returns ``text`` unchanged when there is nothing to do; every
    replacement is reported through ``log`` when one is passed.
    """
    if not text or not hotwords:
        return text

    # (start, end, leading punct, core, trailing punct) per token.
    tokens = []
    for m in _TOKEN_RE.finditer(text):
        lead, core, trail = _split_token(m.group(0))
        tokens.append((m.start(), m.end(), lead, core, trail))
    if not tokens:
        return text

    canonical = {hw.lower() for hw in hotwords}
    # Match targets: (canonical, lowercase target, window token count).
    # Multi-word hotwords are compared to same-size token windows; single-word
    # hotwords also try 2- and 3-token windows joined by spaces, because ASR
    # routinely splits compounds ("daten bank" -> Datenbank) and CamelCase
    # names ("deep seek" -> DeepSeek).
    targets = []
    for hw in hotwords:
        words = hw.split()
        if not words:
            continue
        lowered = " ".join(w.lower() for w in words)
        targets.append((hw, lowered, len(words)))
        if len(words) == 1:
            targets.extend((hw, lowered, n) for n in (2, 3))

    # Candidate replacements: (score, start, end, replacement, original).
    candidates = []

    def _blocked(core):
        # Short tokens, numbers, and tokens that already spell a hotword are
        # never rewritten.
        return (
            not core
            or len(core) < min_len
            or any(ch.isdigit() for ch in core)
            or core.lower() in canonical
        )

    for i in range(len(tokens)):
        for hw, target, n in targets:
            window = tokens[i:i + n]
            if len(window) < n:
                continue
            cores = [w[3] for w in window]
            if any(not c or any(ch.isdigit() for ch in c) for c in cores):
                continue
            joined = " ".join(cores).lower()
            if joined in canonical:
                continue
            # Short strings inflate similarity; keep them out entirely.
            min_joined = min_len if n == 1 else min_len + 2
            if len(joined) < min_joined:
                continue
            # The indel ratio can never exceed 200*min/(len_a+len_b); skip
            # pairs whose ceiling is below the threshold without scoring.
            if 200.0 * min(len(joined), len(target)) / (len(joined) + len(target)) < min_score:
                continue
            s = _score(joined, target)
            if s >= min_score:
                start, end = window[0][0], window[-1][1]
                candidates.append(
                    (
                        s,
                        start,
                        end,
                        window[0][2] + hw + window[-1][4],
                        text[start:end],
                    )
                )

    if not candidates:
        return text

    # Highest score first; longer spans win ties, then the leftmost one.
    # Overlapping candidates are resolved greedily in that order.
    candidates.sort(key=lambda c: (-c[0], c[1] - c[2], c[1]))
    accepted = []
    for cand in candidates:
        s0, e0 = cand[1], cand[2]
        if any(s0 < a_end and e0 > a_start for a_start, a_end, _c in accepted):
            continue
        accepted.append((s0, e0, cand))
    # Apply right-to-left so the string indices stay valid.
    for start, end, (s, _s0, _e0, replacement, original) in sorted(
        accepted, key=lambda a: -a[0]
    ):
        if log:
            log(f"Fuzzy hotword: {original!r} -> {replacement!r} (score {s:.0f})")
        text = text[:start] + replacement + text[end:]
    return text
