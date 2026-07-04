"""Download the configured model and run a dummy transcription so the
first real dictation is instant. Run once after setup or after changing
the model in config.json."""
import os
import sys
import time

APP_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(APP_DIR, "whisp"))
import numpy as np
from configio import load_config
from transcriber import Transcriber

config = load_config(APP_DIR)

print(f"Loading model '{config.get('model', 'base')}' (downloads on first run)...")
t0 = time.time()
t = Transcriber(config)
t.load()
print(f"Model ready in {time.time() - t0:.1f}s. Running warmup transcription...")
t0 = time.time()
t.transcribe(np.zeros(16000, dtype=np.float32))
print(f"Warmup done in {time.time() - t0:.1f}s. All set.")
