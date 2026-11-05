"""Local speech-to-text via faster-whisper (CTranslate2, int8 on CPU).

The model loads lazily on first use and stays resident so later
transcriptions skip the ~2-5s load cost.
"""
import os
import threading

from logsetup import get_logger

_log = get_logger("model")

# Built-in faster-whisper model names. Anything else is treated as a local
# model directory or a Hugging Face repo id (e.g. "Systran/faster-whisper-small").
KNOWN_MODELS = (
    "tiny", "tiny.en", "base", "base.en", "small", "small.en",
    "distil-small.en", "medium", "medium.en", "distil-medium.en",
    "large-v1", "large-v2", "large-v3", "large", "distil-large-v2",
    "distil-large-v3", "distil-large-v3.5", "large-v3-turbo", "turbo",
)


class ModelLoadError(RuntimeError):
    """The speech model could not be loaded. ``str(err)`` is a short,
    user-facing explanation; ``err.hint`` says what to do about it and
    ``err.__cause__`` holds the original exception for the log."""

    def __init__(self, message, hint=""):
        super().__init__(message)
        self.hint = hint

    def user_message(self):
        return f"{self}. {self.hint}" if self.hint else str(self)


def explain_load_error(model_name, exc):
    """Map a raw load failure to a ModelLoadError with an actionable hint.

    faster-whisper / huggingface_hub / CTranslate2 raise a zoo of
    exception types; we classify on type name and message text so this
    works without importing any of them."""
    kind = type(exc).__name__
    text = f"{kind}: {exc}".lower()
    if isinstance(exc, MemoryError) or "out of memory" in text or \
            "bad_alloc" in text or "cannot allocate" in text:
        return ModelLoadError(
            f"Not enough memory to load the '{model_name}' model",
            "Pick a smaller model (tiny or base) in Settings.")
    if "no space left" in text or "errno 28" in text or "disk full" in text:
        return ModelLoadError(
            f"Not enough disk space to download the '{model_name}' model",
            "Free some space on the drive that holds your user folder.")
    if "invalid model size" in text or "repositorynotfound" in text or \
            "repository not found" in text or "401 client error" in text:
        return ModelLoadError(
            f"Unknown speech model '{model_name}'",
            "Choose a model from the list in Settings.")
    if any(w in text for w in ("connection", "timed out", "timeout",
                               "offline", "localentrynotfound",
                               "name resolution", "getaddrinfo",
                               "max retries", "ssl", "proxy")):
        return ModelLoadError(
            f"The '{model_name}' model is not downloaded yet and the download "
            "failed",
            "Connect to the internet once (or run setup.bat) so the model "
            "can be downloaded; after that WhispLocal works offline.")
    if isinstance(exc, ImportError) or (isinstance(exc, OSError) and (
            "dll" in text or "ctranslate2" in text)):
        return ModelLoadError(
            "The speech engine is not installed correctly",
            "Re-run setup.bat to reinstall the dependencies.")
    if "unable to open file" in text or "model.bin" in text or \
            "corrupt" in text or "invalid argument" in text:
        return ModelLoadError(
            f"The downloaded '{model_name}' model looks damaged",
            "Delete it from %USERPROFILE%\\.cache\\huggingface\\hub and "
            "restart WhispLocal to download it again.")
    return ModelLoadError(f"Could not load the '{model_name}' model ({kind})",
                          "See whisp.log for details.")

# Proper nouns Whisper commonly mangles (e.g. "Claude" -> "cloud"). These
# are always offered as recognition hints so names come out right.
DEFAULT_HOTWORDS = (
    "Claude Anthropic ChatGPT OpenAI GitHub GitLab WhispLocal Obsidian "
    "Spotify YouTube OBS Studio Discord Notion Docker Kubernetes Python "
    "JavaScript TypeScript Chrome Edge Firefox VS Code npm API JSON"
)

# For languages where Whisper sometimes falls back to the Latin alphabet,
# a short prompt in the native script steers the output to that script.
SCRIPT_PRIMERS = {
    "hi": "नमस्ते, यह हिंदी में देवनागरी लिपि का एक वाक्य है।",
    "bn": "নমস্কার, এটি বাংলা লিপিতে লেখা একটি বাক্য।",
    "ta": "வணக்கம், இது தமிழ் எழுத்தில் எழுதப்பட்ட வாக்கியம்.",
    "te": "నమస్తే, ఇది తెలుగు లిపిలో రాసిన వాక్యం.",
    "mr": "नमस्कार, हे मराठीत देवनागरी लिपीतील वाक्य आहे.",
    "gu": "નમસ્તે, આ ગુજરાતી લિપિમાં લખેલું વાક્ય છે.",
    "ur": "السلام علیکم، یہ اردو رسم الخط میں لکھا گیا جملہ ہے۔",
    "pa": "ਸਤ ਸ੍ਰੀ ਅਕਾਲ, ਇਹ ਗੁਰਮੁਖੀ ਲਿਪੀ ਵਿੱਚ ਲਿਖਿਆ ਵਾਕ ਹੈ।",
}

# "Roman script" output (indic_script = "roman"): a Latin-alphabet primer
# steers Whisper toward the way people actually type these languages in
# chat ("kal meeting kitne baje hai?"), English words included. Best
# effort: the model can still switch scripts on some clips.
ROMAN_PRIMERS = {
    "hi": "Haan bhai, kal ki meeting kitne baje hai? Main thoda late "
          "aaunga, please wait karna.",
    "mr": "Ho, udya meeting kiti vajta aahe? Mi thoda late yein.",
    "bn": "Haan, kalke meeting koyta baje? Ami ektu deri te asbo.",
    "ta": "Aamaa, naalai meeting evvalavu manikku? Naan konjam late-aa "
          "varuven.",
    "te": "Avunu, repu meeting enni gantalaki? Nenu konchem late ga "
          "vastanu.",
    "gu": "Haa, kale meeting ketla vage che? Hu thodo late aavish.",
    "pa": "Haan ji, kal meeting kinne vaje hai? Main thoda late aavanga.",
    "ur": "Haan, kal meeting kitne baje hai? Main thora late aaunga.",
}


class Transcriber:
    """Lazily-loaded faster-whisper wrapper.

    Holds decode settings (model, language, beam size, CPU threads) from
    ``config`` and loads the model on first use behind a lock so concurrent
    callers share a single instance.
    """

    def __init__(self, config):
        self.model_name = config.get("model") or "base"
        self.language = config.get("language") or None  # None = auto-detect
        self.beam_size = _as_int(config.get("beam_size"), 2, lo=1)
        self.cpu_threads = (_as_int(config.get("cpu_threads"), 0, lo=0)
                            or (os.cpu_count() or 4))
        self.script = config.get("indic_script", "native")  # or "roman"
        self._model = None
        self._lock = threading.Lock()
        # Last load failure (a ModelLoadError), for the UI to report.
        self.last_error = None

    @property
    def loaded(self):
        return self._model is not None

    def load(self):
        """Load the model once and return it.

        Offline first: the model is opened from the local cache without
        touching the network (WhispLocal promises to make no network
        requests of its own). Only when it is not cached yet is it
        downloaded. Any failure is raised as a ModelLoadError with a
        user-facing explanation; the next call retries from scratch.
        """
        with self._lock:
            if self._model is None:
                self._model = self._load_model()
        return self._model

    def _load_model(self):
        try:
            from faster_whisper import WhisperModel
        except Exception as e:  # ImportError, or a DLL load failure
            raise self._failed(e) from e

        kwargs = {"device": "cpu", "compute_type": "int8",
                  "cpu_threads": self.cpu_threads}
        try:
            model = WhisperModel(self.model_name, local_files_only=True,
                                 **kwargs)
            _log.info("model '%s' loaded from the local cache",
                      self.model_name)
        except Exception as cached_err:
            if os.path.isdir(self.model_name) or isinstance(cached_err,
                                                            MemoryError):
                # A local model folder that fails to open, or running out
                # of memory, will not be fixed by downloading anything.
                raise self._failed(cached_err) from cached_err
            _log.info("model '%s' not in the local cache (%s); downloading",
                      self.model_name, type(cached_err).__name__)
            try:
                model = WhisperModel(self.model_name, **kwargs)
            except Exception as e:
                raise self._failed(e) from e
            _log.info("model '%s' downloaded and loaded", self.model_name)
        self.last_error = None
        return model

    def _failed(self, exc):
        """Record and log a load failure; return the ModelLoadError."""
        err = explain_load_error(self.model_name, exc)
        self.last_error = err
        _log.error("model '%s' failed to load: %s", self.model_name,
                   err.user_message(), exc_info=exc)
        return err

    def transcribe(self, audio, task="transcribe", hotwords=None, language=None):
        """audio: float32 numpy array at 16 kHz.

        language overrides the configured language for this call.
        task="translate" outputs English regardless of spoken language.
        Returns (text, detected_language, language_probability).
        """
        if audio is None or len(audio) == 0:
            return "", None, 0.0
        model = self.load()
        if task == "translate":
            lang = None  # translation needs auto-detection to work broadly
        else:
            lang = language if language is not None else self.language

        primers = ROMAN_PRIMERS if self.script == "roman" else SCRIPT_PRIMERS
        primer = primers.get(lang) if task == "transcribe" else None
        # Always include the built-in proper-noun hints so names like
        # "Claude" are not heard as "cloud".
        effective_hotwords = (DEFAULT_HOTWORDS + " " + (hotwords or "")).strip()
        if primer:
            # faster-whisper drops the hotwords parameter when a prompt is
            # set, so fold the hints into the prompt text itself. Names
            # still transcribe correctly even in script-primer languages.
            prompt = primer + "\n" + effective_hotwords
            initial_prompt, hotwords_kw = prompt, None
        else:
            initial_prompt, hotwords_kw = None, effective_hotwords or None
        segments, info = model.transcribe(
            audio,
            task=task,
            language=lang,
            beam_size=self.beam_size,
            initial_prompt=initial_prompt,
            hotwords=hotwords_kw,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 400},
            condition_on_previous_text=False,
        )
        text = " ".join(seg.text.strip() for seg in segments).strip()
        return text, info.language, info.language_probability


def _as_int(value, default, lo=None):
    """int(value), or ``default`` for None/garbage (config is validated on
    load, but a Transcriber can also be built from a hand-made dict)."""
    try:
        n = int(value)
    except (TypeError, ValueError):
        return default
    return max(lo, n) if lo is not None else n
