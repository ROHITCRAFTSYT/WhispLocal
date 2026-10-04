"""Local speech-to-text via faster-whisper (CTranslate2, int8 on CPU).

The model loads lazily on first use and stays resident so later
transcriptions skip the ~2-5s load cost.
"""
import os
import threading

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
        self.model_name = config.get("model", "base")
        self.language = config.get("language") or None  # None = auto-detect
        self.beam_size = int(config.get("beam_size", 2))
        self.cpu_threads = int(config.get("cpu_threads", 0)) or (os.cpu_count() or 4)
        self.script = config.get("indic_script", "native")  # or "roman"
        self._model = None
        self._lock = threading.Lock()

    def load(self):
        with self._lock:
            if self._model is None:
                from faster_whisper import WhisperModel

                self._model = WhisperModel(
                    self.model_name,
                    device="cpu",
                    compute_type="int8",
                    cpu_threads=self.cpu_threads,
                )
        return self._model

    def transcribe(self, audio, task="transcribe", hotwords=None, language=None):
        """audio: float32 numpy array at 16 kHz.

        language overrides the configured language for this call.
        task="translate" outputs English regardless of spoken language.
        Returns (text, detected_language, language_probability).
        """
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
