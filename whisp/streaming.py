"""Live partial transcription.

While the key is still held, transcribe the growing recording buffer every so
often and surface the interim text, so words appear before the key is released.
The final, authoritative transcription still runs once on the complete audio
when recording stops — partials are a preview, never the saved record.

StreamingTranscriber is decoupled from the concrete Recorder/Transcriber: it
only needs a ``source`` exposing ``snapshot() -> audio | None`` and an ``engine``
exposing ``transcribe(audio, task=, hotwords=, language=) -> (text, lang, prob)``.
That keeps it unit-testable with fakes — no audio device or model required.
"""
from __future__ import annotations

import threading


class StreamingTranscriber:
    def __init__(
        self,
        source,
        engine,
        on_partial,
        *,
        interval: float = 0.7,
        min_seconds: float = 0.6,
        sample_rate: int = 16000,
        hotwords_fn=None,
        language=None,
    ):
        self._source = source
        self._engine = engine
        self._on_partial = on_partial
        self._interval = interval
        self._min_samples = int(min_seconds * sample_rate)
        self._hotwords_fn = hotwords_fn
        self._language = language
        self._stop = threading.Event()
        self._thread = None
        self._task = "transcribe"
        self._last_len = 0
        self._last_text = None

    def start(self, task: str = "transcribe") -> None:
        self._task = task
        self._stop.clear()
        self._last_len = 0
        self._last_text = None
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 1.0) -> None:
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout)

    # ----- internals --------------------------------------------------------
    def _should_emit(self, audio) -> bool:
        """Worth a partial pass only once capture has produced enough audio and
        meaningfully more than the last buffer we transcribed (avoids
        re-transcribing an unchanged buffer)."""
        if audio is None:
            return False
        return len(audio) >= self._min_samples and len(audio) > self._last_len

    def _run_once(self) -> None:
        audio = self._source.snapshot()
        if not self._should_emit(audio):
            return
        self._last_len = len(audio)
        hotwords = self._hotwords_fn() if self._hotwords_fn else None
        try:
            text, _lang, _prob = self._engine.transcribe(
                audio, task=self._task, hotwords=hotwords, language=self._language
            )
        except Exception:
            return  # a failed partial must never disrupt the live recording
        text = (text or "").strip()
        if text and text != self._last_text:
            self._last_text = text
            self._on_partial(text)

    def _loop(self) -> None:
        # wait() returns True when stop() fires within the interval, False on
        # timeout — so the body runs once per interval until we're asked to stop.
        while not self._stop.wait(self._interval):
            self._run_once()
