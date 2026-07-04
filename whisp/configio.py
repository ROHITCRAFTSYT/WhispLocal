"""Config loading with first-run bootstrap and upgrade safety.

config.default.json ships with the app and defines every key.
config.json is the user's copy (created on first run, never committed).
User values overlay defaults, so upgrades that add new keys never crash.
A corrupt config.json is set aside as config.json.bad and defaults win.
"""
import json
import os
import shutil


def load_config(app_dir):
    default_path = os.path.join(app_dir, "config.default.json")
    user_path = os.path.join(app_dir, "config.json")
    with open(default_path, encoding="utf-8") as f:
        cfg = json.load(f)
    if os.path.exists(user_path):
        try:
            with open(user_path, encoding="utf-8") as f:
                cfg.update(json.load(f))
        except (json.JSONDecodeError, OSError):
            try:
                shutil.copy2(user_path, user_path + ".bad")
            except OSError:
                pass
    else:
        save_config(app_dir, cfg)
    return cfg


def save_config(app_dir, cfg):
    tmp = os.path.join(app_dir, "config.json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
    os.replace(tmp, os.path.join(app_dir, "config.json"))
