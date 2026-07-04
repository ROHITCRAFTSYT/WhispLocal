"""Voice-control engine: turns a transcribed sentence into an action.

parse() is pure (regex intent matching, no side effects) so it is unit
testable; execute() performs the action. App launching works from an
index of Start Menu shortcuts built in the background at startup.

Everything runs locally. Deliberately excluded: deleting files, closing
other people's work without a window in focus, and instant shutdown
(shutdown gets a 60-second delay and a voice-cancellable escape hatch).
"""
import ctypes
import difflib
import os
import re
import subprocess
import threading
import time
import webbrowser

# ----- intent table ---------------------------------------------------------

KEY_WORDS = {
    "control": "ctrl", "ctrl": "ctrl", "alt": "alt", "shift": "shift",
    "windows": "windows", "win": "windows", "enter": "enter",
    "return": "enter", "tab": "tab", "escape": "esc", "space": "space",
    "backspace": "backspace", "delete": "delete", "up": "up", "down": "down",
    "left": "left", "right": "right", "home": "home", "end": "end",
}
KEY_WORDS.update({f"f{i}": f"f{i}" for i in range(1, 13)})

SITES = {
    "youtube": "https://www.youtube.com", "google": "https://www.google.com",
    "gmail": "https://mail.google.com", "github": "https://github.com",
    "whatsapp": "https://web.whatsapp.com", "instagram": "https://www.instagram.com",
    "facebook": "https://www.facebook.com", "twitter": "https://x.com",
    "x": "https://x.com", "claude": "https://claude.ai",
    "chatgpt": "https://chatgpt.com", "amazon": "https://www.amazon.in",
    "flipkart": "https://www.flipkart.com", "spotify": "https://open.spotify.com",
    "maps": "https://maps.google.com", "netflix": "https://www.netflix.com",
}

ALIASES = {
    "notepad": "notepad", "calculator": "calc", "paint": "mspaint",
    "command prompt": "cmd", "terminal": "wt", "file explorer": "explorer",
    "explorer": "explorer", "files": "explorer", "task manager": "taskmgr",
    "control panel": "control", "settings": "ms-settings:",
    "recycle bin": "shell:RecycleBinFolder", "camera": "microsoft.windows.camera:",
}

FOLDERS = {
    "downloads": "Downloads", "documents": "Documents", "pictures": "Pictures",
    "music": "Music", "videos": "Videos", "desktop": "Desktop",
}

SHORTCUTS = {
    "copy": ("ctrl+c", "Copied"), "paste": ("ctrl+v", "Pasted"),
    "cut": ("ctrl+x", "Cut"), "undo": ("ctrl+z", "Undone"),
    "redo": ("ctrl+y", "Redone"), "select all": ("ctrl+a", "Selected all"),
    "save": ("ctrl+s", "Saved"), "new tab": ("ctrl+t", "New tab"),
    "close tab": ("ctrl+w", "Tab closed"), "reopen tab": ("ctrl+shift+t", "Tab reopened"),
    "refresh": ("f5", "Refreshed"), "reload": ("f5", "Reloaded"),
    "go back": ("alt+left", "Back"), "go forward": ("alt+right", "Forward"),
    "zoom in": ("ctrl+plus", "Zoomed in"), "zoom out": ("ctrl+-", "Zoomed out"),
    "close window": ("alt+f4", "Window closed"),
    "minimize window": ("win+down", "Minimized"), "minimize": ("win+down", "Minimized"),
    "maximize window": ("win+up", "Maximized"), "maximize": ("win+up", "Maximized"),
    "switch window": ("alt+tab", "Switched"),
    "show desktop": ("win+d", "Desktop"),
    "play": ("play/pause media", "Playing"), "pause": ("play/pause media", "Paused"),
    "next song": ("next track", "Next track"), "next track": ("next track", "Next track"),
    "previous song": ("previous track", "Previous track"),
    "previous track": ("previous track", "Previous track"),
    "mute": ("volume mute", "Muted"), "unmute": ("volume mute", "Unmuted"),
}

_FILLER_PREFIX = re.compile(
    r"^(?:please|hey|ok|okay|jarvis|can you|could you|would you)\s+", re.I)


def _normalize(text):
    t = text.strip().lower()
    t = re.sub(r"[!?,]", "", t).rstrip(".")
    while True:
        t2 = _FILLER_PREFIX.sub("", t)
        if t2 == t:
            return t.strip()
        t = t2


def parse(text):
    """Return (kind, arg, None) or None if the sentence is not a command."""
    t = _normalize(text)
    if not t:
        return None

    m = re.match(r"(?:open|launch|start|run)\s+(?:the\s+)?(?:app\s+)?(.+)", t)
    if m:
        target = m.group(1).strip()
        for name, folder in FOLDERS.items():
            if target in (name, f"{name} folder", f"my {name}"):
                return ("folder", folder, None)
        if "." in target or target.startswith("http"):
            return ("url", target, None)
        return ("open_app", target, None)

    m = re.match(r"go to\s+(.+)", t)
    if m:
        return ("url", m.group(1).strip(), None)

    m = re.match(r"(?:search(?:\s+for)?|google)\s+(.+)", t)
    if m:
        return ("search", m.group(1).strip(), None)

    m = re.match(r"play\s+(.+?)\s+on youtube", t)
    if m:
        return ("youtube", m.group(1).strip(), None)

    m = re.match(r"type\s+(.+)", text.strip(), re.I)  # keep original casing
    if m:
        return ("type", m.group(1).strip(), None)

    m = re.match(r"(?:press|hit)\s+(.+)", t)
    if m:
        words = m.group(1).replace("+", " ").split()
        keys = [KEY_WORDS.get(w, w) for w in words if w != "key"]
        if all(len(k) == 1 or k in KEY_WORDS.values() for k in keys):
            return ("keys", "+".join(keys), None)
        return None

    m = re.match(r"(?:volume|turn (?:it|the volume))\s*(up|down)", t)
    if m:
        return ("volume", m.group(1), None)

    m = re.match(r"scroll\s*(up|down)", t)
    if m:
        return ("scroll", m.group(1), None)

    if t in ("click", "left click"):
        return ("click", "left", None)
    if t == "double click":
        return ("click", "double", None)
    if t == "right click":
        return ("click", "right", None)

    if t in SHORTCUTS:
        return ("shortcut", t, None)

    if re.match(r"(?:take a\s+)?screenshot", t):
        return ("screenshot", None, None)
    if re.match(r"lock (?:the\s+)?(?:screen|computer|pc)", t):
        return ("lock", None, None)
    if re.match(r"(?:shut\s?down|turn off) (?:the\s+)?(?:computer|pc|laptop)", t):
        return ("shutdown", None, None)
    if re.match(r"cancel (?:the\s+)?shut\s?down", t):
        return ("cancel_shutdown", None, None)
    if re.match(r"what(?:'s| is) the time|what time is it", t):
        return ("time", None, None)
    if re.match(r"what(?:'s| is) (?:the date|today's date)|what day is it", t):
        return ("date", None, None)

    return None


# ----- execution -------------------------------------------------------------

class CommandEngine:
    def __init__(self, build_index=True):
        self.app_index = {}
        if build_index:
            threading.Thread(target=self._build_index, daemon=True).start()

    def _build_index(self):
        roots = [
            os.path.join(os.environ.get("ProgramData", ""),
                         r"Microsoft\Windows\Start Menu\Programs"),
            os.path.join(os.environ.get("APPDATA", ""),
                         r"Microsoft\Windows\Start Menu\Programs"),
        ]
        skip = ("uninstall", "help", "readme", "website", "documentation")
        index = {}
        for root in roots:
            if not os.path.isdir(root):
                continue
            for dirpath, _dirs, files in os.walk(root):
                for f in files:
                    if not f.lower().endswith((".lnk", ".url")):
                        continue
                    name = os.path.splitext(f)[0].lower()
                    if any(s in name for s in skip):
                        continue
                    if name not in index:
                        index[name] = os.path.join(dirpath, f)
        self.app_index = index

    def find_app(self, name):
        """Resolve a spoken app name to something launchable, or None."""
        name = name.strip()
        if name in ALIASES:
            return ALIASES[name], name
        idx = self.app_index
        if name in idx:
            return idx[name], name
        starts = [k for k in idx if k.startswith(name)]
        if starts:
            best = min(starts, key=len)
            return idx[best], best
        contains = [k for k in idx if name in k]
        if contains:
            best = min(contains, key=len)
            return idx[best], best
        close = difflib.get_close_matches(name, list(idx), n=1, cutoff=0.75)
        if close:
            return idx[close[0]], close[0]
        return None

    def run(self, text):
        """Parse and execute. Returns (ok, feedback)."""
        cmd = parse(text)
        if cmd is None:
            return False, f'Did not understand: "{text.strip()}"'
        kind, arg, _ = cmd
        try:
            return self._execute(kind, arg)
        except Exception as e:
            return False, f"Failed: {e}"

    def _execute(self, kind, arg):
        if kind == "open_app":
            found = self.find_app(arg)
            if found:
                target, label = found
                os.startfile(target)
                return True, f"Opening {label.title()}"
            if arg in SITES:
                webbrowser.open(SITES[arg])
                return True, f"Opening {arg.title()}"
            return False, f'No app called "{arg}" found'

        if kind == "url":
            arg = arg.replace(" dot ", ".").replace(" ", "")
            url = SITES.get(arg) or (
                arg if arg.startswith("http") else "https://" + arg)
            webbrowser.open(url)
            return True, f"Opening {arg}"

        if kind == "search":
            webbrowser.open(
                "https://www.google.com/search?q=" + _quote(arg))
            return True, f"Searching for {arg}"

        if kind == "youtube":
            webbrowser.open(
                "https://www.youtube.com/results?search_query=" + _quote(arg))
            return True, f"Searching YouTube for {arg}"

        if kind == "folder":
            os.startfile(os.path.join(os.path.expanduser("~"), arg))
            return True, f"Opening {arg}"

        if kind == "type":
            import keyboard
            keyboard.write(arg, delay=0.005, exact=True)
            return True, "Typed it"

        if kind == "keys":
            import keyboard
            keyboard.send(arg)
            return True, f"Pressed {arg.replace('+', ' + ')}"

        if kind == "shortcut":
            import keyboard
            combo, feedback = SHORTCUTS[arg]
            keyboard.send(combo)
            return True, feedback

        if kind == "volume":
            import keyboard
            for _ in range(4):
                keyboard.send("volume up" if arg == "up" else "volume down")
            return True, f"Volume {arg}"

        if kind == "scroll":
            delta = 360 if arg == "up" else -360
            for _ in range(3):
                ctypes.windll.user32.mouse_event(0x0800, 0, 0, delta, 0)
                time.sleep(0.05)
            return True, f"Scrolled {arg}"

        if kind == "click":
            u = ctypes.windll.user32
            if arg == "right":
                u.mouse_event(0x0008, 0, 0, 0, 0)
                u.mouse_event(0x0010, 0, 0, 0, 0)
            else:
                for _ in (range(2) if arg == "double" else range(1)):
                    u.mouse_event(0x0002, 0, 0, 0, 0)
                    u.mouse_event(0x0004, 0, 0, 0, 0)
                    time.sleep(0.05)
            return True, f"{arg.title()} click"

        if kind == "screenshot":
            from PIL import ImageGrab
            path = os.path.join(os.path.expanduser("~"), "Pictures",
                                time.strftime("WhispLocal-%Y%m%d-%H%M%S.png"))
            ImageGrab.grab().save(path)
            return True, "Screenshot saved to Pictures"

        if kind == "lock":
            ctypes.windll.user32.LockWorkStation()
            return True, ""

        if kind == "shutdown":
            subprocess.run(["shutdown", "/s", "/t", "60"], check=False)
            return True, "Shutting down in 60 seconds. Say cancel shutdown to stop it"

        if kind == "cancel_shutdown":
            subprocess.run(["shutdown", "/a"], check=False)
            return True, "Shutdown cancelled"

        if kind == "time":
            return True, "It is " + time.strftime("%I:%M %p").lstrip("0")

        if kind == "date":
            return True, "Today is " + time.strftime("%A, %d %B %Y")

        return False, "Not implemented"


def _quote(s):
    from urllib.parse import quote_plus
    return quote_plus(s)


def speak(text):
    """Voice feedback via the built-in Windows speech engine, async."""
    if not text:
        return

    def _run():
        try:
            subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "$t=[Console]::In.ReadToEnd();"
                 "(New-Object -ComObject SAPI.SpVoice).Speak($t) | Out-Null"],
                input=text, text=True, capture_output=True, timeout=15,
                creationflags=0x08000000)  # CREATE_NO_WINDOW
        except Exception:
            pass

    threading.Thread(target=_run, daemon=True).start()
