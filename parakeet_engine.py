"""ggml ASR engine (parakeet.cpp) for Whisper Dictate.

This module adds an alternative engine for profiles that set
``"engine": "parakeet-gguf"``.  Models are ggml GGUF checkpoints executed by
`parakeet.cpp <https://github.com/mudler/parakeet.cpp>`_ through its flat
C API (loaded in-process with :mod:`ctypes` - no per-utterance process, the
model is loaded once and reused for every dictation):

* Multilingual (German default): ``mudler/nemotron-3.5-asr-streaming-0.6b-GGUF``
  - the ggml conversion of the same NVIDIA Nemotron checkpoint the
  transformers engine uses, prompt-conditioned with the profile language.
* English/multilingual: ``mudler/parakeet-tdt-0.6b-v3-GGUF`` - NVIDIA
  parakeet-tdt-0.6b-v3 (25 European languages, native punctuation and
  capitalization).

Both f16 GGUFs are published in the single collection repo
``mudler/parakeet-cpp-gguf`` (converter parity: WER 0 vs NeMo) and resolved
through :mod:`model_manager` to a pinned, hash-verified snapshot exactly like
the transformers models.

The wrapper mimics the slice of the faster-whisper ``WhisperModel`` API that
main.py uses (``transcribe(audio, **kwargs) -> (segments, info)``), so the
rest of the app - recording, status pill, typing, history - stays unchanged.
Whisper-only options (``beam_size``, ``hotwords``,
``condition_on_previous_text``) are accepted and ignored on purpose; use
``corrections-*.txt`` for deterministic fixes instead.

Runtime discovery (first match wins):

1. the ``PARAKEET_GGUF_DLL`` environment variable,
2. next to the frozen executable / ``_internal`` directory (release builds
   bundle ``parakeet.dll`` plus the CUDA runtime DLLs there),
3. ``packaging/parakeet-bin/`` in a source checkout (gitignored; extract the
   parakeet.cpp ``*-lib-win-*.zip`` and ``cudart-*.zip`` release assets).

The CUDA build of ``parakeet.dll`` uses the GPU when one is present and the
cudart DLLs are reachable; otherwise it falls back to CPU.  Like the
transformers engine, clips longer than the encoder's position limit are split
at the quietest frame and transcribed chunk by chunk.
"""

import ctypes
import logging
import os
import sys
import threading
import time

import numpy as np

SAMPLE_RATE = 16000
DEFAULT_MODEL = "mudler/parakeet-tdt-0.6b-v3-GGUF"

# The C API's target_lang entry points (used for prompt-conditioned
# nemotron models) arrived in ABI v3; v0.5.0 ships v6.
MIN_ABI_VERSION = 3

# Same encoder-position rationale as nemotron_engine.MAX_CHUNK_S: chunk safely
# below the position-embedding cap and keep peak VRAM flat on small GPUs.
MAX_CHUNK_S = 330.0
_SPLIT_SEARCH_S = 30.0

_DLL_NAME = "parakeet.dll" if sys.platform == "win32" else "libparakeet.so"


class Segment:
    """Minimal faster-whisper Segment stand-in (only ``.text`` is used)."""

    __slots__ = ("text",)

    def __init__(self, text):
        self.text = text


def _find_library(log):
    """Locate the parakeet runtime shared library."""
    candidates = []
    env = os.environ.get("PARAKEET_GGUF_DLL")
    if env:
        candidates.append(env)
    roots = []
    if getattr(sys, "frozen", False):
        roots.append(os.path.dirname(sys.executable))
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            roots.append(meipass)
    roots.append(os.path.dirname(os.path.abspath(__file__)))
    roots.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "packaging", "parakeet-bin"))
    for root in roots:
        candidates.append(os.path.join(root, _DLL_NAME))
    for candidate in candidates:
        if os.path.isfile(candidate):
            return candidate
    searched = ", ".join(candidates)
    raise FileNotFoundError(
        f"parakeet runtime not found (looked for {_DLL_NAME} in: {searched}). "
        "Set PARAKEET_GGUF_DLL or extract the parakeet.cpp release zips to "
        "packaging/parakeet-bin/."
    )


class ParakeetModel:
    """Transcription with a ggml GGUF model via parakeet.cpp's C API.

    ``transcribe()`` keeps the faster-whisper signature used by main.py.
    ``language`` selects the prompt language for multilingual checkpoints
    (e.g. ``de`` or ``de-DE``); non-prompt models such as
    parakeet-tdt-0.6b-v3 ignore it.  ``vad_filter`` is honored with the same
    conservative energy gate as the transformers engine.
    """

    def __init__(
        self,
        model_id=DEFAULT_MODEL,
        device="cuda",
        compute_type="auto",
        log=None,
        *,
        language=None,
        local_model_path=None,
        model_path=None,
        local_model_dir=None,
        cache_dir=None,
        cache_path=None,
        mirror_url=None,
        huggingface_endpoint=None,
        source_order=None,
        source=None,
        offline=None,
        revision=None,
        manifest=None,
        resolver=None,
        config=None,
        resolver_config=None,
    ):
        self.model_id = os.fspath(model_id) if isinstance(model_id, os.PathLike) else model_id
        self._requested_language = language
        self._log = log or logging.getLogger(__name__).info
        self._lock = threading.Lock()
        self._resolved_model = None
        self._ctx = None
        self._lib = None
        self._resolve_model_reference(
            local_model_path=local_model_path,
            model_path=model_path,
            local_model_dir=local_model_dir,
            cache_dir=cache_dir,
            cache_path=cache_path,
            mirror_url=mirror_url,
            huggingface_endpoint=huggingface_endpoint,
            source_order=source_order,
            source=source,
            offline=offline,
            revision=revision,
            manifest=manifest,
            resolver=resolver,
            config=config,
            resolver_config=resolver_config,
        )
        self._load(device, compute_type)

    # -- model resolution --------------------------------------------------

    def _resolve_model_reference(
        self,
        *,
        local_model_path=None,
        model_path=None,
        local_model_dir=None,
        cache_dir=None,
        cache_path=None,
        mirror_url=None,
        huggingface_endpoint=None,
        source_order=None,
        source=None,
        offline=None,
        revision=None,
        manifest=None,
        resolver=None,
        config=None,
        resolver_config=None,
    ):
        """Resolve the profile model to a verified local snapshot.

        Mirrors the transformers engine's resolver bridge: the same profile
        options work for both engines.  GGUF manifests live in
        :mod:`model_manager`'s default catalog next to the transformers ones.
        """
        from model_manager import (
            ModelManager,
            ModelResolverSettings,
            ResolvedModel,
            load_manifest,
            parse_model_config,
        )

        if config is not None and resolver_config is not None:
            raise ValueError("pass only one of config and resolver_config")
        settings = None
        if isinstance(resolver_config, ModelResolverSettings):
            settings = resolver_config
        elif config is not None or resolver_config is not None:
            raw_config = config if config is not None else resolver_config
            if hasattr(raw_config, "get"):
                settings = parse_model_config(raw_config)
            else:
                raise ValueError("resolver config must be a mapping")

        effective_local_path = local_model_path or model_path
        if effective_local_path is None and isinstance(resolver, (str, os.PathLike)):
            effective_local_path = resolver
            resolver = None
        if effective_local_path is None and settings is not None:
            effective_local_path = settings.local_path
        effective_local_dir = local_model_dir
        if effective_local_dir is None and settings is not None:
            effective_local_dir = settings.local_model_dir
        effective_cache_dir = cache_dir
        if effective_cache_dir is None and settings is not None:
            effective_cache_dir = settings.cache_dir
        effective_cache_path = cache_path
        if effective_cache_path is None and settings is not None:
            effective_cache_path = settings.cache_path
        effective_mirror = mirror_url
        if effective_mirror is None and settings is not None:
            effective_mirror = settings.mirror_url
        effective_hf_endpoint = huggingface_endpoint
        if effective_hf_endpoint is None and settings is not None:
            effective_hf_endpoint = settings.huggingface_endpoint
        effective_order = source_order
        if effective_order is None and settings is not None and source is None:
            effective_order = settings.source_order
        effective_revision = revision
        if effective_revision is None and settings is not None:
            effective_revision = settings.revision
        effective_manifest = manifest
        if effective_manifest is None and settings is not None:
            effective_manifest = settings.manifest
        if isinstance(effective_manifest, (str, os.PathLike)):
            effective_manifest = load_manifest(effective_manifest)
        requested_language = self._requested_language
        if requested_language is None and settings is not None:
            requested_language = settings.language
        effective_model_id = self.model_id
        if settings is not None and settings.model_id:
            effective_model_id = settings.model_id
        elif settings is not None and settings.local_path is not None:
            effective_model_id = settings.local_path
        self.model_id = (
            os.fspath(effective_model_id)
            if isinstance(effective_model_id, os.PathLike)
            else effective_model_id
        )

        if offline is None:
            if settings is not None:
                offline = settings.offline
            else:
                offline = any(
                    os.environ.get(name, "").lower() in {"1", "true", "yes", "on"}
                    for name in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE")
                )

        if isinstance(resolver, ResolvedModel):
            if (
                self.model_id
                and isinstance(self.model_id, str)
                and effective_local_path is None
                and not os.path.isabs(self.model_id)
                and not os.path.exists(self.model_id)
                and resolver.model_id != self.model_id
            ):
                raise ValueError(
                    f"resolved model {resolver.model_id!r} does not match profile {self.model_id!r}"
                )
            resolved = resolver
        else:
            manager = resolver
            if manager is None:
                manager_kwargs = {
                    "offline": bool(offline),
                    "source_order": effective_order,
                    "mirror_url": effective_mirror,
                    "huggingface_endpoint": effective_hf_endpoint,
                    "cache_dir": effective_cache_dir,
                    "cache_path": effective_cache_path,
                    "local_model_dir": effective_local_dir,
                    "max_retries": settings.max_retries if settings is not None else 3,
                    "backoff_factor": settings.backoff_factor if settings is not None else 1.0,
                    "max_backoff": settings.max_backoff if settings is not None else 30.0,
                    "log": self._log,
                }
                if effective_manifest is not None:
                    manager_kwargs["manifest"] = effective_manifest
                manager = ModelManager(**manager_kwargs)
            elif isinstance(manager, dict):
                if "required_files" in manager and "revision" in manager:
                    manager = ModelManager(manifest=manager)
                else:
                    manager = ModelManager(**manager)
            elif not isinstance(manager, ModelManager):
                if not hasattr(manager, "resolve"):
                    raise TypeError("resolver must be a ModelManager or ResolvedModel")
            resolved = manager.resolve(
                self.model_id,
                manifest=effective_manifest,
                revision=effective_revision,
                language=requested_language,
                local_path=effective_local_path,
                source=source,
                source_order=effective_order,
                cache_path=effective_cache_path,
                mirror_url=effective_mirror,
                huggingface_endpoint=effective_hf_endpoint,
                offline=offline,
            )

        self._resolved_model = resolved
        self.model_path = resolved.path
        self.model_revision = resolved.manifest.revision
        self.model_source = resolved.source
        self._model_manifest = resolved.manifest
        self._manifest_languages = resolved.manifest.allowed_languages
        self._log(
            "Parakeet: resolved pinned model "
            f"'{resolved.manifest.model_id}'@{resolved.manifest.revision} "
            f"from {resolved.source} ({resolved.path})"
        )
        if resolved.trace:
            trace = " -> ".join(
                f"{event.source}:{event.status}" for event in resolved.trace
            )
            self._log(f"Parakeet: model resolution trace: {trace}")

    # -- loading -----------------------------------------------------------

    def _gguf_file_path(self):
        """The resolved snapshot's GGUF file.

        The resolver returns the snapshot directory (Hugging Face layout);
        a GGUF manifest pins exactly one required weights file inside it.
        """
        target = self.model_path
        if os.path.isdir(target):
            names = [entry.name for entry in self._model_manifest.required_files]
            if len(names) != 1:
                raise RuntimeError(
                    f"GGUF manifest for {self.model_id!r} must pin exactly one "
                    f"weights file (found {len(names)})"
                )
            target = os.path.join(os.fspath(target), names[0])
        if not os.path.isfile(target):
            raise RuntimeError(f"GGUF weights missing after resolution: {target}")
        self.gguf_path = target
        return target

    def _load(self, device, compute_type):
        dll_path = _find_library(self._log)
        dll_dir = os.path.dirname(os.path.abspath(dll_path))
        try:
            os.add_dll_directory(dll_dir)  # dependencies (cudart, cublas)
        except (AttributeError, OSError):
            pass
        t0 = time.time()
        lib = ctypes.CDLL(dll_path)
        lib.parakeet_capi_abi_version.argtypes = []
        lib.parakeet_capi_abi_version.restype = ctypes.c_int
        abi = lib.parakeet_capi_abi_version()
        if abi < MIN_ABI_VERSION:
            raise RuntimeError(
                f"parakeet runtime at {dll_path} reports C API ABI v{abi}; "
                f"v{MIN_ABI_VERSION}+ is required"
            )
        lib.parakeet_capi_load.argtypes = [ctypes.c_char_p]
        lib.parakeet_capi_load.restype = ctypes.c_void_p
        lib.parakeet_capi_free.argtypes = [ctypes.c_void_p]
        lib.parakeet_capi_free.restype = None
        lib.parakeet_capi_transcribe_pcm_lang.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_float),
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_char_p,
        ]
        lib.parakeet_capi_transcribe_pcm_lang.restype = ctypes.c_void_p
        lib.parakeet_capi_free_string.argtypes = [ctypes.c_void_p]
        lib.parakeet_capi_free_string.restype = None
        lib.parakeet_capi_last_error.argtypes = [ctypes.c_void_p]
        lib.parakeet_capi_last_error.restype = ctypes.c_char_p

        gguf = os.fspath(self._gguf_file_path())
        ctx = lib.parakeet_capi_load(gguf.encode("utf-8", "surrogateescape"))
        if not ctx:
            raise RuntimeError(f"parakeet: failed to load GGUF model {gguf!r}")
        self._lib = lib
        self._ctx = ctypes.c_void_p(ctx)
        # ``device``/``compute_type`` are accepted for signature parity: the
        # runtime picks CUDA automatically when a GPU and its runtime DLLs are
        # available and otherwise runs on CPU.
        self._log(
            f"Parakeet: '{self.model_id}' ready via {os.path.basename(dll_path)} "
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
        self._check_language(language)
        audio = np.ascontiguousarray(np.asarray(audio, dtype=np.float32).reshape(-1))
        if vad_filter:
            audio = self._trim_silence(audio)
        if audio.size == 0:
            return [], {
                "language": language or "en",
                "language_probability": 1.0,
                "duration": 0.0,
            }

        target_lang = self._resolve_language(language)
        chunks = self._split_for_limit(audio)
        texts = []
        for chunk in chunks:
            text = self._transcribe_chunk(chunk, target_lang).strip()
            if text:
                texts.append(text)
        text = " ".join(texts)
        segments = [Segment(text)] if text else []
        info = {
            "language": language or "en",
            "language_probability": 1.0,
            "duration": audio.size / SAMPLE_RATE,
        }
        return segments, info

    def _transcribe_chunk(self, audio, target_lang):
        assert audio.dtype == np.float32 and audio.flags["C_CONTIGUOUS"]
        ptr = audio.ctypes.data_as(ctypes.POINTER(ctypes.c_float))
        lang_bytes = target_lang.encode("utf-8") if target_lang else None
        with self._lock:
            out = self._lib.parakeet_capi_transcribe_pcm_lang(
                self._ctx, ptr, audio.size, SAMPLE_RATE, 0, lang_bytes
            )
            if not out:
                err = self._lib.parakeet_capi_last_error(self._ctx)
                message = err.decode("utf-8", "replace") if err else "unknown error"
                raise RuntimeError(f"parakeet transcription failed: {message}")
            try:
                raw = ctypes.cast(out, ctypes.c_char_p).value
                return raw.decode("utf-8", "replace") if raw else ""
            finally:
                self._lib.parakeet_capi_free_string(out)

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

    def _check_language(self, language):
        """Reject a profile language that belongs to another checkpoint."""
        allowed = tuple(getattr(self, "_manifest_languages", ()) or ())
        if not language or not allowed:
            return
        candidate = str(language).strip().lower().replace("_", "-")
        if candidate in {"auto", "multilingual"}:
            return
        base = candidate.split("-", 1)[0]
        allowed_bases = {item.split("-", 1)[0] for item in allowed}
        if candidate not in allowed and base not in allowed_bases:
            raise ValueError(
                f"language {language!r} is not supported by pinned model "
                f"{self.model_id!r}; supported languages: {', '.join(allowed)}"
            )

    def _resolve_language(self, language):
        """Map the profile language to the C API's ``target_lang``.

        Nemotron prompt dictionaries use locale tags ("de-DE"); parakeet.cpp
        accepts both short codes and locales, and NULL means the model default
        ("auto"), which the non-prompt English models ignore anyway.
        """
        if not language:
            return None
        candidate = str(language).strip()
        return candidate or None

    def _trim_silence(self, audio, frame_ms=20, margin_ms=150):
        """Drop the quiet head/tail of a recording; keep everything between."""
        frame = int(SAMPLE_RATE * frame_ms / 1000)
        n = audio.size // frame
        if n < 2:
            return audio
        rms = np.sqrt(np.mean(audio[: n * frame].reshape(n, frame) ** 2, axis=1))
        peak = float(rms.max())
        floor = max(0.0015, 0.02 * peak)
        active = np.flatnonzero(rms > floor)
        if active.size == 0:
            return audio[:0]
        margin = int(SAMPLE_RATE * margin_ms / 1000)
        start = max(0, int(active[0]) * frame - margin)
        end = min(audio.size, (int(active[-1]) + 1) * frame + margin)
        return audio[start:end]

    # -- unload ------------------------------------------------------------

    def close(self):
        """Release the loaded model (VRAM/RAM is freed by parakeet.cpp)."""
        with self._lock:
            ctx, self._ctx = self._ctx, None
            if ctx is not None and self._lib is not None:
                self._lib.parakeet_capi_free(ctx)

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass
