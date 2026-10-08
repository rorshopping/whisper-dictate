"""VRAM probe for the becker engine (temporary diagnostics tool).

Measures, via nvidia-smi total committed memory (WDDM has no per-process
figure), the VRAM cost of: baseline idle -> becker model loaded -> warm
transcribe -> model closed -> cudaDeviceReset -> reload sanity.

Run: .venv/Scripts/python.exe scripts/vram_probe.py [model_dir]
"""
import ctypes
import subprocess
import sys
import time
import wave
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

MODEL_DIR = sys.argv[1] if len(sys.argv) > 1 else (
    r"C:\Users\Richard\Documents\Cursor_Projects\llamacpp_becker_performant"
    r"\engine-rs\models\parakeet-v3-onnx"
)
WAV = Path(sys.argv[2]) if len(sys.argv) > 2 else REPO / "test.wav"
LANG = sys.argv[3] if len(sys.argv) > 3 else None


def vram_mib():
    out = subprocess.run(
        ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
        capture_output=True, text=True, check=True,
    )
    return float(out.stdout.strip().splitlines()[0])


def load_wav_16k(path):
    with wave.open(str(path), "rb") as w:
        sr = w.getframerate()
        n = w.getnframes()
        pcm = np.frombuffer(w.readframes(n), dtype=np.int16).astype(np.float32) / 32768.0
        if w.getnchannels() == 2:
            pcm = pcm.reshape(-1, 2).mean(axis=1)
    if sr != 16000:
        idx = np.arange(0, len(pcm), sr / 16000.0)
        i0 = idx.astype(np.int64)
        frac = idx - i0
        pcm = pcm[i0] + frac * (pcm[np.minimum(i0 + 1, len(pcm) - 1)] - pcm[i0])
    return pcm.astype(np.float32)


def device_reset():
    """Force-destroy the CUDA primary context after becker_capi_free."""
    import os
    candidates = []
    for base in (
        os.path.join(sys.prefix, "Lib", "site-packages", "nvidia", "cuda_runtime", "bin"),
        os.path.join(REPO, ".venv", "Lib", "site-packages", "nvidia", "cuda_runtime", "bin"),
    ):
        if os.path.isdir(base):
            candidates.append(os.path.join(base, "cudart64_12.dll"))
            os.add_dll_directory(base)
    for c in candidates:
        if Path(c).is_file():
            try:
                cudart = ctypes.CDLL(c)
                rc = cudart.cudaDeviceReset()
                return f"cudaDeviceReset({Path(c).name}) -> rc={rc}"
            except OSError as exc:
                return f"reset failed: {exc}"
    return "cudart64_12.dll not found"


def main():
    from becker_engine import BeckerModel

    print(f"baseline: {vram_mib():.0f} MiB")
    pcm = load_wav_16k(WAV)
    print(f"clip: {WAV.name} {pcm.size / 16000:.2f}s @16k")

    t0 = time.time()
    model = BeckerModel(MODEL_DIR, device="cuda", log=print, language=LANG)
    print(f"loaded:  {vram_mib():.0f} MiB (load {time.time() - t0:.1f}s)")

    t0 = time.time()
    segs, info = model.transcribe(pcm)
    print(f"transcribed: {vram_mib():.0f} MiB ({(time.time() - t0) * 1000:.0f} ms) "
          f"text={segs[0].text[:60]!r}" if segs else "transcribed: empty")

    t0 = time.time()
    segs, info = model.transcribe(pcm)
    print(f"warm 2nd: {(time.time() - t0) * 1000:.0f} ms, vram {vram_mib():.0f} MiB")

    model.close()
    time.sleep(2.0)
    print(f"closed:  {vram_mib():.0f} MiB")

    print(device_reset())
    time.sleep(2.0)
    print(f"reset:   {vram_mib():.0f} MiB")

    t0 = time.time()
    model2 = BeckerModel(MODEL_DIR, device="cuda", log=print)
    segs, info = model2.transcribe(pcm)
    print(f"reloaded after reset: {vram_mib():.0f} MiB (load {time.time() - t0:.1f}s) "
          f"text={segs[0].text[:40]!r}" if segs else "reloaded: empty result")
    model2.close()
    print(device_reset())
    time.sleep(1.0)
    print(f"final:   {vram_mib():.0f} MiB")


if __name__ == "__main__":
    main()
