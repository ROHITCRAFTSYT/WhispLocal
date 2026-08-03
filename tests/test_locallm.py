"""Tests for the optional local-LLM fallback.

Covers the LocalLLM adapter (backend detection, sanitize, timeout, load
errors) and — critically — the latency contract: the model is only ever
consulted after every fast path fails, on a background thread, so normal
commands never touch it.
"""
import os
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "whisp"))

import commands
from commands import CommandEngine
from locallm import LocalLLM, build_prompt, sanitize


class SyncThread:
    """Runs the engine's background LLM attempt inline so tests are
    deterministic — the production code still spawns a real thread."""

    def __init__(self, *args, **kwargs):
        self._target = kwargs.get("target")
        self._args = kwargs.get("args", ())

    def start(self):
        if self._target:
            self._target(*self._args)


def stub_keyboard():
    patcher = mock.patch.dict(sys.modules, {"keyboard": mock.MagicMock()})
    patcher.start()
    return sys.modules["keyboard"]


class SanitizeTests(unittest.TestCase):
    def test_empty_and_none(self):
        self.assertIsNone(sanitize(""))
        self.assertIsNone(sanitize("   "))
        self.assertIsNone(sanitize("NONE"))
        self.assertIsNone(sanitize(" none "))
        self.assertIsNone(sanitize('"NONE"'))

    def test_strips_labels_and_fences(self):
        self.assertEqual(sanitize('"open chrome"'), "open chrome")
        self.assertEqual(sanitize("```open chrome```"), "open chrome")
        self.assertEqual(sanitize("Command: open chrome"), "open chrome")
        self.assertEqual(sanitize("command - open chrome"), "open chrome")

    def test_strips_trailing_punctuation(self):
        self.assertEqual(sanitize("what time is it?"), "what time is it")
        self.assertEqual(sanitize("volume up."), "volume up")


class BuildPromptTests(unittest.TestCase):
    def test_prompt_embeds_phrase_and_rules(self):
        p = build_prompt("floob the zarbo")
        self.assertIn("floob the zarbo", p)
        self.assertIn("NONE", p)
        self.assertIn("open chrome", p)


class LocalLLMTests(unittest.TestCase):
    def test_unconfigured_is_inert(self):
        llm = LocalLLM("")
        self.assertFalse(llm.configured())
        self.assertIsNone(llm.understand("anything at all"))
        self.assertEqual(llm.backend, "llama")  # nothing configured

    def test_backend_detection(self):
        self.assertEqual(LocalLLM("models/small.gguf").backend, "llama")
        self.assertEqual(LocalLLM("models/small.onnx").backend, "onnx")
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(LocalLLM(d).backend, "onnx")

    def test_llama_backend_restates_phrase(self):
        fake = mock.MagicMock()
        fake.Llama.return_value.create_completion.return_value = {
            "choices": [{"text": "open chrome"}]}
        with mock.patch.dict(sys.modules, {"llama_cpp": fake}):
            llm = LocalLLM("models/small.gguf")
            self.assertEqual(llm.understand("floob the zarbo"), "open chrome")
        # The prompt given to the model contains the novel phrase.
        prompt = fake.Llama.return_value.create_completion.call_args.kwargs[
            "prompt"]
        self.assertIn("floob the zarbo", prompt)

    def test_llama_none_answer_is_none(self):
        fake = mock.MagicMock()
        fake.Llama.return_value.create_completion.return_value = {
            "choices": [{"text": "NONE"}]}
        with mock.patch.dict(sys.modules, {"llama_cpp": fake}):
            llm = LocalLLM("models/small.gguf")
            self.assertIsNone(llm.understand("the sky is blue"))

    def test_timeout_abandons_slow_model(self):
        fake = mock.MagicMock()

        def slow(*_a, **_k):
            time.sleep(0.3)
            return {"choices": [{"text": "open chrome"}]}

        fake.Llama.return_value.create_completion.side_effect = slow
        with mock.patch.dict(sys.modules, {"llama_cpp": fake}):
            llm = LocalLLM("models/small.gguf", timeout=0.05)
            self.assertIsNone(llm.understand("floob the zarbo"))

    def test_load_error_is_reported_not_raised(self):
        fake = mock.MagicMock()
        fake.Llama.side_effect = FileNotFoundError("no such file")
        with mock.patch.dict(sys.modules, {"llama_cpp": fake}):
            llm = LocalLLM(r"C:\no\such\model.gguf")
            self.assertIsNone(llm.understand("floob the zarbo"))
            self.assertFalse(llm.healthy())
            self.assertIn("error", llm.describe().lower())

    def test_concurrent_generations_serialize(self):
        # Two rapid novel phrases must not run two inferences at once on
        # one llama.cpp session (unsafe). The lock serializes them, so
        # two 0.15 s generations take ~0.3 s, not ~0.15 s.
        fake = mock.MagicMock()

        def slow(*_a, **_k):
            time.sleep(0.15)
            return {"choices": [{"text": "open chrome"}]}

        fake.Llama.return_value.create_completion.side_effect = slow
        with mock.patch.dict(sys.modules, {"llama_cpp": fake}):
            llm = LocalLLM("models/small.gguf", timeout=5.0)
            results = []

            def call():
                results.append(llm.understand("floob the zarbo"))

            t0 = time.perf_counter()
            a = threading.Thread(target=call)
            b = threading.Thread(target=call)
            a.start(); b.start(); a.join(); b.join()
            elapsed = time.perf_counter() - t0
        self.assertEqual(results, ["open chrome", "open chrome"])
        self.assertGreater(elapsed, 0.25)   # serialized, not overlapped

    def test_onnx_missing_folder_errors_cleanly(self):
        with mock.patch.dict(sys.modules, {"onnxruntime": mock.MagicMock()}):
            llm = LocalLLM(r"C:\no\such\folder")
            self.assertIsNone(llm.understand("floob the zarbo"))
            self.assertIn("error", llm.describe().lower())


class EngineLLMFallbackTests(unittest.TestCase):
    def setUp(self):
        self.e = CommandEngine(build_index=False)
        self.kb = stub_keyboard()
        self._enum = commands._enum_windows
        self._start = commands.os.startfile
        self._open = commands.webbrowser.open
        self._thread = commands.threading.Thread
        commands._enum_windows = lambda: []
        commands.os.startfile = lambda p: None
        commands.webbrowser.open = lambda u: None
        commands.threading.Thread = SyncThread

    def tearDown(self):
        mock.patch.stopall()
        commands._enum_windows = self._enum
        commands.os.startfile = self._start
        commands.webbrowser.open = self._open
        commands.threading.Thread = self._thread

    def test_fast_path_never_calls_llm(self):
        # The model must not run for commands the pattern matcher knows.
        calls = []

        def llm(text):  # pragma: no cover - would fail if ever called
            calls.append(text)
            raise AssertionError("LLM must not run on a fast-path command")

        self.e.llm = llm
        ok, _ = self.e.run("switch tab")
        self.assertTrue(ok)
        self.assertEqual(calls, [])

    def test_llm_called_only_after_all_fast_paths_fail(self):
        calls = []
        self.e.llm = lambda text: calls.append(text) or None
        ok, msg = self.e.run("floob the zarbo")
        self.assertFalse(ok)
        self.assertIn("thinking", msg)   # instant reply, no waiting
        self.assertEqual(calls, ["floob the zarbo"])

    def test_fallback_executes_and_learns(self):
        self.e.llm = lambda text: "open chrome"
        self.e.app_index = {"google chrome": "chrome.lnk"}
        launched = []
        done = []
        learned = []
        commands.os.startfile = lambda p: launched.append(p)
        self.e.on_llm_done = lambda ok, fb: done.append((ok, fb))
        self.e.phrase_learner = lambda h, c: learned.append((h, c))
        ok, msg = self.e.run("floob the zarbo")
        self.assertFalse(ok)                 # immediate reply is "thinking"
        self.assertIn("thinking", msg)
        self.assertEqual(launched, ["chrome.lnk"])
        self.assertEqual(done, [(True, "Opening Google Chrome")])
        self.assertEqual(learned, [("floob the zarbo", "open chrome")])

    def test_none_answer_discarded_silently(self):
        self.e.llm = lambda text: "NONE"
        done = []
        self.e.on_llm_done = lambda ok, fb: done.append((ok, fb))
        ok, _msg = self.e.run("floob the zarbo")
        self.assertFalse(ok)
        self.assertEqual(done, [])

    def test_unparseable_llm_output_ignored(self):
        self.e.llm = lambda text: "flarp the zorp"  # not a known command
        done = []
        self.e.on_llm_done = lambda ok, fb: done.append((ok, fb))
        ok, _msg = self.e.run("floob the zarbo")
        self.assertFalse(ok)
        self.assertEqual(done, [])

    def test_without_llm_reply_is_unchanged(self):
        # Default engine has no LLM: the helpful refusal stays as-is.
        ok, msg = self.e.run("floob the zarbo")
        self.assertFalse(ok)
        self.assertIn("open chrome", msg)
        self.assertNotIn("thinking", msg)

    def test_latency_untouched_with_llm_configured(self):
        # Even a pathological model (10 s per call) cannot slow down normal
        # commands, because the fast path never reaches it.
        def llm(_text):
            time.sleep(10)
            return "open chrome"

        self.e.llm = llm
        corpus = ["switch tab", "volume up", "open settings",
                  "what time is it", "scroll down", "press enter"]
        t0 = time.perf_counter()
        for phrase in corpus:
            self.e.run(phrase)
        self.assertLess(time.perf_counter() - t0, 0.5)


class AsyncLatencyTests(unittest.TestCase):
    """Proves the failure-path latency contract with REAL threads (not the
    SyncThread stub): a novel phrase gets its instant "thinking" reply
    even when the model would take 10 seconds to answer."""

    def setUp(self):
        self.e = CommandEngine(build_index=False)
        self.kb = stub_keyboard()
        self._enum = commands._enum_windows
        self._start = commands.os.startfile
        self._open = commands.webbrowser.open
        commands._enum_windows = lambda: []
        commands.os.startfile = lambda p: None
        commands.webbrowser.open = lambda u: None

    def tearDown(self):
        mock.patch.stopall()
        commands._enum_windows = self._enum
        commands.os.startfile = self._start
        commands.webbrowser.open = self._open

    def test_novel_phrase_reply_not_held_up_by_slow_model(self):
        # The model takes 10 s; the reply must still arrive instantly.
        # (A leftover daemon thread finishes in the background and is
        # harmless — it only posts via the discarded on_llm_done.)
        def llm(_text):
            time.sleep(10)
            return "open chrome"

        self.e.llm = llm
        t0 = time.perf_counter()
        ok, msg = self.e.run("floob the zarbo")
        elapsed = time.perf_counter() - t0
        self.assertFalse(ok)
        self.assertIn("thinking", msg)
        self.assertLess(elapsed, 0.5)


if __name__ == "__main__":
    unittest.main()
