import types
import unittest

import numpy as np

from nemotron_engine import MAX_CHUNK_S, SAMPLE_RATE, NemotronModel


def make_model():
    """A NemotronModel shell without __init__ (no torch / model download)."""
    return object.__new__(NemotronModel)


def tone(freq, seconds):
    t = np.arange(int(seconds * SAMPLE_RATE), dtype=np.float32) / SAMPLE_RATE
    return (0.5 * np.sin(2 * np.pi * freq * t)).astype(np.float32)


class SplitForLimitTests(unittest.TestCase):
    def test_short_audio_untouched(self):
        m = make_model()
        audio = tone(440, 5)
        chunks = m._split_for_limit(audio)
        self.assertEqual(len(chunks), 1)
        self.assertIs(chunks[0], audio)

    def test_long_audio_chunks_within_limit(self):
        m = make_model()
        audio = tone(440, 700)  # ~11.7 min: well past the ~6.7 min encoder cap
        chunks = m._split_for_limit(audio)
        self.assertGreater(len(chunks), 1)
        limit = int(MAX_CHUNK_S * SAMPLE_RATE)
        for chunk in chunks:
            self.assertLessEqual(chunk.size, limit)
            self.assertGreater(chunk.size, 0)
        self.assertEqual(sum(c.size for c in chunks), audio.size)
        # Chunks reassemble into the original audio: nothing is dropped.
        self.assertTrue(np.array_equal(np.concatenate(chunks), audio))

    def test_cut_lands_in_silence(self):
        m = make_model()
        limit = int(MAX_CHUNK_S * SAMPLE_RATE)
        speech = tone(440, 4)
        audio = np.concatenate(
            [speech, np.zeros(limit + SAMPLE_RATE - speech.size, dtype=np.float32)]
        )
        chunks = m._split_for_limit(audio)
        self.assertEqual(len(chunks), 2)
        # The cut falls in the trailing silence, not mid-tone.
        self.assertLess(np.abs(chunks[0][-SAMPLE_RATE // 10 :]).max(), 1e-6)

    def test_cut_avoids_loud_passage(self):
        m = make_model()
        limit = int(MAX_CHUNK_S * SAMPLE_RATE)
        audio = np.zeros(limit + SAMPLE_RATE, dtype=np.float32)
        start = limit - 10 * SAMPLE_RATE
        audio[start : start + 5 * SAMPLE_RATE] = tone(440, 5)
        chunks = m._split_for_limit(audio)
        self.assertEqual(len(chunks), 2)
        # The whole loud passage stays in the first chunk: the cut moved into
        # the silence after it instead of clipping the tone mid-phrase.
        self.assertGreaterEqual(chunks[0].size, start + 5 * SAMPLE_RATE)


class TranscribeChunkingTests(unittest.TestCase):
    def test_long_audio_transcribed_in_chunks_and_joined(self):
        m = make_model()
        m._multilingual = False
        m.device = types.SimpleNamespace(type="cpu")
        calls = []

        def fake_chunk(audio, proc_kwargs):
            calls.append(audio.size)
            return f" part {len(calls)} "

        m._transcribe_chunk = fake_chunk
        segments, info = m.transcribe(np.zeros(int(700 * SAMPLE_RATE), np.float32))
        self.assertGreater(len(calls), 1)
        limit = int(MAX_CHUNK_S * SAMPLE_RATE)
        for size in calls:
            self.assertLessEqual(size, limit)
        self.assertEqual(segments[0].text, "part 1 part 2 part 3")
        self.assertEqual(info["duration"], 700.0)

    def test_empty_audio(self):
        m = make_model()
        m._multilingual = False
        segments, info = m.transcribe(np.zeros(0, dtype=np.float32))
        self.assertEqual(segments, [])
        self.assertEqual(info["duration"], 0.0)


if __name__ == "__main__":
    unittest.main()
