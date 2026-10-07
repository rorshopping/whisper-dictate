"""becker-asr engine (becker.dll) for Whisper Dictate.

Adds an engine for profiles that set ``"engine": "becker"``.  Models are the
becker-performant ONNX exports executed by ``becker.dll`` (Rust + ONNX Runtime
CUDA EP, loaded in-process with :mod:`ctypes` — no per-utterance process, the
model is loaded once and reused for every dictation):

* ``nvidia/parakeet-tdt-0.6b-v3`` (TDT transducer): pass ``"model"`` pointing
  at the prepared model directory (encoder-model.onnx, decoder_joint-model.onnx,
  vocab.txt, hann512.f32, mel_fbanks_257x128.f32).
* ``nvidia/nemotron-3.5-asr-streaming-0.6b`` (RNNT + language prompts):
  directory with encoder.onnx, decoder_joint.onnx, vocab.json, languages.json,
  hann512_nemotron.f32, mel_fbanks_257x128.f32.  ``language`` selects the
  prompt ("en", "de", ...).

The wrapper mimics the slice of the faster-whisper ``WhisperModel`` API that
main.py uses (``transcribe(audio, **kwargs) -> (segments, info)``) and a
``close()`` for deterministic unload — the same contract as parakeet_engine.

Runtime discovery (first match wins):

1. the ``BECKER_DLL`` environment variable,
2. ``packaging/becker-bin/becker.dll`` in the app directory.

Unlike parakeet.cpp, becker.dll links the onnxruntime + CUDA/cuDNN DLLs; make
sure onnxruntime.dll's directory and the CUDA 12 / cuDNN 9 runtime directories
are on PATH (see the becker-performant repo README).
"""

import ctypes
import logging
import os
import sys
import threading
import time

import numpy as np

SAMPLE_RATE = 16000

# Same encoder-position rationale as parakeet_engine.MAX_CHUNK_S: chunk safely
# below the position-embedding cap and keep peak VRAM flat on small GPUs.
MAX_CHUNK_S = 330.0
_SPLIT_SEARCH_S = 30.0

_DLL_NAME = "becker.dll" if sys.platform == "win32" else "libbecker.so"
_MIN_ABI = 1


class Segment:
    """Minimal faster-whisper Segment stand-in (only ``.text`` is used)."""

    __slots__ = ("text",)

    def __init__(self, text):
        self.text = text


def _find_library(log):
    candidates = []
    env = os.environ.get("BECKER_DLL")
    if env:
        candidates.append(env)
    roots = []
    if getattr(sys, "frozen", False):
        roots.append(os.path.dirname(sys.executable))
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            roots.append(meipass)
    roots.append(os.path.dirname(os.path.abspath(__file__)))
    roots.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "packaging", "becker-bin"))
    for root in roots:
        candidates.append(os.path.join(root, _DLL_NAME))
    for candidate in candidates:
        if os.path.isfile(candidate):
            return candidate
    searched = ", ".join(candidates)
    raise FileNotFoundError(
        f"becker runtime not found (looked for {_DLL_NAME} in: {searched}). "
        "Set BECKER_DLL or copy the built becker.dll to packaging/becker-bin/."
    )


class BeckerModel:
    """Transcription with a becker-asr ONNX model via becker.dll's C API."""

    def __init__(
        self,
        model_id,
        device="cuda",
        compute_type="auto",
        log=None,
        *,
        language=None,
        **_kwargs,
    ):
        self.model_id = os.fspath(model_id) if isinstance(model_id, os.PathLike) else model_id
        self._requested_language = language
        self._log = log or logging.getLogger(__name__).info
        self._lock = threading.Lock()
        self._ctx = None
        self._lib = None
        self.model_dir = self._resolve_model_dir()
        self._load(device, compute_type)

    # -- model resolution --------------------------------------------------

    def _resolve_model_dir(self):
        target = os.fspath(self.model_id)
        if not os.path.isdir(target):
            raise RuntimeError(
                f"becker engine expects a prepared model directory (with "
                f"vocab.txt or vocab.json), got {target!r}. See the "
                f"becker-performant repo README for model preparation."
            )
        if not (os.path.isfile(os.path.join(target, "vocab.txt")) or os.path.isfile(os.path.join(target, "vocab.json"))):
            raise RuntimeError(f"becker model dir {target!r} has no vocab.txt/vocab.json")
        return target

    # -- loading -----------------------------------------------------------

    def _load(self, device, compute_type):
        dll_path = _find_library(self._log)
        dll_dir = os.path.dirname(os.path.abspath(dll_path))
        try:
            os.add_dll_directory(dll_dir)
        except (AttributeError, OSError):
            pass
        # becker.dll loads onnxruntime.dll by name (ORT_DYLIB_PATH) and the
        # onnxruntime CUDA provider pulls cudart/cublas/cudnn/cufft — register
        # the app venv's pip nvidia wheels (and the bundled runtime dir) before
        # the CDLL call.
        app_root = os.path.dirname(os.path.abspath(__file__))
        for base in (
            os.path.join(app_root, ".venv", "Lib", "site-packages", "nvidia"),
            os.path.join(sys.prefix, "Lib", "site-packages", "nvidia"),
        ):
            for sub in ("cuda_runtime/bin", "cublas/bin", "cudnn/bin", "cufft/bin", "nvjitlink/bin"):
                d = os.path.join(base, sub)
                if os.path.isdir(d):
                    try:
                        os.add_dll_directory(d)
                    except (AttributeError, OSError):
                        pass
                    os.environ["PATH"] = d + os.pathsep + os.environ.get("PATH", "")
        if "ORT_DYLIB_PATH" not in os.environ:
            candidate = os.path.join(dll_dir, "onnxruntime.dll")
            if os.path.isfile(candidate):
                os.environ["ORT_DYLIB_PATH"] = candidate
        t0 = time.time()
        lib = ctypes.CDLL(dll_path)
        lib.becker_capi_abi_version.argtypes = []
        lib.becker_capi_abi_version.restype = ctypes.c_int
        abi = lib.becker_capi_abi_version()
        if abi < _MIN_ABI:
            raise RuntimeError(
                f"becker runtime at {dll_path} reports C API ABI v{abi}; "
                f"v{_MIN_ABI}+ is required"
            )
        lib.becker_capi_load.argtypes = [ctypes.c_char_p, ctypes.c_char_p]
        lib.becker_capi_load.restype = ctypes.c_void_p
        lib.becker_capi_free.argtypes = [ctypes.c_void_p]
        lib.becker_capi_free.restype = None
        lib.becker_capi_transcribe_pcm.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_float),
            ctypes.c_int,
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_void_p),
        ]
        lib.becker_capi_transcribe_pcm.restype = ctypes.c_int
        lib.becker_capi_free_string.argtypes = [ctypes.c_void_p]
        lib.becker_capi_free_string.restype = None
        lib.becker_capi_last_error.argtypes = [ctypes.c_void_p]
        lib.becker_capi_last_error.restype = ctypes.c_char_p

        lang = (self._requested_language or "").encode("utf-8")
        ctx = lib.becker_capi_load(self.model_dir.encode("utf-8"), lang or None)
        if not ctx:
            raise RuntimeError(f"becker: failed to load model dir {self.model_dir!r}")
        self._lib = lib
        self._ctx = ctypes.c_void_p(ctx)
        # ``device``/``compute_type`` accepted for signature parity: the engine
        # uses CUDA automatically when the GPU and runtime DLLs are reachable.
        self._log(
            f"Becker: '{self.model_dir}' ready via {os.path.basename(dll_path)} "
            f"(ABI v{abi}, device={device}) in {time.time() - t0:.1f}s"
        )

    # -- inference ---------------------------------------------------------

    def transcribe(
        self,
        audio,
        language=None,
        beam_size=None,
        hotwords=None,
        vad_filter=False,
        condition_on_previous_text=False,
        **kwargs,
    ):
        # beam_size / hotwords / condition_on_previous_text are accepted and
        # ignored on purpose (transducer greedy decode, no vocabulary biasing);
        # use corrections-*.txt for deterministic fixes.
        audio = np.ascontiguousarray(np.asarray(audio, dtype=np.float32).reshape(-1))
        if vad_filter:
            audio = self._trim_silence(audio)
        if audio.size == 0:
            return [], {
                "language": language or self._requested_language or "en",
                "language_probability": 1.0,
                "duration": 0.0,
            }

        chunks = self._split_for_limit(audio)
        texts = []
        for chunk in chunks:
            text = self._transcribe_chunk(chunk).strip()
            if text:
                texts.append(text)
        text = " ".join(texts)
        segments = [Segment(text)] if text else []
        info = {
            "language": language or self._requested_language or "en",
            "language_probability": 1.0,
            "duration": audio.size / SAMPLE_RATE,
        }
        return segments, info

    def _transcribe_chunk(self, audio):
        assert audio.dtype == np.float32 and audio.flags["C_CONTIGUOUS"]
        ptr = audio.ctypes.data_as(ctypes.POINTER(ctypes.c_float))
        out = ctypes.c_void_p()
        with self._lock:
            rc = self._lib.becker_capi_transcribe_pcm(
                self._ctx, ptr, audio.size, SAMPLE_RATE, ctypes.byref(out)
            )
            if rc != 0 or not out:
                err = self._lib.becker_capi_last_error(self._ctx)
                message = err.decode("utf-8", "replace") if err else "unknown error"
                raise RuntimeError(f"becker transcription failed: {message}")
            try:
                raw = ctypes.cast(out, ctypes.c_char_p).value
                return raw.decode("utf-8", "replace") if raw else ""
            finally:
                self._lib.becker_capi_free_string(out)

    def _split_for_limit(self, audio):
        """Split audio so no chunk exceeds the encoder's position limit."""
        limit = int(MAX_CHUNK_S * SAMPLE_RATE)
        if audio.size <= limit:
            return [audio]
        chunks = []
        start = 0
        while audio.size - start > limit:
            cut = self._quiet_cut(audio, start + limit)
            chunks.append(audio[start:cut])
            start = cut
        chunks.append(audio[start:])
        return chunks

    def _quiet_cut(self, audio, target, frame_ms=80):
        """Sample index <= target at the quietest frame of the preceding
        _SPLIT_SEARCH_S, so chunk borders fall in pauses between phrases."""
        frame = int(SAMPLE_RATE * frame_ms / 1000)
        back = int(_SPLIT_SEARCH_S * SAMPLE_RATE)
        lo = max(1, (target - back) // frame)
        hi = max(lo + 1, target // frame)
        window = audio[lo * frame : hi * frame]
        frames = window[: (window.size // frame) * frame].reshape(-1, frame)
        rms = np.sqrt(np.mean(frames**2, axis=1))
        quiet = np.flatnonzero(rms <= rms.min() + 1e-4)
        return min((lo + int(quiet[-1])) * frame, target)

    def _trim_silence(self, audio, frame_ms=20, margin_ms=150):
        """Drop the quiet head/tail of a recording; keep everything between."""
        frame = int(SAMPLE_RATE * frame_ms / 1000)
        frames = audio[: (audio.size // frame) * frame].reshape(-1, frame)
        rms = np.sqrt(np.mean(frames**2, axis=1))
        loud = np.flatnonzero(rms > rms.max() * 0.02 + 1e-4)
        if loud.size == 0:
            return audio
        margin = int(SAMPLE_RATE * margin_ms / 1000)
        start = max(0, int(loud[0]) * frame - margin)
        end = min(audio.size, (int(loud[-1]) + 1) * frame + margin)
        return audio[start:end]

    def close(self):
        with self._lock:
            if self._ctx is not None:
                self._lib.becker_capi_free(self._ctx)
                self._ctx = None
