"""Soft synthesised sound cues instead of harsh square-wave beeps.

Each cue is a short sequence of sine notes with a smooth attack and an
exponential decay, rendered once into an in-memory WAV and cached. No
sound files ship with the app.
"""
import io
import math
import struct
import threading
import wave

RATE = 22050

# name -> [(frequency Hz, duration s, gain 0..1), ...]
CUES = {
    "start": [(659.25, 0.07, 0.35), (987.77, 0.11, 0.35)],
    "stop": [(987.77, 0.07, 0.3), (659.25, 0.10, 0.3)],
    "done": [(783.99, 0.06, 0.25), (1046.5, 0.12, 0.25)],
    "error": [(220.0, 0.12, 0.4), (174.61, 0.18, 0.4)],
    "edit": [(523.25, 0.06, 0.32), (659.25, 0.06, 0.32), (783.99, 0.10, 0.32)],
    "notify": [(880.0, 0.09, 0.25)],
    "copied": [(1174.66, 0.05, 0.22), (1174.66, 0.07, 0.22)],
}

_cache = {}
_lock = threading.Lock()


def synth(notes, rate=RATE):
    """Render notes to WAV bytes (16-bit mono)."""
    samples = []
    for freq, dur, gain in notes:
        n = int(rate * dur)
        attack = max(1, int(rate * 0.006))
        for i in range(n):
            env = min(1.0, i / attack) * math.exp(-4.0 * i / n)
            # A quiet octave partial gives the tone a softer, bell-like body.
            v = (math.sin(2 * math.pi * freq * i / rate)
                 + 0.25 * math.sin(4 * math.pi * freq * i / rate)) / 1.25
            samples.append(int(max(-1.0, min(1.0, v * env * gain)) * 32767))
        samples.extend([0] * int(rate * 0.012))  # tiny gap between notes
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(struct.pack(f"<{len(samples)}h", *samples))
    return buf.getvalue()


def wav(name):
    with _lock:
        if name not in _cache:
            _cache[name] = synth(CUES[name])
        return _cache[name]


def play(name, enabled=True):
    """Play a cue without blocking the caller."""
    if not enabled or name not in CUES:
        return

    def _run():
        try:
            import winsound
            # SND_MEMORY cannot be combined with SND_ASYNC, so play
            # synchronously on this daemon thread instead.
            winsound.PlaySound(wav(name), winsound.SND_MEMORY)
        except Exception:
            pass

    threading.Thread(target=_run, daemon=True).start()
