# Sound sources and popularity ranking

Researched 2026-09-17. All five source recordings are **CC0 1.0**:
<https://creativecommons.org/publicdomain/zero/1.0/>. They may be copied,
modified and redistributed, including commercially. Credit is optional;
we retain it here along with the provenance manifest.

## Curated shortlist, ranked by source-file downloads

These are **not** the five most popular sounds on the entire web. The menu
orders our five chosen notification sounds by the same measurable proxy:
Freesound's individual download counts, captured on the date above. This is
not a rating of pleasantness, an app usage statistic, or a live counter.

| Rank | Menu name | Original / creator | Downloads |
|---|---|---|---:|
| 1 | Message chime (new default) | [Message Notification 4 — AnthonyRox](https://freesound.org/people/AnthonyRox/sounds/740423/) | 3,639 |
| 2 | Message tone | [Message Notification 1 — AnthonyRox](https://freesound.org/people/AnthonyRox/sounds/740420/) | 1,785 |
| 3 | Soft high bell | [Soft-Notifications - Bell - HighDing — LegitCheese](https://freesound.org/people/LegitCheese/sounds/571512/) | 1,441 |
| 4 | Soft double bell | [Soft-Notifications - Bell - Ding-Dong — LegitCheese](https://freesound.org/people/LegitCheese/sounds/571513/) | 1,090 |
| 5 | Soft low bell | [Soft-Notifications - Bell - LowDing — LegitCheese](https://freesound.org/people/LegitCheese/sounds/571511/) | 709 |

Also considered [Kenney Interface Sounds](https://kenney.nl/assets/interface-sounds)
and [Kenney's older UI set](https://opengameart.org/content/51-ui-sound-effects-buttons-switches-and-clicks)
(CC0; 45,262 pack downloads / 178 favorites observed). Those are mostly
organic clicks/switches, and pack counts cannot honestly rank individual
sounds against the Freesound files, so they are not mixed into this ranking.

## Bundled adaptations

Public HQ MP3 previews were downloaded from Freesound's CDN (not the
login-protected originals), decoded, trimmed and converted to mono 44.1 kHz
16-bit PCM WAV. These are real source samples, not newly synthesized tones.
Each theme has four short variants:

- Start: up to 280 ms, original pitch.
- Stop: up to 220 ms, slightly lower pitch.
- Done / paste: up to 450 ms, slightly higher pitch.
- Undo: up to 250 ms, lower pitch.

All have an 8 ms attack / 60 ms release, with peaks capped at approximately
-16 dBFS and RMS capped at -26 dBFS. These are deliberately short excerpts,
not full-length ringtones; the source name need not describe every excerpt.
Quieter/shorter playback reduces intrusiveness but cannot eliminate microphone
pickup from speakers. Use headphones or Off if cues enter recordings.

`manifest.json` records exact source URLs, authors, counts, licenses and
SHA-256 hashes for both downloaded previews and bundled files. Rebuild with
`python scripts/prepare_sounds.py` (requires ffmpeg and numpy). Runtime is
fully offline and needs no ffmpeg or additional Python audio dependency.
