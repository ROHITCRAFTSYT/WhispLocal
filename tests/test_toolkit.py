"""Tests for the smaller building blocks: chords, history search/stats,
app categories, sound cues and take recovery."""
import datetime as dt
import io
import os
import sys
import tempfile
import unittest
import wave

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "whisp"))

import appcontext
import chords
import cues
import history
import recovery

try:
    import numpy as np
    HAVE_NUMPY = True
except ImportError:
    HAVE_NUMPY = False


class ChordTests(unittest.TestCase):
    def test_press_and_release(self):
        m = chords.ChordMatcher("ctrl+windows")
        self.assertIsNone(m.feed("down", "ctrl"))
        self.assertEqual(m.feed("down", "left windows"), "press")
        self.assertIsNone(m.feed("down", "left windows"))  # auto-repeat
        self.assertEqual(m.feed("up", "ctrl"), "release")
        self.assertIsNone(m.feed("up", "left windows"))

    def test_generic_modifier_matches_either_side(self):
        m = chords.ChordMatcher("ctrl+alt")
        m.feed("down", "right ctrl")
        self.assertEqual(m.feed("down", "alt"), "press")

    def test_sided_spec_requires_that_side(self):
        m = chords.ChordMatcher("right ctrl+space")
        m.feed("down", "ctrl")
        self.assertIsNone(m.feed("down", "space"))

    def test_aliases(self):
        self.assertEqual(chords.parse("Win+Control"), ["windows", "ctrl"])
        self.assertTrue(chords.is_chord("ctrl+windows"))
        self.assertFalse(chords.is_chord("right ctrl"))
        self.assertFalse(chords.is_chord("+"))


ENTRIES = [
    {"ts": "2026-10-01 10:00:00", "text": "Deploy the launch build",
     "task": "transcribe", "audio_s": 3.0, "app": "slack"},
    {"ts": "2026-10-02 10:00:00", "text": "launch review moved to Friday",
     "task": "transcribe", "audio_s": 3.0, "app": "outlook"},
    {"ts": "2026-10-03 10:00:00", "text": "open chrome -> Opening Chrome",
     "task": "command", "audio_s": 1.0},
    {"ts": "2026-10-04 09:00:00", "text": "the review is done",
     "task": "transcribe", "audio_s": 2.0, "app": "slack"},
]


class HistoryTests(unittest.TestCase):
    def test_bm25_prefers_both_terms(self):
        hits = history.search(ENTRIES, "launch review")
        self.assertEqual(hits[0]["text"], "launch review moved to Friday")
        self.assertEqual(len(hits), 3)

    def test_prefix_match(self):
        hits = history.search(ENTRIES, "depl")
        self.assertEqual(hits[0]["text"], "Deploy the launch build")

    def test_empty_query_lists_newest_first(self):
        self.assertEqual(history.search(ENTRIES)[0]["ts"],
                         "2026-10-04 09:00:00")

    def test_filters(self):
        self.assertEqual(len(history.search(ENTRIES, app="slack")), 2)
        self.assertEqual(len(history.search(ENTRIES, task="command")), 1)

    def test_apps_by_use(self):
        self.assertEqual(history.apps(ENTRIES), ["slack", "outlook"])

    def test_stats(self):
        st = history.stats(ENTRIES, today=dt.date(2026, 10, 4))
        self.assertEqual(st["dictations"], 3)
        self.assertEqual(st["commands"], 1)
        self.assertEqual(st["total_words"], 13)
        self.assertEqual(st["wpm"], 98)  # 13 words in 8 s
        self.assertEqual(st["streak_days"], 4)
        self.assertEqual(st["top_apps"][0], ("slack", 2))

    def test_streak_survives_until_end_of_today(self):
        st = history.stats(ENTRIES[:3], today=dt.date(2026, 10, 4))
        self.assertEqual(st["streak_days"], 3)
        st = history.stats(ENTRIES[:2], today=dt.date(2026, 10, 4))
        self.assertEqual(st["streak_days"], 0)

    def test_load_skips_corrupt_lines(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "h.jsonl")
            with open(p, "w", encoding="utf-8") as f:
                f.write('{"text": "ok"}\nnot json\n')
            self.assertEqual(history.load(p), [{"text": "ok"}])


class AppContextTests(unittest.TestCase):
    def test_desktop_apps(self):
        self.assertEqual(appcontext.categorize(r"C:\x\OUTLOOK.EXE"), "email")
        self.assertEqual(appcontext.categorize("Code.exe"), "code")
        self.assertEqual(appcontext.categorize("WindowsTerminal.exe"),
                         "terminal")
        self.assertEqual(appcontext.categorize("mspaint.exe"), "general")

    def test_browser_titles(self):
        self.assertEqual(appcontext.categorize(
            "chrome.exe", "Inbox (3) - me@x.com - Gmail"), "email")
        self.assertEqual(appcontext.categorize(
            "msedge.exe", "ChatGPT - Microsoft Edge"), "ai_chat")
        self.assertEqual(appcontext.categorize(
            "firefox.exe", "Plan - Google Docs"), "docs")
        self.assertEqual(appcontext.categorize("chrome.exe", "News"),
                         "general")

    def test_no_target_on_desktop(self):
        self.assertFalse(appcontext.Context("explorer.exe", "",
                                            "Progman", hwnd=1).has_target)
        self.assertTrue(appcontext.Context("notepad.exe", "x", "Notepad",
                                           hwnd=1).has_target)
        self.assertFalse(appcontext.Context().has_target)


class CueTests(unittest.TestCase):
    def test_every_cue_renders_valid_wav(self):
        for name in cues.CUES:
            with wave.open(io.BytesIO(cues.wav(name))) as w:
                self.assertEqual(w.getnchannels(), 1)
                self.assertEqual(w.getsampwidth(), 2)
                self.assertGreater(w.getnframes(), 1000)

    def test_disabled_or_unknown_is_silent(self):
        cues.play("start", enabled=False)
        cues.play("no-such-cue")


@unittest.skipUnless(sys.platform == "win32" and HAVE_NUMPY,
                     "DPAPI is Windows-only; takes need numpy")
class RecoveryTests(unittest.TestCase):
    def test_dpapi_roundtrip(self):
        blob = recovery.protect(b"secret audio")
        self.assertNotIn(b"secret audio", blob)
        self.assertEqual(recovery.unprotect(blob), b"secret audio")

    def test_last_take_roundtrip_and_clear(self):
        with tempfile.TemporaryDirectory() as d:
            take = recovery.LastTake(d)
            audio = np.sin(np.linspace(0, 20, 16000)).astype(np.float32) * 0.5
            take.save(audio, {"task": "translate"})
            got, meta = take.load()
            self.assertEqual(meta["task"], "translate")
            self.assertTrue(np.allclose(got, audio, atol=1e-3))
            take.clear()
            self.assertEqual(take.load(), (None, None))

    def test_expired_take_is_discarded(self):
        with tempfile.TemporaryDirectory() as d:
            take = recovery.LastTake(d, max_age=-1)
            take.save(np.zeros(100, dtype=np.float32))
            self.assertEqual(take.load(), (None, None))
            self.assertFalse(take.exists())


class TypingEventTests(unittest.TestCase):
    def setUp(self):
        from unittest import mock
        with mock.patch.dict(sys.modules, {"keyboard": mock.MagicMock(),
                                           "pyperclip": mock.MagicMock()}):
            import inject
        self.inject = inject

    def test_plain_character_is_down_then_up(self):
        ev = self.inject._key_events("a")
        self.assertEqual(ev, [(0, ord("a"), 0x4), (0, ord("a"), 0x6)])

    def test_newline_is_enter(self):
        ev = self.inject._key_events("\r\n")
        self.assertEqual(ev, [(0x0D, 0, 0), (0x0D, 0, 0x2)])

    def test_surrogate_pair_halves_go_down_together(self):
        ev = self.inject._key_events("\U0001F389")
        self.assertEqual([e[2] for e in ev], [0x4, 0x4, 0x6, 0x6])
        self.assertEqual(ev[0][1], 0xD83C)
        self.assertEqual(ev[1][1], 0xDF89)

    def test_devanagari_is_per_code_unit(self):
        self.assertEqual(len(self.inject._key_events("नम")), 4)


class LedgerTests(unittest.TestCase):
    def test_records_last_text(self):
        led = recovery.Ledger()
        self.assertEqual(led.last(), "")
        led.record("hello", "slack")
        self.assertEqual((led.last(), led.app), ("hello", "slack"))


if __name__ == "__main__":
    unittest.main()
