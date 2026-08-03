"""Diagnose why WhispLocal may not be hearing you.

Lists every input device, then records ~2 seconds from a chosen device
(default: the system default) and prints the measured signal level, so
you can tell whether the mic is delivering audio at all — and at which
sample rate. Use it before blaming the app:

    python mic_test.py            # test the system default input
    python mic_test.py 2          # test the device with index 2
    python mic_test.py --all      # scan EVERY input device (~1.5s each)

All output is ASCII-safe so the Windows console (cp1252) never chokes.
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "whisp"))

try:
    import numpy as np
    import sounddevice as sd
    from audio import SAMPLE_RATE, SILENCE_RMS, is_mic_device, rms
except ImportError as e:
    print(f"Missing dependency: {e}")
    print("WhispLocal needs numpy and sounddevice to capture audio.")
    print("Install them with:  pip install -r requirements.txt")
    sys.exit(1)

SECONDS = 2
SCAN_SECONDS = 1.5


def is_mic(dev):
    """True when the device is a real microphone, not a speaker/loopback.
    Reuses the shared marker list from the audio module so the diagnostic
    and the app's auto-select scan always agree."""
    return is_mic_device(dev.get("name") or "")


def capture(device, rate, seconds=SECONDS):
    frames = int(seconds * rate)
    rec = sd.rec(frames, samplerate=rate, channels=1, dtype="float32",
                 device=device)
    sd.wait()
    return rec[:, 0]


def test_device(device, seconds=SECONDS):
    info = sd.query_devices(device, "input")
    native = int(info.get("default_samplerate") or SAMPLE_RATE)
    print(f"\n=== Testing: {info['name']} ===")
    print(f"    default sample rate: {native} Hz")
    if seconds >= SECONDS:
        print(f"    speak into the mic for {seconds} seconds...\n")
    results = {}
    for rate in (SAMPLE_RATE, native):
        if rate in results:
            continue
        try:
            audio = capture(device, rate, seconds)
            results[rate] = rms(audio)
            print(f"    {rate} Hz  ->  RMS level = {results[rate]:.6f}")
        except Exception as e:
            print(f"    {rate} Hz  ->  could not open: {e}")
    if not results:
        print("    FAILED to open this device at any sample rate.")
        return None
    best = max(results.values())
    if not np.isfinite(best) or best < SILENCE_RMS:
        print("    -> SILENT: this device delivers no audio.")
        print("       Causes: wrong device, mic muted/volume zero, Windows")
        print("       privacy blocking, or another app holding the mic.")
    else:
        print("    -> VOICE DETECTED: this mic works.")
    return best if np.isfinite(best) else 0.0


def main():
    devices = sd.query_devices()
    print("=== Input devices ===")
    for i, dev in enumerate(devices):
        if dev.get("max_input_channels", 0) > 0:
            print(f"  [{i}] {dev['name']}  "
                  f"(default {dev.get('default_samplerate')} Hz)")
    if "--all" in sys.argv:
        print("\nScanning every input device (speak a little during the"
              " scan)...")
        best_dev = None
        best_level = 0.0
        for i, dev in enumerate(devices):
            if dev.get("max_input_channels", 0) <= 0 or not is_mic(dev):
                print(f"  [{i}] {dev.get('name','?')}: skipped "
                      f"(not a microphone)")
                continue
            try:
                level = test_device(i, seconds=SCAN_SECONDS)
            except Exception as e:
                print(f"    [{i}] could not test: {e}")
                continue
            if level is not None and np.isfinite(level) and level > best_level:
                best_level, best_dev = level, i
        print("\n=== Result ===")
        if best_dev is None or best_level < SILENCE_RMS:
            print("No microphone delivered real audio. Check Windows")
            print("privacy (Settings > Privacy & security > Microphone, allow")
            print("desktop apps), make sure the mic is not muted, and that no")
            print("other app has exclusive control of it.")
            sys.exit(1)
        print(f"Best microphone: [{best_dev}] "
              f"{devices[best_dev]['name']} (RMS {best_level:.6f})")
        print("Pick it in WhispLocal Settings > Microphone.")
        sys.exit(0)

    target = None
    if len(sys.argv) > 1:
        try:
            target = int(sys.argv[1])
        except ValueError:
            print(f"Unknown argument '{sys.argv[1]}'. Use an index, or --all.")
            sys.exit(1)
        if not (0 <= target < len(devices)):
            print(f"No device with index {target}.")
            sys.exit(1)
    level = test_device(target)
    print("\nResult:", "PASS - this mic works." if level and level >= SILENCE_RMS
          else "FAIL - no voice detected (see causes above).")
    sys.exit(0 if level and level >= SILENCE_RMS else 1)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"Diagnostic error: {e}")
        print("Is the sounddevice library installed? "
              "Run: pip install -r requirements.txt")
        sys.exit(1)
