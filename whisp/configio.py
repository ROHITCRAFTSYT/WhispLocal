"""Config loading with first-run bootstrap and upgrade safety.

config.default.json ships with the app and defines every key.
config.json is the user's copy (created on first run, never committed).
User values overlay defaults, so upgrades that add new keys never crash.
A corrupt config.json (bad JSON, or JSON that is not an object) is set
aside as config.json.bad and defaults win. Every value is then checked
by configcheck.validate_config: an invalid value falls back to its
default and the problem is written to whisp.log instead of crashing the
app somewhere far from the typo.
"""
import json
import os
import shutil
import sys

from configcheck import FALLBACKS, validate_config
from logsetup import get_logger

DEFAULT_NAME = "config.default.json"
USER_NAME = "config.json"

_log = get_logger("config")


def _default_candidates(app_dir):
    """Where config.default.json may live: next to the app, then inside a
    PyInstaller bundle (sys._MEIPASS), then next to this module."""
    yield os.path.join(app_dir, DEFAULT_NAME)
    bundle = getattr(sys, "_MEIPASS", None)
    if bundle:
        yield os.path.join(bundle, DEFAULT_NAME)
    yield os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), DEFAULT_NAME)


def load_defaults(app_dir):
    """Parse the shipped defaults. A missing or unreadable default file
    falls back to the built-in FALLBACKS rather than failing to start."""
    for path in _default_candidates(app_dir):
        if not os.path.exists(path):
            continue
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
            _log.error("%s is not a JSON object; ignoring it", path)
        except (json.JSONDecodeError, OSError, UnicodeDecodeError) as e:
            _log.error("cannot read %s: %s", path, e)
    _log.warning("%s not found; using built-in defaults", DEFAULT_NAME)
    return dict(FALLBACKS)


def _quarantine(user_path, reason):
    _log.error("config.json is unusable (%s); moved aside as "
               "config.json.bad, using defaults", reason)
    try:
        shutil.copy2(user_path, user_path + ".bad")
    except OSError as e:
        _log.error("could not back up config.json: %s", e)


def load_config(app_dir):
    defaults = load_defaults(app_dir)
    cfg = dict(defaults)
    user_path = os.path.join(app_dir, USER_NAME)
    if os.path.exists(user_path):
        try:
            with open(user_path, encoding="utf-8") as f:
                user = json.load(f)
        except (json.JSONDecodeError, OSError, UnicodeDecodeError) as e:
            _quarantine(user_path, e)
        else:
            if isinstance(user, dict):
                cfg.update(user)
            else:
                _quarantine(user_path, f"top level is {type(user).__name__}"
                            ", not an object")
    else:
        try:
            save_config(app_dir, cfg)
        except OSError as e:
            # A read-only install folder must not stop the app starting.
            _log.error("could not create config.json: %s", e)
    cfg, problems = validate_config(cfg, defaults)
    for p in problems:
        _log.warning("config: %s", p)
    return cfg


def save_config(app_dir, cfg):
    tmp = os.path.join(app_dir, USER_NAME + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
    os.replace(tmp, os.path.join(app_dir, USER_NAME))
