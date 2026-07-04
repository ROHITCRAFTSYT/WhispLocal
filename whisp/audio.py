"""Microphone capture at 16 kHz mono, the native rate for Whisper models."""
import threading
from collections import deque

import numpy as np
import sounddevice as sd

SAMPLE_RATE = 16000


class Recorder:
    def __init__(self, device=None):
        self.device = device
        self._frames = []
        self._stream = None
        self._lock = threading.Lock()
        # Rolling RMS levels for the live waveform display.
        self.levels = deque(maxlen=40)

    @property
    def active(self):
        return self._stream is not None

    def start(self):
        with self._lock:
            if self._stream is not None:
                return
            self._frames = []
            self.levels.clear()
            self._stream = sd.InputStream(
                samplerate=SAMPLE_RATE,
                channels=1,
                dtype="float32",
                device=self.device,
                callback=self._on_audio,
            )
            self._stream.start()

    def _on_audio(self, indata, frames, time_info, status):
        self._frames.append(indata.copy())
        self.levels.append(float(np.sqrt(np.mean(indata ** 2))))

    def stop(self):
        """Stop capture and return the recording as a float32 numpy array, or None."""
        with self._lock:
            if self._stream is None:
                return None
            try:
                self._stream.stop()
                self._stream.close()
            finally:
                self._stream = None
            if not self._frames:
                return None
            audio = np.concatenate(self._frames)[:, 0]
            self._frames = []
            return audio

    def abort(self):
        with self._lock:
            if self._stream is None:
                return
            try:
                self._stream.stop()
                self._stream.close()
            finally:
                self._stream = None
                self._frames = []
