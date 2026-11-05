"""PyInstaller entry point for WhispLocal.

Normal start: runs whisp/app.py exactly as ``python whisp\\app.py`` would.

``WhispLocal.exe --self-test`` imports every module the app needs, checks
the bundled data files and the config, writes a report to
``self-test.txt`` next to the executable, and exits 0 (all good) or 1. CI
runs it against the frozen build, because a missing hidden import only
shows up at runtime and a windowed build cannot print a traceback.
"""
import glob
import importlib
import os
import runpy
import sys

FROZEN = getattr(sys, "frozen", False)
if FROZEN:
    APP_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, os.path.join(APP_DIR, "whisp"))

# Imported at the top of some app module or lazily on a hot path; the
# frozen build must contain every one of them.
REQUIRED_MODULES = (
    "app", "audio", "transcriber", "configio", "configcheck", "logsetup",
    "numpy", "sounddevice", "keyboard", "pyperclip", "pystray", "PIL.Image",
    "PIL.ImageDraw", "tkinter", "tkinter.ttk", "websockets",
    "faster_whisper", "ctranslate2", "onnxruntime", "tokenizers",
)
WINDOWS_MODULES = ("comtypes", "comtypes.client", "pystray._win32",
                   "keyboard._winkeyboard", "winsound")


def self_test():
    lines, ok = [], True

    def check(label, fn):
        nonlocal ok
        try:
            detail = fn()
            lines.append(f"ok    {label}" + (f"  ({detail})" if detail else ""))
        except Exception as e:  # report everything, keep going
            ok = False
            lines.append(f"FAIL  {label}: {type(e).__name__}: {e}")

    mods = REQUIRED_MODULES + (WINDOWS_MODULES if sys.platform == "win32" else ())
    for name in mods:
        check(f"import {name}", lambda n=name: importlib.import_module(n) and None)

    def vad_assets():
        from faster_whisper.utils import get_assets_path
        found = glob.glob(os.path.join(get_assets_path(), "*.onnx"))
        if not found:
            raise FileNotFoundError(f"no VAD model in {get_assets_path()}")
        return os.path.basename(found[0])

    def config():
        import configio
        cfg = configio.load_config(APP_DIR)
        return f"model={cfg.get('model')}, hotkey={cfg.get('hotkey')}"

    def version():
        import app
        return app.__version__

    check("faster-whisper VAD asset", vad_assets)
    check("load config", config)
    check("app version", version)

    report = "\n".join(lines) + f"\n\nself-test {'PASSED' if ok else 'FAILED'}\n"
    try:
        with open(os.path.join(APP_DIR, "self-test.txt"), "w",
                  encoding="utf-8") as f:
            f.write(report)
    except OSError:
        pass
    if sys.stdout is not None:
        print(report)
    return 0 if ok else 1


if __name__ == "__main__":
    if "--self-test" in sys.argv[1:]:
        sys.exit(self_test())
    runpy.run_module("app", run_name="__main__", alter_sys=True)
