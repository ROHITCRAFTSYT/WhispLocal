"""Post-transcription text cleanup: filler removal, custom dictionary,
spacing/capitalization fixes. This is the local stand-in for Wispr Flow's
cloud LLM formatting pass.
"""
import re

FILLERS = [
    "um", "umm", "ummm", "uh", "uhh", "uhm", "er", "erm", "ah", "ahh",
    "hmm", "hm", "mmm", "mm-hmm", "mhm",
]
_FILLER_RE = re.compile(
    r"(?<![\w'])(" + "|".join(re.escape(f) for f in FILLERS) + r")(?![\w'])[,.]?\s*",
    re.IGNORECASE,
)


def clean(text, config):
    if not text:
        return text

    if config.get("remove_fillers", True):
        text = _FILLER_RE.sub("", text)

    for wrong, right in (config.get("dictionary") or {}).items():
        text = re.sub(
            r"(?<![\w'])" + re.escape(wrong) + r"(?![\w'])",
            right,
            text,
            flags=re.IGNORECASE,
        )

    # Normalize whitespace and punctuation spacing left behind by removals.
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    text = re.sub(r"([,;:!?])(?=[^\s\d])", r"\1 ", text)
    # Space after periods too, but not inside abbreviations like e.g. / a.m.
    # (a period preceded by a single-letter token is part of an abbreviation).
    text = re.sub(r"(?<!\b\w)\.(?=[^\s\d.])", ". ", text)
    text = re.sub(r"([,.!?]){2,}", r"\1", text)
    text = text.lstrip(",.;: ")

    if text and config.get("capitalize_first", True):
        text = text[0].upper() + text[1:]
        # Re-capitalize sentence starts left lowercase by filler removal.
        text = re.sub(
            r"(?<!\be\.g)(?<!\bi\.e)([.!?]\s+)([a-z])",
            lambda m: m.group(1) + m.group(2).upper(),
            text,
        )

    if config.get("strip_trailing_period", False) and text.endswith("."):
        text = text[:-1]

    return text
