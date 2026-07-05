"""Local personalization: learns from every dictation, entirely on disk.

Three things are learned, all stored in adaptive.json next to the app:

- word frequencies from accepted dictations. The most frequent uncommon
  words are passed to faster-whisper as hotwords, biasing recognition
  toward the user's real vocabulary (names, jargon, project terms).
- corrections the user teaches through the History window. A word-level
  diff of original vs corrected text becomes dictionary entries that are
  applied to future transcriptions automatically.
- language usage. Whisper's per-utterance language detection is
  unreliable on short clips; once a clear preference exists (for example
  Hindi and English), low-confidence detections are retried pinned to
  the user's dominant language.

No network, no telemetry. Delete adaptive.json to reset everything.
"""
import difflib
import json
import os
import threading
from collections import Counter

FILE_NAME = "adaptive.json"
MAX_WORDS = 800
HOTWORD_COUNT = 40
MIN_OCCURRENCES = 3

# Common words that would waste hotword slots.
STOPWORDS = frozenset("""
the and for that this with have from they will would there their what
about which when make like just know take into your some could them
then than been were said each she how their if we do a i is it in on
at of to as be or by an so no not but was are you he his her its our
out up down over under can may might must shall should did does done
going go got get very really then also because
""".split())

_PUNCT = ".,;:!?\"'()[]{}«»।॥"  # includes Devanagari danda


def _tokenize(text):
    """Split into candidate vocabulary words. Whitespace-based so scripts
    with combining marks (Devanagari, Arabic...) stay intact; Python's
    regex \\w would split words at every vowel sign."""
    words = []
    for raw in text.split():
        word = raw.strip(_PUNCT)
        if (len(word) >= 4
                and any(c.isalpha() for c in word)
                and not any(c.isdigit() for c in word)):
            words.append(word)
    return words


class Adaptive:
    def __init__(self, app_dir, enabled=True):
        self.path = os.path.join(app_dir, FILE_NAME)
        self.enabled = enabled
        self._lock = threading.Lock()
        self.word_counts = Counter()
        self.lang_counts = Counter()
        self.learned_dictionary = {}
        self.action_counts = Counter()   # kind of command -> count
        self.app_counts = Counter()      # app opened/closed -> count
        self.topic_counts = Counter()    # search/lookup topics -> count
        self.command_total = 0
        self._load()

    # ----- persistence -----------------------------------------------------
    def _load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
            self.word_counts = Counter(data.get("word_counts", {}))
            self.lang_counts = Counter(data.get("lang_counts", {}))
            self.learned_dictionary = data.get("learned_dictionary", {})
            self.action_counts = Counter(data.get("action_counts", {}))
            self.app_counts = Counter(data.get("app_counts", {}))
            self.topic_counts = Counter(data.get("topic_counts", {}))
            self.command_total = int(data.get("command_total", 0))
        except (OSError, json.JSONDecodeError, ValueError):
            pass

    def _save(self):
        data = {
            "word_counts": dict(self.word_counts),
            "lang_counts": dict(self.lang_counts),
            "learned_dictionary": self.learned_dictionary,
            "action_counts": dict(self.action_counts),
            "app_counts": dict(self.app_counts),
            "topic_counts": dict(self.topic_counts),
            "command_total": self.command_total,
        }
        tmp = self.path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
            os.replace(tmp, self.path)
        except OSError:
            pass

    # ----- learning ---------------------------------------------------------
    def record(self, text, language):
        """Called after each accepted dictation."""
        if not self.enabled or not text:
            return
        with self._lock:
            for word in _tokenize(text):
                lw = word.lower()
                if lw not in STOPWORDS:
                    self.word_counts[lw] += 1
            if language:
                self.lang_counts[language] += 1
            if len(self.word_counts) > MAX_WORDS:
                self.word_counts = Counter(
                    dict(self.word_counts.most_common(MAX_WORDS // 2)))
            self._save()

    def learn_correction(self, original, corrected):
        """Word-diff a user correction and remember the substitutions.
        Returns the number of new dictionary entries learned."""
        strip = ".,;:!?\"'()"
        o_words = original.split()
        c_words = corrected.split()
        o_norm = [w.strip(strip).lower() for w in o_words]
        c_norm = [w.strip(strip).lower() for w in c_words]
        learned = 0
        sm = difflib.SequenceMatcher(None, o_norm, c_norm)
        with self._lock:
            for tag, i1, i2, j1, j2 in sm.get_opcodes():
                if tag != "replace" or (i2 - i1) != (j2 - j1):
                    continue
                for k in range(i2 - i1):
                    wrong = o_norm[i1 + k]
                    right = c_words[j1 + k].strip(strip)
                    if len(wrong) < 2 or not right or wrong == right.lower():
                        continue
                    self.learned_dictionary[wrong] = right
                    # Make the corrected form a strong hotword too.
                    self.word_counts[right.lower()] += 5
                    learned += 1
            if learned:
                self._save()
        return learned

    def record_command(self, kind, label=None, topic=None):
        """Called after each executed voice command, to learn habits."""
        if not self.enabled:
            return
        with self._lock:
            self.command_total += 1
            self.action_counts[kind] += 1
            if label:
                self.app_counts[label.lower()] += 1
                # Learn app names as hotwords so they transcribe better later.
                for word in _tokenize(label):
                    self.word_counts[word.lower()] += 1
            if topic:
                for word in _tokenize(topic):
                    lw = word.lower()
                    if lw not in STOPWORDS:
                        self.topic_counts[lw] += 1
            self._save()

    def profile_summary(self):
        """A small dict describing what has been learned about the user."""
        with self._lock:
            return {
                "commands_total": self.command_total,
                "dictations_by_language": dict(self.lang_counts.most_common()),
                "top_apps": self.app_counts.most_common(10),
                "top_actions": self.action_counts.most_common(10),
                "top_topics": self.topic_counts.most_common(12),
                "corrections": dict(self.learned_dictionary),
                "vocabulary_size": len(self.word_counts),
            }

    # ----- recall -------------------------------------------------------------
    def hotwords(self):
        """A string of the user's characteristic vocabulary, or None."""
        if not self.enabled:
            return None
        with self._lock:
            words = [w for w, n in self.word_counts.most_common(HOTWORD_COUNT * 2)
                     if n >= MIN_OCCURRENCES][:HOTWORD_COUNT]
            # Learned corrections carry the user's intended casing; prefer
            # that form over the lowercase frequency entry.
            for v in self.learned_dictionary.values():
                lv = v.lower()
                if lv in words:
                    words[words.index(lv)] = v
                elif v not in words:
                    words.append(v)
        return " ".join(words) if words else None

    def preferred_language(self):
        """The user's dominant dictation language, once it is clear."""
        if not self.enabled:
            return None
        with self._lock:
            total = sum(self.lang_counts.values())
            if total < 5:
                return None
            lang, count = self.lang_counts.most_common(1)[0]
        return lang if count / total >= 0.5 else None
