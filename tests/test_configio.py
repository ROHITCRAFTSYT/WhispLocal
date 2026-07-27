"""Unit tests for config loading: first-run bootstrap, upgrade overlay, corrupt
-config quarantine, and atomic save. Pure stdlib + a temp dir, so these run on
any CI runner without audio hardware or a Whisper model."""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "whisp"))

from configio import load_config, save_config


class ConfigIoTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.default = {"model": "base", "language": None, "beam_size": 2}
        with open(os.path.join(self.dir, "config.default.json"), "w",
                  encoding="utf-8") as f:
            json.dump(self.default, f)

    def _write_user(self, data):
        with open(os.path.join(self.dir, "config.json"), "w",
                  encoding="utf-8") as f:
            if isinstance(data, str):
                f.write(data)
            else:
                json.dump(data, f)

    def test_first_run_bootstraps_user_config(self):
        user_path = os.path.join(self.dir, "config.json")
        self.assertFalse(os.path.exists(user_path))
        cfg = load_config(self.dir)
        self.assertEqual(cfg, self.default)
        # The user copy is created so subsequent runs persist edits.
        self.assertTrue(os.path.exists(user_path))

    def test_user_values_overlay_defaults(self):
        self._write_user({"model": "small"})
        cfg = load_config(self.dir)
        self.assertEqual(cfg["model"], "small")   # user override wins
        self.assertEqual(cfg["beam_size"], 2)     # untouched default survives

    def test_upgrade_keeps_new_default_keys(self):
        # A user config written before 'beam_size' existed must not lose it.
        self._write_user({"model": "small", "language": "en"})
        cfg = load_config(self.dir)
        self.assertIn("beam_size", cfg)
        self.assertEqual(cfg["beam_size"], 2)

    def test_corrupt_config_is_quarantined_and_defaults_win(self):
        self._write_user("{ this is not json ]")
        cfg = load_config(self.dir)
        self.assertEqual(cfg, self.default)
        self.assertTrue(os.path.exists(os.path.join(self.dir, "config.json.bad")))

    def test_save_is_atomic_and_leaves_no_temp(self):
        save_config(self.dir, {"model": "tiny", "note": "café"})
        with open(os.path.join(self.dir, "config.json"), encoding="utf-8") as f:
            written = json.load(f)
        self.assertEqual(written["model"], "tiny")
        self.assertEqual(written["note"], "café")  # unicode preserved
        self.assertFalse(os.path.exists(os.path.join(self.dir, "config.json.tmp")))

    def test_round_trip_through_save_then_load(self):
        save_config(self.dir, {**self.default, "model": "small.en"})
        cfg = load_config(self.dir)
        self.assertEqual(cfg["model"], "small.en")


if __name__ == "__main__":
    unittest.main()
