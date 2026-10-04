"""Tests for voice-edit instructions (editing.py rules and LLM output
cleanup). The selection capture itself needs a real clipboard and is
covered with mocks only."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "whisp"))

import editing


def edit(instruction, text):
    return editing.apply_rules(instruction, text)[0]


class RuleTests(unittest.TestCase):
    def test_case_changes(self):
        self.assertEqual(edit("make it all caps", "hello there"),
                         "HELLO THERE")
        self.assertEqual(edit("lowercase", "Hello There"), "hello there")
        self.assertEqual(edit("title case", "the lord of the rings"),
                         "The Lord of the Rings")

    def test_bullets_and_numbers(self):
        self.assertEqual(edit("turn this into bullet points",
                              "Buy milk. Call mom. Ship it."),
                         "- Buy milk.\n- Call mom.\n- Ship it.")
        self.assertEqual(edit("make it a numbered list", "milk, eggs, bread"),
                         "1. Milk\n2. Eggs\n3. Bread")

    def test_remove_bullets_joins(self):
        self.assertEqual(edit("remove the bullets", "- one\n- two"),
                         "one two")

    def test_replace_word(self):
        self.assertEqual(edit("replace Monday with Tuesday",
                              "See you Monday."), "See you Tuesday.")

    def test_replace_missing_word_falls_through(self):
        self.assertIsNone(edit("replace Friday with Sunday", "See you."))

    def test_delete_word(self):
        self.assertEqual(edit("delete the word really",
                              "It is really good."), "It is good.")

    def test_delete_last_sentence(self):
        self.assertEqual(edit("delete the last sentence", "One. Two. Three."),
                         "One. Two.")

    def test_formal_and_casual(self):
        self.assertEqual(edit("make it more formal", "idk if it works"),
                         "I do not know if it works.")
        self.assertEqual(edit("make it less formal", "Sounds good."),
                         "Sounds good")

    def test_code_casing(self):
        self.assertEqual(edit("snake case", "user account id"),
                         "user_account_id")

    def test_wrappers(self):
        self.assertEqual(edit("code block", "x = 1"), "```\nx = 1\n```")
        self.assertEqual(edit("put it in backticks", "npm"), "`npm`")

    def test_sort_lines(self):
        self.assertEqual(edit("sort the lines", "pear\napple\nFig"),
                         "apple\nFig\npear")

    def test_unknown_instruction_needs_llm(self):
        self.assertEqual(editing.apply_rules("summarise this", "Long text."),
                         (None, None))

    def test_keeps_trailing_newline(self):
        self.assertEqual(edit("uppercase", "abc\n"), "ABC\n")


class LLMOutputTests(unittest.TestCase):
    def test_strips_preamble_and_quotes(self):
        self.assertEqual(editing.clean_llm_output(
            "Sure! Here is the edited text:\n\"Hello world\""), "Hello world")

    def test_strips_code_fences(self):
        self.assertEqual(editing.clean_llm_output("```\nabc\n```"), "abc")

    def test_rejects_runaway_output(self):
        original = "A short sentence that is long enough."
        self.assertIsNone(editing.clean_llm_output("x" * 1000, original))

    def test_empty_is_none(self):
        self.assertIsNone(editing.clean_llm_output("   "))

    def test_prompts_embed_inputs(self):
        self.assertIn("make it shorter",
                      editing.rewrite_prompt("make it shorter", "abc"))
        self.assertIn("an email app", editing.author_prompt("hi", "email"))


class CaptureTests(unittest.TestCase):
    def test_capture_returns_selection_and_restores_clipboard(self):
        clip = {"v": "previous"}
        kb = mock.MagicMock()

        def send(_combo):
            clip["v"] = "selected text"
        kb.send.side_effect = send
        pc = mock.MagicMock()
        pc.paste.side_effect = lambda: clip["v"]
        pc.copy.side_effect = lambda v: clip.__setitem__("v", v)
        with mock.patch.dict(sys.modules, {"keyboard": kb, "pyperclip": pc}):
            self.assertEqual(editing.capture_selection(wait=0.2),
                             "selected text")
        self.assertEqual(clip["v"], "previous")

    def test_nothing_selected_returns_empty(self):
        clip = {"v": "previous"}
        pc = mock.MagicMock()
        pc.paste.side_effect = lambda: clip["v"]
        pc.copy.side_effect = lambda v: clip.__setitem__("v", v)
        with mock.patch.dict(sys.modules, {"keyboard": mock.MagicMock(),
                                           "pyperclip": pc}):
            self.assertEqual(editing.capture_selection(wait=0.1), "")
        self.assertEqual(clip["v"], "previous")


if __name__ == "__main__":
    unittest.main()
