"""Insert text into whatever window currently has focus.

Default strategy: save the clipboard, place the text on it, send Ctrl+V,
then restore the original clipboard. Near-instant even for long text.
Fallback strategy ("type") simulates keystrokes — slower but works in
apps that block paste.
"""
import time

import keyboard
import pyperclip


def insert(text, config):
    if not text:
        return
    mode = config.get("insert_mode", "paste")
    if mode == "type":
        # exact=True sends OS-level unicode events, so scripts not on the
        # active keyboard layout (Devanagari, Arabic, CJK...) type correctly.
        keyboard.write(text, delay=0.005, exact=True)
        return

    saved = None
    try:
        saved = pyperclip.paste()
    except Exception:
        pass

    pyperclip.copy(text)
    time.sleep(0.05)
    keyboard.send("ctrl+v")

    if saved is not None and config.get("restore_clipboard", True):
        # Give the target app time to read the clipboard before restoring.
        time.sleep(0.45)
        try:
            pyperclip.copy(saved)
        except Exception:
            pass
