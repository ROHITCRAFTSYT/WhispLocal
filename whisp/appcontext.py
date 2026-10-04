"""Where is the user dictating? Foreground app, its category, and the text
just before the caret.

The category drives the writing style (an email gets formal sentences, a
chat gets a relaxed message, a terminal gets the words verbatim). The text
before the caret lets the insertion planner add a leading space or keep a
sentence going in lowercase instead of always starting a fresh sentence.

All of this is read locally through Win32 (and UI Automation when the
optional `comtypes` package is installed). Nothing is stored or sent
anywhere, and password fields are never read.
"""
import ctypes
import os
import re
import threading
from ctypes import wintypes

CATEGORIES = ("email", "chat", "ai_chat", "code", "notes", "docs",
              "terminal", "general")

# Process name (lowercase, no .exe) -> category.
APP_CATEGORIES = {
    # email
    "outlook": "email", "olk": "email", "thunderbird": "email",
    "mailspring": "email", "hxoutlook": "email", "em client": "email",
    # chat
    "slack": "chat", "discord": "chat", "teams": "chat", "ms-teams": "chat",
    "whatsapp": "chat", "whatsapp.root": "chat", "telegram": "chat",
    "signal": "chat", "zoom": "chat", "skype": "chat", "element": "chat",
    "mattermost": "chat",
    # AI assistants
    "claude": "ai_chat", "chatgpt": "ai_chat", "perplexity": "ai_chat",
    # code
    "code": "code", "code - insiders": "code", "cursor": "code",
    "windsurf": "code", "zed": "code", "devenv": "code",
    "sublime_text": "code", "notepad++": "code", "pycharm64": "code",
    "idea64": "code", "webstorm64": "code", "rider64": "code",
    "clion64": "code", "goland64": "code", "phpstorm64": "code",
    "rustrover64": "code", "datagrip64": "code", "studio64": "code",
    # notes
    "obsidian": "notes", "notion": "notes", "onenote": "notes",
    "onenoteim": "notes", "logseq": "notes", "evernote": "notes",
    "notepad": "notes", "joplin": "notes", "stickynotes": "notes",
    # documents
    "winword": "docs", "wordpad": "docs", "powerpnt": "docs",
    "soffice.bin": "docs", "swriter": "docs", "scrivener": "docs",
    # terminals
    "windowsterminal": "terminal", "cmd": "terminal",
    "powershell": "terminal", "pwsh": "terminal", "wezterm-gui": "terminal",
    "alacritty": "terminal", "mintty": "terminal", "conemu64": "terminal",
    "hyper": "terminal", "tabby": "terminal", "warp": "terminal",
}

BROWSERS = frozenset({"chrome", "msedge", "firefox", "brave", "opera",
                      "vivaldi", "arc", "chromium", "zen", "librewolf"})

# For browsers (and generic hosts) the window title names the web app.
# First match wins, so the more specific patterns come first.
TITLE_RULES = [
    (r"\bgmail\b|\binbox\b.*@|outlook\b.*mail|\bproton mail\b", "email"),
    (r"\bchatgpt\b|\bclaude\b|\bgemini\b|\bperplexity\b|\bcopilot\b",
     "ai_chat"),
    (r"\bslack\b|\bdiscord\b|\bwhatsapp\b|\btelegram\b|\bmessenger\b|"
     r"microsoft teams|\bgoogle chat\b", "chat"),
    (r"google docs|\bword\b.*online|\bdropbox paper\b|\bconfluence\b",
     "docs"),
    (r"\bnotion\b|\bobsidian\b|\bgoogle keep\b|\bevernote\b", "notes"),
    (r"\bgithub\b|\bgitlab\b|\bstack overflow\b|\bcodesandbox\b|"
     r"\breplit\b|\bcolab\b|\bjupyter\b", "code"),
]

# Window classes that mean "no text field": the desktop and the taskbar.
NO_TARGET_CLASSES = frozenset({"Progman", "WorkerW", "Shell_TrayWnd",
                               "Shell_SecondaryTrayWnd"})


def normalize_exe(path):
    """'C:\\...\\Code.exe' -> 'code'."""
    name = os.path.basename(path or "").lower()
    return name[:-4] if name.endswith(".exe") else name


def categorize(exe, title=""):
    """Map a process name and window title to one of CATEGORIES."""
    exe = normalize_exe(exe)
    title_l = (title or "").lower()
    if exe in BROWSERS or exe in ("applicationframehost", "electron", ""):
        for pattern, cat in TITLE_RULES:
            if re.search(pattern, title_l):
                return cat
        return APP_CATEGORIES.get(exe, "general")
    return APP_CATEGORIES.get(exe, "general")


class Context:
    """Snapshot of the dictation target, taken when recording starts."""

    def __init__(self, exe="", title="", window_class="", before=None,
                 secure=False, hwnd=None):
        self.exe = normalize_exe(exe)
        self.title = title or ""
        self.window_class = window_class or ""
        self.category = categorize(self.exe, self.title)
        self.before = before      # text left of the caret, or None
        self.secure = secure      # password field: never read or learn
        self.hwnd = hwnd

    @property
    def has_target(self):
        """False when focus is on the desktop or taskbar, where a paste
        would go nowhere."""
        if self.hwnd is None and not self.exe:
            return False
        return self.window_class not in NO_TARGET_CLASSES

    def label(self):
        return self.exe or "unknown app"

    def __repr__(self):
        return (f"Context({self.exe!r}, {self.category!r}, "
                f"before={self.before!r:.40}, secure={self.secure})")


# ----- Win32 ------------------------------------------------------------------

class _GUITHREADINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("flags", wintypes.DWORD),
                ("hwndActive", wintypes.HWND), ("hwndFocus", wintypes.HWND),
                ("hwndCapture", wintypes.HWND),
                ("hwndMenuOwner", wintypes.HWND),
                ("hwndMoveSize", wintypes.HWND),
                ("hwndCaret", wintypes.HWND), ("rcCaret", wintypes.RECT)]


_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_WM_GETTEXT = 0x000D
_WM_GETTEXTLENGTH = 0x000E
_EM_GETSEL = 0x00B0
_GWL_STYLE = -16
_ES_PASSWORD = 0x0020
_SMTO_ABORTIFHUNG = 0x0002
_EDIT_CLASSES = ("edit", "richedit", "windowsforms10.edit", "tedit",
                 "scintilla")


_U32 = None


def _user32():
    """A private, fully typed user32 handle. Typed signatures matter on
    64-bit Windows (pointers and handles do not fit a C int), and a private
    WinDLL keeps these argtypes from leaking into other libraries that
    share ctypes.windll.user32."""
    global _U32
    if _U32 is None:
        u = ctypes.WinDLL("user32", use_last_error=True)
        H, U, D = wintypes.HWND, wintypes.UINT, wintypes.DWORD
        u.GetForegroundWindow.restype = H
        u.GetForegroundWindow.argtypes = []
        u.GetWindowThreadProcessId.restype = D
        u.GetWindowThreadProcessId.argtypes = [H, ctypes.POINTER(D)]
        u.GetGUIThreadInfo.restype = wintypes.BOOL
        u.GetGUIThreadInfo.argtypes = [D, ctypes.POINTER(_GUITHREADINFO)]
        u.GetClassNameW.argtypes = [H, wintypes.LPWSTR, ctypes.c_int]
        u.GetWindowTextW.argtypes = [H, wintypes.LPWSTR, ctypes.c_int]
        u.GetWindowLongW.restype = wintypes.LONG
        u.GetWindowLongW.argtypes = [H, ctypes.c_int]
        u.SendMessageTimeoutW.restype = wintypes.LPARAM
        u.SendMessageTimeoutW.argtypes = [
            H, U, wintypes.WPARAM, wintypes.LPARAM, U, U,
            ctypes.POINTER(ctypes.c_size_t)]
        _U32 = u
    return _U32


def _window_class(hwnd):
    buf = ctypes.create_unicode_buffer(256)
    _user32().GetClassNameW(hwnd, buf, 256)
    return buf.value


def _window_title(hwnd):
    buf = ctypes.create_unicode_buffer(512)
    _user32().GetWindowTextW(hwnd, buf, 512)
    return buf.value


def _process_path(hwnd):
    pid = wintypes.DWORD()
    _user32().GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    k32 = ctypes.windll.kernel32
    h = k32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(1024)
        if k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return buf.value
        return ""
    finally:
        k32.CloseHandle(h)


def _focused_child(hwnd):
    tid = _user32().GetWindowThreadProcessId(hwnd, None)
    info = _GUITHREADINFO(cbSize=ctypes.sizeof(_GUITHREADINFO))
    if _user32().GetGUIThreadInfo(tid, ctypes.byref(info)):
        return info.hwndFocus or hwnd
    return hwnd


def _send(hwnd, msg, wparam=0, lparam=0, timeout_ms=150):
    result = ctypes.c_size_t()
    ok = _user32().SendMessageTimeoutW(hwnd, msg, wparam, lparam,
                                       _SMTO_ABORTIFHUNG, timeout_ms,
                                       ctypes.byref(result))
    return result.value if ok else None


def _is_password_edit(hwnd):
    try:
        style = _user32().GetWindowLongW(hwnd, _GWL_STYLE)
        return bool(style & _ES_PASSWORD)
    except Exception:
        return False


def _edit_text_before(hwnd, max_chars):
    """Classic Edit/RichEdit controls answer WM_GETTEXT and EM_GETSEL even
    across processes, which covers Notepad, WordPad and many older apps."""
    length = _send(hwnd, _WM_GETTEXTLENGTH)
    if length is None:
        return None
    if length == 0:
        return ""
    buf = ctypes.create_unicode_buffer(length + 1)
    got = _send(hwnd, _WM_GETTEXT, length + 1, ctypes.addressof(buf))
    if got is None:
        return None
    text = buf.value
    sel = _send(hwnd, _EM_GETSEL)
    if sel is None:
        return None
    start = sel & 0xFFFF
    if length > 0xFFFF:  # packed selection is 16-bit; caret unknown
        return None
    return text[max(0, start - max_chars):start]


_uia_state = {"failed": False}


def _uia_text_before(max_chars):
    """Text before the caret via UI Automation (browsers, Word, Electron
    apps). Optional: needs `comtypes`; silently unavailable otherwise.
    Runs on a worker thread, so COM is initialised here per call."""
    if _uia_state["failed"]:
        return None, False
    try:
        import comtypes
        import comtypes.client
    except ImportError:
        _uia_state["failed"] = True
        return None, False
    try:
        comtypes.CoInitialize()
    except OSError:
        pass
    try:
        comtypes.client.GetModule("UIAutomationCore.dll")
        from comtypes.gen import UIAutomationClient as uia
        client = comtypes.client.CreateObject(
            uia.CUIAutomation, interface=uia.IUIAutomation)
        el = client.GetFocusedElement()
        if el is None:
            return None, False
        if el.CurrentIsPassword:
            return None, True
        pattern = el.GetCurrentPattern(uia.UIA_TextPatternId)
        if not pattern:
            return None, False
        tp = pattern.QueryInterface(uia.IUIAutomationTextPattern)
        ranges = tp.GetSelection()
        if ranges is None or ranges.Length == 0:
            return None, False
        caret = ranges.GetElement(0).Clone()
        # Collapse to the selection start, then extend backwards.
        caret.MoveEndpointByRange(uia.TextPatternRangeEndpoint_End, caret,
                                  uia.TextPatternRangeEndpoint_Start)
        caret.MoveEndpointByUnit(uia.TextPatternRangeEndpoint_Start,
                                 uia.TextUnit_Character, -max_chars)
        return caret.GetText(max_chars), False
    except Exception:
        return None, False
    finally:
        try:
            comtypes.CoUninitialize()
        except Exception:
            pass


def _foreground():
    """(hwnd, exe, title, top_class, focus_hwnd, focus_class) — fast."""
    hwnd = _user32().GetForegroundWindow()
    if not hwnd:
        return None
    focus = _focused_child(hwnd)
    return (hwnd, _process_path(hwnd), _window_title(hwnd),
            _window_class(hwnd), focus, _window_class(focus))


def _read_before(focus, focus_class, max_chars):
    """(text_before_caret or None, is_password_field)."""
    if focus_class.lower().startswith(_EDIT_CLASSES):
        if _is_password_edit(focus):
            return None, True
        text = _edit_text_before(focus, max_chars)
        if text is not None:
            return text, False
        # Modern rich-edit hosts (Windows 11 Notepad) ignore the classic
        # messages; UI Automation still works for them.
    return _uia_text_before(max_chars)


def capture(read_text=True, max_chars=200):
    """Snapshot the foreground app synchronously. Never raises; returns an
    empty Context off Windows or when nothing is focused."""
    try:
        fg = _foreground()
    except Exception:
        return Context()
    if fg is None:
        return Context()
    hwnd, exe, title, top_class, focus, focus_class = fg
    before, secure = None, False
    if read_text:
        try:
            before, secure = _read_before(focus, focus_class, max_chars)
        except Exception:
            pass
    return Context(exe, title, top_class, before=before, secure=secure,
                   hwnd=hwnd)


def capture_async(read_text=True, max_chars=200):
    """Identify the foreground app now (a few Win32 calls) and read the text
    before the caret on a worker thread, since UI Automation can be slow.
    Returns a callable that waits up to `timeout` for the text; if it is
    not ready the Context still carries the app and category."""
    try:
        fg = _foreground()
    except Exception:
        fg = None
    if fg is None:
        empty = Context()
        return lambda timeout=0.0: empty
    hwnd, exe, title, top_class, focus, focus_class = fg
    ctx = Context(exe, title, top_class, hwnd=hwnd)
    if not read_text:
        return lambda timeout=0.0: ctx

    def _run():
        try:
            before, secure = _read_before(focus, focus_class, max_chars)
            ctx.before, ctx.secure = before, secure
        except Exception:
            pass

    t = threading.Thread(target=_run, daemon=True)
    t.start()

    def result(timeout=0.4):
        t.join(timeout)
        return ctx

    return result
