"""Regression tests for the transcription layer fixes.

Covers:
- hotwords are passed to faster-whisper when no script primer applies;
- for primer languages (Devanagari etc.) the hotwords are folded into the
  initial prompt instead of being silently dropped;
- the audio Recorder survives concurrent callbacks without losing frames.

Kept stdlib-only like the other tests (no numpy, no audio hardware, no
model), so they run on any CI runner. The numpy-dependent parts are
skipped when numpy is not installed.
"""
import os
import sys
import threading
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "whisp"))

from transcriber import Transcriber, SCRIPT_PRIMERS

try:
    import numpy as np
    HAVE_NUMPY = True
except ImportError:
    HAVE_NUMPY = False


class _FakeSegments:
    def __iter__(self):
        yield type("S", (), {"text": "hello world"})()


class TranscriberHotwordTests(unittest.TestCase):
    def setUp(self):
        self.t = Transcriber({"model": "base", "language": None,
                              "beam_size": 2, "cpu_threads": 2})

    def _fake_model(self):
        m = mock.Mock()
        info = type("I", (), {"language": "en", "language_probability": 0.9})
        m.transcribe.return_value = (_FakeSegments(), info)
        return m

    def test_hotwords_passed_when_no_primer(self):
        model = self._fake_model()
        self.t._model = model  # skip lazy load
        self.t.transcribe([0.0] * 16000, hotwords="myproject jargon")
        kwargs = model.transcribe.call_args.kwargs
        self.assertIsNotNone(kwargs["hotwords"])
        self.assertIn("Claude", kwargs["hotwords"])       # default hints kept
        self.assertIn("myproject", kwargs["hotwords"])    # user hotwords kept
        self.assertIsNone(kwargs["initial_prompt"])

    def test_hotwords_folded_into_prompt_for_primer_language(self):
        model = self._fake_model()
        self.t._model = model
        self.t.language = "hi"  # Hindi uses a Devanagari primer
        self.t.transcribe([0.0] * 16000, hotwords="myproject")
        kwargs = model.transcribe.call_args.kwargs
        # hotwords param must be None (faster-whisper rejects it alongside
        # initial_prompt) but the hints survive inside the prompt text.
        self.assertIsNone(kwargs["hotwords"])
        self.assertIsNotNone(kwargs["initial_prompt"])
        prompt = kwargs["initial_prompt"]
        self.assertIn(SCRIPT_PRIMERS["hi"].split()[0], prompt)
        self.assertIn("myproject", prompt)
        self.assertIn("Claude", prompt)


@unittest.skipUnless(HAVE_NUMPY, "numpy not installed")
class RecorderThreadSafetyTests(unittest.TestCase):
    def test_concurrent_callbacks_do_not_lose_frames(self):
        from audio import Recorder

        rec = Recorder()
        rec._stream = object()  # pretend an active stream so callbacks append
        n_threads, n_chunks, chunk = 8, 50, 160

        def feed():
            data = np.ones((chunk, 1), dtype=np.float32)
            for _ in range(n_chunks):
                rec._on_audio(data, chunk, None, None)

        threads = [threading.Thread(target=feed) for _ in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(rec._frames), n_threads * n_chunks)

        # stop() needs a real stream; simulate the read path instead.
        with mock.patch.object(rec, "_stream", None):
            frames, rec._frames = rec._frames, []
        audio = np.concatenate(frames)[:, 0]
        self.assertEqual(audio.shape[0], n_threads * n_chunks * chunk)

    def test_stop_returns_none_when_idle(self):
        from audio import Recorder

        self.assertIsNone(Recorder().stop())


if __name__ == "__main__":
    unittest.main()
