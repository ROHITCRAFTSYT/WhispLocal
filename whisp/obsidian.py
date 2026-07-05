"""Obsidian vault integration: save voice notes as formatted Markdown.

Notes are appended to a per-day file inside a WhispLocal folder in the
vault, with YAML frontmatter and timestamped bullets so they read well
and are easy to find later. Writing is sandboxed: the resolved target
path must stay inside the configured vault, and the vault must already
exist (this never creates a vault in an arbitrary location).

Nothing here touches the network. Data stays in the user's own vault.
"""
import os
import time

SUBFOLDER = "WhispLocal"


def is_valid_vault(vault):
    return bool(vault) and os.path.isdir(vault)


def _daily_path(vault):
    folder = os.path.join(vault, SUBFOLDER)
    day = time.strftime("%Y-%m-%d")
    return folder, os.path.join(folder, f"{day}.md"), day


def _within(base, target):
    base_r = os.path.realpath(base)
    target_r = os.path.realpath(target)
    return os.path.commonpath([base_r, target_r]) == base_r


def save_note(vault, text, kind="note"):
    """Append `text` to today's note in the vault. Returns (ok, feedback)."""
    text = (text or "").strip()
    if not text:
        return False, "Nothing to note"
    if not is_valid_vault(vault):
        return False, ("Obsidian vault path is not set or does not exist. "
                       "Fix it in Settings")

    folder, path, day = _daily_path(vault)
    if not _within(vault, path):
        return False, "Refusing to write outside the vault"

    try:
        os.makedirs(folder, exist_ok=True)
        new_file = not os.path.exists(path)
        with open(path, "a", encoding="utf-8") as f:
            if new_file:
                f.write(
                    "---\n"
                    f"created: {day}\n"
                    "source: WhispLocal\n"
                    "tags: [whisplocal, voice-note]\n"
                    "---\n\n"
                    f"# Voice notes — {day}\n\n")
            stamp = time.strftime("%H:%M")
            # Capitalize the first letter without touching the rest.
            body = text[0].upper() + text[1:] if text else text
            if not body.endswith((".", "!", "?")):
                body += "."
            f.write(f"- **{stamp}** {body}\n")
        return True, "Saved to today's note in Obsidian"
    except OSError as e:
        return False, f"Could not write the note: {e}"


def save_profile(vault, summary):
    """Overwrite a Profile.md in the vault with what has been learned.
    Returns (ok, feedback)."""
    if not is_valid_vault(vault):
        return False, ("Obsidian vault path is not set or does not exist. "
                       "Fix it in Settings")
    folder = os.path.join(vault, SUBFOLDER)
    path = os.path.join(folder, "Profile.md")
    if not _within(vault, path):
        return False, "Refusing to write outside the vault"

    def _rows(pairs):
        return "\n".join(f"- {k} — {v}" for k, v in pairs) or "- (nothing yet)"

    day = time.strftime("%Y-%m-%d %H:%M")
    langs = summary.get("dictations_by_language") or {}
    lang_line = ", ".join(f"{k} ({v})" for k, v in langs.items()) or "none yet"
    try:
        os.makedirs(folder, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(
                "---\n"
                "source: WhispLocal\n"
                "tags: [whisplocal, profile]\n"
                f"updated: {day}\n"
                "---\n\n"
                "# What WhispLocal has learned about me\n\n"
                f"_Updated {day}. This file is maintained locally by "
                "WhispLocal from how you use it._\n\n"
                f"**Voice commands run:** {summary.get('commands_total', 0)}  \n"
                f"**Dictation languages:** {lang_line}  \n"
                f"**Vocabulary learned:** {summary.get('vocabulary_size', 0)} words\n\n"
                "## Apps I open most\n"
                f"{_rows(summary.get('top_apps', []))}\n\n"
                "## Things I look up most\n"
                f"{_rows(summary.get('top_topics', []))}\n\n"
                "## What I do most\n"
                f"{_rows(summary.get('top_actions', []))}\n\n"
                "## Corrections you taught me\n"
                f"{_rows(list((summary.get('corrections') or {}).items()))}\n")
        return True, "Updated your profile in Obsidian"
    except OSError as e:
        return False, f"Could not write the profile: {e}"
