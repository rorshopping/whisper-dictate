"""Measure the post-release drain on the real capture stack.

Replicates main.py's stream config (16 kHz mono f32, latency hint 0.05,
25 ms blocks) and the engine's delivery-based drain criterion: finalize at
the first delivery landing past (release + negotiated latency). Reports the
finalize delay after release (wall clock), the delivery cadence, and the
lost-pre-release-chunk count (correctness: must stay 0).

Run with the app venv python.
"""
from __future__ import annotations

import time

import sounddevice as sd

SR = 16000
BLOCK = 400       # 25 ms at 16 kHz - same as main.py's CAPTURE_BLOCKSIZE
state = {"offset": None, "latency": None, "last_delivery": 0.0, "chunks": []}


def cb(indata, frames, ti, status):
    now = time.time()
    state["chunks"].append((now, frames / SR))
    state["last_delivery"] = now
    if status:
        print("overflow:", status)


stream = sd.InputStream(samplerate=SR, channels=1, dtype="float32", latency=0.05, blocksize=BLOCK, callback=cb)
stream.start()
state["latency"] = float(getattr(stream, "latency", 0.0) or 0.0)
print("actual stream latency:", state["latency"], flush=True)
time.sleep(1.0)

trials = []
for i in range(12):
    time.sleep(2.0 + (i % 3))  # hold, as if speaking
    release = time.time()
    deadline = release + state["latency"]
    # engine criterion: first poll (5 ms) where a delivery landed past deadline
    while time.time() - release < 1.0:
        if state["last_delivery"] >= deadline:
            break
        time.sleep(0.005)
    finalize = time.time() - release
    time.sleep(0.8)  # let stragglers arrive so the loss check is meaningful
    delivered_end = 0.0
    for arrival, dur in state["chunks"]:
        if arrival <= release + finalize:
            delivered_end = max(delivered_end, arrival + dur - state["latency"])
    lost = max(0.0, release - delivered_end)
    trials.append(finalize)
    print(
        f"trial {i:2d}: finalize {finalize*1e3:6.1f} ms after release | "
        f"pre-release audio covered to release-{lost*1e3:.1f} ms",
        flush=True,
    )

trials.sort()
print(
    f"median {trials[len(trials)//2]*1e3:.1f} ms | min {trials[0]*1e3:.1f} ms | "
    f"max {trials[-1]*1e3:.1f} ms  (was 400 ms, then 200 ms at the 100 ms buffer)"
)
stream.stop()
stream.close()
