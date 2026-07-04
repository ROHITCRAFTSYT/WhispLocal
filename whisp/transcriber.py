"""Local speech-to-text via faster-whisper (CTranslate2, int8 on CPU).

The model loads lazily on first use and stays resident so later
transcriptions skip the ~2-5s load cost.
"""
import os
import threading


class Transcriber:
    def __init__(self, config):
        self.model_name = config.get("model", "base")
        self.language = config.get("language") or None  # None = auto-detect
        self.beam_size = int(config.get("beam_size", 2))
        self.cpu_threads = int(config.get("cpu_threads", 0)) or (os.cpu_count() or 4)
        self._model = None
        self._lock = threading.Lock()

    def load(self):
        with self._lock:
            if self._model is None:
                from faster_whisper import WhisperModel

                self._model = WhisperModel(
                    self.model_name,
                    device="cpu",
                    compute_type="int8",
                    cpu_threads=self.cpu_threads,
                )
        return self._model

    def transcribe(self, audio, task="transcribe"):
        """audio: float32 numpy array at 16 kHz. Returns plain text.
        task="translate" outputs English regardless of spoken language."""
        model = self.load()
        segments, _info = model.transcribe(
            audio,
            task=task,
            # Translation needs auto language detection to work broadly.
            language=None if task == "translate" else self.language,
            beam_size=self.beam_size,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 400},
            condition_on_previous_text=False,
        )
        return " ".join(seg.text.strip() for seg in segments).strip()
