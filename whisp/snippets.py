"""Spoken shortcuts: say a trigger phrase, get a saved snippet.

Configure them in Settings as `trigger => expansion` lines, for example
`my email => rohit@example.com` or `sign off => Thanks,\\nRohit`.

- Saying only the trigger ("my email") inserts the expansion verbatim.
- A trigger of two or more words is also expanded inside a sentence
  ("send it to my email please"). Single-word triggers only fire on their
  own, so a common word can never be replaced by accident.
- Expansions may use {date}, {time} and {day} placeholders, and \\n for a
  line break.
"""
import re
import time


def _norm(text):
    return re.sub(r"[^\w\s]", "", (text or "").lower()).split()


def render(expansion, now=None):
    now = now or time.localtime()
    out = expansion.replace("\\n", "\n")
    return (out.replace("{date}", time.strftime("%Y-%m-%d", now))
               .replace("{time}", time.strftime("%H:%M", now))
               .replace("{day}", time.strftime("%A", now)))


def expand(text, snippets, now=None):
    """Return (text, exact). exact=True when the whole dictation was a
    trigger: the caller should insert it as is, skipping style rules."""
    if not text or not snippets:
        return text, False
    words = _norm(text)
    for trigger, expansion in snippets.items():
        if words and words == _norm(trigger):
            return render(expansion, now), True
    out = text
    for trigger in sorted(snippets, key=len, reverse=True):
        tw = _norm(trigger)
        if len(tw) < 2:
            continue
        pattern = (r"(?<![\w])" + r"[\s,]+".join(re.escape(w) for w in tw)
                   + r"(?![\w])")
        expansion = render(snippets[trigger], now)
        out = re.sub(pattern, lambda m, e=expansion: e, out, flags=re.I)
    return out, False


def parse_lines(text):
    """Settings text box -> dict. Lines look like `trigger => expansion`."""
    result = {}
    for line in (text or "").splitlines():
        if "=>" in line:
            trigger, _, expansion = line.partition("=>")
            if trigger.strip() and expansion.strip():
                result[trigger.strip()] = expansion.strip()
    return result
