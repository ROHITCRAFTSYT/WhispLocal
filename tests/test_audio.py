"""Regression tests for the microphone capture fixes.

Covers:
- resample() converts between sample rates while preserving signal;
- the silence threshold separates real voice from a dead mic;
- the Recorder falls back to the device's native rate when 16 kHz is
  refused, and resolves device names to indices.

These need numpy + sounddevice and are skipped when they are missing so
the CI suite stays stdlib-only.
"""
import os
import sys
import threading
import unittest
from contextlib import ExitStack
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "whisp"))

try:
    import numpy as np
    import sounddevice as sd
    HAVE_AUDIO = True
except ImportError:
    HAVE_AUDIO = False

if HAVE_AUDIO:
    from audio import (Recorder, SAMPLE_RATE, SILENCE_RMS, is_mic_device,
                       rms, resample, scan_mics)


@unittest.skipUnless(HAVE_AUDIO, "numpy/sounddevice not installed")
class ResampleTests(unittest.TestCase):
    def test_identity_rate_returns_input(self):
        x = np.linspace(-1, 1, 16000, dtype=np.float32)
        self.assertIs(resample(x, 16000, 16000), x)

    def test_downsample_48k_to_16k(self):
        # 3 seconds of 48 kHz -> 16000 samples at 16 kHz.
        x = np.sin(np.linspace(0, 40 * np.pi, 48000, dtype=np.float32))
        y = resample(x, 48000, 16000)
        self.assertEqual(len(y), 16000)
        self.assertEqual(y.dtype, np.float32)
        # Signal amplitude survives the interpolation.
        self.assertGreater(np.max(np.abs(y)), 0.5)

    def test_upsample_8k_to_16k(self):
        x = np.ones(8000, dtype=np.float32)
        y = resample(x, 8000, 16000)
        self.assertEqual(len(y), 16000)
        self.assertAlmostEqual(float(np.max(y)), 1.0, places=5)

    def test_rms_levels(self):
        self.assertEqual(rms(np.zeros(16000, dtype=np.float32)), 0.0)
        self.assertLess(rms(np.full(16000, 1e-6, np.float32)), SILENCE_RMS)
        self.assertGreater(rms(np.full(16000, 0.05, np.float32)), SILENCE_RMS)


@unittest.skipUnless(HAVE_AUDIO, "numpy/sounddevice not installed")
class RecorderFallbackTests(unittest.TestCase):
    def test_opens_at_native_rate_when_16k_refused(self):
        rec = Recorder()
        opened = []

        class FakeStream:
            def __init__(self, **kwargs):
                opened.append(kwargs)

            def start(self):
                pass

            def stop(self):
                pass

            def close(self):
                pass

        def fake_input(**kwargs):
            if kwargs["samplerate"] == SAMPLE_RATE:
                raise OSError("Invalid sample rate 16000")
            return FakeStream(**kwargs)

        def fake_query(device=None, kind=None):
            return {"name": "fake mic", "default_samplerate": 48000,
                    "max_input_channels": 1}

        with mock.patch.object(sd, "InputStream", fake_input), \
             mock.patch.object(sd, "query_devices", fake_query):
            rec.start()

        self.assertEqual(rec._sample_rate, 48000)
        self.assertEqual(len(opened), 1)
        self.assertEqual(opened[0]["samplerate"], 48000)
        rec.abort()

    def test_48k_clip_resamples_to_16000_samples_per_second(self):
        # 0.1 s of 48 kHz audio becomes 1600 samples at 16 kHz.
        x = np.full(4800, 0.1, dtype=np.float32)
        y = resample(x, 48000, SAMPLE_RATE)
        self.assertEqual(len(y), 1600)

    def test_stop_returns_none_when_idle(self):
        self.assertIsNone(Recorder().stop())


@unittest.skipUnless(HAVE_AUDIO, "numpy/sounddevice not installed")
class ScanMicsTests(unittest.TestCase):
    def setUp(self):
        # Devices: 0 = working mic, 1 = speaker (must be skipped),
        # 2 = dead mic (digital silence), 3 = broken (cannot open).
        self.devices = [
            {"name": "Realtek Microphone", "max_input_channels": 1,
             "default_samplerate": 48000},
            {"name": "Speakers (USB Audio)", "max_input_channels": 1,
             "default_samplerate": 48000},
            {"name": "Dead Mic", "max_input_channels": 1,
             "default_samplerate": 48000},
            {"name": "Broken Mic", "max_input_channels": 1,
             "default_samplerate": 48000},
        ]
        # Signal level each device feeds into its stream callback.
        self.levels = {0: 0.05, 1: 0.9, 2: 0.0}
        self.fail_open = {3}

    def _patch_sd(self):
        class FakeStream:
            def __init__(self, _level=0.0, **_kwargs):
                self._level = _level
                self._callback = _kwargs.get("callback")
                self._thread = None

            def start(self):
                if self._callback:
                    # Deliver audio from a separate thread like real
                    # sounddevice does: Recorder.start() holds the
                    # recorder lock, so an inline callback would deadlock
                    # on the non-reentrant lock in _on_audio.
                    self._thread = threading.Thread(target=self._feed)
                    self._thread.start()

            def _feed(self):
                # 200 ms of audio so stop() has frames to concatenate.
                block = np.full((3200, 1), self._level, dtype=np.float32)
                for _ in range(2):
                    self._callback(block, len(block), None, None)

            def stop(self):
                if self._thread is not None:
                    self._thread.join(timeout=5)

            def close(self):
                pass

        def fake_query(device=None, kind=None):
            if device is None:
                return self.devices
            return self.devices[device]

        def fake_input(**kwargs):
            dev = kwargs.get("device")
            if dev in self.fail_open:
                raise OSError("cannot open device")
            return FakeStream(_level=self.levels.get(dev, 0.0), **kwargs)

        stack = ExitStack()
        stack.enter_context(mock.patch.object(sd, "query_devices", fake_query))
        stack.enter_context(mock.patch.object(sd, "InputStream", fake_input))
        stack.enter_context(mock.patch("audio.time.sleep"))
        return stack

    def test_picks_working_mic_over_silent_and_skips_speaker(self):
        with self._patch_sd():
            name = scan_mics(seconds=0.01)
        self.assertEqual(name, "Realtek Microphone")

    def test_returns_first_working_mic_not_loudest(self):
        # Device 0 is quiet-but-working, device 2 is louder. "First above
        # the silence threshold" wins — not the strongest signal.
        self.levels = {0: 0.001, 2: 0.9}
        with self._patch_sd():
            name = scan_mics(seconds=0.01)
        self.assertEqual(name, "Realtek Microphone")

    def test_returns_none_when_every_mic_is_silent(self):
        self.levels = {0: 0.0, 1: 0.9, 2: 0.0}  # only the speaker "works"
        with self._patch_sd():
            name = scan_mics(seconds=0.01)
        self.assertIsNone(name)

    def test_broken_device_is_skipped(self):
        self.levels = {0: 0.0, 2: 0.0}  # working mic now silent
        self.fail_open = {3}
        with self._patch_sd():
            name = scan_mics(seconds=0.01)
        self.assertIsNone(name)  # no crash, no false positive

    def test_query_error_returns_none(self):
        with mock.patch.object(sd, "query_devices",
                               side_effect=OSError("no audio device")):
            self.assertIsNone(scan_mics())

    def test_is_mic_device_filters_speakers_and_loopbacks(self):
        self.assertTrue(is_mic_device("Realtek Microphone"))
        self.assertFalse(is_mic_device("Speakers (USB Audio)"))
        self.assertFalse(is_mic_device("Stereo Mix (Loopback)"))


if __name__ == "__main__":
    unittest.main()
