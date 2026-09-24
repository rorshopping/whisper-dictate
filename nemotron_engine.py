"""NVIDIA Nemotron Speech Streaming ASR engines.

Whisper Dictate's default engine is faster-whisper. This module adds an
alternative engine for profiles that set ``"engine": "nemotron"``:

* English: ``nvidia/nemotron-speech-streaming-en-0.6b`` (English-only)
* Multilingual: ``nvidia/nemotron-3.5-asr-streaming-0.6b`` (40 locales,
  conditioned on an explicit language prompt so it never auto-detects)

Both are cache-aware FastConformer-RNNT models with native punctuation and
capitalization.

The wrapper mimics the slice of the faster-whisper ``WhisperModel`` API that
main.py uses (``transcribe(audio, **kwargs) -> (segments, info)``), so the rest
of the app - recording, status pill, typing, history - stays unchanged.

Model IDs are resolved through :mod:`model_manager` to a pinned local
snapshot before loading.  A complete explicit ``local_model_path`` (or a
``ResolvedModel``/``ModelManager`` supplied by an embedding application) is
loaded with ``local_files_only=True``.  The language remains an explicit
profile setting; the resolver never swaps in another checkpoint or language.

Requires: torch (CUDA build recommended) and transformers>=5.13.
"""

import logging
import os
import re
import time
import warnings

import numpy as np

SAMPLE_RATE = 16000
DEFAULT_MODEL = "nvidia/nemotron-speech-streaming-en-0.6b"

# The checkpoints' encoder position embedding caps a clip at
# config.max_position_embeddings frames (5000 = ~6.7 min at 80 ms/frame);
# anything longer raises ValueError inside generate() and the dictation is
# lost. Transcribe in chunks safely below the cap - this also keeps peak
# VRAM flat on small GPUs.
MAX_CHUNK_S = 330.0
# When a chunk must be cut, search this many seconds before the hard limit
# for the quietest frame, so the split lands between phrases not mid-word.
_SPLIT_SEARCH_S = 30.0

# Language tags the multilingual model can append in "auto" mode (e.g.
# "<de-DE>"); a special token, stripped by skip_special_tokens, but remove any
# straggler defensively.
_LANG_TAG_RE = re.compile(r"<[a-zA-Z]{2}(?:-[a-zA-Z]{2,4})?>")


class Segment:
    """Minimal faster-whisper Segment stand-in (only ``.text`` is used)."""

    __slots__ = ("text",)

    def __init__(self, text):
        self.text = text


class NemotronModel:
    """Transcription with a Nemotron streaming RNNT model.

    Clips longer than the encoder's position limit (MAX_CHUNK_S) are split at
    the quietest frame near the limit and transcribed chunk by chunk; the
    chunk texts are joined with spaces.

    ``transcribe()`` keeps the faster-whisper signature. Whisper-only options
    are accepted and ignored on purpose:

    * ``beam_size`` - RNNT uses greedy decoding (no beam search).
    * ``hotwords`` - the HF integration has no vocabulary biasing; use
      ``corrections-*.txt`` for deterministic fixes instead.
    * ``condition_on_previous_text`` - the decoder has no prompt slot at all.

    ``language`` selects the language prompt on the multilingual
    ``nemotron-3.5`` model (e.g. ``de`` or ``de-DE``); passing it explicitly
    disables the model's auto-detection. The English-only checkpoint has no
    prompt conditioning and ignores it.

    ``vad_filter`` is honored with a conservative energy gate that only trims
    quiet audio before the first and after the last speech frame (faster-whisper
    profiles use Silero VAD; this avoids pulling a second VAD dependency in).
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
        self._multilingual = False
        self._manifest_languages = ()
        self._resolved_model = None
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

        The old constructor accepted a Hugging Face ID directly.  That form
        still works, but IDs now go through the pinned resolver first.  A
        caller can pass an already-resolved object, a manager, or a manager
        configuration without changing the profile/engine interface.
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
            # A config entry that names only a local directory should not fall
            # back to the constructor's default model ID.
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

        # A pre-resolved snapshot is useful to embedders and focused tests.  Do
        # not silently accept one whose identity disagrees with the profile.
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
                # Accept a serializable manager configuration as a small
                # convenience for config-driven launchers.  A bare manifest
                # mapping is also accepted.
                if "required_files" in manager and "revision" in manager:
                    manager = ModelManager(manifest=manager)
                else:
                    manager = ModelManager(**manager)
            elif not isinstance(manager, ModelManager):
                if not hasattr(manager, "resolve"):
                    raise TypeError("resolver must be a ModelManager or ResolvedModel")
                # A small adapter is intentionally supported for applications
                # that expose a compatible fake in tests.
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
            "Nemotron: resolved pinned model "
            f"'{resolved.manifest.model_id}'@{resolved.manifest.revision} "
            f"from {resolved.source} ({resolved.path})"
        )
        if resolved.trace:
            trace = " -> ".join(
                f"{event.source}:{event.status}" for event in resolved.trace
            )
            self._log(f"Nemotron: model resolution trace: {trace}")

    # -- loading -----------------------------------------------------------

    def _load(self, device, compute_type):
        import torch
        from transformers import AutoModelForRNNT, AutoProcessor

        self._torch = torch
        if device == "cuda" and not torch.cuda.is_available():
            self._log(
                "Nemotron: torch has no CUDA device - falling back to CPU "
                "(install the CUDA build of torch for GPU transcription)"
            )
            device = "cpu"
        # transformers has no int8 path here; CUDA runs fp16, CPU runs fp32.
        self.dtype = (
            torch.float32
            if device == "cpu" or compute_type == "float32"
            else torch.float16
        )
        self.device = torch.device(device)

        t0 = time.time()
        # Resolved snapshots are always local.  Passing local_files_only keeps
        # a misconfigured cache or a stale revision from silently reaching the
        # network during a load; revision remains attached for auditing.
        load_path = os.fspath(self.model_path)
        load_kwargs = {
            "local_files_only": True,
            "revision": self.model_revision,
            "trust_remote_code": False,
        }
        self.processor = AutoProcessor.from_pretrained(load_path, **load_kwargs)
        self.model = AutoModelForRNNT.from_pretrained(
            load_path,
            dtype=self.dtype,
            use_safetensors=True,
            **load_kwargs,
        )
        self.model.to(self.device)
        self.model.eval()
        # Dictation is offline (the whole clip is decoded after release), so
        # there is no latency budget: use the widest right context the
        # checkpoint was trained with - its most accurate setting (1.12 s for
        # both checkpoints; the 3.5 processor otherwise defaults to the 320 ms
        # low-latency operating point).
        set_lookahead = getattr(self.processor, "set_num_lookahead_tokens", None)
        supported = getattr(self.processor, "supported_num_lookahead_tokens", None)
        if set_lookahead and supported:
            set_lookahead(max(supported))
        self._multilingual = self.model.config.model_type == "nemotron3_5_asr"
        if self._multilingual:
            self._log(
                "Nemotron: multilingual checkpoint - transcription is "
                "conditioned on the profile's language prompt"
            )
        self._log(
            f"Nemotron: '{self.model_id}' ready on {self.device} "
            f"({str(self.dtype).replace('torch.', '')}) in {time.time() - t0:.1f}s"
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
        audio = np.asarray(audio, dtype=np.float32).reshape(-1)
        if vad_filter:
            audio = self._trim_silence(audio)
        if audio.size == 0:
            return [], {
                "language": language or "en",
                "language_probability": 1.0,
                "duration": 0.0,
            }

        proc_kwargs = {}
        if self._multilingual:
            # Explicit prompt conditioning: never let the model auto-detect the
            # language for a profile that is meant to transcribe one language.
            proc_kwargs["language"] = self._resolve_language(language)

        chunks = self._split_for_limit(audio)
        texts = []
        for chunk in chunks:
            text = _LANG_TAG_RE.sub(
                "", self._transcribe_chunk(chunk, proc_kwargs)
            ).strip()
            if text:
                texts.append(text)
            if len(chunks) > 1 and self.device.type == "cuda":
                # Free each chunk's scratch buffers so the next starts with a
                # clean slate (peak VRAM stays flat on small GPUs).
                import torch

                torch.cuda.empty_cache()
        text = " ".join(texts)
        segments = [Segment(text)] if text else []
        info = {
            "language": proc_kwargs.get("language", "en"),
            "language_probability": 1.0,
            "duration": audio.size / SAMPLE_RATE,
        }
        return segments, info

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
        # Tie-break toward the latest equally-quiet frame: in sustained
        # silence the cut stays as close to the limit as possible.
        quiet = np.flatnonzero(rms <= rms.min() + 1e-4)
        return min((lo + int(quiet[-1])) * frame, target)

    def _transcribe_chunk(self, audio, proc_kwargs):
        import torch

        inputs = self.processor(
            audio, sampling_rate=SAMPLE_RATE, return_tensors="pt", **proc_kwargs
        )
        inputs = inputs.to(self.device, dtype=self.dtype)
        with torch.no_grad(), warnings.catch_warnings():
            # The model sizes a generous output buffer itself and stops on
            # encoder exhaustion; the generic "set max_new_tokens" hint from
            # generate() does not apply here.
            warnings.filterwarnings(
                "ignore", message="Using the model-agnostic default `max_length`"
            )
            output = self.model.generate(**inputs, return_dict_in_generate=True)
        return self.processor.decode(output.sequences[0], skip_special_tokens=True)

    def _check_language(self, language):
        """Reject a profile language that belongs to another checkpoint."""
        allowed = tuple(getattr(self, "_manifest_languages", ()) or ())
        if not language or not allowed:
            return
        candidate = str(language).strip().lower().replace("_", "-")
        if candidate in {"auto", "multilingual"}:
            raise ValueError(
                f"pinned model {self.model_id!r} requires an explicit language; "
                f"supported languages: {', '.join(allowed)}"
            )
        base = candidate.split("-", 1)[0]
        allowed_bases = {item.split("-", 1)[0] for item in allowed}
        if candidate not in allowed and base not in allowed_bases:
            raise ValueError(
                f"language {language!r} is not supported by pinned model "
                f"{self.model_id!r}; supported languages: {', '.join(allowed)}"
            )

    def _resolve_language(self, language):
        """Map a profile language code to a prompt key the processor accepts."""
        dictionary = self.processor.prompt_dictionary
        if not language:
            raise ValueError(
                f"{self.model_id} requires an explicit language (e.g. 'de'); "
                f"supported: {sorted(dictionary)}"
            )
        candidates = [language]
        if "-" in language:
            candidates.append(language.split("-", 1)[0])
        for cand in candidates:
            if cand in dictionary:
                return cand
        lowered = {key.lower(): key for key in dictionary}
        for cand in candidates:
            if cand.lower() in lowered:
                return lowered[cand.lower()]
        raise ValueError(
            f"Unsupported language {language!r} for {self.model_id}. "
            f"Supported: {sorted(dictionary)}"
        )

    def _trim_silence(self, audio, frame_ms=20, margin_ms=150):
        """Drop the quiet head/tail of a recording; keep everything between.

        Conservative on purpose: the gate scales with the clip's own loudest
        frame, so quiet speech is kept as long as it is clearly above the
        recording's noise floor. Returns an empty array for all-silence input.
        """
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
