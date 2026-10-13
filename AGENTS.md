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

## The becker engine (added 2026-10-07, int4 VRAM rewire 2026-10-08, fluid-speech-mini EN 2026-10-13)

The **EN (ctrl+shift+space)** and **DE (ctrl+alt+space)** profiles both run the
becker-performant engine (`engine: "becker"` in `config.json`) — a Rust + ONNX
Runtime engine from the sibling project
`C:\Users\Richard\Documents\Cursor_Projects\llamacpp_becker_performant`
(7–12× faster than the previous transformers engine at equal accuracy,
verified in that repo's `docs/RESULTS.md`).

**VRAM (2026-10-13 state):** the **EN profile runs on the CPU EP**
(`"device": "cpu"` → BECKER_CPU=1): a loaded model holds **0 MB VRAM** by
construction. Since 2026-10-13 EN runs **FluidVoice fluid-speech-mini**
(becker-asr `FluidTdt`): 302 MB on disk, ~4.53% avg WER vs parakeet-v3's
4.86%, far better on background speech (SVQ 11.1% vs 20.4%), and 100% text
parity between the Rust engine and FluidVoice's reference `transcribe.py` on
the 6-clip bench corpus (incl. 4x/10x repetition long clips). CPU latency:
~0.42–0.75 s for 2–13.5 s dictation, RTF 0.046 on 112 s (fp32 parakeet was
~0.12–0.57 s; mini pays a ~0.4 s fixed encoder overhead, so short clips are
~2–3x slower — both are sub-second). **Do not put mini on the CUDA EP**: its
2-bit MatMulNBits graphs silently return *empty text* on GPU (verified on ORT
1.28), and the CPU EP is the zero-VRAM posture anyway. The **DE profile stays
on the GPU int4 export** (`nemotron35-int4`, ~1.0 GiB; its CPU EP needs 8.6 s
per 10 s clip — 35 streaming chunk passes). After the idle unload the process
holds 0 MB (`unload_models()` → `becker_engine.reset_cuda_device()` →
`cudaDeviceReset()`; skipped when only cpu profiles ever loaded). Profile
knobs: `"fp16"` (null = auto-detect fp16 graphs), `"device": "cpu"` / default
GPU. Reverting EN to parakeet: point the profile back at `parakeet-v3-onnx`
(still prepared) and keep `"device": "cpu"`.

- App side: `becker_engine.py` (ctypes wrapper mirroring `parakeet_engine.py`'s
  API slice) + the `becker` branch in `main.py`'s model-load block. Profiles
  set `"model"` to a **prepared model directory** (contains `vocab.txt` or
  `vocab.json`), not a Hugging Face id — the resolver is bypassed.
- Model dirs (sibling repo `engine-rs\models\`, gitignored there): EN uses
  `fluid-speech-mini-onnx` — FluidVoice-Labs' HF download of the ONNX port
  plus raw assets generated once by the sibling repo's
  `bench\prepare_fluid_mini.py` (`vocab.txt` derived from tokenizer.json,
  `mel_fbanks_257x128.f32` from mel_filters.npy, `hann512_fluid.f32`). The
  becker-asr family auto-detects it by `encoder.onnx` being present without
  `vocab.json`. DE uses `nemotron35-int4` (encoder MatMuls int4-quantized,
  convs fp16; built by `bench\quantize_int4_stream.py nemotron` from
  `nemotron35-onnx`). `parakeet-v3-onnx` (fp32) stays prepared as the EN
  fallback — note parakeet int4 loses the tail of ~112 s continuous audio
  (0.64 agreement), while fluid-speech-mini transcribes all 10 repetitions of
  that clip correctly. If the sibling repo moves, update `config.json`.
- Runtime side: `packaging/becker-bin/` holds `becker.dll` (built by
  `engine-rs\build-msvc.bat` in the sibling repo; copy
  `engine-rs\target\release\becker.dll` there after rebuilding) plus
  `onnxruntime.dll` + `onnxruntime_providers_*.dll` (ORT **1.28.0** GPU build
  since 2026-10-13 — fluid's 2-bit MatMulNBits CPU kernels need ≥1.28, the
  bundled 1.22 only did 4b/8b; the old set is kept in `ort-1.22-backup/`;
  nemotron int4 verified byte-identical on 1.28). cuDNN/cuFFT/nvJitLink come
  from the app venv's pip `nvidia-*` wheels; `becker_engine.py` registers
  those directories and sets `ORT_DYLIB_PATH` itself. `packaging/becker-bin/`
  is gitignored.
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
