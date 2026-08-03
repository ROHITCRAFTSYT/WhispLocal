"""Unit tests for the voice-control intent parser. Parsing is pure and
stdlib-only, so these run on any CI runner."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "whisp"))

import commands
import volume
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

    def test_press_with_articles_and_key_word(self):
        # "the ... key" phrasing must not block a valid key press.
        self.assertEqual(kind_arg("press the escape key"), ("keys", "esc"))
        self.assertEqual(kind_arg("hit the enter key"), ("keys", "enter"))
        self.assertEqual(kind_arg("press the tab key"), ("keys", "tab"))

    def test_press_gibberish_rejected(self):
        self.assertIsNone(parse("press the big red button"))

    def test_volume_and_scroll(self):
        self.assertEqual(kind_arg("volume up"), ("volume", "up"))
        self.assertEqual(kind_arg("volume down"), ("volume", "down"))
        self.assertEqual(kind_arg("scroll down"), ("scroll", "down"))

    def test_turn_the_volume_phrasing(self):
        self.assertEqual(kind_arg("turn up the volume"), ("volume", "up"))
        self.assertEqual(kind_arg("turn down the volume"), ("volume", "down"))

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

    def test_computer_tasks(self):
        self.assertEqual(kind_arg("restart the computer"), ("restart", None))
        self.assertEqual(kind_arg("restart the pc"), ("restart", None))
        self.assertEqual(kind_arg("cancel restart"), ("cancel_shutdown", None))
        self.assertEqual(kind_arg("sleep"), ("sleep", None))
        self.assertEqual(kind_arg("put the computer to sleep"),
                         ("sleep", None))
        self.assertEqual(kind_arg("hibernate"), ("hibernate", None))
        self.assertEqual(kind_arg("hibernate the computer"),
                         ("hibernate", None))
        self.assertEqual(kind_arg("battery level"), ("battery", None))
        self.assertEqual(kind_arg("check battery"), ("battery", None))
        self.assertEqual(kind_arg("turn off the display"),
                         ("monitor_off", None))
        self.assertEqual(kind_arg("turn off the screen"),
                         ("monitor_off", None))

    def test_settings_pages(self):
        self.assertEqual(kind_arg("open wifi settings"),
                         ("open_settings_page", "network-wifi"))
        self.assertEqual(kind_arg("open bluetooth settings"),
                         ("open_settings_page", "bluetooth"))
        self.assertEqual(kind_arg("open display settings"),
                         ("open_settings_page", "display"))
        self.assertEqual(kind_arg("open night light settings"),
                         ("open_settings_page", "nightlight"))
        self.assertEqual(kind_arg("open sound settings"),
                         ("open_settings_page", "sound"))

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

    def test_note_body_survives_polite_prefix(self):
        # The politeness/filler stripping must not shift the note body.
        self.assertEqual(kind_arg("please take a note buy milk tomorrow"),
                         ("note", "buy milk tomorrow"))
        self.assertEqual(kind_arg("Hey, take a note Call Dr. Mehta"),
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

    def test_strips_already_open_qualifiers(self):
        self.assertEqual(kind_arg("open youtube which has already been open"),
                         ("open_app", "youtube"))
        self.assertEqual(kind_arg("open comet that is already opened"),
                         ("open_app", "comet"))
        self.assertEqual(kind_arg("open spotify which is running"),
                         ("open_app", "spotify"))

    def test_strips_on_browser(self):
        self.assertEqual(kind_arg("open youtube on chrome"),
                         ("open_app", "youtube"))

    def test_switch_intent(self):
        self.assertEqual(kind_arg("switch to youtube"), ("switch", "youtube"))
        self.assertEqual(kind_arg("focus the spotify window"),
                         ("switch", "spotify"))

    def test_list_windows_and_help(self):
        self.assertEqual(parse("what's open")[0], "list_windows")
        self.assertEqual(parse("list open windows")[0], "list_windows")
        self.assertEqual(parse("help")[0], "help")
        self.assertEqual(parse("what can you do")[0], "help")

    def test_youtube_search_phrasings(self):
        self.assertEqual(kind_arg("search youtube for lofi beats"),
                         ("youtube", "lofi beats"))
        self.assertEqual(kind_arg("search cats on youtube"),
                         ("youtube", "cats"))

    def test_youtube_search_in_phrasings(self):
        # Whisper says "in youtube" — the exact phrasing from the bug
        # report that used to Google-search the whole sentence.
        self.assertEqual(kind_arg("search mr beast in youtube"),
                         ("youtube", "mr beast"))
        self.assertEqual(kind_arg("search for mr beast in youtube"),
                         ("youtube", "mr beast"))
        self.assertEqual(kind_arg("search mr. beast in youtube"),
                         ("youtube", "mr. beast"))
        self.assertEqual(kind_arg("search in youtube for mr beast"),
                         ("youtube", "mr beast"))
        self.assertEqual(kind_arg("search on youtube for mr beast"),
                         ("youtube", "mr beast"))
        self.assertEqual(kind_arg("youtube search for mr beast"),
                         ("youtube", "mr beast"))
        self.assertEqual(kind_arg("youtube search mr beast"),
                         ("youtube", "mr beast"))

    def test_youtube_search_whisper_variants(self):
        # The many ways whisper can transcribe "search mr beast in
        # youtube" — every one must land on YouTube results, never the
        # generic Google search (the google.com / "mr. beast in youtube"
        # screenshot bug).
        for phrase in (
            "google mr beast in youtube",
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
            "search youtube for mr beast",
            "open youtube search mr beast",
            "open youtube and search mr beast",
            "search mr beast in youtube please",
        ):
            self.assertEqual(kind_arg(phrase), ("youtube", "mr beast"),
                             phrase)
        # Whisper hears the full name: the query must preserve what
        # was said, not force the short form.
        self.assertEqual(kind_arg("search mister beast in youtube"),
                         ("youtube", "mister beast"))

    def test_youtube_search_no_verb_lands_via_suggest(self):
        # Whisper sometimes drops the verb entirely; the fuzzy path must
        # still treat "X in youtube" as a YouTube search, not Google.
        e = CommandEngine(build_index=False)
        self.assertEqual(e._suggest("mr beast in youtube"),
                         ("youtube", "mr beast", None))

    def test_volume_phrasings(self):
        self.assertEqual(kind_arg("louder"), ("volume", "up"))
        self.assertEqual(kind_arg("quieter"), ("volume", "down"))
        self.assertEqual(kind_arg("turn it up"), ("volume", "up"))

    def test_natural_volume_phrasings(self):
        # The exact phrasings that used to answer "not understood".
        self.assertEqual(kind_arg("lower my computer's volume"),
                         ("volume", "down"))
        self.assertEqual(kind_arg("lower my computer volume"),
                         ("volume", "down"))
        self.assertEqual(kind_arg("raise the pc volume"), ("volume", "up"))
        self.assertEqual(kind_arg("reduce the volume"), ("volume", "down"))
        self.assertEqual(kind_arg("make it louder"), ("volume", "up"))
        self.assertEqual(kind_arg("make it quieter"), ("volume", "down"))

    def test_set_volume_level(self):
        self.assertEqual(kind_arg("set volume to 30"), ("volume", "set:30"))
        self.assertEqual(kind_arg("set the volume to 75 percent"),
                         ("volume", "set:75"))
        self.assertEqual(kind_arg("volume 50"), ("volume", "set:50"))
        self.assertEqual(kind_arg("volume to 100 percent"),
                         ("volume", "set:100"))
        self.assertEqual(kind_arg("max volume"), ("volume", "set:100"))
        self.assertEqual(kind_arg("min volume"), ("volume", "set:0"))
        self.assertEqual(kind_arg("set volume to 999"), ("volume", "set:100"))

    def test_volume_by_percent_phrasings(self):
        # The exact phrase from the bug report, plus its siblings.
        self.assertEqual(kind_arg("increase volume by 20%"),
                         ("volume", "add:20"))
        self.assertEqual(kind_arg("increasing volume by 20%"),
                         ("volume", "add:20"))
        self.assertEqual(kind_arg("increase the volume by 20 percent"),
                         ("volume", "add:20"))
        self.assertEqual(kind_arg("decrease volume by 10%"),
                         ("volume", "sub:10"))
        self.assertEqual(kind_arg("lower the volume by 15"),
                         ("volume", "sub:15"))
        self.assertEqual(kind_arg("volume up by 5%"),
                         ("volume", "add:5"))
        self.assertEqual(kind_arg("volume down by 10"),
                         ("volume", "sub:10"))
        self.assertEqual(kind_arg("make it louder by 10%"),
                         ("volume", "add:10"))
        self.assertEqual(kind_arg("make it quieter by 10%"),
                         ("volume", "sub:10"))
        # Split phrasal verbs: verb and particle separated by the object.
        self.assertEqual(kind_arg("turn the volume down by 20%"),
                         ("volume", "sub:20"))
        self.assertEqual(kind_arg("turn it up by 10%"),
                         ("volume", "add:10"))
        # Direction verb + absolute target is a set, not a step.
        self.assertEqual(kind_arg("increase volume to 60"),
                         ("volume", "set:60"))
        self.assertEqual(kind_arg("lower the volume to 30"),
                         ("volume", "set:30"))

    def test_brightness_by_percent_phrasings(self):
        self.assertEqual(kind_arg("increase brightness by 20%"),
                         ("brightness", "add:20"))
        self.assertEqual(kind_arg("decreasing brightness by 10%"),
                         ("brightness", "sub:10"))
        self.assertEqual(kind_arg("brightness down by 15"),
                         ("brightness", "sub:15"))
        self.assertEqual(kind_arg("turn the brightness down by 20%"),
                         ("brightness", "sub:20"))

    def test_brightness_phrasings(self):
        self.assertEqual(kind_arg("brightness up"), ("brightness", "up"))
        self.assertEqual(kind_arg("brightness down"), ("brightness", "down"))
        self.assertEqual(kind_arg("increase the brightness"),
                         ("brightness", "up"))
        self.assertEqual(kind_arg("lower the brightness"),
                         ("brightness", "down"))
        self.assertEqual(kind_arg("set brightness to 50"),
                         ("brightness", "set:50"))
        self.assertEqual(kind_arg("set screen brightness to 30 percent"),
                         ("brightness", "set:30"))
        self.assertEqual(kind_arg("max brightness"), ("brightness", "set:100"))
        self.assertEqual(kind_arg("make it brighter"), ("brightness", "up"))
        self.assertEqual(kind_arg("make it darker"), ("brightness", "down"))

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

    def test_media_transport(self):
        self.assertEqual(kind_arg("stop the music"), ("shortcut", "pause"))
        self.assertEqual(kind_arg("pause music"), ("shortcut", "pause"))
        self.assertEqual(kind_arg("resume"), ("shortcut", "play"))
        # "play <song>" must still start playback, not be treated as transport
        self.assertEqual(kind_arg("play despacito"),
                         ("play_music", ("despacito", None)))

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
        self._enum = commands._enum_windows
        commands._enum_windows = lambda: []   # never depend on real windows
        commands.webbrowser.open = lambda u: self.opened.append(u)
        commands.os.startfile = lambda p: self.launched.append(p)

    def tearDown(self):
        commands._enum_windows = self._enum
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

    def test_known_site_opens_directly_not_searched(self):
        ok, msg = self.e.run("open reddit")
        self.assertIn("reddit.com", self.opened[0])
        self.assertNotIn("google.com/search", self.opened[0])


class ComputerTaskExecutionTests(unittest.TestCase):
    """The new system tasks must execute their helper functions instead of
    answering "not understood", and never touch real hardware in tests."""

    def setUp(self):
        self.e = CommandEngine(build_index=False)
        self.patchers = [
            mock.patch.object(commands, "_set_volume_level"),
            mock.patch.object(commands, "_current_volume", return_value=40),
            mock.patch.object(commands, "_current_brightness", return_value=50),
            mock.patch.object(commands, "_set_brightness", return_value=True),
            mock.patch.object(commands, "_battery_percent", return_value=73),
            mock.patch.dict(sys.modules, {"keyboard": mock.MagicMock()}),
        ]
        for p in self.patchers:
            p.start()
        self._run = commands.subprocess.run
        self._startfile = commands.os.startfile
        self._send = commands.ctypes.windll.user32.SendMessageW
        commands.subprocess.run = lambda *a, **k: None
        commands.os.startfile = lambda p: None
        commands.ctypes.windll.user32.SendMessageW = lambda *a: 0

    def tearDown(self):
        commands.subprocess.run = self._run
        commands.os.startfile = self._startfile
        commands.ctypes.windll.user32.SendMessageW = self._send
        for p in self.patchers:
            p.stop()

    def test_lower_my_computers_volume(self):
        ok, msg = self.e.run("lower my computer's volume")
        self.assertTrue(ok)
        self.assertIn("down", msg.lower())

    def test_set_volume_calls_helper(self):
        ok, msg = self.e.run("set volume to 30")
        self.assertTrue(ok)
        commands._set_volume_level.assert_called_once_with(30)
        self.assertIn("30%", msg)

    def test_increase_volume_by_percent_uses_current(self):
        # "increase volume by 20%" from a current level of 40 -> 60.
        ok, msg = self.e.run("increase volume by 20%")
        self.assertTrue(ok)
        commands._current_volume.assert_called_once()
        commands._set_volume_level.assert_called_once_with(60)
        self.assertIn("60%", msg)

    def test_increasing_volume_gerund(self):
        # The exact wording from the bug report (whisper gerund form).
        ok, msg = self.e.run("increasing volume by 20%")
        self.assertTrue(ok)
        commands._set_volume_level.assert_called_once_with(60)

    def test_decrease_volume_by_percent_clamps_at_zero(self):
        ok, msg = self.e.run("decrease volume by 50%")
        self.assertTrue(ok)
        # 40 - 50 -> clamped to 0.
        commands._set_volume_level.assert_called_once_with(0)

    def test_volume_add_clamps_at_100(self):
        commands._current_volume.return_value = 95
        ok, msg = self.e.run("volume up by 20%")
        self.assertTrue(ok)
        commands._set_volume_level.assert_called_once_with(100)

    def test_volume_read_failure_is_honest(self):
        commands._current_volume.return_value = None
        ok, msg = self.e.run("increase volume by 20%")
        self.assertFalse(ok)
        self.assertIn("Could not read", msg)
        commands._set_volume_level.assert_not_called()

    def test_turn_the_volume_down_by_percent(self):
        ok, msg = self.e.run("turn the volume down by 20%")
        self.assertTrue(ok)
        # 40 - 20 = 20.
        commands._set_volume_level.assert_called_once_with(20)

    def test_increase_volume_to_is_a_set(self):
        ok, msg = self.e.run("increase volume to 60")
        self.assertTrue(ok)
        commands._current_volume.assert_not_called()
        commands._set_volume_level.assert_called_once_with(60)

    def test_brightness_by_percent_uses_current(self):
        ok, msg = self.e.run("increase brightness by 20%")
        self.assertTrue(ok)
        commands._set_brightness.assert_called_once_with(70)
        self.assertIn("70%", msg)

    def test_brightness_down_by_clamps(self):
        ok, msg = self.e.run("brightness down by 60")
        self.assertTrue(ok)
        commands._set_brightness.assert_called_once_with(0)

    def test_brightness_up_uses_helper(self):
        ok, msg = self.e.run("brightness up")
        self.assertTrue(ok)
        commands._current_brightness.assert_called_once()
        commands._set_brightness.assert_called_once_with(60)
        self.assertIn("60%", msg)

    def test_brightness_set_uses_helper(self):
        ok, msg = self.e.run("set brightness to 40")
        self.assertTrue(ok)
        commands._set_brightness.assert_called_once_with(40)

    def test_restart_and_cancel(self):
        ok, msg = self.e.run("restart the computer")
        self.assertTrue(ok)
        self.assertIn("restart", msg.lower())
        self.assertIn("60", msg)
        ok, msg = self.e.run("cancel restart")
        self.assertTrue(ok)

    def test_sleep_hibernate_battery_monitor(self):
        ok, msg = self.e.run("put the computer to sleep")
        self.assertTrue(ok)
        ok, msg = self.e.run("hibernate the computer")
        self.assertTrue(ok)
        ok, msg = self.e.run("battery level")
        self.assertTrue(ok)
        self.assertIn("73%", msg)
        ok, msg = self.e.run("turn off the display")
        self.assertTrue(ok)

    def test_open_settings_page(self):
        opened = []
        commands.os.startfile = lambda p: opened.append(p)
        ok, msg = self.e.run("open wifi settings")
        self.assertTrue(ok)
        self.assertEqual(opened, ["ms-settings:network-wifi"])

    def test_no_not_understood_for_new_tasks(self):
        for phrase in ["lower my computer's volume", "set volume to 30",
                       "increase volume by 20%", "increasing volume by 20%",
                       "decrease volume by 10%", "increase brightness by 20%",
                       "brightness up", "check battery",
                       "restart the computer", "turn off the display",
                       "open wifi settings"]:
            ok, _msg = self.e.run(phrase)
            self.assertTrue(ok, f"{phrase!r} should not be not-understood")


class VolumeHelperTests(unittest.TestCase):
    """The volume helpers must verify the change actually landed — the
    "it says increased but it didn't" bug — and never claim success on a
    silent no-op. Core Audio set is mocked; the read-back contract is
    what is under test."""

    def setUp(self):
        self.vol = mock.MagicMock()
        self.vol.set_volume_level.return_value = None
        self.patch_modules = mock.patch.dict(sys.modules,
                                             {"volume": self.vol})
        self.patch_modules.start()

    def tearDown(self):
        self.patch_modules.stop()

    def test_set_succeeds_when_read_back_confirms(self):
        self.vol.current_volume.return_value = 60
        # Must not raise: the change landed.
        commands._set_volume_level(60)
        self.vol.set_volume_level.assert_called_once_with(60)

    def test_set_raises_when_change_did_not_land(self):
        # The reported bug: the set call succeeds silently but the
        # audible volume never changed — read-back stays at the old
        # level, so the helper must refuse to claim success.
        self.vol.current_volume.return_value = 24
        with self.assertRaises(OSError):
            commands._set_volume_level(60)

    def test_set_tolerates_rounding_step(self):
        # Endpoints may round a fraction of a percent; within 3 is fine.
        self.vol.current_volume.return_value = 59
        commands._set_volume_level(60)

    def test_set_raises_when_read_back_missing(self):
        self.vol.current_volume.return_value = None
        with self.assertRaises(OSError):
            commands._set_volume_level(60)

    def test_set_propagates_endpoint_failure(self):
        self.vol.set_volume_level.side_effect = OSError("endpoint gone")
        with self.assertRaises(OSError):
            commands._set_volume_level(60)

    def test_current_returns_none_on_failure(self):
        self.vol.current_volume.return_value = None
        self.assertIsNone(commands._current_volume())

    def test_current_reads_via_core_audio(self):
        self.vol.current_volume.return_value = 42
        self.assertEqual(commands._current_volume(), 42)
        self.vol.current_volume.assert_called_once_with()

    def test_volume_by_percent_reports_failure_honestly(self):
        # End-to-end: "increase volume by 20%" when the change does not
        # land must come back as a failure, not a fake confirmation.
        self.vol.current_volume.return_value = 24  # unchanged after set
        e = CommandEngine(build_index=False)
        with mock.patch.object(commands, "_current_volume", return_value=40):
            with mock.patch.object(commands, "_set_volume_level",
                                   side_effect=OSError(
                                       "volume did not change (still 24%)")):
                ok, msg = e.run("increase volume by 20%")
        self.assertFalse(ok)
        self.assertIn("did not change", msg)


class CoreAudioVolumeTests(unittest.TestCase):
    """The volume.py Core Audio adapter: set must raise OSError (never
    silently pass) when the endpoint cannot be reached — the contract
    the read-back verification relies on."""

    def test_set_raises_when_no_endpoint(self):
        with mock.patch("volume._endpoint_volume", return_value=None):
            with self.assertRaises(OSError):
                volume.set_volume_level(50)

    def test_set_raises_on_bad_hresult(self):
        p = mock.MagicMock()
        with mock.patch("volume._endpoint_volume", return_value=p):
            with mock.patch("volume._vmethod",
                            return_value=lambda *a, **k: -1):
                with self.assertRaises(OSError):
                    volume.set_volume_level(50)

    def test_current_returns_none_when_no_endpoint(self):
        with mock.patch("volume._endpoint_volume", return_value=None):
            self.assertIsNone(volume.current_volume())


class HotwordTests(unittest.TestCase):
    def test_default_hotwords_include_common_names(self):
        import transcriber
        for name in ("Claude", "GitHub", "OBS", "Spotify", "YouTube"):
            self.assertIn(name, transcriber.DEFAULT_HOTWORDS)


class StoreAppAndReinforcementTests(unittest.TestCase):
    def setUp(self):
        self.e = CommandEngine(build_index=False)
        self.launched = []
        self.popened = []
        self.opened = []
        self._start = commands.os.startfile
        self._popen = commands.subprocess.Popen
        self._open = commands.webbrowser.open
        self._enum = commands._enum_windows
        commands._enum_windows = lambda: []   # never depend on real windows
        commands.os.startfile = lambda p: self.launched.append(p)
        commands.subprocess.Popen = lambda a, **k: self.popened.append(a)
        commands.webbrowser.open = lambda u: self.opened.append(u)

    def tearDown(self):
        commands._enum_windows = self._enum
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


class SwitchToWindowTests(unittest.TestCase):
    def setUp(self):
        self.e = CommandEngine(build_index=False)
        self.focused = []
        self.launched = []
        self.opened = []
        self._enum = commands._enum_windows
        self._focus = commands._focus_hwnd
        self._start = commands.os.startfile
        self._open = commands.webbrowser.open
        commands._focus_hwnd = lambda h: self.focused.append(h)
        commands.os.startfile = lambda p: self.launched.append(p)
        commands.webbrowser.open = lambda u: self.opened.append(u)

    def tearDown(self):
        commands._enum_windows = self._enum
        commands._focus_hwnd = self._focus
        commands.os.startfile = self._start
        commands.webbrowser.open = self._open

    def _windows(self, wins):
        commands._enum_windows = lambda: wins

    def test_open_focuses_already_open_site_tab(self):
        self._windows([(101, "YouTube - Google Chrome", "chrome.exe")])
        ok, msg = self.e.run("open youtube which is already open")
        self.assertTrue(ok)
        self.assertIn("Switched", msg)
        self.assertEqual(self.focused, [101])   # focused, not searched
        self.assertEqual(self.opened, [])

    def test_open_installed_app_ignores_browser_tab(self):
        # A browser tab titled "notepad ..." must NOT satisfy "open notepad".
        self._windows([(202, "notepad - Google Search", "chrome.exe")])
        self.e.app_index = {"notepad": "notepad"}
        ok, msg = self.e.run("open notepad")
        self.assertIn("Opening", msg)           # launched, not focused
        self.assertEqual(self.launched, ["notepad"])
        self.assertEqual(self.focused, [])

    def test_open_focuses_running_app_window(self):
        self._windows([(303, "Untitled - Notepad", "notepad.exe")])
        self.e.app_index = {"notepad": "notepad"}
        ok, msg = self.e.run("open notepad")
        self.assertIn("Switched", msg)
        self.assertEqual(self.focused, [303])
        self.assertEqual(self.launched, [])

    def test_switch_falls_back_to_open_when_not_running(self):
        self._windows([])
        ok, msg = self.e.run("switch to spotify")
        # nothing open -> opens (web here, since app_index empty)
        self.assertTrue(ok)
        self.assertEqual(self.focused, [])
        self.assertEqual(len(self.opened), 1)

    def test_open_browser_focuses_the_browser_itself(self):
        # "open chrome" with Chrome already open must focus it, not
        # launch a second instance — the browser itself is a valid match
        # even when browser *tabs* are excluded.
        self._windows([(404, "Google Chrome", "chrome.exe")])
        self.e.app_index = {"google chrome": "chrome.lnk"}
        ok, msg = self.e.run("open chrome")
        self.assertIn("Switched", msg)
        self.assertEqual(self.focused, [404])
        self.assertEqual(self.launched, [])


class CloseAppBrowserSafetyTests(unittest.TestCase):
    def setUp(self):
        self.e = CommandEngine(build_index=False)
        self.closed = []
        self._enum = commands._enum_windows
        self._post = commands._post_close
        self._sleep = commands.time.sleep
        commands._post_close = lambda h: self.closed.append(h)
        commands.time.sleep = lambda s: None   # skip the 0.6s verify pause

    def tearDown(self):
        commands._enum_windows = self._enum
        commands._post_close = self._post
        commands.time.sleep = self._sleep

    def _windows(self, wins):
        commands._enum_windows = lambda: wins

    def test_close_notepad_does_not_close_a_browser_tab_window(self):
        # A Chrome window whose title merely mentions "notepad" is a tab,
        # not the app — closing it would kill the whole browser.
        self._windows([(1, "Notepad - Google Search", "chrome.exe"),
                       (2, "Untitled - Notepad", "notepad.exe")])
        ok, _msg = self.e._close_app("notepad")
        self.assertTrue(ok)
        self.assertEqual(self.closed, [2])   # only the real Notepad window

    def test_close_browser_still_closes_the_browser(self):
        self._windows([(3, "YouTube - Google Chrome", "chrome.exe")])
        ok, _msg = self.e._close_app("chrome")
        self.assertTrue(ok)
        self.assertEqual(self.closed, [3])   # the browser itself is closable


if __name__ == "__main__":
    unittest.main()
