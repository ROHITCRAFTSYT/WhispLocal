"""History search and usage stats over history.jsonl.

Search ranks entries with BM25 (the classic full-text ranking), so
"launch review" finds the dictation that mentions both words before the
ones that mention either. Stats summarise how much you dictate: words,
speaking speed, time saved compared with typing, and your daily streak.
"""
import datetime as _dt
import json
import math
import os
import re
from collections import Counter

TYPING_WPM = 40  # average typing speed used for "time saved"


def load(path):
    """Entries oldest first; corrupt lines are skipped."""
    entries = []
    if not os.path.exists(path):
        return entries
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return entries


def tokenize(text):
    return re.findall(r"\w+", (text or "").lower())


def search(entries, query="", app=None, task=None, limit=200):
    """Matching entries, best first. An empty query lists the newest."""
    pool = [e for e in entries
            if (not app or e.get("app") == app)
            and (not task or e.get("task", "transcribe") == task)]
    terms = tokenize(query)
    if not terms:
        return list(reversed(pool))[:limit]
    docs = [tokenize(e.get("text", "")) for e in pool]
    n = len(docs) or 1
    avg = (sum(len(d) for d in docs) / n) or 1.0
    df = Counter(t for d in docs for t in set(d))
    k1, b = 1.5, 0.75
    scored = []
    for idx, (entry, doc) in enumerate(zip(pool, docs)):
        tf = Counter(doc)
        score = 0.0
        for t in terms:
            if not tf[t]:
                # Prefix match ("deplo" finds "deploy") at reduced weight.
                hits = sum(c for w, c in tf.items() if w.startswith(t))
                if not hits:
                    continue
                freq, weight = hits, 0.5
            else:
                freq, weight = tf[t], 1.0
            idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
            score += weight * idf * freq * (k1 + 1) / (
                freq + k1 * (1 - b + b * len(doc) / avg))
        if score > 0:
            scored.append((score, idx, entry))
    scored.sort(key=lambda s: (-s[0], -s[1]))  # ties: newest first
    return [e for _, _, e in scored[:limit]]


def apps(entries):
    """Apps seen in history, most used first."""
    counts = Counter(e.get("app") for e in entries if e.get("app"))
    return [a for a, _ in counts.most_common()]


def _day(entry):
    try:
        return _dt.datetime.strptime(entry.get("ts", "")[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def stats(entries, today=None, typing_wpm=TYPING_WPM):
    """Summary numbers for the Stats window."""
    today = today or _dt.date.today()
    dictations = [e for e in entries
                  if e.get("task", "transcribe") in ("transcribe", "translate")]
    words = [len(e.get("text", "").split()) for e in dictations]
    total_words = sum(words)
    audio_s = sum(float(e.get("audio_s", 0) or 0) for e in dictations)
    week_ago = today - _dt.timedelta(days=6)
    words_7d = sum(w for e, w in zip(dictations, words)
                   if (_day(e) or _dt.date.min) >= week_ago)
    wpm = total_words / (audio_s / 60) if audio_s > 0 else 0.0
    typed_min = total_words / typing_wpm if typing_wpm else 0.0
    saved_min = max(0.0, typed_min - audio_s / 60)

    days = {_day(e) for e in entries if _day(e)}
    streak, d = 0, today
    if d not in days:  # today not used yet: the streak can still be alive
        d -= _dt.timedelta(days=1)
    while d in days:
        streak += 1
        d -= _dt.timedelta(days=1)

    return {
        "dictations": len(dictations),
        "commands": sum(1 for e in entries if e.get("task") == "command"),
        "edits": sum(1 for e in entries if e.get("task") == "edit"),
        "total_words": total_words,
        "words_7d": words_7d,
        "wpm": round(wpm),
        "minutes_saved": round(saved_min),
        "streak_days": streak,
        "top_apps": Counter(e.get("app") for e in dictations
                            if e.get("app")).most_common(5),
    }
