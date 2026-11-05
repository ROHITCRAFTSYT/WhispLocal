"""Validation for config.json.

config.json is hand-editable, so it can contain anything: a typo'd
enum ("insert_mode": "pastee"), a wrong type ("beam_size": "two"), a null
where a number belongs, or a value far out of range. Before this module
those reached the code as-is and crashed far from the cause (int(None)
inside the Transcriber, a KeyError in the overlay, ...).

validate_config() checks every known key against a rule and returns a
cleaned copy plus a list of human-readable problems:

- wrong type or unknown choice -> the shipped default for that key;
- a number outside its range   -> clamped into the range;
- a dict/list with some bad entries -> the bad entries are dropped;
- unknown keys                 -> kept untouched (forward compatibility,
  and keys written by newer versions are not lost).

It never raises and never mutates its input. Stdlib only.
"""
import re

# Mirrors overlay.POSITIONS (overlay.py imports tkinter, which this
# module must not need). tests/test_configcheck.py keeps them in sync.
OVERLAY_POSITIONS = ("bottom-center", "bottom-right", "bottom-left",
                     "top-center", "top-right", "top-left", "center")
# Mirrors styles.PRESETS (kept in sync by the same test).
STYLE_PRESETS = ("verbatim", "casual", "standard", "formal", "concise")

_LANG_RE = re.compile(r"^[a-z]{2,3}$")

_BOOL_KEYS = (
    "voice_replies", "auto_select_mic", "live_partials", "restore_clipboard",
    "remove_fillers", "capitalize_first", "strip_trailing_period",
    "sound_cues", "save_history", "adaptive_learning", "context_styles",
    "read_context", "spoken_commands", "smart_lists", "retain_last_take",
    "llm_enabled", "llm_polish", "bridge_enabled",
)

# Fallbacks for keys that may be missing from config.default.json (an old
# or partial default file). The shipped default file wins when present.
FALLBACKS = {
    "hotkey": "right ctrl",
    "translate_hotkey": "",
    "command_hotkey": "",
    "edit_hotkey": "",
    "mode": "dictate",
    "model": "base",
    "language": None,
    "indic_script": "native",
    "beam_size": 2,
    "cpu_threads": 0,
    "input_device": None,
    "insert_mode": "paste",
    "overlay_position": "bottom-center",
    "obsidian_vault": "",
    "llm_model_path": "",
    "max_take_seconds": 360,
    "style_presets": {},
    "app_styles": {},
    "snippets": {},
    "vocabulary": [],
    "dictionary": {},
    "bridge_allowed_ext_ids": [],
    **{k: True for k in _BOOL_KEYS},
}
for _k in ("live_partials", "strip_trailing_period", "llm_enabled",
           "llm_polish"):
    FALLBACKS[_k] = False


class _Invalid(Exception):
    """Raised by a rule: the value cannot be used; use the default."""


def _is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _int_in(lo, hi):
    def rule(v):
        if isinstance(v, str) and v.strip().lstrip("-").isdigit():
            v = int(v.strip())  # "3" from a hand edit is clearly 3
        if not _is_number(v) or v != v:  # rejects bool, None, NaN
            raise _Invalid("expected a whole number")
        if isinstance(v, float):
            if not v.is_integer():
                raise _Invalid("expected a whole number")
            v = int(v)
        return min(hi, max(lo, v))
    rule.describe = f"a whole number {lo}-{hi}"
    return rule


def _num_in(lo, hi):
    def rule(v):
        if not _is_number(v) or v != v or v in (float("inf"), float("-inf")):
            raise _Invalid("expected a number")
        return min(hi, max(lo, v))
    rule.describe = f"a number {lo}-{hi}"
    return rule


def _bool(v):
    if isinstance(v, bool):
        return v
    raise _Invalid("expected true or false")


def _choice(*options):
    def rule(v):
        if isinstance(v, str) and v.strip().lower() in options:
            return v.strip().lower()
        raise _Invalid(f"expected one of {', '.join(options)}")
    return rule


def _str(allow_empty=True):
    def rule(v):
        if not isinstance(v, str):
            raise _Invalid("expected text")
        if not allow_empty and not v.strip():
            raise _Invalid("must not be empty")
        return v
    return rule


def _optional_str(v):
    """None or text; empty text normalises to None."""
    if v is None:
        return None
    if isinstance(v, str):
        return v if v.strip() else None
    raise _Invalid("expected text or null")


def _language(v):
    """None (auto-detect) or a Whisper language code such as "en"."""
    if v is None:
        return None
    if isinstance(v, str):
        code = v.strip().lower()
        if code in ("", "auto"):
            return None
        if _LANG_RE.match(code):
            return code
    raise _Invalid('expected a language code like "en" or null for auto')


def _str_dict(value_rule=None):
    def rule(v, problems, key):
        if not isinstance(v, dict):
            raise _Invalid("expected an object")
        out = {}
        for k, val in v.items():
            if not isinstance(k, str) or not isinstance(val, str):
                problems.append(f"{key}: dropped non-text entry {k!r}")
                continue
            if value_rule is not None and val not in value_rule:
                problems.append(
                    f"{key}: dropped {k!r} (unknown value {val!r})")
                continue
            out[k] = val
        return out
    rule.collection = True
    return rule


def _str_list(v, problems, key):
    if not isinstance(v, list):
        raise _Invalid("expected a list")
    out = [x for x in v if isinstance(x, str)]
    if len(out) != len(v):
        problems.append(f"{key}: dropped {len(v) - len(out)} non-text item(s)")
    return out


_str_list.collection = True

RULES = {
    "hotkey": _str(allow_empty=False),
    "translate_hotkey": _str(),
    "command_hotkey": _str(),
    "edit_hotkey": _str(),
    "mode": _choice("dictate", "command"),
    "model": _str(allow_empty=False),
    "language": _language,
    "indic_script": _choice("native", "roman"),
    "beam_size": _int_in(1, 10),
    "cpu_threads": _int_in(0, 256),
    "input_device": _optional_str,
    "insert_mode": _choice("paste", "type"),
    "overlay_position": _choice(*OVERLAY_POSITIONS),
    "obsidian_vault": _str(),
    "llm_model_path": _str(),
    "max_take_seconds": _num_in(0, 3600),
    "style_presets": _str_dict(STYLE_PRESETS),
    "app_styles": _str_dict(STYLE_PRESETS),
    "snippets": _str_dict(),
    "dictionary": _str_dict(),
    "vocabulary": _str_list,
    "bridge_allowed_ext_ids": _str_list,
    **{k: _bool for k in _BOOL_KEYS},
}


def validate_config(cfg, defaults=None):
    """Return ``(clean_cfg, problems)``.

    ``defaults`` (normally the parsed config.default.json) supplies the
    replacement for an invalid value; FALLBACKS covers keys it lacks.
    Keys that are absent from ``cfg`` are not added — callers merge
    defaults first (see configio.load_config).
    """
    if not isinstance(cfg, dict):
        return dict(defaults or {}), ["config is not a JSON object"]
    defaults = defaults if isinstance(defaults, dict) else {}
    out = dict(cfg)
    problems = []
    for key, rule in RULES.items():
        if key not in cfg:
            continue
        value = cfg[key]
        try:
            if getattr(rule, "collection", False):
                clean = rule(value, problems, key)
            else:
                clean = rule(value)
        except _Invalid as e:
            fallback = defaults.get(key, FALLBACKS.get(key))
            problems.append(
                f"{key}: {value!r} is invalid ({e}); using {fallback!r}")
            out[key] = fallback
            continue
        if _is_number(value) and _is_number(clean) and clean != value:
            problems.append(f"{key}: {value!r} is out of range; using {clean!r}")
        out[key] = clean
    return out, problems
