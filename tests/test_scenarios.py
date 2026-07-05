"""Regression tests for specific reported bugs, so they never come back.

These mirror real situations that misbehaved: saying "open X which is
already open" web-searched the whole sentence instead of switching to
the open window.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "whisp"))

import commands
from commands import CommandEngine, parse


class ReportedScenarioTests(unittest.TestCase):
    def setUp(self):
        self.e = CommandEngine(build_index=False)
        self.opened = []
        self.focused = []
        self.launched = []
        self._enum = commands._enum_windows
        self._focus = commands._focus_hwnd
        self._open = commands.webbrowser.open
        self._start = commands.os.startfile
        commands._focus_hwnd = lambda h: self.focused.append(h)
        commands.webbrowser.open = lambda u: self.opened.append(u)
        commands.os.startfile = lambda p: self.launched.append(p)

    def tearDown(self):
        commands._enum_windows = self._enum
        commands._focus_hwnd = self._focus
        commands.webbrowser.open = self._open
        commands.os.startfile = self._start

    def test_open_already_open_youtube_is_not_a_web_search(self):
        # The exact phrase from the bug report must parse to a plain open.
        self.assertEqual(parse("open youtube which has already been open")[:2],
                         ("open_app", "youtube"))

    def test_open_already_open_youtube_switches_to_the_tab(self):
        commands._enum_windows = lambda: [
            (11, "YouTube - Google Chrome", "chrome.exe")]
        ok, msg = self.e.run("open youtube which has already been open")
        self.assertTrue(ok)
        self.assertEqual(self.focused, [11])   # switched to the open tab
        self.assertEqual(self.opened, [])      # did NOT search the sentence

    def test_open_comet_already_opened_switches(self):
        commands._enum_windows = lambda: [(22, "Comet Browser", "comet.exe")]
        self.e.app_index = {"comet": "appid:Comet"}
        ok, msg = self.e.run("open comet which is already opened")
        self.assertIn("Switched", msg)
        self.assertEqual(self.focused, [22])

    def test_youtube_on_chrome_does_not_search_the_phrase(self):
        commands._enum_windows = lambda: []
        ok, msg = self.e.run("open youtube on chrome")
        # opens the YouTube site, not a search for "youtube on chrome"
        self.assertTrue(any("youtube.com" in u for u in self.opened))
        self.assertFalse(any("search?q=youtube+on+chrome" in u
                             for u in self.opened))


if __name__ == "__main__":
    unittest.main()
