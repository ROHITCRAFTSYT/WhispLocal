"""Fit a dictation into the text already around the caret.

Whisper returns every clip as a fresh sentence: capitalised, no leading
space. Dropped into the middle of a line that reads wrong ("I said
hello.Then" or "and then I. Went home"). When the text before the caret
is known, this adds the missing space and continues a sentence in
lowercase instead of starting a new one.
"""
import re

# Words that are safe to lowercase when continuing a sentence. Anything
# else (names, brands, acronyms) keeps its capital, so the planner never
# turns "Rohit" or "GitHub" into lowercase.
COMMON_WORDS = frozenset("""
a about after again all also although an and another any are as at
be because been before being both but by can could did do does doing
during each either even every few for from had has have having he her
here hers him his how however if in into is it its just later let like
maybe me more most my neither no nor not now of off on once only or
other our out over perhaps please probably really she should since so
some still such than that the their them then there these they this
those though through thus to too under unless until up us very was we
well were what when where whether which while who whom whose why will
with within without would yes yet you your actually anyway basically
besides finally first second third next instead meanwhile otherwise
plus regardless similarly therefore today tomorrow tonight yesterday
""".split())

# A dictation that starts with one of these attaches without a space.
_NO_SPACE_BEFORE = set(".,;:!?)]}%'’”")
# Text before the caret ending in one of these takes no extra space.
_OPENERS = set("([{\"'‘“/\\-@#$₹\n\t ")
_SENTENCE_END = re.compile(r"[.!?।॥]['\")\]’”]*\s*$")


def _first_word(text):
    m = re.match(r"[A-Za-z][A-Za-z']*", text)
    return m.group(0) if m else ""


def plan(text, before, keep_caps=()):
    """Return `text` adjusted to follow `before` (text left of the caret).

    before=None means the context is unknown: the text is returned as is.
    keep_caps: extra words (vocabulary, proper nouns) never lowercased.
    """
    if not text or before is None:
        return text
    stripped = before.rstrip(" \t")

    # Capitalisation: a new sentence starts at the beginning of the field,
    # after a line break, or after sentence-ending punctuation.
    new_sentence = (not stripped or stripped.endswith("\n")
                    or bool(_SENTENCE_END.search(stripped)))
    if new_sentence:
        if text[0].islower():
            text = text[0].upper() + text[1:]
    else:
        word = _first_word(text)
        keep = {k.lower() for k in keep_caps}
        if (word and word != "I" and not word.startswith("I'")
                and word[0].isupper() and word[1:] == word[1:].lower()
                and word.lower() in COMMON_WORDS
                and word.lower() not in keep):
            text = text[0].lower() + text[1:]

    # Spacing: join with a single space unless either side supplies one or
    # the dictation starts with closing punctuation.
    if before and before[-1] not in _OPENERS and text[0] not in _NO_SPACE_BEFORE:
        text = " " + text
    return text
