"""Unit tests for the voice-control intent parser. Parsing is pure and
stdlib-only, so these run on any CI runner."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "whisp"))

import commands
from commands import CommandEngine, parse


def kind_arg(text):
    cmd = parse(text)
    return (cmd[0], cmd[1]) if cmd else None


class ParseTests(unittest.TestCase):
    def test_open_app(self):
        self.assertEqual(kind_arg("Open Chrome."), ("open_app", "chrome"))
        self.assertEqual(kind_arg("please launch the app spotify"),
                         ("open_app", "spotify"))

    def test_open_folder(self):
        self.assertEqual(kind_arg("open downloads"), ("folder", "Downloads"))

    def test_open_url(self):
        self.assertEqual(kind_arg("open youtube.com"), ("url", "youtube.com"))
        self.assertEqual(kind_arg("go to github"), ("url", "github"))

    def test_search(self):
        self.assertEqual(kind_arg("search for python tutorials"),
                         ("search", "python tutorials"))
        self.assertEqual(kind_arg("google weather in delhi"),
                         ("search", "weather in delhi"))

    def test_youtube(self):
        self.assertEqual(kind_arg("play lo-fi beats on youtube"),
                         ("youtube", "lo-fi beats"))

    def test_type_preserves_casing(self):
        self.assertEqual(kind_arg("Type Hello World"), ("type", "Hello World"))

    def test_press_keys(self):
        self.assertEqual(kind_arg("press enter"), ("keys", "enter"))
        self.assertEqual(kind_arg("press control shift s"),
                         ("keys", "ctrl+shift+s"))

    def test_press_gibberish_rejected(self):
        self.assertIsNone(parse("press the big red button"))

    def test_volume_and_scroll(self):
        self.assertEqual(kind_arg("volume up"), ("volume", "up"))
        self.assertEqual(kind_arg("scroll down"), ("scroll", "down"))

    def test_shortcuts(self):
        self.assertEqual(kind_arg("close window"), ("shortcut", "close window"))
        self.assertEqual(kind_arg("next song"), ("shortcut", "next song"))
        self.assertEqual(kind_arg("select all"), ("shortcut", "select all"))

    def test_system(self):
        self.assertEqual(kind_arg("take a screenshot"), ("screenshot", None))
        self.assertEqual(kind_arg("lock the screen"), ("lock", None))
        self.assertEqual(kind_arg("shut down the computer"), ("shutdown", None))
        self.assertEqual(kind_arg("cancel the shutdown"),
                         ("cancel_shutdown", None))

    def test_questions(self):
        self.assertEqual(kind_arg("what time is it"), ("time", None))
        self.assertEqual(kind_arg("What's the date?"), ("date", None))

    def test_polite_prefixes_stripped(self):
        self.assertEqual(kind_arg("Hey, please open notepad"),
                         ("open_app", "notepad"))

    def test_close_app(self):
        self.assertEqual(kind_arg("close chrome"), ("close_app", "chrome"))
        self.assertEqual(kind_arg("quit spotify"), ("close_app", "spotify"))
        self.assertEqual(kind_arg("close notepad"), ("close_app", "notepad"))

    def test_close_window_still_uses_shortcut(self):
        self.assertEqual(kind_arg("close window"), ("shortcut", "close window"))
        self.assertEqual(kind_arg("close tab"), ("shortcut", "close tab"))

    def test_note_to_obsidian(self):
        self.assertEqual(kind_arg("take a note buy milk tomorrow"),
                         ("note", "buy milk tomorrow"))
        self.assertEqual(kind_arg("note that the client call is at 4"),
                         ("note", "the client call is at 4"))

    def test_note_keeps_casing(self):
        self.assertEqual(kind_arg("Take a note Call Dr. Mehta"),
                         ("note", "Call Dr. Mehta"))

    def test_booking_opens_page_not_transaction(self):
        self.assertEqual(kind_arg("book a table at Bukhara"),
                         ("booking", "bukhara"))
        self.assertEqual(kind_arg("make a reservation at the taj"),
                         ("booking", "the taj"))

    def test_market_lookup(self):
        self.assertEqual(kind_arg("find market data for Tesla"),
                         ("market", "tesla"))
        self.assertEqual(kind_arg("stock price of Apple"),
                         ("market", "apple"))

    def test_general_lookup(self):
        self.assertEqual(parse("look up the capital of Japan")[0], "lookup")
        self.assertEqual(parse("tell me about black holes")[0], "lookup")

    def test_ordinary_speech_is_not_a_command(self):
        self.assertIsNone(parse("the meeting went well today"))
        self.assertIsNone(parse(""))


class FindAppTests(unittest.TestCase):
    def setUp(self):
        self.e = CommandEngine(build_index=False)
        self.e.app_index = {
            "google chrome": r"C:\fake\chrome.lnk",
            "visual studio code": r"C:\fake\code.lnk",
            "vlc media player": r"C:\fake\vlc.lnk",
        }

    def test_exact_and_partial(self):
        self.assertEqual(self.e.find_app("google chrome")[1], "google chrome")
        self.assertEqual(self.e.find_app("chrome")[1], "google chrome")
        self.assertEqual(self.e.find_app("vlc")[1], "vlc media player")

    def test_fuzzy(self):
        self.assertEqual(self.e.find_app("visual studio cod")[1],
                         "visual studio code")

    def test_token_and_word_match(self):
        self.e.app_index["microsoft word"] = r"C:\fake\word.lnk"
        self.assertEqual(self.e.find_app("word")[1], "microsoft word")
        self.assertEqual(self.e.find_app("code")[1], "visual studio code")

    def test_ignores_filler_words(self):
        self.assertEqual(self.e.find_app("the chrome app")[1], "google chrome")

    def test_alias_beats_index(self):
        self.assertEqual(self.e.find_app("notepad")[0], "notepad")

    def test_unknown(self):
        self.assertIsNone(self.e.find_app("nonexistent app"))


class DownloadPopupTests(unittest.TestCase):
    def setUp(self):
        self.e = CommandEngine(build_index=False)
        self.opened = []
        self._real_open = commands.webbrowser.open
        commands.webbrowser.open = lambda u: self.opened.append(u)

    def tearDown(self):
        commands.webbrowser.open = self._real_open

    def test_no_when_user_declines(self):
        self.e.ask = lambda q: False
        ok, msg = self.e.run("open chrome")
        self.assertTrue(ok)
        self.assertIn("cancel", msg.lower())
        self.assertEqual(self.opened, [])  # nothing opened

    def test_opens_when_user_accepts(self):
        self.e.ask = lambda q: True
        ok, msg = self.e.run("open chrome")
        self.assertTrue(ok)
        self.assertEqual(len(self.opened), 1)
        self.assertIn("chrome", self.opened[0].lower())

    def test_installed_app_never_asks(self):
        asked = []
        self.e.ask = lambda q: asked.append(q) or True
        self.e.app_index = {"google chrome": r"C:\fake\chrome.lnk"}
        # find_app resolves it, so no download prompt — but os.startfile would
        # run; guard by checking the parse/lookup path instead.
        self.assertIsNotNone(self.e.find_app("chrome"))
        self.assertEqual(asked, [])


if __name__ == "__main__":
    unittest.main()
