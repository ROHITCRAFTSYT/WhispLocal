"""Unit tests for the Obsidian note writer. Stdlib-only."""
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "whisp"))

import obsidian


class ObsidianTests(unittest.TestCase):
    def setUp(self):
        self.vault = tempfile.mkdtemp()

    def _today_file(self):
        return os.path.join(self.vault, obsidian.SUBFOLDER,
                            time.strftime("%Y-%m-%d") + ".md")

    def test_rejects_missing_vault(self):
        ok, msg = obsidian.save_note(r"C:\does\not\exist_xyz", "hello")
        self.assertFalse(ok)

    def test_rejects_empty_text(self):
        ok, _ = obsidian.save_note(self.vault, "   ")
        self.assertFalse(ok)

    def test_writes_frontmatter_and_bullet(self):
        ok, msg = obsidian.save_note(self.vault, "buy milk tomorrow")
        self.assertTrue(ok, msg)
        with open(self._today_file(), encoding="utf-8") as f:
            content = f.read()
        self.assertIn("source: WhispLocal", content)
        self.assertIn("# Voice notes", content)
        self.assertIn("Buy milk tomorrow.", content)  # capitalized + period

    def test_appends_without_duplicating_header(self):
        obsidian.save_note(self.vault, "first note")
        obsidian.save_note(self.vault, "second note")
        with open(self._today_file(), encoding="utf-8") as f:
            content = f.read()
        self.assertEqual(content.count("# Voice notes"), 1)
        self.assertIn("First note.", content)
        self.assertIn("Second note.", content)

    def test_preserves_existing_punctuation(self):
        obsidian.save_note(self.vault, "is the build green?")
        with open(self._today_file(), encoding="utf-8") as f:
            content = f.read()
        self.assertIn("Is the build green?", content)
        self.assertNotIn("green?.", content)

    def test_note_stays_inside_vault(self):
        # The written file must be under the vault folder.
        obsidian.save_note(self.vault, "sandbox check")
        real = os.path.realpath(self._today_file())
        self.assertTrue(real.startswith(os.path.realpath(self.vault)))


if __name__ == "__main__":
    unittest.main()
