"""Model loading: offline-first (cache before network), a classified,
user-facing ModelLoadError on failure, retry after a failure, and no crash
on empty audio or garbage decode settings. faster_whisper is replaced by a
fake module, so no model, network or numpy is needed."""
import os
import sys
import types

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "whisp"))

import transcriber as tr  # noqa: E402
from transcriber import ModelLoadError, Transcriber, explain_load_error  # noqa: E402


class LocalEntryNotFoundError(Exception):
    """Stand-in for huggingface_hub's 'not in cache' error."""


class FakeWhisper:
    """Records constructor calls; behaviour scripted per test."""
    calls = []
    script = []  # list of exceptions/None, consumed per construction

    def __init__(self, name, **kwargs):
        FakeWhisper.calls.append((name, kwargs))
        outcome = FakeWhisper.script.pop(0) if FakeWhisper.script else None
        if outcome is not None:
            raise outcome
        self.name = name


@pytest.fixture
def fake_fw(monkeypatch):
    FakeWhisper.calls = []
    FakeWhisper.script = []
    mod = types.ModuleType("faster_whisper")
    mod.WhisperModel = FakeWhisper
    monkeypatch.setitem(sys.modules, "faster_whisper", mod)
    return FakeWhisper


def make(**cfg):
    return Transcriber({"model": "base", "cpu_threads": 2, **cfg})


def test_cached_model_loads_without_network(fake_fw):
    t = make()
    model = t.load()
    assert isinstance(model, FakeWhisper)
    assert len(fake_fw.calls) == 1
    name, kwargs = fake_fw.calls[0]
    assert name == "base" and kwargs["local_files_only"] is True
    assert kwargs["compute_type"] == "int8" and kwargs["cpu_threads"] == 2
    assert t.loaded and t.last_error is None


def test_uncached_model_is_downloaded_once(fake_fw):
    fake_fw.script = [LocalEntryNotFoundError("not cached"), None]
    t = make()
    t.load()
    assert [kw.get("local_files_only", False) for _, kw in fake_fw.calls] == [True, False]
    t.load()  # stays resident: no further constructions
    assert len(fake_fw.calls) == 2


def test_offline_first_run_raises_friendly_error(fake_fw):
    fake_fw.script = [LocalEntryNotFoundError("not cached"),
                      ConnectionError("Max retries exceeded with url")]
    t = make()
    with pytest.raises(ModelLoadError) as info:
        t.load()
    err = info.value
    assert "not downloaded" in str(err)
    assert "internet" in err.hint
    assert isinstance(err.__cause__, ConnectionError)
    assert t.last_error is err and not t.loaded


def test_failure_is_retried_on_next_call(fake_fw):
    fake_fw.script = [LocalEntryNotFoundError("x"), ConnectionError("offline"),
                      LocalEntryNotFoundError("x"), None]
    t = make()
    with pytest.raises(ModelLoadError):
        t.load()
    assert t.load() is not None
    assert t.last_error is None


def test_local_model_dir_is_not_downloaded(fake_fw, tmp_path):
    fake_fw.script = [RuntimeError("Unable to open file 'model.bin'")]
    t = make(model=str(tmp_path))
    with pytest.raises(ModelLoadError) as info:
        t.load()
    assert len(fake_fw.calls) == 1  # no download attempt for a folder
    assert "damaged" in str(info.value)


def test_missing_engine_is_reported(monkeypatch):
    monkeypatch.setitem(sys.modules, "faster_whisper", None)  # import fails
    with pytest.raises(ModelLoadError) as info:
        make().load()
    assert "speech engine" in str(info.value)
    assert "setup.bat" in info.value.hint


def test_transcribe_raises_model_error_not_raw(fake_fw):
    fake_fw.script = [LocalEntryNotFoundError("x"),
                      ValueError("Invalid model size 'huge', expected one of: tiny")]
    with pytest.raises(ModelLoadError) as info:
        make(model="huge").transcribe([0.0] * 16000)
    assert "Unknown speech model" in str(info.value)


def test_empty_audio_skips_the_model(fake_fw):
    t = make()
    assert t.transcribe([]) == ("", None, 0.0)
    assert t.transcribe(None) == ("", None, 0.0)
    assert fake_fw.calls == []  # never even loaded


@pytest.mark.parametrize("beam,threads", [(None, None), ("x", "y"), (0, -3)])
def test_garbage_settings_do_not_crash(beam, threads):
    t = Transcriber({"model": None, "beam_size": beam, "cpu_threads": threads})
    assert t.model_name == "base"
    assert t.beam_size >= 1
    assert t.cpu_threads >= 1


@pytest.mark.parametrize("exc,needle", [
    (MemoryError(), "memory"),
    (RuntimeError("std::bad_alloc"), "memory"),
    (OSError(28, "No space left on device"), "disk space"),
    (ValueError("Invalid model size 'x'"), "Unknown speech model"),
    (Exception("RepositoryNotFoundError: 401 Client Error"), "Unknown speech model"),
    (ConnectionError("Failed to establish a new connection"), "not downloaded"),
    (TimeoutError("timed out"), "not downloaded"),
    (ImportError("DLL load failed while importing _ext"), "speech engine"),
    (RuntimeError("Unable to open file 'model.bin' in model '/x'"), "damaged"),
    (KeyError("weird"), "Could not load"),
])
def test_error_classification(exc, needle):
    err = explain_load_error("small", exc)
    assert isinstance(err, ModelLoadError)
    assert needle in str(err)
    assert err.user_message().startswith(str(err))


def test_known_models_cover_settings_choices():
    settings_models = ["tiny", "tiny.en", "base", "base.en", "small", "small.en"]
    assert set(settings_models) <= set(tr.KNOWN_MODELS)
