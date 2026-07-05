"""Unit tests for the local personalization engine. Stdlib-only."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "whisp"))

from adaptive import Adaptive


class AdaptiveTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.a = Adaptive(self.dir)

    def test_learns_vocabulary_as_hotwords(self):
        for _ in range(3):
            self.a.record("deploy the kubernetes manifest tonight", "en")
        hot = self.a.hotwords()
        self.assertIn("kubernetes", hot)
        self.assertIn("manifest", hot)
        self.assertNotIn("the", (hot or "").split())

    def test_hotwords_need_repetition(self):
        self.a.record("ephemeral zeitgeist", "en")
        self.assertIsNone(self.a.hotwords())

    def test_learns_correction_pairs(self):
        n = self.a.learn_correction(
            "i asked clod about the jason file",
            "i asked Claude about the JSON file")
        self.assertEqual(n, 2)
        self.assertEqual(self.a.learned_dictionary["clod"], "Claude")
        self.assertEqual(self.a.learned_dictionary["jason"], "JSON")

    def test_correction_ignores_unaligned_edits(self):
        n = self.a.learn_correction("send the file", "please send the file now")
        self.assertEqual(n, 0)

    def test_corrected_words_become_hotwords(self):
        self.a.learn_correction("use postgress here", "use Postgres here")
        self.assertIn("Postgres", self.a.hotwords())

    def test_language_preference_needs_evidence(self):
        self.a.record("some words here today", "hi")
        self.assertIsNone(self.a.preferred_language())
        for _ in range(5):
            self.a.record("aur kuch shabd yahan likho", "hi")
        self.assertEqual(self.a.preferred_language(), "hi")

    def test_persistence_roundtrip(self):
        self.a.learn_correction("open the jason file", "open the JSON file")
        reloaded = Adaptive(self.dir)
        self.assertEqual(reloaded.learned_dictionary.get("jason"), "JSON")

    def test_devanagari_words_are_counted(self):
        for _ in range(3):
            self.a.record("परियोजना की रिपोर्ट कल भेजना", "hi")
        self.assertIn("परियोजना", self.a.hotwords())

    def test_disabled_learns_nothing(self):
        a = Adaptive(self.dir, enabled=False)
        a.record("kubernetes kubernetes kubernetes", "en")
        self.assertIsNone(a.hotwords())
        self.assertIsNone(a.preferred_language())

    def test_records_commands_and_builds_profile(self):
        self.a.record_command("open_app", label="discord")
        self.a.record_command("open_app", label="discord")
        self.a.record_command("search", topic="python asyncio tutorial")
        prof = self.a.profile_summary()
        self.assertEqual(prof["commands_total"], 3)
        self.assertEqual(prof["top_apps"][0], ("discord", 2))
        self.assertIn("open_app", dict(prof["top_actions"]))
        self.assertTrue(any("python" in t for t, _ in prof["top_topics"]))

    def test_command_learning_persists(self):
        self.a.record_command("open_app", label="obsidian")
        reloaded = Adaptive(self.dir)
        self.assertEqual(reloaded.command_total, 1)
        self.assertEqual(reloaded.app_counts["obsidian"], 1)

    def test_app_names_become_hotwords(self):
        for _ in range(3):
            self.a.record_command("open_app", label="discord")
        self.assertIn("discord", self.a.hotwords())


if __name__ == "__main__":
    unittest.main()
