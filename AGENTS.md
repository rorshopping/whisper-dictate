# AGENTS.md — working in this repository

Notes for AI coding agents (and humans) who extend **whisper-dictate**, the
Windows desktop dictation app.

Created 2026-09-30. The commands below are verified, not assumed — this file
existed only as a gap until then, which cost an agent real time rediscovering
the venv and the suite layout.

## What this is

Local speech-to-text for Windows: hotkey-driven recording, model resolution
across multiple sources, and a community preview release channel. Python, not
Electron. Desktop only — **the iOS app is a separate project**
(`whispr_based_app`), and the two must not be conflated.

## Commands

Verified 2026-09-30.

```sh
# full suite - from the repo root, using the project venv
.venv\Scripts\python.exe -m pytest -q
# baseline: 138 passed, 1 skipped, 55 subtests

# one file / one test
.venv\Scripts\python.exe -m pytest tests/test_model_manager.py -q
.venv\Scripts\python.exe -m pytest tests/test_release_hygiene.py::TestX -q
```

There is **no** `pyproject.toml`, `pytest.ini`, `setup.cfg` or `tox.ini`, and
`.github/workflows/release.yml` does not run pytest — so `pytest` from the venv
is the real suite. `.github/workflows/release.yml` only does `pip install` +
`pyinstaller`.

Environment notes:

- Use `.venv\Scripts\python.exe`, not a bare `python`. The venv is required.
- Python 3.12.10, pytest 9.1.1 (as of 2026-09-30).
- `requirements-release.txt` is the pinned release dependency set, distinct
  from the dev environment.

## Gotchas

- `.zcodeignore` and `scripts/x_get_reply.js` are **untracked and
  unrelated** to the project. They are not gitignored. Never `git add -A`,
  never commit them, never delete them.
- Release work is split across `scripts/` (`export_community.py`,
  `release_guard.py`, `release_manifest.py`) and `packaging/`
  (`windows/WhisperDictate.iss`, `macos/build_signed_dmg.sh`).
- `community-site/` is a separate static site with its own validators and
  tests; a site change is not an app change.
- `INTEGRATION_VERIFICATION.md` and the `NOTES_*.md` files record what was
  actually verified. Read them before claiming a release path works.

## Git state (2026-09-30)

`master` is at `e63c1ec`, carrying the 37 commits from
`integration/community-release` (a clean `--ff-only` fast-forward over
`46813e3`; 53 files, 11k insertions). The 8 feature branches and 9 worktrees
have been removed.

`master` is **37 commits ahead of `origin/master`** — unpushed. Do not push
without the owner asking; GitHub credentials live in the owner's keyring, not
in this environment.

`origin/release/macos-1.1.0-verified` is a separate, unmerged remote branch.
**Do not delete it.**

## The becker engine (added 2026-10-07, int4 VRAM rewire 2026-10-08)

The **EN (ctrl+shift+space)** and **DE (ctrl+alt+space)** profiles both run the
becker-performant engine (`engine: "becker"` in `config.json`) — a Rust + ONNX
Runtime engine from the sibling project
`C:\Users\Richard\Documents\Cursor_Projects\llamacpp_becker_performant`
(7–12× faster than the previous transformers engine at equal accuracy,
verified in that repo's `docs/RESULTS.md`).

**VRAM (2026-10-08, final state):** the **EN profile runs on the CPU EP**
(`"device": "cpu"` → BECKER_CPU=1, fp32 graphs): a loaded model holds **0 MB
VRAM** by construction, at CPU latency (fp32 parakeet: RTF 0.034, ~0.37 s for
an 11 s clip). Rationale: the GPU floor for this model is ~600-790 MiB —
measured across fp32/fp16/int4 configs, resident VRAM ≈ 1.26 × weights (MiB)
+ 191 MiB fixed (CUDA context + ORT pools), so <500 MiB would need ≤246 MB of
weights while the int4 MatMuls alone are 266 MB. The **DE profile stays on the
GPU int4 export** (`nemotron35-int4`, ~1.0 GiB) because the streaming encoder
pays 35 chunk passes per clip on CPU: measured **8.6 s ASR for a 10 s clip**
(RTF 0.87) — unusable. Note the fp16 and int4 graphs do NOT execute on the
CPU EP (silent empty output); CPU mode forces the fp32 graphs. After the idle
unload the process holds 0 MB (`unload_models()` →
`becker_engine.reset_cuda_device()` → `cudaDeviceReset()`; skipped when only
cpu profiles ever loaded). Profile knobs: `"fp16"` (null = auto-detect fp16
graphs in the dir), `"device": "cpu"` / default GPU. To give EN its GPU back:
remove `"device": "cpu"` and point it at `parakeet-int4` (~793 MiB, int4).

- App side: `becker_engine.py` (ctypes wrapper mirroring `parakeet_engine.py`'s
  API slice) + the `becker` branch in `main.py`'s model-load block. Profiles
  set `"model"` to a **prepared model directory** (contains `vocab.txt` or
  `vocab.json`), not a Hugging Face id — the resolver is bypassed.
- Model dirs (sibling repo `engine-rs\models\`, gitignored there): EN uses
  `parakeet-v3-onnx` (fp32 graphs, CPU mode), DE uses `nemotron35-int4`
  (encoder MatMuls int4-quantized, convs fp16; built by
  `bench\quantize_int4_stream.py nemotron` from `nemotron35-onnx`). For the
  GPU EN flip: `parakeet-int4` (from `parakeet-fp16`, same tooling).
  Agreements vs fp32: 1.000 on ≤45 s dictation clips; int4 loses the tail of
  ~112 s continuous audio (0.64 agreement there — split long monologues;
  dictation clips are fine). fp32/fp16 sources stay in `parakeet-v3-onnx` /
  `parakeet-fp16` / `nemotron35-onnx`. If the sibling repo moves, update
  `config.json`.
- Runtime side: `packaging/becker-bin/` holds `becker.dll` (built by
  `engine-rs\build-msvc.bat` in the sibling repo; copy
  `engine-rs\target\release\becker.dll` there after rebuilding) plus
  `onnxruntime.dll` + `onnxruntime_providers_*.dll` (ORT 1.22, CUDA 12).
  cuDNN/cuFFT/nvJitLink come from the app venv's pip `nvidia-*` wheels;
  `becker_engine.py` registers those directories and sets `ORT_DYLIB_PATH`
  itself. `packaging/becker-bin/` is gitignored.
- C ABI: `becker_capi_*` (v1) — load(model_dir, lang) / transcribe_pcm /
  free_string / free. `becker_engine.py` mirrors this; bump both together.
  fp16/CPU selection and the CUDA-EP memory options (arena kSameAsRequested,
  capped cuDNN conv workspace) are env-driven (`BECKER_FP16`, `BECKER_CPU`),
  so the ABI did not change.

## Constraints

- No live audio capture in tests; use fixtures.
- Model downloads are pinned and first-use downloads are preserved — do not
  re-add unconditional fetches.
- Community exports must stay sanitized and must keep internal planning files
  out of the export surface.
