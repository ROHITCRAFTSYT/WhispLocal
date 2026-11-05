# PyInstaller spec for WhispLocal (Windows, one-folder, windowed).
#
#   packaging\build.bat            (recommended: creates a clean build venv)
#   pyinstaller --noconfirm packaging\whisplocal.spec   (from the repo root)
#
# Output: dist\WhispLocal\WhispLocal.exe plus its _internal\ folder. The
# folder must stay writable: config.json, whisp.log and history.jsonl are
# written next to the exe, like the source install writes them next to
# whisp\.
import glob
import os

from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_dynamic_libs,
    collect_submodules,
)

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))  # noqa: F821 (PyInstaller global)
WHISP = os.path.join(ROOT, "whisp")

# The launcher runs the app with runpy, which PyInstaller cannot follow, and
# app modules import each other by bare name from whisp/. List them all
# (including any sub-packages) so new modules are picked up automatically.
app_modules = sorted(
    os.path.splitext(os.path.basename(p))[0]
    for p in glob.glob(os.path.join(WHISP, "*.py")))
for init in glob.glob(os.path.join(WHISP, "*", "__init__.py")):
    app_modules += collect_submodules(os.path.basename(os.path.dirname(init)))

hiddenimports = app_modules + [
    # Imported dynamically by their libraries at runtime.
    "pystray._win32",
    "keyboard._winkeyboard",
    "comtypes.client",
    "comtypes.stream",
    "PIL.ImageGrab",
] + collect_submodules("websockets")

datas = [
    (os.path.join(ROOT, "config.default.json"), "."),
    (os.path.join(ROOT, "icon.ico"), "."),
]
# Silero VAD model shipped inside faster_whisper/assets.
datas += collect_data_files("faster_whisper")

# CTranslate2 ships its inference DLLs next to the Python extension.
binaries = collect_dynamic_libs("ctranslate2")

a = Analysis(  # noqa: F821
    [os.path.join(SPECPATH, "launcher.py")],  # noqa: F821
    pathex=[WHISP],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=[
        # Optional local-LLM backends: large, and only used when installed
        # by hand in a source install (see README, "Local LLM fallback").
        "llama_cpp", "transformers", "torch", "tensorflow",
        # Never used at runtime.
        "pytest", "ruff", "IPython", "matplotlib",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="WhispLocal",
    icon=os.path.join(ROOT, "icon.ico"),
    console=False,  # like pythonw: no console window
    upx=False,  # UPX-packed binaries trip antivirus heuristics
    disable_windowed_traceback=False,
)

coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="WhispLocal",
)
