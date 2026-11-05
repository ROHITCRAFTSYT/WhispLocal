"""Microphone capture at 16 kHz mono, the native rate for Whisper models.

Many Windows mics cannot open at 16 kHz directly (they only advertise
44.1/48 kHz). start() tries 16 kHz first and, if the driver refuses,
falls back to the device's native rate, resampling the captured audio to
16 kHz in stop() so the model always receives what it expects.

scan_mics() probes every input device with a short recording and returns
the name of the first one that delivers real audio, so the app can pick
a working microphone instead of trusting a possibly-dead system default.

Opening a device can fail for many reasons on Windows (unplugged since
startup, held in exclusive mode by another app, blocked by the privacy
settings, no input device at all). Recorder.start() retries once after
refreshing PortAudio's device list (hot-plugged headsets), then falls back
from a configured-but-broken device to the system default, and finally
raises MicrophoneError with a message a user can act on.
"""
import threading
import time
from collections import deque

import numpy as np
import sounddevice as sd

from logsetup import get_logger

_log = get_logger("audio")

SAMPLE_RATE = 16000
# Below this RMS (float32, roughly -66 dBFS) the mic is effectively
# silent: muted, the wrong device, or Windows privacy blocking access.
SILENCE_RMS = 0.0005

# Outputs/loopbacks that can masquerade as inputs (max_input_channels > 0,
# sometimes with garbage NaN/inf levels). The scanner must never pick them.
NON_MIC_MARKERS = ("speaker", "output", "stereo mix", "loopback")


class MicrophoneError(RuntimeError):
    """The microphone could not be opened. ``str(err)`` is a short,
    user-facing explanation and ``err.hint`` what to do about it; the
    original exception is chained as ``__cause__``."""

    def __init__(self, message, hint=""):
        super().__init__(message)
        self.hint = hint

    def user_message(self):
        return f"{self}. {self.hint}" if self.hint else str(self)


# PortAudio error codes (portaudio.h, PaErrorCode).
_PA_INVALID_CHANNELS = -9998
_PA_INVALID_SAMPLE_RATE = -9997
_PA_INVALID_DEVICE = -9996
_PA_DEVICE_UNAVAILABLE = -9985
_PA_HOST_ERROR = -9999


def _pa_code(exc):
    """PaErrorCode from a sounddevice.PortAudioError, else None."""
    args = getattr(exc, "args", ())
    if len(args) >= 2 and isinstance(args[1], int):
        return args[1]
    return None


def explain_device_error(exc, device=None):
    """Map a raw open failure to a MicrophoneError with an actionable hint."""
    code = _pa_code(exc)
    text = str(exc).lower()
    which = f"'{device}'" if device else "the default microphone"
    if "no default input" in text or "error querying device -1" in text or \
            "no input device" in text:
        return MicrophoneError(
            "No microphone found",
            "Plug one in, or enable it in Windows Sound settings > Input.")
    if code == _PA_INVALID_DEVICE or "invalid device" in text:
        return MicrophoneError(
            f"Microphone {which} is not available any more",
            "Reconnect it, or pick another one in Settings > Microphone.")
    if code == _PA_DEVICE_UNAVAILABLE or "unavailable" in text or \
            "busy" in text or "in use" in text:
        return MicrophoneError(
            f"Microphone {which} is busy",
            "Close apps using it in exclusive mode, or pick another mic in "
            "Settings > Microphone.")
    if code == _PA_HOST_ERROR or "host error" in text or \
            ("access" in text and "denied" in text):
        return MicrophoneError(
            "Windows blocked microphone access",
            "Settings > Privacy & security > Microphone: turn on 'Let "
            "desktop apps access your microphone'.")
    if code in (_PA_INVALID_SAMPLE_RATE, _PA_INVALID_CHANNELS) or \
            "sample rate" in text or "channels" in text:
        return MicrophoneError(
            f"Microphone {which} does not support mono recording at a usable "
            "sample rate", "Pick another mic in Settings > Microphone.")
    return MicrophoneError(f"Could not open microphone {which}",
                           "Run mic_test.py or see whisp.log for details.")


def refresh_devices():
    """Re-scan audio hardware. PortAudio snapshots the device list when it
    initialises, so a headset plugged in after launch is invisible (and
    indices shift) until it is re-initialised. Only call this while no
    stream is open. Returns True on success."""
    try:
        sd._terminate()
        sd._initialize()
        return True
    except Exception as e:  # private API: never let it break recording
        _log.warning("could not refresh the audio device list: %s", e)
        return False


def is_mic_device(name):
    """True unless the device name marks it as an output or loopback."""
    return not any(m in (name or "").lower() for m in NON_MIC_MARKERS)


def scan_mics(seconds=1.5):
    """Probe input devices in order and return the name of the first one
    that delivers real audio (RMS at or above SILENCE_RMS), or None when
    none does.

    Speakers and loopbacks are skipped; devices that fail to open are
    treated as unusable. Each probe reuses Recorder, so a device that
    only opens at its native sample rate is still measured correctly.
    A result of None means every device was silent or unopenable — the
    mic is muted, Windows privacy is blocking access, or nothing is
    plugged in.
    """
    try:
        devices = sd.query_devices()
    except Exception:
        return None
    for dev in devices:
        if dev.get("max_input_channels", 0) <= 0:
            continue
        name = dev.get("name") or ""
        if not is_mic_device(name):
            continue
        try:
            level = _probe_device(name, seconds)
        except Exception:
            continue  # cannot open -> not a usable mic right now
        if level >= SILENCE_RMS:
            return name
    return None


def _probe_device(name, seconds):
    """Record `seconds` of audio from a device and return its RMS level,
    or 0.0 when it delivered nothing."""
    # No fallback: a probe must measure *this* device, not the default.
    rec = Recorder(name, fallback_to_default=False)
    rec.start()
    try:
        time.sleep(seconds)
    finally:
        audio = rec.stop()
    return rms(audio) if audio is not None else 0.0


def resolve_input_device(name):
    """Map a configured device name to a sounddevice index, or None for
    the system default. A name that matches nothing falls back to the
    default instead of failing every recording."""
    if not name:
        return None
    try:
        for i, dev in enumerate(sd.query_devices()):
            if dev.get("max_input_channels", 0) > 0 and \
                    name.lower() in dev.get("name", "").lower():
                return i
    except Exception:
        pass
    return None


def rms(audio):
    """Root-mean-square level of a float32 array.

    Returns 0.0 for empty input and for non-finite values (NaN/inf can
    appear on broken or loopback devices and must never be treated as a
    real signal, which would bypass the silence check)."""
    if not len(audio):
        return 0.0
    value = float(np.sqrt(np.mean(audio ** 2)))
    return value if np.isfinite(value) else 0.0


def resample(audio, src_rate, dst_rate):
    """Linearly interpolate a mono float32 array between sample rates.
    Returns the input unchanged when the rates already match."""
    if src_rate == dst_rate or len(audio) < 2:
        return audio
    n = max(1, int(round(len(audio) * dst_rate / src_rate)))
    x_old = np.linspace(0.0, 1.0, len(audio))
    x_new = np.linspace(0.0, 1.0, n)
    return np.interp(x_new, x_old, audio).astype(np.float32)


class Recorder:
    def __init__(self, device=None, fallback_to_default=True):
        # Keep the raw configured name for diffing in reload_config;
        # it is re-resolved to a concrete device index at every open, so
        # an unplug/replug (which renumbers devices) cannot point a take
        # at the wrong mic.
        self.device = device
        self.fallback_to_default = fallback_to_default
        self._device_index = resolve_input_device(device)
        # True while the current/last take runs on the system default
        # because the configured device could not be opened.
        self.using_fallback = False
        self._frames = []
        self._stream = None
        self._sample_rate = SAMPLE_RATE
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
            self._open_stream()

    def _open_stream(self):
        """Open the configured mic; on failure refresh the device list and
        retry it once, then fall back to the system default (when allowed).
        Raises MicrophoneError when nothing can be opened."""
        self._device_index = resolve_input_device(self.device)
        # A configured name that matches no device records from the default.
        self.using_fallback = bool(self.device) and self._device_index is None
        if self.using_fallback and not self.fallback_to_default:
            raise MicrophoneError(
                f"Microphone '{self.device}' is not available any more",
                "Reconnect it, or pick another one in Settings > Microphone.")
        if self.using_fallback:
            _log.warning("microphone '%s' not found; using the system default",
                         self.device)
        try:
            self._open_at_best_rate()
            return
        except Exception as first:
            err = first
        if not self.fallback_to_default:
            raise explain_device_error(err, self.device) from err
        _log.warning("could not open %s (%s); refreshing the device list",
                     self.device or "default mic", err)
        if refresh_devices():
            self._device_index = resolve_input_device(self.device)
            self.using_fallback = (bool(self.device)
                                   and self._device_index is None)
            try:
                self._open_at_best_rate()
                _log.info("opened %s after refreshing the device list",
                          self.device or "default mic")
                return
            except Exception as e:
                err = e
        if self.device and self._device_index is not None:
            try:
                self._device_index = None
                self._open_at_best_rate()
                self.using_fallback = True
                _log.warning("microphone '%s' failed (%s); recording from the "
                             "system default instead", self.device, err)
                return
            except Exception as e:
                _log.error("default microphone failed too: %s", e)
        raise explain_device_error(err, self.device) from err

    def _open_at_best_rate(self):
        """Open the current device at 16 kHz, falling back to the device's
        native rate when the driver refuses 16 kHz (common on Windows)."""
        stream = None
        rate = SAMPLE_RATE
        try:
            try:
                stream = self._make_stream(SAMPLE_RATE)
            except Exception:
                native = self._native_rate()
                if native == SAMPLE_RATE:
                    raise
                stream = self._make_stream(native)
                rate = native
            stream.start()
        except Exception:
            # Never leave a half-open or failed stream attached, or every
            # later start() would silently no-op and dictation would stay
            # dead until restart.
            if stream is not None:
                try:
                    stream.close()
                except Exception:
                    pass
            self._stream = None
            raise
        self._stream = stream
        self._sample_rate = rate

    def _make_stream(self, rate):
        return sd.InputStream(
            samplerate=rate,
            channels=1,
            dtype="float32",
            device=self._device_index,
            callback=self._on_audio,
        )

    def _native_rate(self):
        try:
            info = sd.query_devices(self._device_index, "input")
            return int(info.get("default_samplerate") or SAMPLE_RATE)
        except Exception:
            return SAMPLE_RATE

    def _on_audio(self, indata, frames, time_info, status):
        # Guarded by the same lock stop()/abort() use: the callback thread
        # and the hotkey thread otherwise race on _frames, which can drop
        # the tail of a recording or crash np.concatenate mid-iteration.
        with self._lock:
            if self._stream is None:
                return
            self._frames.append(indata.copy())
            self.levels.append(rms(indata[:, 0]))

    def stop(self):
        """Stop capture and return the recording as a 16 kHz float32 numpy
        array, or None when nothing was captured."""
        with self._lock:
            if self._stream is None:
                return None
            # Atomically detach the stream and frames under the lock. Any
            # callback that runs after this sees _stream is None and skips.
            stream = self._stream
            self._stream = None
            frames, self._frames = self._frames, []
            rate = self._sample_rate
        # Outside the lock: Pa_StopStream blocks until the in-flight callback
        # returns, so it must never run while a callback could be waiting on
        # the lock — that would deadlock the hotkey thread.
        try:
            stream.stop()
        finally:
            stream.close()
        if not frames:
            return None
        audio = np.concatenate(frames)[:, 0]
        if rate != SAMPLE_RATE:
            audio = resample(audio, rate, SAMPLE_RATE)
        return audio

    def snapshot(self):
        """Return the audio captured so far as a 16 kHz float32 array without
        stopping capture, or None when nothing has been captured yet.

        Lets a streaming consumer transcribe a growing buffer for live
        partials. The frame list is copied under the lock; each frame is
        already an immutable snapshot (the callback only appends new arrays),
        so the concatenate/resample runs safely outside the lock.
        """
        with self._lock:
            if self._stream is None or not self._frames:
                return None
            frames = list(self._frames)
            rate = self._sample_rate
        audio = np.concatenate(frames)[:, 0]
        if rate != SAMPLE_RATE:
            audio = resample(audio, rate, SAMPLE_RATE)
        return audio

    def abort(self):
        with self._lock:
            if self._stream is None:
                return
            stream = self._stream
            self._stream = None
            self._frames = []
        try:
            stream.stop()
        finally:
            stream.close()
