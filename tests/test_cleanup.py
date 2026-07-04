"""Unit tests for the text-cleanup pass. Dependency-free (pure stdlib),
so they run on any CI runner without audio hardware or models."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "whisp"))

from cleanup import clean

CFG = {
    "remove_fillers": True,
    "capitalize_first": True,
    "dictionary": {"clod": "Claude"},
}


class CleanupTests(unittest.TestCase):
    def test_removes_fillers(self):
        self.assertEqual(
            clean("um, hello there, uh, how are you?", CFG),
            "Hello there, how are you?")

    def test_filler_words_only_match_whole_words(self):
        self.assertEqual(
            clean("umbrella is not a filler", CFG),
            "Umbrella is not a filler")

    def test_dictionary_replacement(self):
        self.assertEqual(
            clean("i asked clod about it.", CFG),
            "I asked Claude about it.")

    def test_recapitalizes_after_sentence_filler_removal(self):
        self.assertEqual(
            clean("First part. Hmm, it worked.", CFG),
            "First part. It worked.")

    def test_normalizes_whitespace_and_punctuation(self):
        self.assertEqual(clean("  spaced   out  text .", CFG),
                         "Spaced out text.")

    def test_strip_trailing_period(self):
        cfg = dict(CFG, strip_trailing_period=True)
        self.assertEqual(clean("send it now.", cfg), "Send it now")

    def test_empty_input(self):
        self.assertEqual(clean("", CFG), "")

    def test_fillers_kept_when_disabled(self):
        cfg = dict(CFG, remove_fillers=False)
        self.assertIn("um", clean("um, keep this", cfg).lower())

    def test_abbreviations_not_recapitalized(self):
        self.assertEqual(
            clean("Use tools, e.g. hammers.", CFG),
            "Use tools, e.g. hammers.")


if __name__ == "__main__":
    unittest.main()
