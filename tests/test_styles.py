"""Tests for context-aware writing styles (styles.py). Pure stdlib."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "whisp"))

import styles
from cleanup import clean

CFG = {"remove_fillers": True, "capitalize_first": True}


def run(text, preset, category, **cfg):
    return styles.apply(clean(text, CFG), preset, category, cfg)


class PresetResolutionTests(unittest.TestCase):
    def test_defaults_per_category(self):
        self.assertEqual(styles.resolve_preset("email", "outlook", {}),
                         "formal")
        self.assertEqual(styles.resolve_preset("chat", "slack", {}), "casual")
        self.assertEqual(styles.resolve_preset("terminal", "cmd", {}),
                         "verbatim")

    def test_category_setting_overrides_default(self):
        cfg = {"style_presets": {"chat": "formal"}}
        self.assertEqual(styles.resolve_preset("chat", "slack", cfg), "formal")

    def test_per_app_override_wins(self):
        cfg = {"style_presets": {"chat": "casual"},
               "app_styles": {"Slack": "concise"}}
        self.assertEqual(styles.resolve_preset("chat", "slack", cfg),
                         "concise")

    def test_unknown_preset_falls_back(self):
        cfg = {"style_presets": {"chat": "shouty"}}
        self.assertEqual(styles.resolve_preset("chat", "x", cfg), "standard")


class FormalTests(unittest.TestCase):
    def test_expands_shorthand_and_adds_commas(self):
        self.assertEqual(
            run("hey FYI idk if the launch review can stay at 3 tomorrow. "
                "please check the numbers", "formal", "email"),
            "Hey, for your information, I do not know if the launch review "
            "can stay at 3 tomorrow. Please check the numbers.")

    def test_names_after_greeting_are_left_alone(self):
        self.assertEqual(run("Hi John, the deck is ready", "formal", "email"),
                         "Hi John, the deck is ready.")

    def test_single_letters_are_not_expanded(self):
        self.assertEqual(run("My U key is broken", "formal", "email"),
                         "My U key is broken.")

    def test_drops_verbal_fillers(self):
        self.assertEqual(run("We should, you know, ship it", "formal", "docs"),
                         "We should ship it.")


class CasualAndConciseTests(unittest.TestCase):
    def test_casual_drops_lone_period(self):
        self.assertEqual(run("sounds good.", "casual", "chat"), "Sounds good")

    def test_casual_keeps_periods_between_sentences(self):
        self.assertEqual(run("sounds good. see you then.", "casual", "chat"),
                         "Sounds good. See you then.")

    def test_casual_keeps_question_mark(self):
        self.assertEqual(run("are you coming?", "casual", "chat"),
                         "Are you coming?")

    def test_spoken_emoji_in_chat(self):
        self.assertEqual(run("great job thumbs up emoji", "casual", "chat"),
                         "Great job \U0001F44D")

    def test_concise_removes_hedges(self):
        self.assertEqual(
            run("So, basically, I think that we should really ship it.",
                "concise", "docs"),
            "We should ship it.")


class VerbatimTests(unittest.TestCase):
    def test_terminal_keeps_shell_casing(self):
        self.assertEqual(run("git status.", "verbatim", "terminal"),
                         "git status")

    def test_verbatim_skips_time_normalisation(self):
        self.assertEqual(run("at three pm", "verbatim", "code"),
                         "At three pm")


class SpokenCommandTests(unittest.TestCase):
    def test_new_line_and_paragraph(self):
        self.assertEqual(
            run("Dear team new paragraph the report is ready new line thanks",
                "standard", "general"),
            "Dear team\n\nThe report is ready\nThanks")

    def test_bullet_points(self):
        self.assertEqual(
            run("Shopping list bullet point milk bullet point eggs",
                "standard", "notes"),
            "Shopping list\n- Milk\n- Eggs")

    def test_spoken_commands_can_be_disabled(self):
        out = styles.apply("Write a new line of code.", "standard", "general",
                           {"spoken_commands": False})
        self.assertEqual(out, "Write a new line of code.")

    def test_scratch_that_drops_previous_sentence(self):
        self.assertEqual(run("Buy milk. Actually scratch that. Buy eggs.",
                             "standard", "general"), "Buy eggs.")

    def test_scratch_that_mid_sentence(self):
        self.assertEqual(run("Send it to John, scratch that, send it to Mary.",
                             "standard", "general"), "Send it to Mary.")

    def test_number_self_correction(self):
        self.assertEqual(run("Meet me at 3, no wait, 4 pm.", "standard",
                             "general"), "Meet me at 4 PM.")


class TimeTests(unittest.TestCase):
    def test_spoken_times_become_digits(self):
        self.assertEqual(styles.normalize_times("at three thirty pm"),
                         "at 3:30 PM")
        self.assertEqual(styles.normalize_times("by 9 a.m. sharp"),
                         "by 9 AM sharp")

    def test_pm_at_sentence_end_keeps_full_stop(self):
        self.assertEqual(styles.normalize_times("It's at 5 p.m. Bring it."),
                         "It's at 5 PM. Bring it.")

    def test_out_of_range_hour_untouched(self):
        self.assertEqual(styles.normalize_times("twenty pm"), "twenty pm")


class ListTests(unittest.TestCase):
    def test_first_then_finally_becomes_numbered_list(self):
        self.assertEqual(
            run("Hey, first update the retry handler, then keep the session "
                "active, and finally run the tests.", "standard", "notes"),
            "Hey,\n1. Update the retry handler\n2. Keep the session "
            "active\n3. Run the tests")

    def test_first_of_all(self):
        self.assertEqual(
            run("First of all thanks. Second, the plan is fine. Finally "
                "ship.", "standard", "notes"),
            "1. Thanks\n2. The plan is fine\n3. Ship")

    def test_plain_then_is_not_a_list(self):
        self.assertEqual(run("I like it then we go home.", "standard",
                             "notes"), "I like it then we go home.")

    def test_no_lists_in_chat(self):
        out = run("first do this then that and finally the other",
                  "casual", "chat")
        self.assertNotIn("\n", out)


class CodeHelperTests(unittest.TestCase):
    def test_file_mentions(self):
        self.assertEqual(run("Fix the bug in at file app dot py?", "casual",
                             "ai_chat"), "Fix the bug in @app.py?")

    def test_identifier_casing(self):
        self.assertEqual(styles.apply_code_helpers(
            "rename it to snake case user account id"),
            "rename it to user_account_id")
        self.assertEqual(styles.to_case("camel", "user account id"),
                         "userAccountId")
        self.assertEqual(styles.to_case("pascal", "user id"), "UserId")
        self.assertEqual(styles.to_case("kebab", "user id"), "user-id")
        self.assertEqual(styles.to_case("constant", "max size"), "MAX_SIZE")

    def test_code_helpers_only_in_code_apps(self):
        out = run("open app dot py", "standard", "general")
        self.assertEqual(out, "Open app dot py")


if __name__ == "__main__":
    unittest.main()
