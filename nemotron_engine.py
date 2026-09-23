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

Requires: torch (CUDA build recommended) and transformers>=5.13.
"""

import logging
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
        self, model_id=DEFAULT_MODEL, device="cuda", compute_type="auto", log=None
    ):
        self.model_id = model_id
        self._log = log or logging.getLogger(__name__).info
        self._multilingual = False
        self._load(device, compute_type)

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
        self.processor = AutoProcessor.from_pretrained(self.model_id)
        self.model = AutoModelForRNNT.from_pretrained(self.model_id, dtype=self.dtype)
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
