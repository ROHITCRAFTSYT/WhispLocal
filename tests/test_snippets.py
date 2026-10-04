"""Tests for spoken shortcuts (snippets.py)."""
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "whisp"))

import snippets

SNIPS = {"my email": "rohit@example.com", "sign off": "Thanks,\\nRohit",
         "addr": "12 Main St", "today": "{date}"}
NOW = time.strptime("2026-10-04 09:30", "%Y-%m-%d %H:%M")


class SnippetTests(unittest.TestCase):
    def test_whole_utterance_is_exact(self):
        self.assertEqual(snippets.expand("My email.", SNIPS, NOW),
                         ("rohit@example.com", True))

    def test_newline_escape(self):
        self.assertEqual(snippets.expand("Sign off", SNIPS, NOW)[0],
                         "Thanks,\nRohit")

    def test_inline_multiword_trigger(self):
        self.assertEqual(
            snippets.expand("Send it to my email please.", SNIPS, NOW),
            ("Send it to rohit@example.com please.", False))

    def test_single_word_trigger_not_inline(self):
        self.assertEqual(snippets.expand("The addr field", SNIPS, NOW),
                         ("The addr field", False))

    def test_single_word_trigger_alone(self):
        self.assertEqual(snippets.expand("Addr.", SNIPS, NOW),
                         ("12 Main St", True))

    def test_placeholders(self):
        self.assertEqual(snippets.expand("today", SNIPS, NOW)[0],
                         "2026-10-04")

    def test_no_snippets(self):
        self.assertEqual(snippets.expand("hello", {}, NOW), ("hello", False))

    def test_parse_lines(self):
        self.assertEqual(snippets.parse_lines("a b => c\nbad line\n => x"),
                         {"a b": "c"})


if __name__ == "__main__":
    unittest.main()
