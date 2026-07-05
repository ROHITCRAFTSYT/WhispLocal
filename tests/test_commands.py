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
                         ("play_music", ("lo-fi beats", "youtube")))

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

    def test_download_command(self):
        self.assertEqual(kind_arg("download spotify"), ("download", "spotify"))
        self.assertEqual(kind_arg("install discord"), ("download", "discord"))

    def test_open_in_web_forces_web(self):
        self.assertEqual(kind_arg("open spotify in web"),
                         ("open_web", "spotify"))
        self.assertEqual(kind_arg("open youtube in the browser"),
                         ("open_web", "youtube"))
        self.assertEqual(kind_arg("open notion website"),
                         ("open_web", "notion"))

    def test_plain_open_is_open_app(self):
        self.assertEqual(kind_arg("open notepad"), ("open_app", "notepad"))

    def test_play_music_variants(self):
        self.assertEqual(kind_arg("play some music"), ("play_music", ("", None)))
        self.assertEqual(kind_arg("play music"), ("play_music", ("", None)))
        self.assertEqual(kind_arg("play bohemian rhapsody"),
                         ("play_music", ("bohemian rhapsody", None)))
        self.assertEqual(kind_arg("play lo-fi beats on spotify"),
                         ("play_music", ("lo-fi beats", "spotify")))

    def test_bare_play_is_media_key(self):
        self.assertEqual(kind_arg("play"), ("shortcut", "play"))
        self.assertEqual(kind_arg("pause"), ("shortcut", "pause"))

    def test_profile_command(self):
        self.assertEqual(kind_arg("what do you know about me"),
                         ("profile", None))
        self.assertEqual(kind_arg("update my profile"), ("profile", None))


class RepairTests(unittest.TestCase):
    def setUp(self):
        self.e = CommandEngine(build_index=False)

    def test_repairs_misheard_verb(self):
        # "oben" -> "open"
        self.assertEqual(self.e._repair("oben chrome"), "open chrome")

    def test_repairs_close_verb(self):
        self.assertEqual(self.e._repair("cloze notepad"), "close notepad")

    def test_repairs_known_phrase(self):
        self.assertEqual(self.e._repair("take a screenshoot"),
                         "take a screenshot")

    def test_leaves_good_commands_alone(self):
        self.assertIsNone(self.e._repair("open notepad"))

    def test_run_uses_repair(self):
        # A misheard verb should still route to the right intent.
        cmd = parse(self.e._repair("oben spotify"))
        self.assertEqual(cmd[0], "open_app")

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


class OpenBehaviourTests(unittest.TestCase):
    def setUp(self):
        self.e = CommandEngine(build_index=False)
        self.e.app_index = {"notepad plus plus": r"C:\fake\npp.lnk"}
        self.opened = []
        self.launched = []
        self._real_open = commands.webbrowser.open
        self._real_start = commands.os.startfile
        commands.webbrowser.open = lambda u: self.opened.append(u)
        commands.os.startfile = lambda p: self.launched.append(p)

    def tearDown(self):
        commands.webbrowser.open = self._real_open
        commands.os.startfile = self._real_start

    def test_installed_app_opens_the_app(self):
        ok, msg = self.e.run("open notepad plus plus")
        self.assertTrue(ok)
        self.assertEqual(len(self.launched), 1)   # app launched
        self.assertEqual(self.opened, [])         # browser not used

    def test_missing_app_with_known_site_opens_web_version(self):
        ok, msg = self.e.run("open spotify")
        self.assertTrue(ok)
        self.assertEqual(self.launched, [])
        self.assertIn("spotify.com", self.opened[0])
        self.assertIn("web", msg.lower())

    def test_missing_unknown_app_opens_search(self):
        ok, msg = self.e.run("open someunknownapp")
        self.assertTrue(ok)
        self.assertIn("google.com/search", self.opened[0])

    def test_force_web_even_if_installed(self):
        ok, msg = self.e.run("open notepad plus plus in web")
        self.assertEqual(self.launched, [])       # app NOT launched
        self.assertEqual(len(self.opened), 1)     # opened on web instead

    def test_download_opens_download_page(self):
        ok, msg = self.e.run("download spotify")
        self.assertTrue(ok)
        self.assertIn("spotify.com/download", self.opened[0])


class StoreAppAndReinforcementTests(unittest.TestCase):
    def setUp(self):
        self.e = CommandEngine(build_index=False)
        self.launched = []
        self.popened = []
        self.opened = []
        self._start = commands.os.startfile
        self._popen = commands.subprocess.Popen
        self._open = commands.webbrowser.open
        commands.os.startfile = lambda p: self.launched.append(p)
        commands.subprocess.Popen = lambda a, **k: self.popened.append(a)
        commands.webbrowser.open = lambda u: self.opened.append(u)

    def tearDown(self):
        commands.os.startfile = self._start
        commands.subprocess.Popen = self._popen
        commands.webbrowser.open = self._open

    def test_launches_store_app_by_appid(self):
        self.e.app_index = {"spotify": "appid:SpotifyAB.SpotifyMusic!Spotify"}
        ok, msg = self.e.run("open spotify")
        self.assertTrue(ok)
        self.assertIn("Spotify", msg)
        self.assertEqual(self.opened, [])          # not the browser
        self.assertEqual(len(self.popened), 1)     # launched via explorer
        self.assertIn("shell:AppsFolder\\SpotifyAB.SpotifyMusic!Spotify",
                      self.popened[0])

    def test_play_installed_app_opens_the_app(self):
        self.e.app_index = {"spotify": "appid:SpotifyAB.SpotifyMusic!Spotify"}
        ok, msg = self.e.run("play spotify")
        self.assertTrue(ok)
        self.assertIn("Spotify", msg)
        self.assertEqual(len(self.popened), 1)     # opened the app
        self.assertEqual(self.opened, [])          # not a music search

    def test_play_song_still_searches(self):
        self.e.app_index = {}
        ok, msg = self.e.run("play despacito")
        self.assertEqual(len(self.opened), 1)
        self.assertIn("music", self.opened[0])

    def test_usage_reinforces_ambiguous_match(self):
        self.e.app_index = {"microsoft teams": "p1", "teams classic": "p2"}
        self.e.usage = {}
        self.assertEqual(self.e.find_app("teams")[1], "teams classic")
        self.e.usage = {"microsoft teams": 3}
        self.assertEqual(self.e.find_app("teams")[1], "microsoft teams")


if __name__ == "__main__":
    unittest.main()
