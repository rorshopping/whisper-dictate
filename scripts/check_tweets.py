#!/usr/bin/env python3
"""Check the launch thread against X's posting limits.

X's rules, implemented rather than guessed:

* 280 characters per tweet, counted in Unicode code points, except
* every URL counts as exactly 23 characters (t.co shortening), and
* emoji / other extended grapheme clusters count as 2 characters.

Run: .venv/bin/python scripts/check_tweets.py docs/LAUNCH_TWEETS.md
Exits non-zero when any tweet is over, so it can gate a release note update.
"""

import re
import sys
import unicodedata

URL_RE = re.compile(r"https?://\S+")
LIMIT = 280
# Emoji and a few symbol ranges X charges double for (roughly: anything that is
# a single grapheme cluster beyond the BMP, plus the pictographic blocks).
DOUBLE_RE = re.compile(
    "[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\uFE0F\u200D]"
)


def weighted_length(text):
    """X's character count: URLs are 23, emoji count 2."""
    text = URL_RE.sub("x" * 23, text)
    total = 0
    for char in text:
        if DOUBLE_RE.match(char) and not unicodedata.combining(char):
            total += 2
        else:
            total += 1
    return total


def parse_tweets(path):
    """Yield (label, text) for each blockquote tweet in the markdown file."""
    raw = open(path, "r", encoding="utf-8").read()
    # Only the thread section: everything before the "## Single-post" heading.
    thread = raw.split("## Single-post")[0]
    parts = re.split(r"\n\*\*(\d+/\d+)\*\*\s*\n", thread)
    for index in range(1, len(parts) - 1, 2):
        label = parts[index]
        body = parts[index + 1]
        lines = []
        for line in body.splitlines():
            if line.startswith("> "):
                lines.append(line[2:].strip())
            elif line.startswith(">"):
                lines.append("")
            elif lines and not line.startswith((">", "---", "#")):
                break  # left the blockquote
        text = " ".join(part for part in lines if part).strip()
        if text:
            yield label, text
    # The single-post variant.
    match = re.search(r"## Single-post.*?\n\n> (.*?)\n\n", raw, flags=re.S)
    if match:
        lines = [l.lstrip("> ").strip() for l in match.group(1).splitlines()]
        yield "single", " ".join(l for l in lines if l).strip()


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "docs/LAUNCH_TWEETS.md"
    failures = 0
    for label, text in parse_tweets(path):
        count = weighted_length(text)
        over = count > LIMIT
        failures += 1 if over else 0
        print(f"{'OVER' if over else 'ok  '}  {label:>7}  {count:>4}/280")
    if failures:
        print(f"\n{failures} tweet(s) over the limit")
        return 1
    print("\nAll tweets fit.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
