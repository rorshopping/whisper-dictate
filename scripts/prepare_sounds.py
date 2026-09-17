"""Rebuild bundled CC0 cues (developer-only; requires ffmpeg and numpy).

Downloads public HQ previews, not login-protected originals. Playback needs
neither network access nor ffmpeg. See assets/sounds/SOURCES.md.
"""
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import urllib.request
import wave

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "assets" / "sounds"
SOURCES = [
    ("message-chime", "AnthonyRox", 740423, 2675894, 3639),
    ("message-tone", "AnthonyRox", 740420, 2675894, 1785),
    ("high-bell", "LegitCheese", 571512, 2226836, 1441),
    ("double-bell", "LegitCheese", 571513, 2226836, 1090),
    ("low-bell", "LegitCheese", 571511, 2226836, 709),
]
# Small pitch differences preserve the old start/stop/done/undo distinction.
EVENTS = {"start": (1.0, 0.28), "stop": (0.84, 0.22),
          "done": (1.12, 0.45), "undo": (0.70, 0.25)}
RATE = 44100


def main():
    DEST.mkdir(parents=True, exist_ok=True)
    manifest = []
    with tempfile.TemporaryDirectory() as tmp:
        for key, author, sid, uid, downloads in SOURCES:
            url = f"https://cdn.freesound.org/previews/{sid // 1000}/{sid}_{uid}-hq.mp3"
            source = urllib.request.urlopen(url, timeout=30).read()
            mp3 = Path(tmp) / f"{key}.mp3"
            mp3.write_bytes(source)
            decoded = subprocess.run(
                ["ffmpeg", "-v", "error", "-i", str(mp3), "-f", "f32le",
                 "-ac", "1", "-ar", str(RATE), "pipe:1"],
                check=True, capture_output=True,
            ).stdout
            samples = np.frombuffer(decoded, dtype="<f4").copy()
            peak = np.max(np.abs(samples))
            active = np.flatnonzero(np.abs(samples) > peak * 0.015)
            samples = samples[max(0, active[0] - 220):active[-1] + 1]
            entry = {"id": key, "author": author, "sound_id": sid,
                     "source_page": f"https://freesound.org/people/{author}/sounds/{sid}/",
                     "preview_url": url, "license": "CC0-1.0",
                     "downloads": downloads, "observed": "2026-09-17",
                     "source_sha256": hashlib.sha256(source).hexdigest(), "files": {}}
            for event, (pitch, duration) in EVENTS.items():
                cue = np.interp(np.arange(0, len(samples), pitch),
                                np.arange(len(samples)), samples)[:int(RATE * duration)]
                # Gentle attack/release; cap peaks at -16 dBFS and RMS at -26 dBFS.
                attack = min(int(RATE * 0.008), len(cue))
                release = min(int(RATE * 0.060), len(cue))
                cue[:attack] *= np.linspace(0, 1, attack)
                cue[-release:] *= np.linspace(1, 0, release)
                cue *= min(0.16 / max(np.max(np.abs(cue)), 1e-9),
                           0.05 / max(np.sqrt(np.mean(cue ** 2)), 1e-9))
                path = DEST / f"{key}-{event}.wav"
                with wave.open(str(path), "wb") as wav:
                    wav.setparams((1, 2, RATE, 0, "NONE", "not compressed"))
                    wav.writeframes((cue * 32767).astype("<i2").tobytes())
                entry["files"][path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
            manifest.append(entry)
            print(f"Prepared {key}: {downloads:,} source downloads")
    (DEST / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
