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
    "youtube": "https://www.youtube.com",
    "youtube music": "https://music.youtube.com",
    "google": "https://www.google.com", "gmail": "https://mail.google.com",
    "github": "https://github.com", "whatsapp": "https://web.whatsapp.com",
    "instagram": "https://www.instagram.com",
    "facebook": "https://www.facebook.com", "twitter": "https://x.com",
    "x": "https://x.com", "claude": "https://claude.ai",
    "chatgpt": "https://chatgpt.com", "gemini": "https://gemini.google.com",
    "perplexity": "https://www.perplexity.ai",
    "amazon": "https://www.amazon.in", "flipkart": "https://www.flipkart.com",
    "spotify": "https://open.spotify.com", "maps": "https://maps.google.com",
    "netflix": "https://www.netflix.com", "reddit": "https://www.reddit.com",
    "linkedin": "https://www.linkedin.com",
    "wikipedia": "https://www.wikipedia.org",
    "stack overflow": "https://stackoverflow.com",
    "drive": "https://drive.google.com", "docs": "https://docs.google.com",
    "sheets": "https://sheets.google.com",
    "calendar": "https://calendar.google.com",
    "translate": "https://translate.google.com",
    "outlook": "https://outlook.live.com", "teams": "https://teams.microsoft.com",
    "notion": "https://www.notion.so", "twitch": "https://www.twitch.tv",
    "telegram": "https://web.telegram.org",
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

# Ordering sites: "order monster from instamart" deep-links to the site's
# product search with the query pre-filled, so the item is one tap from
# the cart. Verified live for Amazon/Flipkart/BigBasket; the quick-com
# sites are JS app-walls with standard search URL patterns. Sites not in
# this table (or without a workable pattern) fall back to a web search,
# so "order X from <anything>" always lands somewhere useful.
# The app opens the search page and never submits the order itself.
ORDER_SITES = {
    "amazon": ("Amazon", "https://www.amazon.in/s?k={q}"),
    "amazon.in": ("Amazon", "https://www.amazon.in/s?k={q}"),
    "flipkart": ("Flipkart", "https://www.flipkart.com/search?q={q}"),
    "bigbasket": ("BigBasket", "https://www.bigbasket.com/ps/?q={q}"),
    "big basket": ("BigBasket", "https://www.bigbasket.com/ps/?q={q}"),
    "blinkit": ("Blinkit", "https://blinkit.com/s?q={q}"),
    "zepto": ("Zepto", "https://www.zepto.com/en-IN/search?q={q}"),
    "instamart": ("Instamart",
                  "https://www.swiggy.com/instamart/search?query={q}"),
    "swiggy": ("Swiggy", "https://www.swiggy.com/search?query={q}"),
    "meesho": ("Meesho", "https://www.meesho.com/search?q={q}"),
    "jiomart": ("JioMart", "https://www.jiomart.com/search?q={q}"),
    "jio mart": ("JioMart", "https://www.jiomart.com/search?q={q}"),
}


def _resolve_order_site(site):
    """Map a spoken site name to (label, url template), matching aliases
    and substring overlap ("swiggy instamart" -> instamart)."""
    s = (site or "").strip().lower()
    if s in ORDER_SITES:
        return ORDER_SITES[s]
    for name, entry in ORDER_SITES.items():
        if name in s or s in name:
            return entry
    return None


def _order_url(product, site):
    """Deep-link to the site's product search for `product`, or a web
    search when the site is unknown / has no workable pattern."""
    entry = _resolve_order_site(site)
    if entry:
        return entry[1].format(q=_quote(product))
    return ("https://www.google.com/search?q="
            + _quote(f"order {product} from {site}"))

# "open <site> and search for X" chains the search INTO that site
# instead of a bare Google search ("open youtube and search for mr
# beast" searches YouTube itself).
SITE_SEARCH = {
    "youtube": "https://www.youtube.com/results?search_query={q}",
    "youtube music": "https://music.youtube.com/search?q={q}",
    "google": "https://www.google.com/search?q={q}",
    "amazon": "https://www.amazon.in/s?k={q}",
    "flipkart": "https://www.flipkart.com/search?q={q}",
    "spotify": "https://open.spotify.com/search/{q}",
    "reddit": "https://www.reddit.com/search/?q={q}",
    "github": "https://github.com/search?q={q}",
    "wikipedia": "https://en.wikipedia.org/w/index.php?search={q}",
    "stack overflow": "https://stackoverflow.com/search?q={q}",
    "maps": "https://www.google.com/maps/search/{q}",
    "bing": "https://www.bing.com/search?q={q}",
}

# Sites that host bookings/reservations, so "book a table at X" opens a
# real starting point rather than pretending to transact.
RESERVATION_SEARCH = "https://www.google.com/search?q="

# Voice-reachable Windows Settings pages ("open wifi settings",
# "open bluetooth settings"...). These are opened via ms-settings: URIs.
SETTINGS_PAGES = {
    "wifi": "network-wifi", "wi-fi": "network-wifi",
    "bluetooth": "bluetooth", "display": "display",
    "night light": "nightlight", "sound": "sound",
    "power": "power", "battery": "batterysaver",
    "storage": "storagesense", "network": "network",
    "airplane mode": "network-airplanemode", "about": "about",
}

# Windows whose apps must never be closed by voice (shell, this app).
_PROTECTED_CLOSE = ("program manager", "whisplocal", "task manager")

# Browser processes — a title match inside one is a tab, not an app window.
_BROWSER_EXES = frozenset((
    "chrome", "msedge", "firefox", "brave", "opera", "opera_gx", "vivaldi"))

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

# Trailing politeness whisper often appends ("search mr beast in youtube
# please"). Stripped in _normalize so every intent — especially the
# youtube patterns, which anchor on "youtube$" — matches despite it.
_TRAILER = re.compile(r"\s+(?:please|pls|okay|ok|thanks|thank you)\s*$",
                      re.I)

# Verbs that can introduce a YouTube search ("search/google/look for/find
# X in youtube"). Shared by parse() and _suggest() so the sets cannot
# drift apart.
_YT_VERBS = (r"(?:search|google|look for|look up|find|show me|"
             r"pull up|bring up)")
# A YouTube token as whisper can write it: "youtube", the split "you
# tube" (also rejoined in _normalize), or the short "yt".
_YT = r"(?:youtube|you\s+tube|\byt\b)"

# "X and Y" / "X then Y" spoken as one sentence are two commands.
# Whisper freely adds commas without a preceding space ("open youtube,
# search for mr beast"), "and then", and "&" — cover all of them so a
# punctuation variant never falls through to the open-app / URL path.
_COMPOUND_SPLIT = re.compile(
    r"\s+(?:and\s+then|and|then|&)\s+"
    r"|\s*,\s*(?:and\s+|then\s+)?", re.I)

# Tab navigation in the active app/browser: "switch tab", "next tab",
# "switch to tab 3". Checked before the generic switch/open intents so
# "switch to the next tab" isn't read as a window named "the next tab".
_TAB_NEXT = re.compile(
    r"^(?:switch|change|go|move|open)(?: to| over| to the)?(?: the)? "
    r"(?:next|following|forward) tabs?$", re.I)
_TAB_PREV = re.compile(
    r"^(?:switch|change|go|move|open)(?: to| back| to the)?(?: the)? "
    r"(?:previous|prior|back) tabs?$", re.I)
_TAB_NUM = re.compile(
    r"^(?:switch|go|open|move)(?: to)?(?: the)? tab "
    r"(?:number )?(one|two|three|four|five|six|seven|eight|nine|last|[1-9])$",
    re.I)
_TAB_WORDS = {"one": "1", "two": "2", "three": "3", "four": "4",
              "five": "5", "six": "6", "seven": "7", "eight": "8",
              "nine": "9", "last": "9"}
_TAB_NEXT_BARE = frozenset(("next tab", "next tabs", "the next tab",
                             "switch tab", "switch the tab", "change tab",
                             "switch tabs", "change the tab"))
_TAB_PREV_BARE = frozenset(("previous tab", "previous tabs",
                            "the previous tab"))

# Trailing descriptions people add to a target: "youtube which is already
# open", "comet that is running", "youtube on chrome". Strip them so the
# real name ("youtube", "comet") is what gets resolved.
_TARGET_TAIL = re.compile(
    r"\s+(?:which|that|thats|it|the one)?\s*"
    r"(?:is|has|have|was|i)?\s*(?:already|just)?\s*(?:been\s+)?"
    r"(?:open|opened|opening|running|there)\b.*$"
    r"|\s+(?:on|in|inside|using|with)\s+(?:the\s+)?"
    r"(?:chrome|edge|firefox|brave|browser|window|tab)\b.*$"
    r"|\s+(?:window|tab|app)s?$",
    re.I)


def _strip_target(target):
    cleaned = _TARGET_TAIL.sub("", target).strip()
    return cleaned or target


def heard_part(entry_text):
    """History stores command entries as "heard -> feedback"; return the
    heard phrase the user actually said (commands only). Splits at the
    LAST " -> " so a command whose text itself contains an arrow (e.g.
    "type a -> b") is not truncated. Non-command entries pass through
    untouched."""
    if " -> " in entry_text:
        return entry_text.rsplit(" -> ", 1)[0].strip()
    return entry_text.strip()


def _normalize(text):
    t = text.strip().lower()
    t = re.sub(r"[!?,]", "", t).rstrip(".")
    # Whisper splits "youtube" into two words ("search mr beast in you
    # tube"); rejoin so every youtube pattern sees the canonical token.
    t = t.replace("you tube", "youtube")
    t = _TRAILER.sub("", t)
    while True:
        t2 = _FILLER_PREFIX.sub("", t)
        if t2 == t:
            return t.strip()
        t = t2


def _preserve_case(text):
    """Same stripping as _normalize but keeps the user's original casing,
    so slicing a regex match on the result returns the original spelling.
    Used for note bodies, where the text itself is the payload."""
    t = text.strip()
    t = re.sub(r"[!?,]", "", t).rstrip(".")
    while True:
        t2 = _FILLER_PREFIX.sub("", t)
        if t2 == t:
            return t
        t = t2


def parse(text):
    """Return (kind, arg, None) or None if the sentence is not a command."""
    t = _normalize(text)
    if not t:
        return None

    # Notes go to Obsidian. Keep the original casing of the note body and
    # match against the case-preserved text, because the filler/politeness
    # stripping in _normalize shifts indices and would garble the body.
    note_text = _preserve_case(text)
    m = re.match(
        r"(?:take|make|write|add|save|create)\s+(?:a\s+)?note\s+"
        r"(?:that\s+|saying\s+|about\s+)?(.+)", note_text, re.I)
    if not m:
        m = re.match(
            r"(?:note that|remember that|note down|jot down)\s+(.+)",
            note_text, re.I)
    if not m:
        m = re.match(
            r"save (?:this )?to obsidian[:,]?\s+(.+)", note_text, re.I)
    if m:
        return ("note", m.group(1).strip(), None)

    m = re.match(r"(?:close|quit|exit|kill)\s+(?:the\s+)?(.+)", t)
    if m:
        target = m.group(1).strip()
        if target not in ("window", "this window", "current window",
                          "tab", "this tab", "current tab", "this", "everything"):
            return ("close_app", target, None)

    m = re.match(r"(?:download|install)\s+(?:the\s+)?(?:app\s+)?(.+)", t)
    if m:
        return ("download", m.group(1).strip(), None)

    # --- tab navigation (before generic switch/open) ---------------------
    if _TAB_NEXT.match(t) or t in _TAB_NEXT_BARE:
        return ("tab", "next", None)
    if _TAB_PREV.match(t) or t in _TAB_PREV_BARE \
            or t in ("go back a tab", "go back one tab", "tab back"):
        return ("tab", "prev", None)
    m = _TAB_NUM.match(t)
    if m:
        return ("tab", _TAB_WORDS.get(m.group(1), m.group(1)), None)
    if t in ("last tab", "the last tab", "switch to the last tab",
             "go to the last tab", "switch to last tab"):
        return ("tab", "9", None)
    # "open a new tab" / "switch to a new tab" / "close this tab" -> the
    # existing shortcuts.
    if re.match(r"^(?:open|make|start|switch to)(?: a| an| the)? new tab$",
                t) or t in ("open tab", "open a tab", "open the tab"):
        return ("shortcut", "new tab", None)
    if re.match(r"^close (?:this|the|current) tab$", t):
        return ("shortcut", "close tab", None)

    # --- app settings ------------------------------------------------------
    # "open settings" means THIS app's settings window (the assistant's
    # own), not Windows Settings — the user is talking to us, so that is
    # the intent. Windows Settings stays reachable explicitly.
    if re.match(r"^(?:open|show|launch)(?: the)?(?: app)? settings$", t) \
            or t in ("settings", "app settings", "your settings",
                     "open my settings", "open app settings",
                     "open the app settings", "show settings"):
        return ("app_settings", None, None)
    if re.match(r"^(?:open|show)(?: the)? "
                r"(?:windows|system|pc|computer) settings$", t):
        return ("open_app", "settings", None)
    # Voice-reachable Windows Settings pages ("open wifi settings").
    # Placed before the generic open/launch match so the page name is not
    # mistaken for an app to launch.
    m = re.match(
        r"open (?:the\s+)?(?:windows\s+)?(?:settings\s+)?"
        r"(wifi|wi-fi|bluetooth|display|night light|sound|power|battery|"
        r"storage|network|airplane mode|about) settings$", t)
    if m:
        page = SETTINGS_PAGES.get(m.group(1))
        if page:
            return ("open_settings_page", page, None)

    # --- ordering: "order monster from instamart" -------------------------
    m = re.match(
        r"(?P<verb>order|buy|purchase|get)\s+(?:me\s+)?(?:a\s+|an\s+|the\s+|some\s+)?"
        r"(?P<prod>.+?)\s+(?:from|on|at)\s+(?:the\s+)?(?P<site>.+)$", t)
    if m:
        product = m.group("prod").strip()
        site = m.group("site").strip()
        # "get X from Y" is common non-ordering English ("get market data
        # on Tesla", "get the weather on friday") — only treat it as an
        # order when Y is a real ordering site, so those phrases still fall
        # through to the market/lookup intents below.
        if product and site and (m.group("verb") != "get"
                                 or _resolve_order_site(site)):
            return ("order", (product, site), None)
    m = re.match(
        r"add\s+(?:a\s+|an\s+|the\s+)?(.+?)\s+to\s+(?:my\s+|the\s+)?"
        r"(?:cart|basket|bag)\s+(?:on|from|at)\s+(?:the\s+)?(.+)$", t)
    if m:
        product = m.group(1).strip()
        site = m.group(2).strip()
        if product and site:
            return ("order", (product, site), None)

    m = re.match(r"(?:switch to|bring up|focus)\s+(?:the\s+)?(.+)", t)
    if m:
        return ("switch", _strip_target(m.group(1).strip()), None)

    # "open youtube search mr beast" — whisper drops the "and"; the
    # search still runs on YouTube, not a Google search for the phrase.
    m = re.match(
        r"open\s+(?:the\s+)?" + _YT + r"\s+(?:and\s+)?"
        r"(?:search|find|look for)\s+(?:for\s+)?(.+)", t)
    if m:
        return ("youtube", m.group(1).strip(), None)

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
        target = _strip_target(target)
        for name, folder in FOLDERS.items():
            if target in (name, f"{name} folder", f"my {name}"):
                return ("folder", folder, None)
        # A URL must be a single domain-ish token. A target with spaces
        # ("youtube and search for mr. beast") is a sentence, never a
        # domain — sending it to the URL path would strip the spaces and
        # open a garbage address.
        if target.startswith("http") \
                or ("." in target and " " not in target):
            return ("url", target, None)
        return ("open_web" if force_web else "open_app", target, None)

    m = re.match(r"go to\s+(.+)", t)
    if m:
        return ("url", m.group(1).strip(), None)

    # YouTube search — every way whisper can phrase it: "search X on/in
    # youtube", "google X in youtube", "look for X in youtube", "find X
    # in youtube", "show me X in youtube", "search X in the youtube",
    # "in youtube app", "in youtube.com", "you tube" split into two
    # words, the short "yt", inverted "search in youtube X", and even
    # the bare "X in youtube" with the verb dropped. All land on YouTube
    # results — never a bare Google search for the whole sentence.
    m = re.match(
        _YT_VERBS + r"\s+(?:for\s+)?(.+?)\s+(?:on|in)\s+(?:the\s+)?"
        + _YT + r"(?:\s+(?:app|website|the)|\.com)?$", t)
    if m:
        return ("youtube", m.group(1).strip(), None)
    m = re.match(
        _YT_VERBS + r"\s+(?:for\s+)?(?:on|in)\s+(?:the\s+)?" + _YT
        + r"\s+(?:for\s+)?(.+)$", t)
    if m:
        return ("youtube", m.group(1).strip(), None)
    m = re.match(
        _YT_VERBS + r"\s+(?:for\s+)?(?:the\s+)?(?:youtube|you\s+tube)"
        r"\s+(?:for\s+)?(.+)$", t)
    if m:
        return ("youtube", m.group(1).strip(), None)
    m = re.match(_YT + r"\s+search\s+(?:for\s+)?(.+)", t)
    if m:
        return ("youtube", m.group(1).strip(), None)

    m = re.match(r"(?:search(?:\s+for)?|google|look for)\s+(.+)", t)
    if m:
        return ("search", m.group(1).strip(), None)

    # Media transport: stop / pause / resume the current playback.
    if (re.match(r"(?:stop|pause)\s+(?:the\s+)?"
                 r"(?:music|song|playback|playing|video|audio)$", t)
            or t in ("stop playing", "pause playing")):
        return ("shortcut", "pause", None)
    if re.match(r"(?:resume|unpause|continue)"
                r"(?:\s+(?:the\s+)?(?:music|song|playback|playing))?$", t):
        return ("shortcut", "play", None)

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
        keys = [KEY_WORDS.get(w, w) for w in words
                if w not in ("key", "keys", "the", "a", "an")]
        # Reject "press the key" / "press a key": nothing left to press.
        if keys and all(len(k) == 1 or k in KEY_WORDS.values()
                        for k in keys):
            return ("keys", "+".join(keys), None)
        return None

    # --- volume -----------------------------------------------------------
    # Exact level first, so "set volume to 30" is not read as a step.
    m = re.match(
        r"(?:set|turn|change|adjust|put)\s+(?:the\s+)?(?:volume|volume "
        r"(?:of the )?(?:computer|pc|laptop|system))\s+(?:to\s+|at\s+)?"
        r"(\d{1,3})\s*(?:percent|%)?$", t)
    if m:
        return ("volume", "set:" + str(max(0, min(100, int(m.group(1))))),
                None)
    m = re.match(r"volume\s+(?:to\s+|at\s+)?(\d{1,3})\s*(?:percent|%)?$", t)
    if m:
        return ("volume", "set:" + str(max(0, min(100, int(m.group(1))))),
                None)
    # "increase volume by 20%" / "increasing volume by 20%" — a relative
    # change from the current level, not a step and not an absolute set.
    m = re.match(
        r"(?:increase|increasing|raise|raising|boost|boosting|turn up)\s+"
        r"(?:my\s+|the\s+)?(?:computer'?s?|pc'?s?|laptop'?s?|"
        r"system'?s?)?\s*volume\s+by\s+(\d{1,3})\s*(?:percent|%)?$", t)
    if m:
        return ("volume", "add:" + m.group(1), None)
    m = re.match(
        r"(?:decrease|decreasing|lower|lowering|reduce|reducing|drop|"
        r"turn down)\s+(?:my\s+|the\s+)?(?:computer'?s?|pc'?s?|"
        r"laptop'?s?|system'?s?)?\s*volume\s+by\s+(\d{1,3})\s*"
        r"(?:percent|%)?$", t)
    if m:
        return ("volume", "sub:" + m.group(1), None)
    m = re.match(
        r"volume\s+up\s+by\s+(\d{1,3})\s*(?:percent|%)?$", t)
    if m:
        return ("volume", "add:" + m.group(1), None)
    m = re.match(
        r"volume\s+down\s+by\s+(\d{1,3})\s*(?:percent|%)?$", t)
    if m:
        return ("volume", "sub:" + m.group(1), None)
    m = re.match(
        r"make (?:it|the volume) louder\s+by\s+(\d{1,3})\s*(?:percent|%)?$",
        t)
    if m:
        return ("volume", "add:" + m.group(1), None)
    m = re.match(
        r"make (?:it|the volume) quieter\s+by\s+(\d{1,3})\s*(?:percent|%)?$",
        t)
    if m:
        return ("volume", "sub:" + m.group(1), None)
    # Split phrasal verbs: "turn the volume down by 20%" / "turn it up
    # by 10%" — the verb and its particle are separated by the object.
    m = re.match(
        r"turn (?:it|the volume|the volume of (?:the )?(?:computer|pc|laptop|system))"
        r" (up|down) by (\d{1,3})\s*(?:percent|%)?$", t)
    if m:
        return ("volume", ("add:" if m.group(1) == "up" else "sub:")
                + m.group(2), None)
    # "increase volume to 60" / "lower the volume to 30" — a direction
    # verb plus an absolute target is still a set, not a step.
    m = re.match(
        r"(?:increase|decrease|raise|lower|reduce)\s+(?:my\s+|the\s+)?"
        r"(?:computer'?s?|pc'?s?|laptop'?s?|system'?s?)?\s*volume\s+"
        r"(?:to\s+|at\s+)?(\d{1,3})\s*(?:percent|%)?$", t)
    if m:
        return ("volume", "set:" + str(max(0, min(100, int(m.group(1))))),
                None)
    if t in ("max volume", "full volume", "maximum volume", "volume max",
             "volume to max", "maximum"):
        return ("volume", "set:100", None)
    if t in ("min volume", "minimum volume", "volume min", "volume to min",
             "zero volume", "volume zero"):
        return ("volume", "set:0", None)
    # "lower my computer's volume" / "raise the pc volume" — the exact
    # phrasing that used to answer "not understood".
    m = re.match(
        r"(?:lower|reduce|decrease|drop|cut|turn down)\s+(?:my\s+|the\s+)?"
        r"(?:computer'?s?|pc'?s?|laptop'?s?|system'?s?)?\s*volume$", t)
    if m:
        return ("volume", "down", None)
    m = re.match(
        r"(?:raise|increase|boost|turn up)\s+(?:my\s+|the\s+)?"
        r"(?:computer'?s?|pc'?s?|laptop'?s?|system'?s?)?\s*volume$", t)
    if m:
        return ("volume", "up", None)
    m = re.match(r"(?:volume|turn (?:it|the volume))\s*(up|down)", t)
    if m:
        return ("volume", m.group(1), None)
    m = re.match(r"turn (up|down) (?:the )?volume", t)
    if m:
        return ("volume", m.group(1), None)
    if t in ("louder", "turn it up", "turn up", "increase volume",
             "increase the volume", "raise the volume", "make it louder",
             "make the volume louder"):
        return ("volume", "up", None)
    if t in ("quieter", "softer", "turn it down", "turn down",
             "decrease volume", "decrease the volume", "lower the volume",
             "make it quieter", "make the volume quieter"):
        return ("volume", "down", None)

    # --- brightness --------------------------------------------------------
    m = re.match(
        r"(?:set|turn|change|adjust)\s+(?:the\s+)?(?:screen\s+)?"
        r"brightness\s+(?:to\s+|at\s+)?(\d{1,3})\s*(?:percent|%)?$", t)
    if m:
        return ("brightness", "set:" + str(max(0, min(100, int(m.group(1))))),
                None)
    m = re.match(r"brightness\s+(?:to\s+|at\s+)?(\d{1,3})\s*(?:percent|%)?$",
                 t)
    if m:
        return ("brightness", "set:" + str(max(0, min(100, int(m.group(1))))),
                None)
    # "increase brightness by 20%" — relative change, like volume.
    m = re.match(
        r"(?:increase|increasing|raise|raising|turn up)\s+(?:my\s+|the\s+)?"
        r"(?:screen\s+)?brightness\s+by\s+(\d{1,3})\s*(?:percent|%)?$", t)
    if m:
        return ("brightness", "add:" + m.group(1), None)
    # "turn the brightness down by 20%" — split phrasal verb.
    m = re.match(
        r"turn (?:the\s+)?(?:screen\s+)?brightness (up|down) by (\d{1,3})"
        r"\s*(?:percent|%)?$", t)
    if m:
        return ("brightness", ("add:" if m.group(1) == "up" else "sub:")
                + m.group(2), None)
    m = re.match(
        r"(?:decrease|decreasing|lower|lowering|reduce|reducing|turn down)\s+"
        r"(?:my\s+|the\s+)?(?:screen\s+)?brightness\s+by\s+(\d{1,3})\s*"
        r"(?:percent|%)?$", t)
    if m:
        return ("brightness", "sub:" + m.group(1), None)
    m = re.match(
        r"brightness\s+up\s+by\s+(\d{1,3})\s*(?:percent|%)?$", t)
    if m:
        return ("brightness", "add:" + m.group(1), None)
    m = re.match(
        r"brightness\s+down\s+by\s+(\d{1,3})\s*(?:percent|%)?$", t)
    if m:
        return ("brightness", "sub:" + m.group(1), None)
    if t in ("max brightness", "full brightness", "maximum brightness"):
        return ("brightness", "set:100", None)
    if t in ("min brightness", "minimum brightness"):
        return ("brightness", "set:0", None)
    m = re.match(r"(?:brightness|screen brightness)\s*(up|down)", t)
    if m:
        return ("brightness", m.group(1), None)
    m = re.match(
        r"(?:increase|raise|turn up)\s+(?:the\s+)?(?:screen\s+)?brightness$",
        t)
    if m:
        return ("brightness", "up", None)
    m = re.match(
        r"(?:decrease|lower|reduce|turn down)\s+(?:the\s+)?"
        r"(?:screen\s+)?brightness$", t)
    if m:
        return ("brightness", "down", None)
    if t in ("brighter", "make it brighter"):
        return ("brightness", "up", None)
    if t in ("dimmer", "darker", "make it darker", "make it dimmer"):
        return ("brightness", "down", None)

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
    if re.match(r"cancel (?:the\s+)?shut\s?down", t) \
            or t in ("cancel restart", "cancel the restart"):
        return ("cancel_shutdown", None, None)
    # Restart is delayed and cancellable, exactly like shutdown.
    if re.match(r"restart (?:the\s+)?(?:computer|pc|laptop)", t) \
            or t in ("restart", "restart the system", "reboot"):
        return ("restart", None, None)
    if re.match(r"sleep (?:the\s+)?(?:computer|pc|laptop)", t) \
            or t in ("sleep", "put the computer to sleep",
                     "put the pc to sleep", "go to sleep"):
        return ("sleep", None, None)
    if re.match(r"hibernate (?:the\s+)?(?:computer|pc|laptop)", t) \
            or t in ("hibernate",):
        return ("hibernate", None, None)
    if re.match(r"(?:what'?s|what is|check|tell me)\s+(?:my\s+)?battery"
                r"(?:\s+(?:level|percentage|percent|status))?$", t) \
            or t in ("battery", "battery level", "battery percentage",
                     "battery status"):
        return ("battery", None, None)
    if re.match(r"turn off (?:the\s+)?(?:display|screen|monitor)", t) \
            or t in ("turn off the screen", "turn off display"):
        return ("monitor_off", None, None)
    if re.match(r"(?:help|what can you do|what can i say|"
                r"show commands|list commands)$", t):
        return ("help", None, None)

    if re.match(r"(?:what(?:'s| is)\s+open|list (?:open )?windows|"
                r"what windows are open|what apps are open|show open windows)", t):
        return ("list_windows", None, None)

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
          "minimize", "maximize", "refresh", "switch", "next",
          "previous", "go", "tab", "settings", "order", "buy", "add",
          "lower", "raise", "reduce", "increase", "decrease", "set",
          "brightness", "restart", "sleep", "hibernate", "battery",
          "shutdown", "cancel")

# Verb groups for compound commands: a bare noun after one of these
# inherits the verb ("open chrome and notepad" opens both apps).
_OPEN_VERBS = ("open", "launch", "start", "run")
_CLOSE_VERBS = ("close", "quit", "exit", "kill")


class CommandEngine:
    def __init__(self, build_index=True, note_saver=None, on_action=None,
                 profile_saver=None, on_open_settings=None, llm=None,
                 on_llm_done=None, phrase_learner=None):
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
        # on_open_settings() -> None; wired by the app to open its own
        # Settings window ("open settings" means THIS app's settings).
        self.on_open_settings = on_open_settings
        # Optional local-LLM fallback: llm(phrase) -> canonical command or
        # None, only consulted after every fast path fails, on a background
        # thread (see _llm_retry). on_llm_done(ok, feedback) announces the
        # async result; phrase_learner(heard, canonical) persists it so the
        # same phrase resolves instantly next time.
        self.llm = llm
        self.on_llm_done = on_llm_done
        self.phrase_learner = phrase_learner
        # heard phrase -> corrected command phrase, taught via History.
        self.learned_commands = {}
        # Set once the app index has finished building.
        self.index_ready = threading.Event()
        if build_index:
            threading.Thread(target=self._build_index, daemon=True).start()
        else:
            self.index_ready.set()

    def wait_ready(self, timeout):
        """Block until the app index is built, so a command issued right
        after startup does not miss installed apps."""
        self.index_ready.wait(timeout)

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
        self.index_ready.set()

    def switch_to(self, term, allow_browser=True):
        """If a window whose title contains `term` is open, focus it and
        return its title; otherwise return None. Lets 'open youtube' jump
        to an already-open YouTube instead of opening a duplicate.
        With allow_browser=False, browser tabs are ignored (so "open
        notepad" won't grab a browser tab titled "notepad - Search")."""
        term = (term or "").strip().lower()
        if len(term) < 2:
            return None
        best = None
        for hwnd, title, exe in _enum_windows():
            tl = title.lower()
            if any(p in tl for p in _PROTECTED_CLOSE):
                continue
            el = os.path.splitext(exe)[0].lower()
            # With allow_browser=False, browser windows only count when the
            # term IS the browser itself ("open chrome" should focus an open
            # Chrome, not a tab that merely mentions the name).
            if not allow_browser and el in _BROWSER_EXES \
                    and term != el and term not in el:
                continue
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
            # A browser window whose title merely mentions the name is a
            # tab, not the app — closing it would kill the whole browser.
            if el in _BROWSER_EXES and name != el and name not in el:
                continue
            if needle in tl or needle == el or needle in el:
                matches.append((hwnd, title))

        if not matches:
            return False, f'No open window for "{name}" found'
        hwnds = [h for h, _ in matches]
        for hwnd in hwnds:
            _post_close(hwnd)
        label = name.title()
        # Verify it actually closed (it may be prompting to save).
        time.sleep(0.6)
        still = {h for h, _t, _e in _enum_windows()} & set(hwnds)
        if not still:
            return True, (f"Closed {label}" if len(hwnds) == 1
                          else f"Closed {len(hwnds)} {label} windows")
        return True, f"Asked {label} to close (it may be waiting for you)"

    def _inherit_verb(self, verb, noun):
        """Give a bare noun in a compound sentence the previous part's
        verb: "open chrome and notepad" opens notepad too, "close tab
        and notepad" closes notepad, and "order monster from instamart
        and red bull from blinkit" orders both. Only when the noun
        plausibly names an app / a product+site, so we never invent
        actions."""
        noun = noun.strip().lower()
        if verb in _OPEN_VERBS and self.find_app(noun):
            return ("open_app", noun, None)
        if verb in _CLOSE_VERBS and noun not in (
                "window", "this window", "current window", "tab",
                "this tab", "current tab", "this", "everything"):
            return ("close_app", noun, None)
        if verb in ("order", "buy", "purchase", "get", "add"):
            m = re.match(
                r"(.+?)\s+(?:from|on|at)\s+(?:the\s+)?(.+)$", noun)
            if m:
                product = m.group(1).strip()
                site = m.group(2).strip()
                # Same "get" guard as parse(): a bare noun after "get" is
                # only an order when the site is a real ordering site.
                if product and site and (verb != "get"
                                         or _resolve_order_site(site)):
                    return ("order", (product, site), None)
        return None

    def set_learned_phrases(self, phrases):
        """Adopt the heard -> corrected command map the user taught in
        the History window, so those phrases resolve instead of failing."""
        self.learned_commands = {
            str(k).strip().lower(): str(v)
            for k, v in (phrases or {}).items() if str(k).strip()
        }

    def _learned(self, text):
        """Resolve a phrase the user previously corrected in History:
        exact heard-phrase match first, then a fuzzy close match. Returns
        a parsed command or None."""
        t = _normalize(text)
        if not t or not self.learned_commands:
            return None
        if t in self.learned_commands:
            return parse(self.learned_commands[t])
        # The user may have taught the phrase with trailing politeness
        # ("next window please"); _normalize strips it, so compare both
        # sides without the trailer. Bounded by the 100-phrase cap.
        t_plain = _TRAILER.sub("", t).strip()
        if t_plain:
            for key, corrected in self.learned_commands.items():
                if _TRAILER.sub("", key).strip() == t_plain:
                    return parse(corrected)
        near = difflib.get_close_matches(
            t, list(self.learned_commands), n=1, cutoff=0.8)
        if near:
            return parse(self.learned_commands[near[0]])
        return None

    def _split_commands(self, text):
        """Split "X and Y" / "X then Y" into two commands, but only when
        every part resolves — otherwise the sentence is a single command
        (e.g. "take a note buy milk and eggs" stays one note). A bare
        noun after an open/close verb inherits it (see _inherit_verb)."""
        parts = _COMPOUND_SPLIT.split(text.strip())
        if len(parts) < 2:
            return None
        out = []
        last_verb = None
        for p in parts:
            p = p.strip()
            if not p:
                return None
            cmd = parse(p)
            if cmd is None:
                r = self._repair(p)
                if r:
                    cmd = parse(r)
                    # A misheard part that repaired successfully is worth
                    # remembering too, so the same half-sentence resolves
                    # instantly next time ("swith tab" on its own).
                    if cmd is not None and self.phrase_learner:
                        try:
                            self.phrase_learner(p, r)
                        except Exception:
                            pass
            if cmd is None and last_verb:
                inherited = self._inherit_verb(last_verb, p)
                if inherited:
                    cmd = inherited
            if cmd is None:
                return None
            out.append(cmd)
            words = _normalize(p).split()
            last_verb = words[0] if words else None
        return out

    def run(self, text):
        """Parse and execute. Returns (ok, feedback)."""
        # One sentence can carry two commands: "switch tab and open
        # settings". Split first so the pair runs instead of failing as
        # an unknown phrase. (Single commands never split — see above.)
        cmds = self._split_commands(text)
        if cmds:
            results = []
            all_ok = True
            site = None
            for kind, arg, _ in cmds:
                # "open youtube and search for mr beast" — chain the
                # search into the site that was just opened instead of a
                # bare Google search.
                if kind == "search" and site in SITE_SEARCH \
                        and isinstance(arg, str):
                    kind, arg = "site_search", (site, arg)
                try:
                    ok, feedback = self._execute(kind, arg)
                except Exception as e:
                    ok, feedback = False, f"Failed: {e}"
                all_ok = all_ok and ok
                if self.on_action:
                    try:
                        self.on_action(kind, arg, ok)
                    except Exception:
                        pass
                if feedback:
                    results.append(feedback)
                # Remember the site the user opened so a following
                # "search for X" lands on it.
                if kind in ("open_app", "open_web", "url") \
                        and isinstance(arg, str):
                    site = arg
            return all_ok, " ".join(results) or "Done"

        # A phrase the user explicitly taught in History beats the generic
        # grammar: it must win even when the text still parses, because
        # "open chrrm" parses as open_app("chrrm") and would otherwise
        # produce a useless web search instead of opening chrome.
        cmd = self._learned(text)
        if cmd is None:
            cmd = parse(text)
        if cmd is None:
            # Repair a misheard command before giving up.
            repaired = self._repair(text)
            if repaired:
                cmd = parse(repaired)
                # The user will phrase it the same way again — remember
                # the repair so it resolves instantly next time (the
                # same mechanism that persists LLM resolutions).
                if cmd is not None and self.phrase_learner:
                    try:
                        self.phrase_learner(text, repaired)
                    except Exception:
                        pass
        if cmd is None:
            # Fuzzy-match the whole phrase to the closest known command
            # instead of answering "I don't understand".
            cmd = self._suggest(text)
        if cmd is None and self.llm is not None:
            # Genuinely novel phrasing: reply instantly, then ask the
            # local LLM to restate it in the background. The reply is not
            # held up by the model call (it can take seconds), and a
            # successful resolution is announced + learned afterwards.
            threading.Thread(target=self._llm_retry, args=(text,),
                             daemon=True).start()
            return False, (f'Not sure yet — thinking about "{text.strip()}"…')
        if cmd is None:
            return False, (f'Not sure what you meant by "{text.strip()}". '
                           "Try: open chrome, switch tab, volume up, "
                           "take a note, or say help")
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

    def _llm_retry(self, text):
        """Background fallback for novel phrasing: ask the local LLM to
        restate the phrase as a canonical command, then run it through the
        same parser and executor. The LLM never executes anything directly
        — its output must parse, so it cannot gain powers the pattern
        matcher does not already have."""
        if self.llm is None:
            return
        try:
            canonical = self.llm(text)
        except Exception:
            return
        if not canonical:
            return
        cmd = parse(canonical)
        if cmd is None:
            return  # model produced nothing parseable — keep quiet
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
        # Teach the resolution so the identical phrase is instant next
        # time — the LLM is only ever a first-line-of-defense.
        if self.phrase_learner:
            try:
                self.phrase_learner(text, canonical)
            except Exception:
                pass
        if self.on_llm_done:
            try:
                self.on_llm_done(ok, feedback)
            except Exception:
                pass

    def _suggest(self, text):
        """Fuzzy-match an unparseable phrase to the closest known command,
        so a slight mishearing still lands instead of a blind refusal.
        Pure string matching — no network, no model, microseconds."""
        t = _normalize(text)
        if not t:
            return None
        # Cheap keyword routes for the most common phrasings that miss the
        # grammar: "switch to the next tab", "open up settings", etc.
        if "tab" in t:
            if any(w in t for w in ("next", "forward", "following",
                                    "switch", "change", "go")):
                return ("tab", "next", None)
            if any(w in t for w in ("previous", "back", "prior", "last")):
                return ("tab", "prev", None)
        if "settings" in t and any(w in t for w in ("open", "show",
                                                     "launch")):
            return ("app_settings", None, None)
        # Volume / brightness phrases with an extra word still land.
        # A "by N" change ("increase volume by 20%") is computed from
        # the current level, so it must win over the plain up/down route.
        m = re.search(r"by\s+(\d{1,3})", t)
        if m:
            if "volume" in t and any(w in t for w in ("increase", "raise",
                                                       "up", "louder",
                                                       "boost")):
                return ("volume", "add:" + m.group(1), None)
            if "volume" in t and any(w in t for w in ("decrease", "lower",
                                                       "down", "quieter",
                                                       "reduce")):
                return ("volume", "sub:" + m.group(1), None)
            if "brightness" in t and any(w in t for w in ("increase",
                                                           "raise", "up",
                                                           "brighter")):
                return ("brightness", "add:" + m.group(1), None)
            if "brightness" in t and any(w in t for w in ("decrease",
                                                           "lower", "down",
                                                           "dimmer")):
                return ("brightness", "sub:" + m.group(1), None)
        if "volume" in t and any(w in t for w in ("down", "lower",
                                                   "quieter", "reduce")):
            return ("volume", "down", None)
        if "volume" in t and any(w in t for w in ("up", "raise",
                                                   "louder", "increase")):
            return ("volume", "up", None)
        if "brightness" in t and any(w in t for w in ("down", "lower",
                                                       "decrease", "dimmer")):
            return ("brightness", "down", None)
        if "brightness" in t and any(w in t for w in ("up", "raise",
                                                       "increase", "brighter")):
            return ("brightness", "up", None)
        # "search mr beast in youtube" (or any mishearing: "google ... in
        # youtube", "look for ... on youtube", "find ... in youtube", "in
        # the youtube", "you tube" split, "youtube app", "youtube.com")
        # must land on YouTube results, never a bare Google search.
        m = re.search(
            _YT_VERBS + r"\s+(?:for\s+)?(.+?)\s+(?:on|in)\s+(?:the\s+)?"
            + _YT, t)
        if m:
            return ("youtube", m.group(1).strip(), None)
        if re.search(_YT, t):
            m = re.search(_YT + r"\s+search\s+(?:for\s+)?(.+)", t)
            if m:
                return ("youtube", m.group(1).strip(), None)
        # Whisper sometimes drops the verb entirely: "mr beast in youtube"
        # is still a YouTube search, not a Google search for the sentence.
        # A short query guard keeps filler-only fragments ("the in
        # youtube") from becoming searches.
        m = re.search(
            r"(.+?)\s+(?:on|in)\s+(?:the\s+)?(?:youtube|you\s+tube)"
            r"(?:\s+(?:app|website|the)|\.com)?\s*$", t)
        if m and len(m.group(1).strip()) >= 3:
            return ("youtube", m.group(1).strip(), None)
        # "order monster from instamart" (or a slight mishearing of it).
        if any(w in t for w in ("order", "buy", "purchase", "get")) \
                and any(w in t for w in ("from", "on", "at")):
            m = re.match(
                r"(?P<verb>order|buy|purchase|get)\s+(?:me\s+)?(?:a\s+|an\s+|"
                r"the\s+|some\s+)?(?P<prod>.+?)\s+(?:from|on|at)\s+"
                r"(?:the\s+)?(?P<site>.+)$", t)
            if m and (m.group("verb") != "get"
                      or _resolve_order_site(m.group("site").strip())):
                return ("order", (m.group("prod").strip(),
                                   m.group("site").strip()), None)
        known = (list(SHORTCUTS) + ["open chrome", "open notepad",
                                    "take a screenshot", "lock the screen",
                                    "volume up", "volume down", "scroll up",
                                    "scroll down", "what time is it",
                                    "what's the date", "play music"])
        near = difflib.get_close_matches(t, known, n=1, cutoff=0.72)
        if near:
            return parse(near[0])
        return None

    def _execute(self, kind, arg):
        if kind == "switch":
            got = self.switch_to(arg)
            if got:
                return True, f"Switched to {arg.title()}"
            # Nothing open by that name — open it instead.
            kind = "open_app"

        if kind == "open_app":
            # Verify the app is installed first: if so, focus it when it is
            # already running, otherwise open the app. If not installed,
            # open it on the web (focusing an existing tab if there is one).
            found = self.find_app(arg)
            if found:
                target, label = found
                # Already running? Jump to it instead of a duplicate. Match
                # by the app itself, not a browser tab that mentions the name.
                got = self.switch_to(arg, allow_browser=False)
                if got:
                    return True, f"Switched to {label.title()}"
                self._launch(target)
                return True, f"Opening {label.title()}"
            got = self.switch_to(arg)  # site/tab already open?
            if got:
                return True, f"Switched to {arg.title()}"
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

        if kind == "order":
            product, site = arg
            url = _order_url(product, site)
            webbrowser.open(url)
            label, _ = _resolve_order_site(site) or (site.title(), None)
            return True, (f"Opened {label} with {product} in search — "
                          f"tap the item to add it to your cart")

        if kind == "tab":
            import keyboard
            if arg == "next":
                keyboard.send("ctrl+tab")
                return True, "Switched to the next tab"
            if arg == "prev":
                keyboard.send("ctrl+shift+tab")
                return True, "Switched to the previous tab"
            keyboard.send(f"ctrl+{arg}")
            return True, f"Switched to tab {arg}"

        if kind == "app_settings":
            if self.on_open_settings is None:
                return False, "Opening settings is not available right now"
            self.on_open_settings()
            return True, "Opening Settings"

        if kind == "help":
            return True, ("Try: open or close an app, switch tab, open "
                          "settings, lower the volume, set brightness, "
                          "check battery, restart the computer, order from "
                          "instamart or amazon, or take a note.")

        if kind == "list_windows":
            seen = []
            for _hwnd, title, _exe in _enum_windows():
                tl = title.lower()
                if any(p in tl for p in _PROTECTED_CLOSE):
                    continue
                if title and title not in seen:
                    seen.append(title)
            if not seen:
                return True, "No windows are open"
            shown = "; ".join(seen[:6])
            extra = f" and {len(seen) - 6} more" if len(seen) > 6 else ""
            return True, f"{len(seen)} open: {shown}{extra}"

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
            # "youtube dot com" -> youtube.com; but NEVER strip spaces to
            # make a domain — a phrase like "youtube and search for mr
            # beast" is not a URL, it is a mis-split sentence. Route it
            # to a web search instead of opening a garbage address.
            arg = arg.replace(" dot ", ".")
            if " " in arg:
                webbrowser.open("https://www.google.com/search?q="
                                + _quote(arg))
                return True, f"Searching for {arg}"
            url = SITES.get(arg) or (
                arg if arg.startswith("http") else "https://" + arg)
            webbrowser.open(url)
            return True, f"Opening {arg}"

        if kind == "site_search":
            # "open youtube and search for mr beast" — the search runs
            # on the site the user opened, not Google. Only reached when
            # the site is known (guarded in run()); .get() keeps direct
            # calls safe too.
            site, topic = arg
            url = SITE_SEARCH.get(site)
            if url is None:
                webbrowser.open("https://www.google.com/search?q="
                                + _quote(topic))
                return True, f"Searching for {topic}"
            webbrowser.open(url.format(q=_quote(topic)))
            return True, f"Searching {site.title()} for {topic}"

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
            if arg.startswith("set:"):
                level = max(0, min(100, int(arg.split(":", 1)[1])))
                try:
                    _set_volume_level(level)
                except Exception as e:
                    return False, f"Could not set volume: {e}"
                return True, f"Volume set to {level}%"
            if arg.startswith(("add:", "sub:")):
                # "increase volume by 20%" — read the current level so
                # the delta lands on reality, and clamp to 0-100.
                cur = _current_volume()
                if cur is None:
                    return False, "Could not read the current volume"
                delta = int(arg.split(":", 1)[1])
                level = max(0, min(100, cur + delta if arg.startswith("add:")
                                   else cur - delta))
                try:
                    _set_volume_level(level)
                except Exception as e:
                    return False, f"Could not set volume: {e}"
                return True, f"Volume set to {level}%"
            import keyboard
            for _ in range(4):
                keyboard.send("volume up" if arg == "up" else "volume down")
            return True, f"Volume {arg}"

        if kind == "brightness":
            if arg.startswith("set:"):
                level = max(0, min(100, int(arg.split(":", 1)[1])))
            elif arg.startswith(("add:", "sub:")):
                # "increase brightness by 20%" — same relative logic as
                # volume, clamped to 0-100.
                cur = _current_brightness()
                delta = int(arg.split(":", 1)[1])
                level = max(0, min(100, cur + delta if arg.startswith("add:")
                                   else cur - delta))
            else:
                cur = _current_brightness()
                level = max(0, min(100, cur + (10 if arg == "up" else -10)))
            try:
                ok = _set_brightness(level)
            except Exception as e:
                return False, f"Could not adjust brightness: {e}"
            if not ok:
                return False, "Brightness is not adjustable on this display"
            return True, f"Brightness set to {level}%"

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

        if kind == "restart":
            subprocess.run(["shutdown", "/r", "/t", "60"], check=False)
            return True, "Restarting in 60 seconds. Say cancel restart to stop it"

        if kind == "cancel_shutdown":
            subprocess.run(["shutdown", "/a"], check=False)
            return True, "Shutdown or restart cancelled"

        if kind == "sleep":
            subprocess.run(
                ["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"],
                check=False)
            return True, "Putting the computer to sleep"

        if kind == "hibernate":
            subprocess.run(["shutdown", "/h"], check=False)
            return True, "Hibernating the computer"

        if kind == "battery":
            pct = _battery_percent()
            if pct is None:
                return False, "No battery detected — this looks like a desktop"
            return True, f"Battery at {pct}%"

        if kind == "monitor_off":
            ctypes.windll.user32.SendMessageW(
                0xFFFF, 0x0112, 0xF170, 2)  # broadcast, WM_SYSCOMMAND,
            # SC_MONITORPOWER, 2=off — turns off just the display
            return True, "Turning off the display"

        if kind == "open_settings_page":
            os.startfile("ms-settings:" + arg)
            return True, f"Opening {arg.replace('-', ' ')} settings"

        if kind == "time":
            return True, "It is " + time.strftime("%I:%M %p").lstrip("0")

        if kind == "date":
            return True, "Today is " + time.strftime("%A, %d %B %Y")

        return False, "Not implemented"


def _current_volume():
    """Read the current system volume (0-100) from the default audio
    endpoint via the Core Audio API, or None when it cannot be read.
    Used for "increase volume by 20%" so the new level is computed from
    reality, not guessed."""
    try:
        import volume
        return volume.current_volume()
    except Exception:
        return None


def _set_volume_level(level):
    """Set the system volume to `level` percent (0-100) on the default
    audio endpoint via Core Audio (the same control the Windows volume
    flyout uses). winmm's waveOutSetVolume only drives the legacy wave
    device and can return success while nothing audible changes — so the
    change is verified by reading it back, and raises OSError when it did
    not land, so the user never hears a fake confirmation."""
    level = max(0, min(100, int(level)))
    try:
        import volume
        volume.set_volume_level(level)
    except Exception as e:
        raise OSError(f"could not set volume: {e}") from e
    # Verify the change actually landed; tolerate a rounding step or two.
    try:
        got = volume.current_volume()
    except Exception:
        got = None
    if got is None or abs(got - level) > 3:
        raise OSError(f"volume did not change (still {got}%)")


def _current_brightness():
    """Query the current display brightness (0-100), or 50 if unknown."""
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "(Get-WmiObject -Namespace root/WMI -Class "
             "WmiMonitorBrightness).CurrentBrightness"],
            capture_output=True, text=True, timeout=10,
            creationflags=CREATE_NO_WINDOW)
        return int(out.stdout.strip() or 50)
    except Exception:
        return 50


def _set_brightness(level):
    """Set display brightness via WMI (works on laptops without extra
    dependencies). Returns True when the display accepted the change."""
    level = max(0, min(100, int(level)))
    out = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "(Get-WmiObject -Namespace root/WMI -Class "
         f"WmiMonitorBrightnessMethods).WmiSetBrightness(1, {level})"],
        capture_output=True, text=True, timeout=10,
        creationflags=CREATE_NO_WINDOW)
    # Only claim success when PowerShell itself succeeded AND the WMI
    # method did not raise (desktop displays often lack this method).
    return (out.returncode == 0
            and "MethodInvocationException" not in (out.stderr or ""))


def _battery_percent():
    """Read the battery charge (0-100), or None when there is no battery.
    Multi-battery machines return one line per battery; the first is used."""
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "(Get-CimInstance -ClassName Win32_Battery) | "
             "Select-Object -ExpandProperty EstimatedChargeRemaining"],
            capture_output=True, text=True, timeout=10,
            creationflags=CREATE_NO_WINDOW)
        lines = [ln.strip() for ln in (out.stdout or "").splitlines()
                 if ln.strip()]
        return int(lines[0]) if lines else None
    except Exception:
        return None


def _quote(s):
    from urllib.parse import quote_plus
    return quote_plus(s)


def _post_close(hwnd):
    """Send a graceful WM_CLOSE to a window (never a force-kill), so apps
    can still prompt to save unsaved work."""
    ctypes.windll.user32.PostMessageW(hwnd, 0x0010, 0, 0)


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
