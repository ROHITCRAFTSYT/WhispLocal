"""Voice editing: select text anywhere, hold the edit hotkey, say what to
change ("make this formal", "turn it into bullet points", "replace Monday
with Tuesday"), and the selection is replaced with the result.

Instructions are matched by deterministic rules first, so common edits
are instant and fully offline. Anything the rules do not understand
("summarise this", "reply politely saying I will be late") goes to the
optional local LLM when one is configured. With nothing selected, the
LLM can also write new text at the cursor.

Safety: the selection is read only while the edit hotkey is used, never
from a password field, and the clipboard is restored afterwards. The LLM
only ever returns text to paste, so it cannot run anything.
"""
import re
import time

import styles

SENTINEL = "⁣whisplocal-selection-probe⁣"


# ----- selection capture ----------------------------------------------------------

def capture_selection(wait=0.45):
    """Copy the current selection and return it ("" when nothing is
    selected), restoring the previous clipboard afterwards. Returns None if
    the clipboard could not be used at all."""
    import keyboard
    import pyperclip
    try:
        saved = pyperclip.paste()
    except Exception:
        saved = None
    try:
        pyperclip.copy(SENTINEL)
    except Exception:
        return None
    keyboard.send("ctrl+c")
    deadline = time.time() + wait
    text = SENTINEL
    while time.time() < deadline:
        time.sleep(0.03)
        try:
            text = pyperclip.paste()
        except Exception:
            continue
        if text != SENTINEL:
            break
    if saved is not None:
        try:
            pyperclip.copy(saved)
        except Exception:
            pass
    return "" if text == SENTINEL else text


# ----- rule-based transforms ------------------------------------------------------

def _sentences(text):
    parts = re.split(r"(?<=[.!?])\s+|\n+|;\s*", text.strip())
    if len(parts) == 1 and "," in text:
        parts = text.split(",")
    return [p.strip(" -*•\t,") for p in parts if p.strip(" -*•\t,")]


def _strip_list_markers(text):
    return re.sub(r"(?m)^\s*(?:[-*•]|\d+[.)])\s+", "", text)


def _title_case(text):
    small = {"a", "an", "the", "and", "but", "or", "for", "nor", "on", "at",
             "to", "by", "of", "in", "with"}
    words = text.split(" ")
    out = []
    for i, w in enumerate(words):
        if i and w.lower() in small:
            out.append(w.lower())
        else:
            out.append(w[:1].upper() + w[1:])
    return " ".join(out)


def _sentence_case(text):
    text = text.lower()
    text = re.sub(r"(^\s*|[.!?]\s+)([a-z])",
                  lambda m: m.group(1) + m.group(2).upper(), text)
    return re.sub(r"\bi\b", "I", text)


def _fix_up(text):
    from cleanup import clean
    return clean(text, {"remove_fillers": True, "capitalize_first": True})


def _cap(s):
    return s[:1].upper() + s[1:]


# (pattern, function(text, match) -> new text, description)
RULES = [
    (r"\b(?:all caps|upper ?case|capitali[sz]e (?:it all|everything|all))\b",
     lambda t, m: t.upper(), "uppercase"),
    (r"\blower ?case\b", lambda t, m: t.lower(), "lowercase"),
    (r"\btitle case\b|\bcapitali[sz]e (?:each|every) word\b",
     lambda t, m: _title_case(t), "title case"),
    (r"\bsentence case\b", lambda t, m: _sentence_case(t), "sentence case"),
    (r"\bsort (?:the |these )?(?:lines|items|list)?\b|\balphabeti[sz]e\b",
     lambda t, m: "\n".join(sorted(t.splitlines(), key=str.lower)), "sorted"),
    (r"\breverse (?:the )?order\b",
     lambda t, m: "\n".join(reversed(t.splitlines())), "reversed"),
    (r"\b(?:one|single) (?:line|paragraph)\b|\bjoin (?:the |these )?lines\b"
     r"|\bremove (?:the )?(?:line breaks|bullets|numbers)\b",
     lambda t, m: re.sub(r"\s*\n\s*", " ", _strip_list_markers(t)).strip(),
     "joined into one paragraph"),
    (r"\bnumbered list\b|\bnumber (?:the|these|them)\b",
     lambda t, m: "\n".join(f"{i}. {_cap(s)}" for i, s in
                            enumerate(_sentences(_strip_list_markers(t)), 1)),
     "numbered list"),
    (r"\bbullet(?:ed)?(?: point)?s?\b|\bbulleti[sz]e\b|\b(?:a )?list\b",
     lambda t, m: "\n".join(f"- {_cap(s)}" for s in
                            _sentences(_strip_list_markers(t))),
     "bullet list"),
    (r"\b(?:more )?casual\b|\bless formal\b|\binformal\b",
     lambda t, m: styles.apply(t, "casual", "chat", {"smart_lists": False}),
     "made casual"),
    (r"\b(?:more )?formal\b|\bprofessional\b",
     lambda t, m: styles.apply(t, "formal", "docs", {"smart_lists": False}),
     "made formal"),
    (r"\bshorter\b|\bconcise\b|\btighten\b|\bless wordy\b",
     lambda t, m: styles.apply(t, "concise", "docs", {"smart_lists": False}),
     "made concise"),
    (r"\bfix (?:the |this |it|up)?\s*(?:grammar|punctuation|capitali[sz]ation|"
     r"spacing|it|this)?\b|\bclean (?:it|this) up\b|\bclean up\b",
     lambda t, m: _fix_up(t), "cleaned up"),
    (r"\bremove (?:all )?(?:the )?punctuation\b",
     lambda t, m: re.sub(r"[^\w\s'-]", "", t), "punctuation removed"),
    (r"\b(snake|camel|pascal|kebab|constant) case\b",
     lambda t, m: styles.to_case(m.group(1), t), "re-cased"),
    (r"\b(?:wrap (?:it |this )?in |put (?:it |this )?in )?(?:double )?quotes\b",
     lambda t, m: f"“{t.strip()}”", "quoted"),
    (r"\bparenthes[ie]s\b|\bbrackets\b",
     lambda t, m: f"({t.strip()})", "in parentheses"),
    (r"\bcode block\b", lambda t, m: f"```\n{t.strip()}\n```", "code block"),
    (r"\bbackticks?\b|\binline code\b", lambda t, m: f"`{t.strip()}`",
     "inline code"),
    (r"\b(?:add|end with|put) an? (?:period|full stop)\b",
     lambda t, m: t.rstrip(" .") + ".", "period added"),
    (r"\b(?:add|end with|make it) an? question(?: mark)?\b",
     lambda t, m: t.rstrip(" .?!") + "?", "question mark added"),
]

_REPLACE = re.compile(
    r"^(?:please\s+)?(?:replace|change|swap)\s+(?:the word\s+)?[\"']?(.+?)[\"']?"
    r"\s+(?:with|to|for|into)\s+[\"']?(.+?)[\"']?[.!]?$", re.I)
_DELETE = re.compile(
    r"^(?:please\s+)?(?:delete|remove|drop)\s+(?:the word\s+|the phrase\s+)?"
    r"[\"']?(.+?)[\"']?[.!]?$", re.I)


def apply_rules(instruction, text):
    """(new_text, description) for instructions the rules understand, or
    (None, None) when the instruction needs the LLM."""
    ins = (instruction or "").strip().strip(".!").strip()
    if not ins or not text:
        return None, None
    m = _REPLACE.match(ins)
    if m:
        old, new = m.group(1).strip(), m.group(2).strip()
        pattern = re.compile(r"(?<!\w)" + re.escape(old) + r"(?!\w)", re.I)
        if pattern.search(text):
            return pattern.sub(new, text), f"replaced “{old}”"
    m = re.match(r"^(?:please\s+)?(?:delete|remove|drop)\s+(?:the\s+)?"
                 r"(last|first) sentence$", ins, re.I)
    if m:
        parts = re.split(r"(?<=[.!?])\s+", text.strip())
        if len(parts) > 1:
            keep = parts[:-1] if m.group(1).lower() == "last" else parts[1:]
            return " ".join(keep), f"removed the {m.group(1).lower()} sentence"
    m = _DELETE.match(ins)
    if m and not re.search(r"\b(?:punctuation|line breaks|bullets|numbers)\b",
                           m.group(1), re.I):
        target = m.group(1).strip()
        pattern = re.compile(r"\s*(?<!\w)" + re.escape(target) + r"(?!\w)",
                             re.I)
        if pattern.search(text):
            out = pattern.sub("", text).strip()
            return re.sub(r"\s+([,.!?])", r"\1", out), \
                f"removed “{target}”"
    for pattern, fn, desc in RULES:
        m = re.search(pattern, ins, re.I)
        if m:
            out = fn(text, m)
            # Keep a trailing newline the user selected (whole lines).
            if text.endswith("\n") and not out.endswith("\n"):
                out += "\n"
            return out, desc
    return None, None


# ----- LLM prompts ----------------------------------------------------------------

def rewrite_prompt(instruction, text):
    return ("You are a precise text editor. Apply the instruction to the "
            "text. Reply with ONLY the edited text: no preamble, no quotes, "
            "no explanation.\n\n"
            f"Instruction: {instruction}\n\nText:\n{text}\n\nEdited text:\n")


def author_prompt(instruction, app_category="general"):
    return ("You write text that the user will paste into "
            f"{'an' if app_category[0] in 'aeiou' else 'a'} "
            f"{app_category.replace('_', ' ')} app. Follow the request. "
            "Reply with ONLY the text to insert: no preamble, no quotes.\n\n"
            f"Request: {instruction}\n\nText:\n")


def polish_prompt(text, preset):
    tone = {"formal": "clear, professional and grammatical",
            "casual": "relaxed and conversational",
            "concise": "as short as possible without losing meaning",
            "standard": "clean and grammatical"}.get(preset, "clean")
    return ("Rewrite this dictated text so it reads "
            f"{tone}. Fix punctuation and obvious speech-recognition "
            "mistakes. Keep the meaning, language and facts unchanged. "
            "Reply with ONLY the rewritten text.\n\n"
            f"Dictated: {text}\n\nRewritten:\n")


_PREAMBLE = re.compile(
    r"^(?:sure[,!.]?\s*)?(?:here(?: is|'s) (?:the |your )?(?:edited |"
    r"rewritten |revised |updated )?(?:text|version)[^:\n]*:\s*)", re.I)


def clean_llm_output(text, original=None):
    """Strip chatty wrappers from a model reply. Returns None when the reply
    is empty or wildly out of proportion to the input."""
    t = (text or "").strip()
    t = _PREAMBLE.sub("", t).strip()
    t = re.sub(r"^```[a-z]*\n?|\n?```$", "", t).strip()
    if len(t) >= 2 and t[0] == t[-1] and t[0] in "\"'“":
        t = t[1:-1].strip()
    if not t:
        return None
    if original and len(original) > 20 and not (
            0.15 <= len(t) / len(original) <= 6):
        return None
    return t
