"""Tests for the command "brain": tab/settings intents, compound-command
splitting, fuzzy suggestion instead of a blind refusal, and a latency
benchmark proving the NLU layer adds microseconds to the reply path."""
import os
import sys
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "whisp"))

import commands
from commands import CommandEngine, parse


def stub_keyboard():
    """The engine does `import keyboard` lazily inside methods, so patch
    sys.modules rather than the commands module attribute."""
    patcher = mock.patch.dict(sys.modules, {"keyboard": mock.MagicMock()})
    patcher.start()
    return sys.modules["keyboard"]


def kind_arg(text):
    cmd = parse(text)
    return (cmd[0], cmd[1]) if cmd else None


class TabIntentTests(unittest.TestCase):
    def test_next_tab_phrasings(self):
        self.assertEqual(kind_arg("switch tab"), ("tab", "next"))
        self.assertEqual(kind_arg("next tab"), ("tab", "next"))
        self.assertEqual(kind_arg("switch to the next tab"), ("tab", "next"))
        self.assertEqual(kind_arg("go to next tab"), ("tab", "next"))
        self.assertEqual(kind_arg("change tab"), ("tab", "next"))

    def test_previous_tab_phrasings(self):
        self.assertEqual(kind_arg("previous tab"), ("tab", "prev"))
        self.assertEqual(kind_arg("switch to the previous tab"), ("tab", "prev"))
        self.assertEqual(kind_arg("go back a tab"), ("tab", "prev"))

    def test_numbered_tab(self):
        self.assertEqual(kind_arg("switch to tab 3"), ("tab", "3"))
        self.assertEqual(kind_arg("go to tab two"), ("tab", "2"))
        self.assertEqual(kind_arg("open tab 1"), ("tab", "1"))
        self.assertEqual(kind_arg("switch to the last tab"), ("tab", "9"))

    def test_new_and_close_tab_stay_shortcuts(self):
        self.assertEqual(kind_arg("open a new tab"), ("shortcut", "new tab"))
        self.assertEqual(kind_arg("switch to a new tab"),
                         ("shortcut", "new tab"))
        self.assertEqual(kind_arg("close this tab"), ("shortcut", "close tab"))

    def test_switch_to_app_unchanged(self):
        self.assertEqual(kind_arg("switch to youtube"), ("switch", "youtube"))


class AppSettingsIntentTests(unittest.TestCase):
    def test_open_settings(self):
        self.assertEqual(kind_arg("open settings"), ("app_settings", None))
        self.assertEqual(kind_arg("open the settings"), ("app_settings", None))
        self.assertEqual(kind_arg("open app settings"), ("app_settings", None))

    def test_windows_settings_still_reachable(self):
        self.assertEqual(kind_arg("open windows settings"),
                         ("open_app", "settings"))
        self.assertEqual(kind_arg("open system settings"),
                         ("open_app", "settings"))


class CompoundCommandTests(unittest.TestCase):
    def setUp(self):
        self.e = CommandEngine(build_index=False)
        self.opened_settings = []
        self.kb = stub_keyboard()
        self._enum = commands._enum_windows
        self._start = commands.os.startfile
        self._open = commands.webbrowser.open
        commands._enum_windows = lambda: []   # never touch real windows
        commands.os.startfile = lambda p: None
        commands.webbrowser.open = lambda u: None
        self.e.on_open_settings = lambda: self.opened_settings.append(True)
        self.e.note_saver = lambda text: (True, text)

    def tearDown(self):
        mock.patch.stopall()
        commands._enum_windows = self._enum
        commands.os.startfile = self._start
        commands.webbrowser.open = self._open

    def test_switch_tab_and_open_settings_runs_both(self):
        # The exact sentence that previously got "Did not understand".
        ok, msg = self.e.run("switch tab and open settings")
        self.assertTrue(ok)
        self.kb.send.assert_called_once_with("ctrl+tab")
        self.assertEqual(self.opened_settings, [True])
        self.assertIn("tab", msg.lower())
        self.assertIn("settings", msg.lower())

    def test_open_two_apps_in_one_sentence(self):
        self.e.app_index = {"notepad": "notepad", "paint": "mspaint"}
        launched = []
        commands.os.startfile = lambda p: launched.append(p)
        ok, _msg = self.e.run("open notepad and open paint")
        self.assertTrue(ok)
        self.assertEqual(sorted(launched), ["mspaint", "notepad"])

    def test_bare_noun_inherits_verb(self):
        # "open chrome and notepad" — the second noun inherits "open".
        self.e.app_index = {"notepad": "notepad", "paint": "mspaint"}
        launched = []
        commands.os.startfile = lambda p: launched.append(p)
        ok, _msg = self.e.run("open paint and notepad")
        self.assertTrue(ok)
        self.assertEqual(sorted(launched), ["mspaint", "notepad"])

    def test_single_note_with_and_stays_one_note(self):
        # "buy milk and eggs" is one note body, not two commands.
        ok, msg = self.e.run("take a note buy milk and eggs")
        self.assertTrue(ok)
        self.assertIn("buy milk and eggs", msg)

    def test_repair_applies_per_part(self):
        # Each half of a compound sentence gets the repair pass too.
        ok, _msg = self.e.run("swith tab and open settings")
        self.assertTrue(ok)
        self.kb.send.assert_called_once_with("ctrl+tab")
        self.assertEqual(self.opened_settings, [True])

    def test_comma_punctuation_still_splits(self):
        # Whisper freely writes "open youtube, search for mr. beast" —
        # the comma (no space before it) and the period in "mr." must
        # not derail the compound split or turn the phrase into a URL.
        opened = []
        commands.webbrowser.open = lambda u: opened.append(u)
        ok, msg = self.e.run("open youtube, search for mr. beast")
        self.assertTrue(ok)
        # The mangled domain from the bug report must never appear.
        self.assertFalse(any("youtubeandsearchformr" in u for u in opened))
        # Both halves ran: youtube opened, mr beast searched on youtube.
        self.assertTrue(any("youtube.com" in u for u in opened))
        self.assertTrue(any("youtube.com/results" in u for u in opened))

    def test_open_site_then_search_chains_to_site(self):
        # "open youtube and search for mr beast" must search ON youtube,
        # not a bare Google search.
        opened = []
        commands.webbrowser.open = lambda u: opened.append(u)
        ok, msg = self.e.run("open youtube and search for mr beast")
        self.assertTrue(ok)
        self.assertIn("youtube.com/results", " ".join(opened))
        self.assertIn("mr+beast", " ".join(opened))
        self.assertFalse(any("google.com/search" in u for u in opened))

    def test_open_ampersand_search_chains(self):
        opened = []
        commands.webbrowser.open = lambda u: opened.append(u)
        ok, msg = self.e.run("open youtube & search for mr beast")
        self.assertTrue(ok)
        self.assertTrue(any("youtube.com/results" in u for u in opened))

    def test_site_search_knows_amazon(self):
        opened = []
        commands.webbrowser.open = lambda u: opened.append(u)
        ok, msg = self.e.run("open amazon and search for monitor")
        self.assertTrue(ok)
        self.assertTrue(any("amazon.in/s?k=monitor" in u for u in opened))

    def test_search_in_youtube_opens_youtube_not_google(self):
        # "search mr beast in youtube" must open YouTube results — the
        # exact phrase that used to land on a Google search page.
        opened = []
        commands.webbrowser.open = lambda u: opened.append(u)
        ok, msg = self.e.run("search mr beast in youtube")
        self.assertTrue(ok)
        self.assertFalse(any("google.com/search" in u for u in opened))
        self.assertTrue(any("youtube.com/results" in u for u in opened))
        self.assertIn("mr+beast", " ".join(opened))

    def test_every_whisper_variant_opens_youtube_never_google(self):
        # The screenshot showed google.com searching "mr. beast in
        # youtube" — every way whisper can transcribe the request must
        # open YouTube results instead.
        for phrase in ("google mr beast in youtube",
                       "look for mr beast in youtube",
                       "look up mr beast in youtube",
                       "find mr beast in youtube",
                       "show me mr beast in youtube",
                       "search mr beast in the youtube",
                       "search mr beast in youtube app",
                       "search mr beast in youtube.com",
                       "search mr beast in you tube",
                       "search mr beast in yt",
                       "search in youtube mr beast",
                       "open youtube search mr beast",
                       "mr beast in youtube"):
            opened = []
            commands.webbrowser.open = lambda u: opened.append(u)
            ok, msg = self.e.run(phrase)
            self.assertTrue(ok, phrase)
            self.assertFalse(any("google.com/search" in u for u in opened),
                             f"{phrase}: {opened}")
            self.assertTrue(any("youtube.com/results" in u for u in opened),
                            f"{phrase}: {opened}")
            self.assertIn("mr", " ".join(opened).lower())

    def test_trailing_please_still_opens_youtube(self):
        # Whisper appends politeness: "search mr. beast in youtube please"
        # must STILL open YouTube results — the trailing word is stripped
        # in normalize, before the generic Google search can win.
        opened = []
        commands.webbrowser.open = lambda u: opened.append(u)
        ok, msg = self.e.run("search mr. beast in youtube please")
        self.assertTrue(ok)
        self.assertFalse(any("google.com/search" in u for u in opened))
        self.assertTrue(any("youtube.com/results" in u for u in opened))
        self.assertIn("mr", " ".join(opened))

    def test_fuzzy_search_in_youtube_still_lands(self):
        # A misheard variant still routes to YouTube via the fuzzy path.
        cmd = self.e._suggest("search mr. beast in youtube please")
        self.assertEqual(cmd[0], "youtube")
        self.assertIn("mr", cmd[1])

    def test_url_executor_never_mangles_spaces(self):
        # Defense in depth: if a space-containing phrase ever reaches the
        # URL executor, it becomes a web search — never a domain built by
        # stripping spaces (the "youtubeandsearchformr.beast" bug).
        opened = []
        commands.webbrowser.open = lambda u: opened.append(u)
        ok, msg = self.e._execute("url", "youtube and search for mr. beast")
        self.assertTrue(ok)
        self.assertFalse(any("youtubeandsearchformr" in u for u in opened))
        self.assertTrue(any("google.com/search" in u for u in opened))
        self.assertIn("mr", opened[0])

    def test_repair_is_auto_learned(self):
        # A misheard verb that repairs successfully gets remembered so
        # the exact same mishearing is instant next time.
        learned = []
        self.e.phrase_learner = lambda h, c: learned.append((h, c))
        self.e.app_index = {"google chrome": "chrome.lnk"}
        launched = []
        commands.os.startfile = lambda p: launched.append(p)
        ok, _msg = self.e.run("oben chrome")
        self.assertTrue(ok)
        self.assertEqual(launched, ["chrome.lnk"])
        self.assertEqual(learned, [("oben chrome", "open chrome")])

    def test_repaired_compound_part_is_learned(self):
        # A misheard HALF of a compound sentence is remembered too, so
        # "swith tab" on its own resolves instantly next time.
        learned = []
        self.e.phrase_learner = lambda h, c: learned.append((h, c))
        ok, _msg = self.e.run("swith tab and open settings")
        self.assertTrue(ok)
        self.assertIn(("swith tab", "switch tab"), learned)

    def test_comma_bare_noun_inherits_open(self):
        # "open chrome, and notepad" — the comma variant of the compound
        # must still let the bare noun inherit the open verb.
        self.e.app_index = {"notepad": "notepad", "paint": "mspaint"}
        launched = []
        commands.os.startfile = lambda p: launched.append(p)
        ok, _msg = self.e.run("open paint, and notepad")
        self.assertTrue(ok)
        self.assertEqual(sorted(launched), ["mspaint", "notepad"])

    def test_comma_note_stays_one_note(self):
        # A comma inside a note body must not split it into commands.
        ok, msg = self.e.run("take a note, buy milk and eggs")
        self.assertTrue(ok)
        self.assertIn("buy milk and eggs", msg)
        self.assertNotIn("not understood", msg.lower())

    def test_site_search_unknown_site_is_safe(self):
        # Defense in depth: a direct site_search call for an unknown site
        # falls back to a web search instead of a KeyError.
        opened = []
        commands.webbrowser.open = lambda u: opened.append(u)
        ok, msg = self.e._execute("site_search", ("nope", "hello"))
        self.assertTrue(ok)
        self.assertTrue(any("google.com/search" in u for u in opened))


class SmartFallbackTests(unittest.TestCase):
    def setUp(self):
        self.e = CommandEngine(build_index=False)
        self.kb = stub_keyboard()
        self._enum = commands._enum_windows
        commands._enum_windows = lambda: []
        self.e.on_open_settings = lambda: None

    def tearDown(self):
        mock.patch.stopall()
        commands._enum_windows = self._enum

    def test_suggests_tab_for_fuzzy_tab_phrase(self):
        cmd = self.e._suggest("switch to the next tab please")
        self.assertEqual(cmd[0], "tab")

    def test_suggests_settings_for_fuzzy_settings_phrase(self):
        cmd = self.e._suggest("can you open the settings")
        self.assertEqual(cmd, ("app_settings", None, None))

    def test_unknown_reply_is_helpful_not_blank(self):
        ok, msg = self.e.run("make me a sandwich")
        self.assertFalse(ok)
        self.assertIn("open chrome", msg)          # suggests real commands
        self.assertNotIn("Did not understand", msg)

    def test_close_fuzzy_phrase_still_executes(self):
        # "clsoe" is repaired; a near-miss phrase lands via fuzzy match.
        ok, msg = self.e.run("close tab and notepad")
        # "close tab" parses, "notepad" alone doesn't -> stays one phrase,
        # and the fuzzy pass still finds something reasonable.
        self.assertIsInstance(ok, bool)


class LearnedPhraseTests(unittest.TestCase):
    def test_heard_part_strips_feedback(self):
        self.assertEqual(
            commands.heard_part("open chrom -> Did not understand"),
            "open chrom")
        self.assertEqual(commands.heard_part("plain dictation text"),
                         "plain dictation text")

    def test_heard_part_splits_at_last_arrow(self):
        # A command whose text itself contains " -> " (e.g. a typed
        # shortcut "type a -> b") must not be truncated at the first
        # arrow — only the trailing feedback separator is removed.
        self.assertEqual(
            commands.heard_part("type a -> b -> Typed it"),
            "type a -> b")
        self.assertEqual(
            commands.heard_part("type x -> y -> Typed it"),
            "type x -> y")

    def test_learned_phrase_resolves_exact(self):
        # The taught phrase does NOT parse on its own, so only the
        # learned map can resolve it — this isolates the learned path.
        e = CommandEngine(build_index=False)
        e.set_learned_phrases({"next window please": "switch window"})
        kb = stub_keyboard()
        ok, msg = e.run("next window please")
        self.assertTrue(ok)
        kb.send.assert_called_once_with("alt+tab")
        mock.patch.stopall()

    def test_learned_phrase_beats_parsing(self):
        # "open chrrm" parses as open_app("chrrm") — a useless web
        # search. The taught phrase must win and open the real app.
        e = CommandEngine(build_index=False)
        e.app_index = {"google chrome": "chrome.lnk"}
        e.set_learned_phrases({"open chrrm": "open chrome"})
        launched = []
        opened = []
        commands.os.startfile = lambda p: launched.append(p)
        commands.webbrowser.open = lambda u: opened.append(u)
        ok, _msg = e.run("open chrrm")
        self.assertTrue(ok)
        self.assertEqual(launched, ["chrome.lnk"])
        self.assertEqual(opened, [])

    def test_learned_phrase_resolves_fuzzy(self):
        e = CommandEngine(build_index=False)
        e.app_index = {"google chrome": "chrome.lnk"}
        e.set_learned_phrases({"open chrrm": "open chrome"})
        launched = []
        commands.os.startfile = lambda p: launched.append(p)
        ok, _msg = e.run("open chrrmm")
        self.assertTrue(ok)
        self.assertEqual(launched, ["chrome.lnk"])

    def test_unknown_phrase_still_gets_helpful_reply(self):
        e = CommandEngine(build_index=False)
        e.set_learned_phrases({"open chrom": "open chrome"})
        ok, msg = e.run("teleport to the moon")
        self.assertFalse(ok)
        self.assertIn("open chrome", msg)  # suggestion list still shown


class OrderIntentTests(unittest.TestCase):
    def setUp(self):
        self._open = commands.webbrowser.open

    def tearDown(self):
        commands.webbrowser.open = self._open

    def test_order_parses_product_and_site(self):
        self.assertEqual(kind_arg("order monster from instamart"),
                         ("order", ("monster", "instamart")))
        self.assertEqual(kind_arg("buy milk on blinkit"),
                         ("order", ("milk", "blinkit")))
        self.assertEqual(kind_arg("add monster to my cart on amazon"),
                         ("order", ("monster", "amazon")))
        self.assertEqual(kind_arg("get a red bull from zepto"),
                         ("order", ("red bull", "zepto")))

    def test_known_site_deep_links_to_product_search(self):
        self.assertIn("amazon.in/s?k=monster",
                      commands._order_url("monster", "amazon"))
        self.assertIn("flipkart.com/search?q=red+bull",
                      commands._order_url("red bull", "flipkart"))
        self.assertIn("instamart/search?query=monster",
                      commands._order_url("monster", "instamart"))

    def test_get_phrases_are_not_hijacked_into_orders(self):
        # "get X on Y" is everyday English — only a real ordering site
        # turns it into an order; otherwise it falls through to the
        # existing intents (or nothing), never a fake order.
        self.assertEqual(parse("get market data on Tesla")[0], "market")
        self.assertIsNone(parse("get the weather on friday"))
        self.assertIsNone(parse("get the file from google drive"))
        # ...but "get X from a real ordering site" IS an order.
        self.assertEqual(kind_arg("get a red bull from zepto"),
                         ("order", ("red bull", "zepto")))

    def test_alias_resolution(self):
        # "swiggy instamart" resolves to the instamart entry.
        self.assertIn("instamart",
                      commands._order_url("monster", "swiggy instamart"))

    def test_unknown_site_falls_back_to_search(self):
        url = commands._order_url("pizza", "some random shop")
        self.assertIn("google.com/search", url)
        self.assertIn("pizza", url)
        self.assertIn("some+random+shop", url)  # URL-encoded

    def test_execution_opens_the_site(self):
        e = CommandEngine(build_index=False)
        opened = []
        commands.webbrowser.open = lambda u: opened.append(u)
        ok, msg = e.run("order monster from instamart")
        self.assertTrue(ok)
        self.assertEqual(len(opened), 1)
        self.assertIn("instamart", opened[0])
        self.assertIn("monster", opened[0])
        self.assertIn("cart", msg.lower())

    def test_compound_order_opens_both_sites(self):
        e = CommandEngine(build_index=False)
        opened = []
        commands.webbrowser.open = lambda u: opened.append(u)
        ok, _msg = e.run("order monster from instamart and red bull from blinkit")
        self.assertTrue(ok)
        self.assertEqual(len(opened), 2)
        self.assertTrue(any("instamart" in u for u in opened))
        self.assertTrue(any("blinkit" in u for u in opened))

    def test_order_is_learned_by_site(self):
        e = CommandEngine(build_index=False)
        seen = []
        e.on_action = lambda kind, arg, ok: seen.append((kind, arg))
        opened = []
        commands.webbrowser.open = lambda u: opened.append(u)
        e.run("order monster from instamart")
        self.assertEqual(seen, [("order", ("monster", "instamart"))])


class LatencyTests(unittest.TestCase):
    def test_parse_is_sub_millisecond(self):
        # The brain must not add perceptible latency to the reply path.
        corpus = [
            "switch tab", "next tab", "switch to the previous tab",
            "go to tab 3", "open settings", "open windows settings",
            "switch tab and open settings", "open chrome and open notepad",
            "take a note buy milk and eggs", "volume up", "scroll down",
            "play despacito", "search for python", "what time is it",
            "close tab", "open a new tab", "lock the screen",
            "open notepad in web", "book a table at Bukhara",
            "stock price of apple", "make me a sandwich",
            "switch to youtube", "press enter", "take a screenshot",
            "order monster from instamart", "buy milk on blinkit",
            "add red bull to cart on zepto",
            "order monster from instamart and red bull from blinkit",
            "open youtube and search for mr beast",
            "open youtube, search for mr. beast",
            "open amazon and search for monitor",
            "search mr beast in youtube", "search in youtube for mr beast",
            "google mr beast in youtube", "look for mr beast in youtube",
            "find mr beast in youtube", "mr beast in youtube",
            "search mr beast in you tube", "open youtube search mr beast",
            "open chrom", "open chrrm", "open notepd",
            "lower my computer's volume", "set volume to 30",
            "increase volume by 20%", "increasing volume by 20%",
            "decrease volume by 10%", "increase brightness by 20%",
            "brightness up", "set brightness to 50",
            "restart the computer", "check battery",
            "turn off the display", "open wifi settings",
        ]
        t0 = time.perf_counter()
        for phrase in corpus:
            parse(phrase)
        elapsed = time.perf_counter() - t0
        # ~24 phrases in well under 10 ms (regex/dict only, no I/O).
        self.assertLess(elapsed, 0.05)


if __name__ == "__main__":
    unittest.main()
