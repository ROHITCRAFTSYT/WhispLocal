"""Optional local-LLM fallback for the command brain.

When the fast pattern matcher fails on a genuinely novel phrase, an
optional local language model can restate the phrase as a canonical
command. That canonical command is then fed through the existing parser
and executor, so the LLM never executes anything directly and cannot
gain any capability the pattern matcher does not already have.

Why this cannot hurt reply latency:

- It is OFF by default and needs an explicit model path in Settings.
- It only runs AFTER every fast path (learned phrases, parse, repair,
  fuzzy suggest) has already failed.
- The LLM call happens on a background daemon thread with a timeout;
  the immediate reply ("not sure yet") is returned without waiting.
- The model's output is accepted only if parse() understands it;
  NONE, garbage, and timeouts are discarded silently.
- Successful resolutions are handed back to the app so the phrase can
  be learned (heard -> canonical) and resolve instantly next time.

Backends (both local, never a network call):

- llama.cpp: a GGUF model via the `llama-cpp-python` package.
- onnx: an ONNX text-generation model via `onnxruntime`, with a
  HuggingFace tokenizer (transformers / tokenizers) beside it.

Heavy imports (llama_cpp, onnxruntime, transformers) happen lazily,
only when a model is configured, so installing the optional packages
never affects the app until you opt in.
"""
import os
import re
import threading

DEFAULT_TIMEOUT = 8.0  # seconds before a background attempt is abandoned

_SYSTEM = (
    "You map a spoken instruction to ONE canonical voice command from "
    "this fixed list. Reply with ONLY the canonical command, nothing "
    "else. If the instruction is not a computer command, reply exactly "
    "NONE.\n"
    "Canonical commands look like:\n"
    "open chrome, open notepad, close chrome, switch tab, switch to "
    "tab 3, open settings, open windows settings, volume up, volume "
    "down, set volume to 30, increase volume by 20, decrease volume "
    "by 10, mute, brightness up, set brightness to 50, increase "
    "brightness by 20, scroll up, search for python tutorial, search "
    "for lofi on youtube, search mr beast in youtube, google mr beast "
    "in youtube, look for mr beast in youtube, play despacito, open "
    "youtube and search for mr beast, "
    "take a note buy milk, order monster from instamart, add milk to "
    "cart on blinkit, what time is it, lock the screen, check battery, "
    "restart the computer, sleep, hibernate, take a screenshot, open "
    "a new tab, close this tab, press enter\n"
)


def build_prompt(phrase):
    """The few-shot instruction shown to the model."""
    return f"{_SYSTEM}\nInstruction: {phrase}\nCommand:"


def sanitize(text):
    """Clean the model's reply into a canonical command, or None when it
    refused / produced nothing useful."""
    t = (text or "").strip()
    if not t:
        return None
    # Strip markdown fence markers and surrounding quotes. Only the
    # backticks themselves are removed — a trailing language tag is not
    # guessed, so the command text is never eaten.
    t = re.sub(r"^```\s*", "", t)
    t = t.strip("`\"' ")
    t = re.sub(r"\s+", " ", t).strip()
    # Some models answer "Command: open chrome" — take the part after the
    # label instead of treating the whole sentence as the command.
    m = re.match(r"^(?:command|canonical command|reply)\s*[:\-]\s*(.+)$",
                 t, re.I)
    if m:
        t = m.group(1).strip()
    if not t or t.upper() == "NONE":
        return None
    # Trailing sentence punctuation would make "what time is it?" fail to
    # parse; drop it. parse() re-validates everything anyway.
    t = t.rstrip(".!?")
    return t.strip() or None


class LocalLLM:
    def __init__(self, model_path="", timeout=DEFAULT_TIMEOUT):
        self.model_path = (model_path or "").strip()
        self.timeout = timeout
        # Reentrant: the daemon thread holds this lock for the whole
        # generation so two rapid novel commands cannot run concurrent
        # inferences on one llama.cpp session (unsafe), while each call's
        # timeout join still bounds it individually.
        self._lock = threading.RLock()
        self._session = None
        self._load_error = None

    # ----- introspection --------------------------------------------------
    @property
    def backend(self):
        """Which engine this model path targets (llama.cpp or onnx)."""
        p = self.model_path.lower()
        if p.endswith(".onnx") or os.path.isdir(self.model_path):
            return "onnx"
        return "llama"

    def configured(self):
        return bool(self.model_path)

    def healthy(self):
        return self._session is not None

    def describe(self):
        """A one-line status for the Settings window."""
        if not self.configured():
            return "No model configured — fallback is off."
        if self._session is not None:
            return f"Loaded ({self.backend}) — ready for novel commands."
        if self._load_error:
            return f"Load error: {self._load_error}"
        return (f"{self.backend} model set — will load on first "
                f"unrecognized command.")

    # ----- loading ----------------------------------------------------------
    def _load(self):
        """Load the model exactly once, lazily, under a lock."""
        if self._session is not None or self._load_error is not None:
            return
        with self._lock:
            if self._session is not None or self._load_error is not None:
                return
            try:
                if self.backend == "onnx":
                    self._session = self._load_onnx()
                else:
                    self._session = self._load_llama()
            except Exception as e:
                self._load_error = str(e)

    def load(self):
        """Force the lazy model load (used by the Settings Test button)."""
        self._load()

    def _load_llama(self):
        from llama_cpp import Llama
        return Llama(model_path=self.model_path, n_ctx=1024, verbose=False)

    def _load_onnx(self):
        import onnxruntime as ort
        model_path = self.model_path
        if os.path.isdir(model_path):
            model_path = os.path.join(model_path, "model.onnx")
        if not os.path.exists(model_path):
            raise FileNotFoundError(
                f"no model.onnx in {self.model_path}")
        session = ort.InferenceSession(
            model_path, providers=["CPUExecutionProvider"])
        tokenizer = None
        try:
            from transformers import AutoTokenizer
            tok_dir = os.path.dirname(model_path) or "."
            tokenizer = AutoTokenizer.from_pretrained(tok_dir)
        except Exception:
            pass  # raw onnxruntime without a tokenizer: handled at generate
        return {"session": session, "tokenizer": tokenizer}

    # ----- inference ---------------------------------------------------------
    def understand(self, phrase):
        """Restate `phrase` as a canonical command, or None.

        Blocking up to self.timeout (it is meant to run on a background
        thread). Any failure or refusal quietly returns None — the caller
        simply keeps the original "not sure" reply.
        """
        if not self.configured():
            return None
        result = {}

        def _run():
            # The lock is held for the whole generation (load + inference)
            # so concurrent understand() calls serialize instead of two
            # threads hammering one session at once.
            with self._lock:
                self._load()
                if self._session is None:
                    return
                try:
                    result["text"] = self._generate(phrase)
                except Exception as e:
                    result["error"] = str(e)

        t = threading.Thread(target=_run, daemon=True)
        t.start()
        t.join(self.timeout)
        if "error" in result:
            self._load_error = result["error"]  # don't retry a broken model
            return None
        if "text" not in result:
            return None  # timed out
        return sanitize(result["text"])

    def _generate(self, phrase):
        if self.backend == "onnx":
            return self._generate_onnx(phrase)
        return self._generate_llama(phrase)

    def _generate_llama(self, phrase):
        out = self._session.create_completion(
            prompt=build_prompt(phrase),
            max_tokens=48,
            temperature=0.0,
            stop=["\n", "NONE"],
            echo=False)
        return out["choices"][0]["text"]

    def _generate_onnx(self, phrase):
        """Greedy decode with onnxruntime. Needs a tokenizer; without one
        the attempt fails cleanly (the caller keeps its normal reply)."""
        session = self._session["session"]
        tokenizer = self._session.get("tokenizer")
        if tokenizer is None:
            raise RuntimeError(
                "ONNX backend needs a HuggingFace tokenizer next to the "
                "model (tokenizer.json / transformers)")
        import numpy as np
        enc = tokenizer(build_prompt(phrase), return_tensors="np")
        ids = np.asarray(enc["input_ids"], dtype=np.int64)
        attn = enc.get("attention_mask")
        feed = {}
        for inp in session.get_inputs():
            if inp.name == "input_ids":
                feed["input_ids"] = ids
            elif inp.name == "attention_mask":
                feed["attention_mask"] = (
                    np.ones_like(ids) if attn is None else np.asarray(
                        attn, dtype=np.int64))
            elif inp.name == "position_ids":
                feed["position_ids"] = np.arange(ids.shape[1])[None, :]
            else:
                raise RuntimeError(f"unsupported model input: {inp.name}")
        if "input_ids" not in feed:
            raise RuntimeError("model has no input_ids input")
        eos = tokenizer.eos_token_id or 0
        prompt_len = ids.shape[1]
        max_new = 48
        for _ in range(max_new):
            out = session.run(None, feed)[0]
            logits = out[0, -1]
            nxt = int(np.argmax(logits))
            if nxt == eos:
                break
            ids = np.concatenate([ids, np.array([[nxt]], dtype=np.int64)],
                                 axis=1)
            if "attention_mask" in feed:
                feed["attention_mask"] = np.concatenate(
                    [feed["attention_mask"],
                     np.ones((1, 1), dtype=np.int64)], axis=1)
            if "position_ids" in feed:
                feed["position_ids"] = np.concatenate(
                    [feed["position_ids"],
                     np.array([[ids.shape[1] - 1]], dtype=np.int64)], axis=1)
            feed["input_ids"] = ids
        return tokenizer.decode(ids[0, prompt_len:], skip_special_tokens=True)
