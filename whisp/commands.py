"""Voice-control engine: turns a transcribed sentence into an action.

parse() is pure (regex intent matching, no side effects) so it is unit
testable; execute() performs the action. App launching works from an
index of Start Menu shortcuts built in the background at startup.

Guardrails (see GUARDRAILS.md):
- No autonomous purchases, payments, or bookings. "book"/"find" style
  commands open the relevant page so the user completes the action.
- Closing an app sends a graceful close (WM_CLOSE), never a force-kill,
  so apps can still prompt to save unsaved work. The shell/taskbar and
  this app itself are never targeted.
- Note-taking writes only inside the user's configured Obsidian vault.
- Shutdown is delayed 60 s and voice-cancellable. File deletion is not
  supported at all.
"""
import ctypes
import ctypes.wintypes as wintypes
import difflib
import json
import os
import re
import subprocess
import threading
import time
import webbrowser

CREATE_NO_WINDOW = 0x08000000

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

# Official download pages for common apps, used when the app is not
# installed. Anything not here falls back to a web search for "download X".
DOWNLOADS = {
    "chrome": "https://www.google.com/chrome/",
    "firefox": "https://www.mozilla.org/firefox/new/",
    "brave": "https://brave.com/download/",
    "spotify": "https://www.spotify.com/download/",
    "discord": "https://discord.com/download",
    "zoom": "https://zoom.us/download",
    "vlc": "https://www.videolan.org/vlc/",
    "vs code": "https://code.visualstudio.com/download",
    "visual studio code": "https://code.visualstudio.com/download",
    "obs": "https://obsobject.example/invalid",  # replaced below
    "obs studio": "https://obsproject.com/download",
    "obsidian": "https://obsidian.md/download",
    "telegram": "https://desktop.telegram.org/",
    "whatsapp": "https://www.whatsapp.com/download",
    "slack": "https://slack.com/downloads/windows",
    "steam": "https://store.steampowered.com/about/",
    "notion": "https://www.notion.so/desktop",
    "figma": "https://www.figma.com/downloads/",
    "python": "https://www.python.org/downloads/",
    "git": "https://git-scm.com/download/win",
}
DOWNLOADS["obs"] = "https://obsproject.com/download"

# Sites that host bookings/reservations, so "book a table at X" opens a
# real starting point rather than pretending to transact.
RESERVATION_SEARCH = "https://www.google.com/search?q="

# Windows whose apps must never be closed by voice (shell, this app).
_PROTECTED_CLOSE = ("program manager", "whisplocal", "task manager")

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

    # Notes go to Obsidian. Keep the original casing of the note body.
    m = re.match(
        r"(?:take|make|write|add|save|create)\s+(?:a\s+)?note\s+"
        r"(?:that\s+|saying\s+|about\s+)?(.+)", t)
    if not m:
        m = re.match(r"(?:note that|remember that|note down|jot down)\s+(.+)", t)
    if not m:
        m = re.match(r"save (?:this )?to obsidian[:,]?\s+(.+)", t, )
    if m:
        span = m.span(1)
        return ("note", text.strip()[span[0]:span[1]].strip() or m.group(1), None)

    m = re.match(r"(?:close|quit|exit|kill)\s+(?:the\s+)?(.+)", t)
    if m:
        target = m.group(1).strip()
        if target not in ("window", "this window", "current window",
                          "tab", "this tab", "current tab", "this", "everything"):
            return ("close_app", target, None)

    m = re.match(r"(?:download|install)\s+(?:the\s+)?(?:app\s+)?(.+)", t)
    if m:
        return ("download", m.group(1).strip(), None)

    m = re.match(r"(?:open|launch|start|run)\s+(?:the\s+)?(?:app\s+)?(.+)", t)
    if m:
        target = m.group(1).strip()
        # "open X in the web / in browser / website / online" forces the web.
        force_web = False
        wm = re.search(
            r"\s+(?:in|on)\s+(?:the\s+)?(?:web|browser|internet)$"
            r"|\s+(?:website|online)$", target)
        if wm:
            target = target[:wm.start()].strip()
            force_web = True
        for name, folder in FOLDERS.items():
            if target in (name, f"{name} folder", f"my {name}"):
                return ("folder", folder, None)
        if "." in target or target.startswith("http"):
            return ("url", target, None)
        return ("open_web" if force_web else "open_app", target, None)

    m = re.match(r"go to\s+(.+)", t)
    if m:
        return ("url", m.group(1).strip(), None)

    m = re.match(r"(?:search(?:\s+for)?|google)\s+(.+)", t)
    if m:
        return ("search", m.group(1).strip(), None)

    # Music: "play X on spotify/youtube", "play some music", "play <song>".
    # (Bare "play"/"pause" stay media keys via SHORTCUTS below.)
    m = re.match(r"(?:play|put on|start playing)\s+(.+?)\s+on\s+"
                 r"(youtube music|youtube|spotify)$", t)
    if m:
        return ("play_music", (m.group(1).strip(), m.group(2)), None)
    m = re.match(r"(?:play|put on|start playing)\s+(?:some\s+|a\s+|the\s+)?"
                 r"(?:music|songs?|playlist|tunes)\b.*", t)
    if m:
        return ("play_music", ("", None), None)
    m = re.match(r"(?:play|put on|start playing)\s+(.+)", t)
    if m:
        return ("play_music", (m.group(1).strip(), None), None)

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
    if re.match(r"(?:what do you know about me|update my profile|"
                r"save my profile|show my profile|"
                r"what have you learned about me)", t):
        return ("profile", None, None)

    if re.match(r"what(?:'s| is) the time|what time is it", t):
        return ("time", None, None)
    if re.match(r"what(?:'s| is) (?:the date|today's date)|what day is it", t):
        return ("date", None, None)

    # Reservations and bookings: open a starting point, never transact.
    m = re.match(
        r"(?:book|reserve|make)\s+(?:a\s+)?(?:table|reservation|booking|"
        r"appointment)\s+(?:at|for|with|in)?\s*(.+)", t)
    if m:
        return ("booking", m.group(1).strip(), None)

    # Market data and stock lookups open the relevant finance page.
    m = re.match(
        r"(?:find|get|show|look up)?\s*(?:the\s+)?(?:market data|stock price|"
        r"share price|stock)\s+(?:for|of|on)?\s*(.+)", t)
    if m and m.group(1).strip():
        return ("market", m.group(1).strip(), None)
    m = re.match(r"(?:price of|how is)\s+(.+?)(?:\s+stock| doing)?$", t)
    if m and ("stock" in t or "price" in t or "share" in t):
        return ("market", m.group(1).strip(), None)

    # General information: open a web search so the answer is one click away.
    m = re.match(
        r"(?:look up|find out|find|tell me about|what(?:'s| is)|who(?:'s| is)|"
        r"how (?:do|to|much|many)|when (?:is|was)|where (?:is|are))\s+(.+)", t)
    if m:
        return ("lookup", m.group(0).strip(), None)

    return None


# ----- execution -------------------------------------------------------------

# Command verbs, used to repair a slightly misheard first word.
_VERBS = ("open", "launch", "start", "run", "close", "quit", "exit",
          "play", "pause", "search", "google", "type", "press", "hit",
          "volume", "scroll", "click", "download", "install", "note",
          "lock", "screenshot", "mute", "copy", "paste", "save",
          "minimize", "maximize", "refresh")


class CommandEngine:
    def __init__(self, build_index=True, note_saver=None, on_action=None,
                 profile_saver=None):
        self.app_index = {}
        # usage counts (label -> times launched); the app points this at the
        # learning profile so previously-used apps win ambiguous matches.
        self.usage = {}
        # note_saver(text) -> (ok, feedback); wired by the app to Obsidian.
        self.note_saver = note_saver
        # profile_saver() -> (ok, feedback); writes the learned profile.
        self.profile_saver = profile_saver
        # on_action(kind, arg, ok) -> None; wired by the app to learning.
        self.on_action = on_action
        if build_index:
            threading.Thread(target=self._build_index, daemon=True).start()

    def _repair(self, text):
        """Try to fix a command that did not parse: correct a misheard
        leading verb, or fuzzy-match the whole phrase to a known command.
        Returns a repaired string or None."""
        t = _normalize(text)
        if not t:
            return None
        words = t.split()
        near = difflib.get_close_matches(words[0], _VERBS, n=1, cutoff=0.72)
        if near and near[0] != words[0]:
            words[0] = near[0]
            return " ".join(words)
        known = (list(SHORTCUTS.keys())
                 + ["take a screenshot", "lock the screen", "what time is it",
                    "what's the date", "play music", "show desktop"])
        near = difflib.get_close_matches(t, known, n=1, cutoff=0.82)
        if near:
            return near[0]
        return None

    def _build_index(self):
        skip = ("uninstall", "help", "readme", "website", "documentation")
        index = {}

        # 1. Classic Start Menu shortcuts (.lnk / .url).
        roots = [
            os.path.join(os.environ.get("ProgramData", ""),
                         r"Microsoft\Windows\Start Menu\Programs"),
            os.path.join(os.environ.get("APPDATA", ""),
                         r"Microsoft\Windows\Start Menu\Programs"),
        ]
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

        # 2. Get-StartApps also lists Microsoft Store / UWP apps (Spotify,
        #    WhatsApp, etc.) that have no Start Menu shortcut. Launch those
        #    by their AppUserModelID via the AppsFolder shell namespace.
        try:
            out = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "Get-StartApps | ConvertTo-Json -Compress"],
                capture_output=True, text=True, timeout=20,
                creationflags=CREATE_NO_WINDOW)
            data = json.loads(out.stdout or "[]")
            if isinstance(data, dict):
                data = [data]
            for item in data:
                name = (item.get("Name") or "").strip().lower()
                appid = (item.get("AppID") or "").strip()
                if not name or not appid or any(s in name for s in skip):
                    continue
                if name not in index:
                    index[name] = (appid if os.path.exists(appid)
                                   else "appid:" + appid)
        except Exception:
            pass

        self.app_index = index

    def switch_to(self, term):
        """If a window whose title contains `term` is open, focus it and
        return its title; otherwise return None. Lets 'open youtube' jump
        to an already-open YouTube instead of opening a duplicate."""
        term = (term or "").strip().lower()
        if len(term) < 2:
            return None
        best = None
        for hwnd, title, exe in _enum_windows():
            tl = title.lower()
            if any(p in tl for p in _PROTECTED_CLOSE):
                continue
            el = os.path.splitext(exe)[0].lower()
            if term in tl or term == el:
                # Prefer the most specific (shortest) matching title.
                if best is None or len(title) < len(best[1]):
                    best = (hwnd, title)
        if best is None:
            return None
        _focus_hwnd(best[0])
        return best[1]

    def _launch(self, target):
        """Start an indexed app, handling both file shortcuts and UWP AppIDs."""
        if target.startswith("appid:"):
            subprocess.Popen(
                ["explorer.exe", "shell:AppsFolder\\" + target[6:]],
                creationflags=CREATE_NO_WINDOW)
        else:
            os.startfile(target)

    def _best(self, candidates):
        """Pick among matching shortcuts: prefer ones the user has launched
        before (reinforcement), then the shortest name."""
        return sorted(candidates,
                      key=lambda k: (-self.usage.get(k, 0), len(k)))[0]

    # Filler words that add nothing to an app name.
    _APP_STOP = frozenset(("app", "the", "my", "please", "up", "program"))

    def find_app(self, name):
        """Resolve a spoken app name to something launchable, or None.
        Tries, in order: alias, exact, prefix, substring, all-words-present,
        and fuzzy — so slightly misheard names still resolve."""
        name = name.strip().lower()
        if name in ALIASES:
            return ALIASES[name], name
        idx = self.app_index
        if not idx:
            return None
        if name in idx:
            return idx[name], name

        tokens = {k: k.split() for k in idx}

        # A whole word of the shortcut equals the spoken name. Most precise,
        # so "obs" prefers "obs studio" and "code" avoids "zcode".
        word_exact = [k for k, ts in tokens.items() if name in ts]
        if word_exact:
            best = self._best(word_exact)
            return idx[best], best

        # Prefix of the whole shortcut name ("microsoft ed" -> microsoft edge).
        starts = [k for k in idx if k.startswith(name)]
        if starts:
            best = self._best(starts)
            return idx[best], best

        if " " in name:
            # A multi-word phrase appearing verbatim in the shortcut.
            phrase = [k for k in idx if name in k]
            if phrase:
                best = self._best(phrase)
                return idx[best], best
            # Or each spoken word begins some word of the shortcut.
            words = [w for w in name.split() if w not in self._APP_STOP]
            if words:
                allw = [k for k, ts in tokens.items()
                        if all(any(t.startswith(w) for t in ts) for w in words)]
                if allw:
                    best = self._best(allw)
                    return idx[best], best
        elif len(name) >= 3:
            # A word of the shortcut begins with the name ("calc" -> calculator).
            word_prefix = [k for k, ts in tokens.items()
                           if any(t.startswith(name) for t in ts)]
            if word_prefix:
                best = self._best(word_prefix)
                return idx[best], best

        # Conservative fuzzy match, only for longer names, to catch small
        # mishearings ("discrd" -> discord) without grabbing unrelated apps.
        if len(name) >= 5:
            close = difflib.get_close_matches(name, list(idx), n=1, cutoff=0.8)
            if close:
                return idx[close[0]], close[0]
        return None

    def _open_web(self, arg, forced=False, installed=False):
        """Open the app's web version (known site) or a web search for it."""
        if arg in SITES:
            webbrowser.open(SITES[arg])
            site = arg.title()
        else:
            webbrowser.open("https://www.google.com/search?q=" + _quote(arg))
            site = arg
        if forced:
            return True, f"Opening {site} on the web"
        return True, f"{arg.title()} is not installed — opening it on the web"

    def _download(self, arg):
        """Explicit 'download X': open its official download page or a search."""
        known = arg in DOWNLOADS
        url = DOWNLOADS.get(arg) or (
            "https://www.google.com/search?q=" + _quote(f"download {arg}"))
        webbrowser.open(url)
        if known:
            return True, f"Opening the download page for {arg.title()}"
        return True, f"Finding {arg} to download"

    def _close_app(self, name):
        """Gracefully close the app whose window or process matches `name`.
        Uses WM_CLOSE (never TerminateProcess) so unsaved-work prompts
        still appear. Returns (ok, feedback)."""
        name = name.strip().lower()
        # Let common aliases match their real process/title.
        alias_titles = {"chrome": "google chrome", "vscode": "visual studio code",
                        "vs code": "visual studio code", "explorer": "file explorer"}
        needle = alias_titles.get(name, name)

        matches = []
        for hwnd, title, exe in _enum_windows():
            tl = title.lower()
            el = os.path.splitext(exe)[0].lower()
            if any(p in tl for p in _PROTECTED_CLOSE):
                continue
            if el in ("explorer",) and "file explorer" not in tl:
                continue  # never close the shell/taskbar
            if needle in tl or needle == el or needle in el:
                matches.append((hwnd, title))

        if not matches:
            return False, f'No open window for "{name}" found'
        WM_CLOSE = 0x0010
        hwnds = [h for h, _ in matches]
        for hwnd in hwnds:
            ctypes.windll.user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
        label = name.title()
        # Verify it actually closed (it may be prompting to save).
        time.sleep(0.6)
        still = {h for h, _t, _e in _enum_windows()} & set(hwnds)
        if not still:
            return True, (f"Closed {label}" if len(hwnds) == 1
                          else f"Closed {len(hwnds)} {label} windows")
        return True, f"Asked {label} to close (it may be waiting for you)"

    def run(self, text):
        """Parse and execute. Returns (ok, feedback)."""
        cmd = parse(text)
        if cmd is None:
            # Second pass: repair a misheard command before giving up.
            repaired = self._repair(text)
            if repaired:
                cmd = parse(repaired)
        if cmd is None:
            return False, f'Did not understand: "{text.strip()}"'
        kind, arg, _ = cmd
        try:
            ok, feedback = self._execute(kind, arg)
        except Exception as e:
            ok, feedback = False, f"Failed: {e}"
        if self.on_action:
            try:
                self.on_action(kind, arg, ok)
            except Exception:
                pass
        return ok, feedback

    def _execute(self, kind, arg):
        if kind == "open_app":
            # Verify the app is installed first: if so, open the app; if not,
            # open it on the web. Download only happens on an explicit
            # "download X" command.
            found = self.find_app(arg)
            if found:
                target, label = found
                self._launch(target)
                return True, f"Opening {label.title()}"
            return self._open_web(arg, installed=False)

        if kind == "open_web":
            return self._open_web(arg, forced=True)

        if kind == "download":
            return self._download(arg)

        if kind == "close_app":
            return self._close_app(arg)

        if kind == "note":
            if self.note_saver is None:
                return False, ("No Obsidian vault is set. Add one in "
                               "Settings to save notes")
            return self.note_saver(arg)

        if kind == "profile":
            if self.profile_saver is None:
                return False, "Learning is not available right now"
            return self.profile_saver()

        if kind == "booking":
            webbrowser.open(RESERVATION_SEARCH
                            + _quote(f"{arg} reservation book a table online"))
            return True, (f"Opening reservation options for {arg}. "
                          f"You confirm the booking yourself")

        if kind == "market":
            webbrowser.open("https://www.google.com/search?q="
                            + _quote(f"{arg} stock price"))
            return True, f"Opening market data for {arg}"

        if kind == "lookup":
            webbrowser.open("https://www.google.com/search?q=" + _quote(arg))
            return True, f"Looking that up"

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

        if kind == "play_music":
            query, service = arg
            if not query:
                webbrowser.open("https://music.youtube.com/")
                return True, "Opening music"
            # "play spotify" means open the Spotify app if it is installed,
            # not search the web for a song called "spotify".
            if service is None:
                found = self.find_app(query)
                if found:
                    self._launch(found[0])
                    return True, f"Opening {found[1].title()}"
            if service == "spotify":
                webbrowser.open(
                    "https://open.spotify.com/search/" + _quote(query))
                return True, f"Playing {query} on Spotify"
            if service == "youtube":
                webbrowser.open(
                    "https://www.youtube.com/results?search_query="
                    + _quote(query))
                return True, f"Playing {query} on YouTube"
            webbrowser.open(
                "https://music.youtube.com/search?q=" + _quote(query))
            return True, f"Playing {query}"

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


def _enum_windows():
    """Yield (hwnd, title, exe_basename) for visible top-level windows."""
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    results = []
    WNDENUMPROC = ctypes.WINFUNCTYPE(
        wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def cb(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        title = buf.value
        if not title:
            return True
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        exe = ""
        # PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        h = kernel32.OpenProcess(0x1000, False, pid.value)
        if h:
            size = wintypes.DWORD(260)
            path_buf = ctypes.create_unicode_buffer(260)
            if kernel32.QueryFullProcessImageNameW(
                    h, 0, path_buf, ctypes.byref(size)):
                exe = os.path.basename(path_buf.value)
            kernel32.CloseHandle(h)
        results.append((hwnd, title, exe))
        return True

    user32.EnumWindows(WNDENUMPROC(cb), 0)
    return results


def _focus_hwnd(hwnd):
    """Bring a window to the foreground reliably (SwitchToThisWindow is the
    same call Alt+Tab uses, so it bypasses the foreground-lock timeout)."""
    u = ctypes.windll.user32
    if u.IsIconic(hwnd):
        u.ShowWindow(hwnd, 9)  # SW_RESTORE
    u.SwitchToThisWindow(hwnd, True)


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
