"""Insert text into whatever window currently has focus.

Default strategy: save the clipboard, place the text on it, send Ctrl+V,
then restore the original clipboard. Near-instant even for long text.
Fallback strategy ("type") simulates keystrokes — slower but works in
apps that block paste.
"""
import ctypes
import sys
import time
from ctypes import wintypes

import keyboard
import pyperclip

_INPUT_KEYBOARD = 1
_KEYEVENTF_KEYUP = 0x0002
_KEYEVENTF_UNICODE = 0x0004
_VK_RETURN = 0x0D
# One character per SendInput call, 20 ms apart. Measured on Windows 11
# Notepad: a 5 ms gap (the old keyboard.write setting) drops and repeats
# characters, batching several characters per call garbles them, and
# emoji (UTF-16 surrogate pairs) need extra settling time.
_CHAR_GAP = 0.02
_WIDE_CHAR_GAP = 0.08


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.c_size_t)]


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG),
                ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("ki", _KEYBDINPUT), ("mi", _MOUSEINPUT)]


class _INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


def _key_events(text):
    """KEYEVENTF_UNICODE down/up pairs; newlines become Enter presses.
    Characters outside the BMP are sent as their UTF-16 surrogate pair."""
    events = []
    for ch in text.replace("\r\n", "\n"):
        if ch == "\n":
            events.append((_VK_RETURN, 0, 0))
            events.append((_VK_RETURN, 0, _KEYEVENTF_KEYUP))
            continue
        data = ch.encode("utf-16-le")
        units = [int.from_bytes(data[i:i + 2], "little")
                 for i in range(0, len(data), 2)]
        # Both halves of a surrogate pair go down before either goes up,
        # so the target composes one character instead of two halves.
        events.extend((0, u, _KEYEVENTF_UNICODE) for u in units)
        events.extend((0, u, _KEYEVENTF_UNICODE | _KEYEVENTF_KEYUP)
                      for u in units)
    return events


def _send_input(events):
    arr = (_INPUT * len(events))()
    for i, (vk, scan, flags) in enumerate(events):
        arr[i].type = _INPUT_KEYBOARD
        arr[i].u.ki = _KEYBDINPUT(vk, scan, flags, 0, 0)
    sent = ctypes.windll.user32.SendInput(len(events), arr,
                                          ctypes.sizeof(_INPUT))
    return sent == len(events)


def type_text(text):
    """Type text as unicode key events, paced so busy apps keep up. Each
    character's down/up (or surrogate pair) goes to SendInput together."""
    if sys.platform == "win32":
        sent = 0
        try:
            for ch in text:
                if not _send_input(_key_events(ch)):
                    raise OSError("SendInput was blocked")
                sent += 1
                time.sleep(_WIDE_CHAR_GAP if ord(ch) > 0xFFFF else _CHAR_GAP)
            return
        except Exception:
            text = text[sent:]  # finish the rest the portable way
    # exact=True sends OS-level unicode events, so scripts not on the
    # active keyboard layout (Devanagari, Arabic, CJK...) type correctly.
    keyboard.write(text, delay=0.02, exact=True)


def insert(text, config):
    if not text:
        return
    mode = config.get("insert_mode", "paste")
    if mode == "type":
        type_text(text)
        return

    saved = None
    try:
        saved = pyperclip.paste()
    except Exception:
        pass

    try:
        pyperclip.copy(text)
    except Exception:
        # Clipboard unavailable (locked by another app): fall back to
        # simulated typing rather than silently dropping the dictation.
        type_text(text)
        return
    time.sleep(0.05)
    keyboard.send("ctrl+v")

    if saved is not None and config.get("restore_clipboard", True):
        # Give the target app time to read the clipboard before restoring.
        time.sleep(0.45)
        try:
            pyperclip.copy(saved)
        except Exception:
            pass
