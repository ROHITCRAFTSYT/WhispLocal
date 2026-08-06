"""Live partial-transcription coordinator.

Uses a fake audio source (scripted snapshots) and a fake engine (scripted
transcripts) so the scheduling/dedup logic is exercised with no device or model.
Covers the emit gate (too-short, no-growth, None), interim emission, unchanged-
text dedup, engine-error suppression, and a clean start()/stop() lifecycle.
"""
import os
import sys
import threading
import time
import unittest

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "whisp"))

from streaming import StreamingTranscriber  # noqa: E402


class FakeSource:
    def __init__(self, snapshots):
        self._snapshots = list(snapshots)
        self.calls = 0

    def snapshot(self):
        self.calls += 1
        return self._snapshots.pop(0) if self._snapshots else None


class FakeEngine:
    def __init__(self, texts):
        self._texts = list(texts)
        self.seen = []

    def transcribe(self, audio, task="transcribe", hotwords=None, language=None):
        self.seen.append((len(audio), task, hotwords, language))
        text = self._texts.pop(0) if self._texts else ""
        return text, "en", 0.9


def _audio(n):
    return np.zeros(n, dtype=np.float32)


class ShouldEmitTests(unittest.TestCase):
    def _st(self, min_seconds=0.6):
        return StreamingTranscriber(FakeSource([]), FakeEngine([]), lambda t: None,
                                    min_seconds=min_seconds, sample_rate=16000)

    def test_none_audio_never_emits(self):
        self.assertFalse(self._st()._should_emit(None))

    def test_too_short_does_not_emit(self):
        st = self._st(min_seconds=0.6)  # needs >= 9600 samples
        self.assertFalse(st._should_emit(_audio(4000)))

    def test_requires_growth_over_last_pass(self):
        st = self._st(min_seconds=0.1)  # needs >= 1600 samples
        self.assertTrue(st._should_emit(_audio(2000)))
        st._last_len = 2000
        self.assertFalse(st._should_emit(_audio(2000)))   # no growth
        self.assertTrue(st._should_emit(_audio(2500)))    # grew


class RunOnceTests(unittest.TestCase):
    def test_emits_interim_text_on_growth(self):
        got = []
        st = StreamingTranscriber(
            FakeSource([_audio(20000)]), FakeEngine(["hello world"]),
            got.append, min_seconds=0.1)
        st._run_once()
        self.assertEqual(got, ["hello world"])

    def test_dedups_unchanged_text(self):
        got = []
        st = StreamingTranscriber(
            FakeSource([_audio(20000), _audio(30000)]),
            FakeEngine(["same", "same"]), got.append, min_seconds=0.1)
        st._run_once()
        st._run_once()
        self.assertEqual(got, ["same"])  # second identical partial suppressed

    def test_engine_error_is_swallowed(self):
        got = []

        class Boom:
            def transcribe(self, *a, **k):
                raise RuntimeError("model busy")

        st = StreamingTranscriber(FakeSource([_audio(20000)]), Boom(),
                                  got.append, min_seconds=0.1)
        st._run_once()  # must not raise
        self.assertEqual(got, [])

    def test_passes_task_and_hotwords_through(self):
        st = StreamingTranscriber(
            FakeSource([_audio(20000)]), FakeEngine(["x"]), lambda t: None,
            min_seconds=0.1, hotwords_fn=lambda: "Claude Obsidian", language="hi")
        st._task = "translate"
        st._run_once()
        _, task, hot, lang = st._engine.seen[0]
        self.assertEqual(task, "translate")
        self.assertEqual(hot, "Claude Obsidian")
        self.assertEqual(lang, "hi")


class LifecycleTests(unittest.TestCase):
    def test_start_then_stop_terminates_thread(self):
        st = StreamingTranscriber(FakeSource([]), FakeEngine([]), lambda t: None,
                                  interval=0.01)
        st.start()
        time.sleep(0.05)
        st.stop(timeout=1.0)
        self.assertNotIn(st._thread, threading.enumerate())
        self.assertIsNone(st._thread)


if __name__ == "__main__":
    unittest.main()
