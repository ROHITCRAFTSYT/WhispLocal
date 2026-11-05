"""Config validation: wrong types fall back to defaults, numbers are clamped,
bad collection entries are dropped, unknown keys survive, and load_config
copes with non-object JSON and a missing default file. Stdlib only."""
import json
import logging
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "whisp"))

import configcheck  # noqa: E402
import configio  # noqa: E402
from configcheck import FALLBACKS, validate_config  # noqa: E402


@pytest.fixture
def defaults():
    with open(os.path.join(ROOT, "config.default.json"), encoding="utf-8") as f:
        return json.load(f)


def test_shipped_defaults_are_valid(defaults):
    clean, problems = validate_config(defaults, defaults)
    assert problems == []
    assert clean == defaults


def test_every_rule_has_a_fallback():
    assert set(configcheck.RULES) <= set(FALLBACKS)


def test_shipped_defaults_cover_the_fallback_values(defaults):
    # A fallback that disagrees with the shipped default would silently
    # change behaviour when config.default.json is missing.
    for key, value in defaults.items():
        if key in FALLBACKS and key not in ("style_presets",):
            assert FALLBACKS[key] == value, key


@pytest.mark.parametrize("key,bad", [
    ("beam_size", "two"), ("beam_size", None), ("beam_size", True),
    ("beam_size", 2.5), ("cpu_threads", [4]), ("insert_mode", "pastee"),
    ("mode", 1), ("overlay_position", "middle"), ("indic_script", "latin"),
    ("hotkey", ""), ("hotkey", None), ("model", "  "), ("sound_cues", "yes"),
    ("save_history", 1), ("language", "english"), ("language", 7),
    ("max_take_seconds", "long"), ("max_take_seconds", float("nan")),
    ("vocabulary", "word"), ("snippets", ["a"]), ("input_device", 3),
])
def test_invalid_value_falls_back_to_default(defaults, key, bad):
    cfg = {**defaults, key: bad}
    clean, problems = validate_config(cfg, defaults)
    assert clean[key] == defaults[key]
    assert len(problems) == 1 and problems[0].startswith(key)


@pytest.mark.parametrize("key,value,expected", [
    ("beam_size", 0, 1), ("beam_size", 99, 10), ("cpu_threads", -2, 0),
    ("max_take_seconds", -5, 0), ("max_take_seconds", 10_000, 3600),
])
def test_out_of_range_numbers_are_clamped(defaults, key, value, expected):
    clean, problems = validate_config({**defaults, key: value}, defaults)
    assert clean[key] == expected
    assert "out of range" in problems[0]


@pytest.mark.parametrize("key,value,expected", [
    ("beam_size", "3", 3), ("beam_size", 4.0, 4), ("language", "EN", "en"),
    ("language", "auto", None), ("language", "", None),
    ("insert_mode", " Type ", "type"), ("input_device", "", None),
    ("input_device", "USB Mic", "USB Mic"),
])
def test_harmless_variants_are_normalised(defaults, key, value, expected):
    clean, problems = validate_config({**defaults, key: value}, defaults)
    assert clean[key] == expected
    assert problems == []


def test_bad_collection_entries_are_dropped(defaults):
    cfg = {**defaults,
           "style_presets": {"email": "formal", "chat": "shouty"},
           "app_styles": {"slack": "casual", "code": 3},
           "vocabulary": ["Kubernetes", 42, None],
           "dictionary": {"teh": "the", "x": None}}
    clean, problems = validate_config(cfg, defaults)
    assert clean["style_presets"] == {"email": "formal"}
    assert clean["app_styles"] == {"slack": "casual"}
    assert clean["vocabulary"] == ["Kubernetes"]
    assert clean["dictionary"] == {"teh": "the"}
    assert len(problems) == 4


def test_unknown_keys_are_kept_and_input_not_mutated(defaults):
    cfg = {**defaults, "future_option": {"x": 1}, "beam_size": "bad"}
    snapshot = json.dumps(cfg, sort_keys=True)
    clean, _ = validate_config(cfg, defaults)
    assert clean["future_option"] == {"x": 1}
    assert json.dumps(cfg, sort_keys=True) == snapshot


def test_missing_keys_are_not_invented():
    clean, problems = validate_config({"model": "small"}, {})
    assert clean == {"model": "small"}
    assert problems == []


def test_non_dict_config_returns_defaults(defaults):
    clean, problems = validate_config(["not", "a", "dict"], defaults)
    assert clean == defaults
    assert problems


def test_fallback_used_when_default_lacks_key():
    clean, _ = validate_config({"insert_mode": "nope"}, {})
    assert clean["insert_mode"] == FALLBACKS["insert_mode"]


def test_enums_match_the_modules_they_mirror():
    styles = pytest.importorskip("styles")
    assert tuple(configcheck.STYLE_PRESETS) == tuple(styles.PRESETS)
    pytest.importorskip("tkinter")
    overlay = pytest.importorskip("overlay")
    assert tuple(configcheck.OVERLAY_POSITIONS) == tuple(overlay.POSITIONS)


# ----- load_config integration ------------------------------------------

@pytest.fixture
def app_dir(tmp_path, defaults):
    (tmp_path / "config.default.json").write_text(
        json.dumps(defaults), encoding="utf-8")
    return tmp_path


def _write_user(app_dir, data):
    text = data if isinstance(data, str) else json.dumps(data)
    (app_dir / "config.json").write_text(text, encoding="utf-8")


def test_load_config_repairs_invalid_values(app_dir, defaults, caplog):
    _write_user(app_dir, {"beam_size": None, "insert_mode": "x", "model": "small"})
    # The app logger does not propagate to root once logging is set up, so
    # attach the capture handler to it directly.
    logger = logging.getLogger("whisp")
    logger.addHandler(caplog.handler)
    try:
        cfg = configio.load_config(str(app_dir))
    finally:
        logger.removeHandler(caplog.handler)
    assert cfg["beam_size"] == defaults["beam_size"]
    assert cfg["insert_mode"] == "paste"
    assert cfg["model"] == "small"
    assert "beam_size" in caplog.text and "insert_mode" in caplog.text
    # The user's file is left as written; only the in-memory copy is fixed.
    raw = json.loads((app_dir / "config.json").read_text(encoding="utf-8"))
    assert raw["beam_size"] is None


@pytest.mark.parametrize("payload", ["[1, 2, 3]", '"just a string"', "42", "null"])
def test_load_config_quarantines_non_object_json(app_dir, defaults, payload):
    _write_user(app_dir, payload)
    cfg = configio.load_config(str(app_dir))
    assert cfg == defaults
    assert (app_dir / "config.json.bad").exists()


def test_load_config_quarantines_non_utf8(app_dir, defaults):
    (app_dir / "config.json").write_bytes(b'{"model": "\xff\xfe"}')
    cfg = configio.load_config(str(app_dir))
    assert cfg == defaults
    assert (app_dir / "config.json.bad").exists()


def test_missing_default_file_uses_builtin(tmp_path, monkeypatch):
    monkeypatch.setattr(configio, "_default_candidates",
                        lambda app_dir: iter([str(tmp_path / "nope.json")]))
    cfg = configio.load_config(str(tmp_path))
    assert cfg["hotkey"] == FALLBACKS["hotkey"]
    assert cfg["model"] == "base"


def test_default_file_found_in_pyinstaller_bundle(tmp_path, monkeypatch, defaults):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "config.default.json").write_text(
        json.dumps({**defaults, "model": "tiny"}), encoding="utf-8")
    app = tmp_path / "app"
    app.mkdir()
    monkeypatch.setattr(sys, "_MEIPASS", str(bundle), raising=False)
    cfg = configio.load_config(str(app))
    assert cfg["model"] == "tiny"


def test_unwritable_app_dir_still_loads(app_dir, monkeypatch, defaults):
    def boom(*_a, **_k):
        raise PermissionError("read-only")
    monkeypatch.setattr(configio, "save_config", boom)
    assert configio.load_config(str(app_dir)) == defaults
