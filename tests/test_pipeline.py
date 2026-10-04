"""End-to-end tests of the App pipeline glue: formatting for the target
app, spoken shortcuts, delivery without a text field, voice editing,
incognito and the recording time limit.

The App is built without its __init__ (no mic, tray, model or window);
keyboard, tray and audio libraries are stubbed so this runs anywhere.
"""
import os
import sys
import tempfile
import threading
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "whisp"))

_STUBS = {name: mock.MagicMock() for name in (
    "keyboard", "pyperclip", "pystray", "PIL", "PIL.Image", "PIL.ImageDraw",
    "sounddevice", "websockets")}
try:
    import numpy  # noqa: F401  (audio.py needs the real thing)
    HAVE_NUMPY = True
except ImportError:
    HAVE_NUMPY = False

if HAVE_NUMPY:
    with mock.patch.dict(sys.modules, _STUBS):
        import app as app_mod
        import appcontext
        from adaptive import Adaptive
        from locallm import LocalLLM
        from recovery import Ledger


def make_app(tmp, **config):
    a = app_mod.App.__new__(app_mod.App)
    a.config = {"remove_fillers": True, "capitalize_first": True,
                "context_styles": True, "sound_cues": False,
                "save_history": True, **config}
    a.adaptive = Adaptive(tmp, enabled=True)
    a.llm = LocalLLM("")
    a.overlay = mock.MagicMock()
    a.ledger = Ledger()
    a.last_take = mock.MagicMock()
    a.transcriber = mock.MagicMock()
    a.recorder = mock.MagicMock()
    a.incognito = False
    a.lock = threading.Lock()
    a._ctx_future = None
    a._streamer = None
    a._take_id = 0
    a.state = app_mod.IDLE
    a.task = "transcribe"
    return a


def ctx(exe="slack", title="general", window_class="Chrome_WidgetWin_1",
        before=None, secure=False):
    return appcontext.Context(exe, title, window_class, before=before,
                              secure=secure, hwnd=1)


@unittest.skipUnless(HAVE_NUMPY, "numpy not installed")
class FormatTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.app = make_app(self.tmp)

    def test_email_gets_formal(self):
        out = self.app._format("hey idk if it works", ctx("outlook"))
        self.assertEqual(out, "Hey, I do not know if it works.")

    def test_chat_gets_casual(self):
        self.assertEqual(self.app._format("sounds good.", ctx("slack")),
                         "Sounds good")

    def test_styles_can_be_turned_off(self):
        self.app.config["context_styles"] = False
        self.assertEqual(self.app._format("sounds good.", ctx("slack")),
                         "Sounds good.")

    def test_snippet_is_exact(self):
        self.app.config["snippets"] = {"my email": "me@x.com"}
        self.assertEqual(self.app._format("My email.", ctx("outlook")),
                         "me@x.com")

    def test_fits_text_before_caret(self):
        out = self.app._format("Then we left.",
                               ctx("notepad", window_class="Notepad",
                                   before="We ate and"))
        self.assertEqual(out, " then we left.")

    def test_dictionary_still_applies(self):
        self.app.config["dictionary"] = {"clod": "Claude"}
        self.assertEqual(self.app._format("ask clod", ctx("notepad")),
                         "Ask Claude")


@unittest.skipUnless(HAVE_NUMPY, "numpy not installed")
class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.app = make_app(tempfile.mkdtemp())

    def test_no_text_field_copies_instead(self):
        clip = mock.MagicMock()
        with mock.patch.object(app_mod, "insert") as ins, \
                mock.patch.dict(sys.modules, {"pyperclip": clip}):
            self.app._deliver("hello", ctx("explorer",
                                           window_class="Progman"))
        ins.assert_not_called()
        clip.copy.assert_called_once_with("hello")
        self.assertEqual(self.app.ledger.last(), "hello")

    def test_normal_insert(self):
        with mock.patch.object(app_mod, "insert") as ins:
            self.app._deliver("hello", ctx())
        ins.assert_called_once()
        self.assertEqual(self.app.ledger.last(), "hello")


@unittest.skipUnless(HAVE_NUMPY, "numpy not installed")
class EditTests(unittest.TestCase):
    def setUp(self):
        self.app = make_app(tempfile.mkdtemp())
        self.app.transcriber.transcribe.return_value = (
            "make it all caps", "en", 0.9)
        self.app._wait_hotkey_release = lambda timeout=1.5: None

    def _run(self, selection, context=None):
        self.app._ctx_future = lambda timeout=0.4: context or ctx()
        with mock.patch.object(app_mod.editing, "capture_selection",
                               return_value=selection), \
                mock.patch.object(app_mod, "insert") as ins, \
                mock.patch.object(self.app, "_save_history"):
            self.app._process_edit([0.0] * 16000)
        return ins

    def test_rule_edit_replaces_selection(self):
        ins = self._run("hello world")
        self.assertEqual(ins.call_args[0][0], "HELLO WORLD")

    def test_password_field_is_refused(self):
        ins = self._run("secret", ctx(secure=True))
        ins.assert_not_called()

    def test_nothing_selected_without_llm(self):
        ins = self._run("")
        ins.assert_not_called()
        msg = self.app.overlay.post.call_args[0][0]
        self.assertIn("Select text first", msg[1])

    def test_unknown_instruction_uses_llm(self):
        self.app.transcriber.transcribe.return_value = (
            "summarise this", "en", 0.9)
        self.app.llm = mock.MagicMock()
        self.app.llm.configured.return_value = True
        self.app.llm.rewrite.return_value = "Short."
        ins = self._run("A very long text about many things.")
        self.assertEqual(ins.call_args[0][0], "Short.")

    def test_author_mode_with_llm(self):
        self.app.transcriber.transcribe.return_value = (
            "write a thank you note", "en", 0.9)
        self.app.llm = mock.MagicMock()
        self.app.llm.configured.return_value = True
        self.app.llm.author.return_value = "Thank you!"
        ins = self._run("")
        self.assertEqual(ins.call_args[0][0], "Thank you!")


@unittest.skipUnless(HAVE_NUMPY, "numpy not installed")
class PrivacyAndLimitTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.app = make_app(self.tmp)

    def test_incognito_saves_no_history(self):
        path = os.path.join(self.tmp, "h.jsonl")
        self.app.incognito = True
        with mock.patch.object(app_mod, "HISTORY_PATH", path):
            self.app._save_history("secret", "transcribe", 1.0, 0.1)
        self.assertFalse(os.path.exists(path))

    def test_history_records_app_and_raw(self):
        path = os.path.join(self.tmp, "h.jsonl")
        with mock.patch.object(app_mod, "HISTORY_PATH", path):
            self.app._save_history("Hi.", "transcribe", 1.0, 0.1,
                                   app="slack", raw="hi")
        with open(path, encoding="utf-8") as f:
            line = f.read()
        self.assertIn('"app": "slack"', line)
        self.assertIn('"raw": "hi"', line)

    def test_incognito_retains_no_audio(self):
        self.app.incognito = True
        self.app._retain([0.0], "transcribe")
        self.app.last_take.save.assert_not_called()

    def test_take_limit_stops_locked_recording(self):
        self.app.state = app_mod.LOCKED
        self.app._take_id = 7
        with mock.patch.object(self.app, "_finish_recording") as fin:
            self.app._take_limit_hit(7)
        fin.assert_called_once()
        self.assertEqual(self.app.state, app_mod.IDLE)

    def test_stale_take_limit_is_ignored(self):
        self.app.state = app_mod.LOCKED
        self.app._take_id = 8
        with mock.patch.object(self.app, "_finish_recording") as fin:
            self.app._take_limit_hit(7)
        fin.assert_not_called()


if __name__ == "__main__":
    unittest.main()
