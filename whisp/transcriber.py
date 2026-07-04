"""Local speech-to-text via faster-whisper (CTranslate2, int8 on CPU).

The model loads lazily on first use and stays resident so later
transcriptions skip the ~2-5s load cost.
"""
import os
import threading

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


class Transcriber:
    def __init__(self, config):
        self.model_name = config.get("model", "base")
        self.language = config.get("language") or None  # None = auto-detect
        self.beam_size = int(config.get("beam_size", 2))
        self.cpu_threads = int(config.get("cpu_threads", 0)) or (os.cpu_count() or 4)
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

        primer = SCRIPT_PRIMERS.get(lang) if task == "transcribe" else None
        segments, info = model.transcribe(
            audio,
            task=task,
            language=lang,
            beam_size=self.beam_size,
            # faster-whisper ignores hotwords when initial_prompt is set,
            # so pass whichever applies.
            initial_prompt=primer,
            hotwords=None if primer else hotwords,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 400},
            condition_on_previous_text=False,
        )
        text = " ".join(seg.text.strip() for seg in segments).strip()
        return text, info.language, info.language_probability
