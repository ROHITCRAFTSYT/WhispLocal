"""Tests for fitting a dictation into surrounding text (planner.py)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "whisp"))

from planner import plan


class PlannerTests(unittest.TestCase):
    def test_unknown_context_is_unchanged(self):
        self.assertEqual(plan("Hello there.", None), "Hello there.")

    def test_empty_field_starts_a_sentence(self):
        self.assertEqual(plan("hello there.", ""), "Hello there.")

    def test_adds_space_after_word(self):
        self.assertEqual(plan("Then we left.", "We ate."), " Then we left.")

    def test_continues_sentence_in_lowercase(self):
        self.assertEqual(plan("Then we left.", "We ate and"),
                         " then we left.")

    def test_keeps_names_and_pronoun_i(self):
        self.assertEqual(plan("Rohit agreed.", "and"), " Rohit agreed.")
        self.assertEqual(plan("I agreed.", "and"), " I agreed.")
        self.assertEqual(plan("GitHub is down.", "and"), " GitHub is down.")

    def test_keep_caps_list(self):
        self.assertEqual(plan("Will called.", "and", keep_caps=["Will"]),
                         " Will called.")

    def test_no_double_space(self):
        self.assertEqual(plan("Then we left.", "We ate. "), "Then we left.")

    def test_no_space_after_opening_bracket(self):
        self.assertEqual(plan("see notes", "("), "see notes")

    def test_punctuation_attaches_without_space(self):
        self.assertEqual(plan(", and more", "word"), ", and more")

    def test_new_line_starts_a_sentence(self):
        self.assertEqual(plan("next item", "first item\n"), "Next item")

    def test_after_comma_lowercases_common_word(self):
        self.assertEqual(plan("But it failed.", "It ran,"),
                         " but it failed.")


if __name__ == "__main__":
    unittest.main()
