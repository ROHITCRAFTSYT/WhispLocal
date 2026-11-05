"""Microphone open failures: PortAudio errors become a MicrophoneError with
an actionable hint, a configured device is re-resolved at every open (so an
unplug/replug cannot point at the wrong index), the device list is refreshed
once before giving up, a broken configured mic falls back to the system
default, and the auto-select probe never falls back. sounddevice is mocked;
needs numpy + sounddevice installed (skipped otherwise)."""
import os
import sys
from unittest import mock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "whisp"))

np = pytest.importorskip("numpy")
sd = pytest.importorskip("sounddevice")

import audio  # noqa: E402
from audio import MicrophoneError, Recorder, explain_device_error  # noqa: E402


class PortAudioError(Exception):
    """Same shape as sounddevice.PortAudioError: (message, code, host_info)."""


class FakeStream:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.closed = False

    def start(self):
        pass

    def stop(self):
        pass

    def close(self):
        self.closed = True


class FakeAudio:
    """A scripted device table. ``broken`` holds device indices (None =
    default) that refuse to open."""

    def __init__(self, devices, broken=()):
        self.devices = devices
        self.broken = set(broken)
        self.opened = []
        self.refreshes = 0

    def query_devices(self, device=None, kind=None):
        if device is None:
            return self.devices
        return self.devices[device]

    def input_stream(self, **kwargs):
        dev = kwargs.get("device")
        if dev in self.broken:
            raise PortAudioError("Error opening InputStream: Device unavailable",
                                 -9985)
        self.opened.append(dev)
        return FakeStream(**kwargs)

    def refresh(self):
        self.refreshes += 1
        return True

    def patch(self):
        return mock.patch.multiple(
            "audio", refresh_devices=self.refresh,
            sd=mock.Mock(query_devices=self.query_devices,
                         InputStream=self.input_stream))


DEVICES = [
    {"name": "Realtek Microphone", "max_input_channels": 1,
     "default_samplerate": 16000},
    {"name": "USB Headset Mic", "max_input_channels": 1,
     "default_samplerate": 16000},
]


def test_device_is_re_resolved_at_every_open():
    fake = FakeAudio(list(DEVICES))
    with fake.patch():
        rec = Recorder("USB Headset")
        rec.start()
        rec.abort()
        # The headset was unplugged and replugged: now it is index 0.
        fake.devices = [DEVICES[1], DEVICES[0]]
        rec.start()
        rec.abort()
    assert fake.opened == [1, 0]
    assert not rec.using_fallback


def test_refresh_then_retry_recovers_hot_plug():
    fake = FakeAudio(list(DEVICES), broken={1})

    def refresh():
        fake.refreshes += 1
        fake.broken.clear()  # after re-init, the device opens
        return True

    with fake.patch(), mock.patch("audio.refresh_devices", refresh):
        rec = Recorder("USB Headset")
        rec.start()
    assert fake.refreshes == 1
    assert fake.opened == [1]
    assert not rec.using_fallback
    rec.abort()


def test_broken_configured_mic_falls_back_to_default():
    fake = FakeAudio(list(DEVICES), broken={1})
    with fake.patch():
        rec = Recorder("USB Headset")
        rec.start()
    assert fake.opened == [None]
    assert rec.using_fallback and rec.active
    rec.abort()


def test_missing_configured_mic_uses_default_and_says_so():
    fake = FakeAudio([DEVICES[0]])
    with fake.patch():
        rec = Recorder("Unplugged Mic")
        rec.start()
    assert fake.opened == [None]
    assert rec.using_fallback
    rec.abort()


def test_everything_broken_raises_microphone_error():
    fake = FakeAudio(list(DEVICES), broken={0, 1, None})
    with fake.patch():
        rec = Recorder("USB Headset")
        with pytest.raises(MicrophoneError) as info:
            rec.start()
    assert "busy" in str(info.value)
    assert isinstance(info.value.__cause__, PortAudioError)
    assert not rec.active  # no half-open stream left behind
    # And the recorder still works once the device recovers.
    fake.broken.clear()
    with fake.patch():
        rec.start()
    assert rec.active
    rec.abort()


def test_probe_mode_never_falls_back():
    fake = FakeAudio(list(DEVICES), broken={1})
    with fake.patch():
        rec = Recorder("USB Headset", fallback_to_default=False)
        with pytest.raises(MicrophoneError):
            rec.start()
        with pytest.raises(MicrophoneError):
            Recorder("Not There", fallback_to_default=False).start()
    assert fake.opened == []
    assert fake.refreshes == 0


def test_scan_does_not_report_a_broken_device_as_working():
    # Device 0 cannot open. If its probe fell back to the default mic, the
    # scan would measure the default and could report device 0 as working.
    fake = FakeAudio([DEVICES[1], DEVICES[0]], broken={0})
    with fake.patch(), mock.patch("audio.time.sleep"):
        assert audio.scan_mics(seconds=0) is None  # nothing delivered audio
    assert fake.opened == [1]  # only the openable device was probed
    assert fake.refreshes == 0


@pytest.mark.parametrize("exc,needle", [
    (PortAudioError("Error querying device -1", -9996), "No microphone found"),
    (PortAudioError("No default input device available", -9996), "No microphone"),
    (PortAudioError("Invalid device [PaErrorCode -9996]", -9996), "not available"),
    (PortAudioError("Device unavailable", -9985), "busy"),
    (PortAudioError("Unanticipated host error [MME error 1]", -9999), "blocked"),
    (OSError("Access is denied."), "blocked"),
    (PortAudioError("Invalid sample rate", -9997), "sample rate"),
    (PortAudioError("Invalid number of channels", -9998), "sample rate"),
    (RuntimeError("something odd"), "Could not open"),
])
def test_error_classification(exc, needle):
    err = explain_device_error(exc, "USB Headset")
    assert needle in str(err)
    assert err.hint
    assert err.user_message().startswith(str(err))


def test_refresh_devices_swallows_errors():
    with mock.patch.object(audio.sd, "_terminate", side_effect=RuntimeError("x")):
        assert audio.refresh_devices() is False
