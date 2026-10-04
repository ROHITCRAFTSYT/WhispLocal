"""Never lose a dictation.

- LastTake keeps the most recent recording on disk, encrypted with
  Windows DPAPI (only your Windows account can decrypt it), so a take
  that failed to transcribe or paste can be retried from the tray. It
  holds a single take, expires after a day, and is wiped in incognito
  mode or when retention is turned off.
- Ledger remembers the last text that was inserted, so "Paste last
  dictation" can put it down again if it landed in the wrong window.
"""
import ctypes
import json
import os
import struct
import sys
import threading
import time
from ctypes import wintypes

MAX_AGE_S = 24 * 3600
_MAGIC = b"WLT1"


class _BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD),
                ("pbData", ctypes.POINTER(ctypes.c_char))]


def _blob(data):
    buf = ctypes.create_string_buffer(data, len(data))
    return _BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), buf


def protect(data):
    """Encrypt bytes for the current Windows user (DPAPI)."""
    if sys.platform != "win32":
        raise OSError("DPAPI is only available on Windows")
    src, _keep = _blob(data)
    out = _BLOB()
    if not ctypes.windll.crypt32.CryptProtectData(
            ctypes.byref(src), "WhispLocal take", None, None, None, 0x1,
            ctypes.byref(out)):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(out.pbData)


def unprotect(data):
    if sys.platform != "win32":
        raise OSError("DPAPI is only available on Windows")
    src, _keep = _blob(data)
    out = _BLOB()
    if not ctypes.windll.crypt32.CryptUnprotectData(
            ctypes.byref(src), None, None, None, None, 0x1,
            ctypes.byref(out)):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(out.pbData)


class LastTake:
    def __init__(self, app_dir, max_age=MAX_AGE_S):
        self.path = os.path.join(app_dir, "recovery", "last_take.bin")
        self.max_age = max_age
        self._lock = threading.Lock()

    def save(self, audio, meta=None):
        """Store a float32 16 kHz recording (overwrites the previous one)."""
        import numpy as np
        pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype("<i2").tobytes()
        header = json.dumps({"saved": time.time(), **(meta or {})}).encode()
        payload = _MAGIC + struct.pack("<I", len(header)) + header + pcm
        blob = protect(payload)
        with self._lock:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "wb") as f:
                f.write(blob)
            os.replace(tmp, self.path)

    def load(self):
        """(audio, meta) or (None, None) when absent, expired or unreadable."""
        with self._lock:
            try:
                with open(self.path, "rb") as f:
                    payload = unprotect(f.read())
            except (OSError, ValueError):
                return None, None
        if payload[:4] != _MAGIC:
            return None, None
        (n,) = struct.unpack("<I", payload[4:8])
        meta = json.loads(payload[8:8 + n])
        if time.time() - meta.get("saved", 0) > self.max_age:
            self.clear()
            return None, None
        import numpy as np
        pcm = np.frombuffer(payload[8 + n:], dtype="<i2")
        return pcm.astype(np.float32) / 32767.0, meta

    def exists(self):
        return os.path.exists(self.path)

    def clear(self):
        with self._lock:
            try:
                os.remove(self.path)
            except OSError:
                pass


class Ledger:
    """The last inserted text, in memory only."""

    def __init__(self):
        self.text = ""
        self.app = ""
        self.ts = 0.0

    def record(self, text, app=""):
        self.text, self.app, self.ts = text, app, time.time()

    def last(self):
        return self.text
