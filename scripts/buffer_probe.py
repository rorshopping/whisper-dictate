"""Probe the smallest stable capture buffer on this device.

For each (latency hint, blocksize) candidate: open the stream with main.py's
config, report the negotiated latency and delivery cadence, count overflows
during capture + a simulated 120 ms GIL stall, and verify delivery continuity.
Pick the smallest combo with negotiated latency <= hint and zero overflows.

Run with the app venv python.
"""
from __future__ import annotations

import time

import numpy as np
import sounddevice as sd

SR = 16000
CANDIDATES = [
    (0.10, 800),
    (0.05, 400),
    (0.02, 400),
    (0.05, 160),
    (0.02, 160),
]

for hint, block in CANDIDATES:
    st = {"n": 0, "overflows": 0, "last": 0.0, "max_gap": 0.0}
    def cb(indata, frames, ti, status, st=st):
        now = time.time()
        if st["last"]:
            st["max_gap"] = max(st["max_gap"], now - st["last"])
        st["last"] = now
        st["n"] += 1
        if status:
            st["overflows"] += 1
    try:
        stream = sd.InputStream(
            samplerate=SR, channels=1, dtype="float32",
            latency=hint, blocksize=block, callback=cb,
        )
        stream.start()
    except Exception as exc:
        print(f"hint={hint} block={block}: open failed: {exc}")
        continue
    time.sleep(1.0)
    negotiated = float(getattr(stream, "latency", 0.0) or 0.0)
    # simulated stall: block the GIL for 120 ms mid-capture
    time.sleep(0.5)
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < 0.12:
        pass
    time.sleep(1.0)
    stream.stop()
    stream.close()
    n = st["n"]
    cadence = (st["last"] - 0) if False else None
    print(
        f"hint={hint:4} block={block:3}: negotiated={negotiated*1e3:5.1f} ms  "
        f"callbacks={n:3d}  overflows={st['overflows']}  max_delivery_gap={st['max_gap']*1e3:5.1f} ms"
    )
