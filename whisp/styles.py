"""Context-aware writing styles, applied after the basic cleanup pass.

The same words should land differently depending on where you are
speaking: a full, formal sentence in an email; a relaxed message in
Slack; exact words in a terminal; a numbered list when you dictate steps
into your notes. Each app category (see appcontext.CATEGORIES) maps to a
preset, every preset is a fixed set of deterministic rules, and you can
override the preset per category or per app in Settings.

Presets:
  verbatim  exactly what you said: no style changes, no trailing period
  casual    relaxed messages: drops a lone trailing period, spoken emoji
  standard  the classic cleanup only (the default for unknown apps)
  formal    expands chat shorthand (idk, FYI, gonna...), drops verbal
            fillers, always ends with punctuation
  concise   formal, plus removes hedges and filler phrases

Independently of the preset, spoken layout commands work everywhere
("new line", "new paragraph", "bullet point"), self-corrections are
applied ("at 3, no wait, 4" -> "at 4", "scratch that"), spoken times
become digits ("three thirty pm" -> "3:30 PM"), and code apps understand
"at file app dot py" -> "@app.py" and "snake case user id" -> user_id.
"""
import re

PRESETS = ("verbatim", "casual", "standard", "formal", "concise")

DEFAULT_PRESETS = {
    "email": "formal",
    "chat": "casual",
    "ai_chat": "casual",
    "code": "verbatim",
    "notes": "standard",
    "docs": "formal",
    "terminal": "verbatim",
    "general": "standard",
}

# Categories where dictated step sequences become numbered lists.
LIST_CATEGORIES = frozenset({"notes", "docs", "email", "ai_chat", "general"})
# Categories with developer helpers (mentions, identifier casing).
CODE_CATEGORIES = frozenset({"code", "ai_chat", "terminal"})
EMOJI_CATEGORIES = frozenset({"chat", "ai_chat"})

NUMBER_WORDS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
    "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
}

SHORTHAND = {
    "idk": "I do not know", "fyi": "for your information",
    "btw": "by the way", "imo": "in my opinion", "imho": "in my opinion",
    "tbh": "to be honest", "afaik": "as far as I know",
    "gonna": "going to", "wanna": "want to", "gotta": "have to",
    "kinda": "kind of", "sorta": "sort of", "lemme": "let me",
    "gimme": "give me", "dunno": "do not know", "ya know": "you know",
    "pls": "please", "plz": "please", "thx": "thanks", "cuz": "because",
    "coz": "because", "tho": "though",
}

# Verbal fillers dropped by the formal and concise presets. Each needs the
# surrounding commas so meaningful uses ("I like it") are left alone.
_VERBAL_FILLERS = [
    r",?\s*\byou know\b,\s*", r",\s*\blike\b,\s*", r"^\s*so,\s+",
    r"\bbasically,\s*", r"\bliterally,\s*", r",\s*\bI mean\b,\s*",
]
# Extra hedges removed by the concise preset.
_HEDGES = [
    r"\bI think that\s+", r"\bI just wanted to\s+", r"\bI was wondering if\s+",
    r"\bjust\s+", r"\breally\s+", r"\bvery\s+", r"\bactually\s+",
    r"\bkind of\s+", r"\bsort of\s+", r"\bbasically\s+",
    r"\bin order to\b", r"\bat this point in time\b", r"\bdue to the fact that\b",
]
_HEDGE_SUBS = {r"\bin order to\b": "to", r"\bat this point in time\b": "now",
               r"\bdue to the fact that\b": "because"}

EMOJI = {
    "smiley face": "\U0001F642", "smiley emoji": "\U0001F642",
    "smile emoji": "\U0001F642", "laughing emoji": "\U0001F602",
    "crying laughing emoji": "\U0001F602", "heart emoji": "❤️",
    "thumbs up emoji": "\U0001F44D", "fire emoji": "\U0001F525",
    "party emoji": "\U0001F389", "wink emoji": "\U0001F609",
    "sad face": "\U0001F641", "thinking emoji": "\U0001F914",
    "clap emoji": "\U0001F44F", "rocket emoji": "\U0001F680",
    "check mark emoji": "✅", "eyes emoji": "\U0001F440",
}

CODE_EXTS = ("py js ts tsx jsx json md txt css scss html htm java kt go rs "
             "cpp cc c h hpp cs rb php sh ps1 bat yml yaml toml ini cfg sql "
             "vue svelte swift dart lua r ipynb lock env xml csv").split()


def resolve_preset(category, exe, config):
    """Pick the preset for this app: a per-app override wins, then the
    per-category setting, then the built-in default."""
    overrides = {k.lower(): v for k, v in
                 (config.get("app_styles") or {}).items()}
    if exe and exe.lower() in overrides and overrides[exe.lower()] in PRESETS:
        return overrides[exe.lower()]
    per_cat = config.get("style_presets") or {}
    preset = per_cat.get(category) or DEFAULT_PRESETS.get(category, "standard")
    return preset if preset in PRESETS else "standard"


# ----- shared rules -------------------------------------------------------------

def _num(word):
    w = word.lower()
    if w.isdigit():
        return int(w)
    return NUMBER_WORDS.get(w)


_FILLER_ONLY = re.compile(r"^(?:\s|,|oh|no|wait|sorry|ok|okay|actually|um|hmm)*$",
                          re.I)
_SCRATCH = re.compile(r"[,.]?\s*\b(?:scratch that|strike that|delete that)\b"
                      r"[.,!]?\s*", re.I)


def apply_self_corrections(text):
    """'scratch that' deletes what came before it: the clause it ends, or the
    whole previous sentence when it opens a sentence of its own ('Buy milk.
    Actually, scratch that.'). 'at 3, no wait, 4' keeps the corrected number."""
    while True:
        m = _SCRATCH.search(text)
        if not m:
            break
        head = text[:m.start()]
        cut = max(head.rfind("."), head.rfind("!"), head.rfind("?"))
        sentence_start = cut + 1
        if _FILLER_ONLY.match(head[sentence_start:]):
            # Command opens its own sentence: drop the previous sentence too.
            prev = head[:max(cut, 0)]
            pcut = max(prev.rfind("."), prev.rfind("!"), prev.rfind("?"))
            sentence_start = pcut + 1 if cut >= 0 else 0
        text = (text[:sentence_start] + " " + text[m.end():]).strip()
    num = r"(\d{1,4}|" + "|".join(NUMBER_WORDS) + r")"
    text = re.sub(
        num + r"(\s*(?:am|pm|a\.m\.|p\.m\.|o'clock|%|percent)?)[,]?\s+"
        r"(?:no wait|no sorry|sorry|no|actually|i mean|make that|make it)"
        r"[,]?\s+" + num + r"\b",
        lambda m: m.group(3) + (m.group(2) or ""), text, flags=re.I)
    return re.sub(r"\s{2,}", " ", text).strip()


def normalize_times(text):
    """'three pm' -> '3 PM', 'three thirty p.m.' -> '3:30 PM'."""
    word = r"(\d{1,2}|" + "|".join(NUMBER_WORDS) + r")"

    def repl(m):
        h = _num(m.group(1))
        mins = m.group(2)
        if h is None or h > 12:
            return m.group(0)
        out = str(h)
        if mins:
            parts = mins.split()
            total = sum(_num(p) or 0 for p in parts)
            if parts[0].lower() in ("oh", "o"):
                total = _num(parts[-1]) or 0
            if not 0 <= total < 60:
                return m.group(0)
            out += f":{total:02d}"
        raw = m.group(3)
        out += " AM" if raw.lower().startswith("a") else " PM"
        # "p.m." at the end of a sentence also carried its full stop.
        rest = m.string[m.end():]
        if raw.endswith(".") and (not rest.strip() or
                                  rest.lstrip()[:1].isupper()):
            out += "."
        return out

    mins = (r"((?:oh |o )?(?:" + "|".join(NUMBER_WORDS) + r"|\d{2})"
            r"(?: (?:one|two|three|four|five|six|seven|eight|nine))?)")
    return re.sub(r"\b" + word + r"(?:[ :]" + mins + r")?\s*"
                  r"(a\.m\.|p\.m\.|a\.m|p\.m|am|pm)(?![a-z])", repl, text, flags=re.I)


def apply_layout_commands(text):
    """Spoken 'new line', 'new paragraph' and 'bullet point' commands."""
    text = re.sub(r"[,.;]?\s*\bnew paragraph\b[,.;:]?\s*", "\n\n", text,
                  flags=re.I)
    text = re.sub(r"[,.;]?\s*\b(?:new line|next line|line break)\b[,.;:]?\s*",
                  "\n", text, flags=re.I)
    if re.search(r"\bbullet (?:point|item)\b", text, re.I):
        parts = re.split(r"[,.;]?\s*\bbullet (?:point|item)\b[,.;:]?\s*",
                         text, flags=re.I)
        head, items = parts[0].strip(), [p.strip(" ,.;") for p in parts[1:]]
        items = [i[0].upper() + i[1:] for i in items if i]
        lines = ([head] if head else []) + [f"- {i}" for i in items]
        text = "\n".join(lines)
    return _capitalize_lines(text)


def _capitalize_lines(text):
    out = []
    for line in text.split("\n"):
        m = re.match(r"^(\s*(?:[-*]|\d+\.)?\s*)([a-z])", line)
        if m:
            line = m.group(1) + m.group(2).upper() + line[m.end():]
        out.append(line)
    return "\n".join(out)


_FIRST = r"(?:first of all|first(?:ly)?|number one|step one)"
_LATER = (r"(?:second(?:ly)?|third(?:ly)?|fourth|fifth|then|next|after that|"
          r"and then|and finally|finally|lastly|last|number (?:two|three|"
          r"four|five)|step (?:two|three|four|five))")
_STRONG_LATER = r"(?:second|third|finally|lastly|number two|step two)"


def apply_smart_lists(text):
    """Turn 'first X, then Y, and finally Z' into a numbered list. Needs an
    explicit 'first' plus a 'second'/'finally'-style marker, so ordinary
    prose with a stray 'then' is never restructured."""
    if "\n" in text:
        return text
    m = re.search(r"(?:^|[\s,.;:])" + _FIRST + r"\b[,:]?\s+", text, re.I)
    if not m or not re.search(r"\b" + _STRONG_LATER + r"\b",
                              text[m.end():], re.I):
        return text
    intro = text[:m.start()].strip(" ,.;:")
    body = text[m.end():]
    items = re.split(r"[,.;]?\s+\b" + _LATER + r"\b[,:]?\s+", body,
                     flags=re.I)
    items = [i.strip(" ,.;") for i in items if i and i.strip(" ,.;")]
    if len(items) < 2:
        return text
    lines = []
    if intro:
        greeting = intro.lower() in ("hey", "hi", "hello", "so", "okay", "ok")
        lines.append(intro + ("," if greeting else ":"))
    for n, item in enumerate(items, 1):
        lines.append(f"{n}. {item[0].upper()}{item[1:]}")
    return "\n".join(lines)


def apply_emoji(text):
    for phrase in sorted(EMOJI, key=len, reverse=True):
        text = re.sub(r"\s*\b" + re.escape(phrase) + r"\b[.,]?", " " +
                      EMOJI[phrase], text, flags=re.I)
    return text.strip()


_CASE_CMD = re.compile(
    r"\b(snake|camel|pascal|kebab|constant|screaming snake) case\s+"
    r"([A-Za-z0-9]+(?:\s+[A-Za-z0-9]+){0,5}?)(?=[.,;:!?]|$|\s+(?:and|then|"
    r"to|in|of|with|for|from)\b)", re.I)


def to_case(kind, words):
    words = [w.lower() for w in re.findall(r"[A-Za-z0-9]+", words)]
    if not words:
        return ""
    kind = kind.lower()
    if kind == "snake":
        return "_".join(words)
    if kind in ("constant", "screaming snake"):
        return "_".join(words).upper()
    if kind == "kebab":
        return "-".join(words)
    if kind == "pascal":
        return "".join(w.capitalize() for w in words)
    return words[0] + "".join(w.capitalize() for w in words[1:])  # camel


def apply_code_helpers(text):
    """Identifier casing, spoken file extensions and @-mentions."""
    text = _CASE_CMD.sub(lambda m: to_case(m.group(1), m.group(2)), text)
    ext = "|".join(CODE_EXTS)
    # "app dot py" -> "app.py"
    text = re.sub(r"\b([\w\-]+)\s+dot\s+(" + ext + r")\b",
                  lambda m: f"{m.group(1)}.{m.group(2).lower()}", text,
                  flags=re.I)
    # "at file app.py" / "at sign app.py" / "mention file app.py" -> "@app.py"
    text = re.sub(r"\b(?:at|mention|tag)\s+(?:file|sign|the file)\s+"
                  r"([\w\-./]+)", r"@\1", text, flags=re.I)
    text = re.sub(r"(@[\w\-./]*\w)\.(?=\s|$)", r"\1", text)
    return text


def _expand_shorthand(text):
    for short in sorted(SHORTHAND, key=len, reverse=True):
        full = SHORTHAND[short]

        text = re.sub(r"(?<![\w'])" + re.escape(short) + r"(?![\w'])",
                      full, text, flags=re.I)
    return text


_DISCOURSE = (r"for your information|by the way|to be honest|in my opinion|"
              r"as far as I know")


def _formal_commas(text):
    """'Hey for your information I...' -> 'Hey, for your information, I...'."""
    text = re.sub(r"(^|\n)(hey|hi|hello)\s+(?=(?:" + _DISCOURSE +
                  r"|(?-i:[a-z]|I\b)))",
                  lambda m: m.group(1) + m.group(2) + ", ",
                  text, flags=re.I)
    text = re.sub(r"\b(" + _DISCOURSE + r")\s+(?=[A-Za-z])", r"\1, ", text,
                  flags=re.I)
    return text


def _ensure_terminal_punct(text):
    lines = text.split("\n")
    last = lines[-1].rstrip()
    if last and not re.match(r"^\s*(?:[-*]|\d+\.)\s", last) \
            and last[-1] not in ".!?:;।" and last[-1].isalnum():
        lines[-1] = last + "."
    return "\n".join(lines)


def _tidy(text):
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r" +([,.;:!?])", r"\1", text)
    text = re.sub(r"([,;:]){2,}", r"\1", text)
    text = re.sub(r"(^|\n)\s*[,;:]\s*", r"\1", text)
    text = "\n".join(line.strip() for line in text.split("\n"))
    return text.strip()


def _recap_sentences(text):
    text = _capitalize_lines(text)
    return re.sub(r"([.!?]\s+)([a-z])",
                  lambda m: m.group(1) + m.group(2).upper(), text)


# ----- entry point ----------------------------------------------------------------

def apply(text, preset, category="general", config=None):
    """Return `text` rewritten for `preset` in an app of `category`."""
    if not text:
        return text
    config = config or {}
    if config.get("spoken_commands", True):
        text = apply_self_corrections(text)
        text = apply_layout_commands(text)
    if preset != "verbatim":
        text = normalize_times(text)
    if category in CODE_CATEGORIES:
        text = apply_code_helpers(text)
    if (config.get("smart_lists", True) and category in LIST_CATEGORIES
            and preset != "verbatim"):
        text = apply_smart_lists(text)

    if preset == "verbatim":
        if "\n" not in text and text.endswith(".") and not text.endswith(".."):
            text = text[:-1]
        if category == "terminal":
            # Shell input is case-sensitive: undo the sentence capital the
            # cleanup pass added ("Git status" -> "git status").
            m = re.match(r"[A-Z][a-z]+\b", text)
            if m:
                text = text[0].lower() + text[1:]
    elif preset == "casual":
        if category in EMOJI_CATEGORIES:
            text = apply_emoji(text)
        # One sentence with a plain period reads stiff in chat; drop it.
        if ("\n" not in text and text.endswith(".")
                and len(re.findall(r"[.!?](?:\s|$)", text)) == 1):
            text = text[:-1]
    elif preset in ("formal", "concise"):
        text = _expand_shorthand(text)
        for pattern in _VERBAL_FILLERS:
            text = re.sub(pattern, " ", text, flags=re.I)
        if preset == "concise":
            for pattern in _HEDGES:
                text = re.sub(pattern, _HEDGE_SUBS.get(pattern, ""), text,
                              flags=re.I)
        text = _formal_commas(_tidy(text))
        text = _recap_sentences(text)
        text = _ensure_terminal_punct(text)
    return _tidy(text) if preset != "verbatim" else text.strip()
