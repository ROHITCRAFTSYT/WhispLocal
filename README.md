# WhispLocal 🎙️

**Private, fully-offline voice dictation for Windows** — an open-source
alternative to Wispr Flow that never sends your voice anywhere.

![CI](https://github.com/ROHITCRAFTSYT/WhispLocal/actions/workflows/ci.yml/badge.svg)
![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)
![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)
![Platform: Windows](https://img.shields.io/badge/platform-Windows%2010%2F11-lightgrey)

Hold a hotkey, speak, release — your words appear at the cursor in any
app, cleaned up and punctuated. Cloud dictation tools upload every word
you say; WhispLocal runs the entire pipeline on your own CPU:

```
hotkey → mic capture (16 kHz) → faster-whisper (int8, CPU) → cleanup
(fillers, custom dictionary, punctuation) → paste at cursor in any app
```

## Features

- 🎤 **Hold-to-talk or tap-to-lock** dictation into any application
- 📊 **Live waveform pill** showing your real mic levels while you speak
- 🌍 **Translate mode** — optional second hotkey: speak any language,
  English comes out
- 🧹 **AI-style cleanup** — filler-word removal (um, uh…), sentence
  capitalization, custom dictionary (`heard => replacement`)
- ⚡ **Six models** — from `tiny` (fastest) to `small` (most accurate),
  switchable from the tray; `base` runs faster than real-time even on a
  2-core i3
- 🖥️ **Real app experience** — tray icon, Settings and History windows,
  single-instance guard, silent launch (no console window ever)
- 🔒 **Offline by design** — no telemetry, no accounts, no subscription

## Install

```
git clone https://github.com/ROHITCRAFTSYT/WhispLocal.git
cd WhispLocal
setup.bat              (creates venv, installs deps, downloads the model)
install_shortcuts.bat  (adds WhispLocal to Desktop + Start Menu)
```

Requires Windows 10/11 and [Python 3.11+](https://www.python.org/downloads/).
The one-time model download (~75 MB) is the only network access the app
ever makes — after that it works with the network cable unplugged.

## Usage

Launch **WhispLocal** from the Start Menu — a mic icon appears in the tray.

| Action | Result |
|---|---|
| Hold `Right Ctrl`, speak, release | Text typed at your cursor |
| Quick-tap `Right Ctrl` | Recording locks on (🔒); tap again to stop |
| Translate hotkey (set in Settings) | Any spoken language → English text |
| Tray → Settings… | Model, language, mic, hotkeys, cleanup, dictionary |
| Tray → History… | Browse past dictations, double-click to copy |
| Tray → Model | Quick-switch model |
| Tray → Pause dictation | Temporarily disable hotkeys |

Auto-start at login: `Win+R` → `shell:startup` → copy the WhispLocal
shortcut there.

## Model guide

| Model | Speed on a 2-core CPU | Notes |
|---|---|---|
| `tiny` / `tiny.en` | fastest | lower accuracy |
| `base` / `base.en` | faster than real-time | **recommended** |
| `small` / `small.en` | ~2.5× slower | most accurate |

`.en` variants are faster and more accurate for English only. Translate
mode needs a multilingual model (no `.en` suffix). Switching to a model
you haven't used yet downloads it once.

## Privacy, honestly

- **Audio never leaves your machine.** Transcription runs locally; there
  are no analytics, accounts, or update pings. The only network access is
  downloading a model from Hugging Face when you first select it.
- **History** is saved in plaintext in `history.jsonl` next to the app so
  the History window can show it. Turn it off in Settings or delete the
  file anytime.
- **Clipboard**: the default insert method briefly places the dictated
  text on the clipboard and then restores what was there. If you disable
  "Restore clipboard", the dictated text remains on the clipboard; use
  the `type` insert method to bypass the clipboard entirely.
- The global hotkey uses a keyboard hook (that's how push-to-talk works
  system-wide); keystrokes are never stored or transmitted.

## Development

```
venv\Scripts\python.exe -m unittest discover -s tests   # unit tests
debug.bat                                               # run with console
```

Errors are logged to `whisp.log` (auto-rotated). Pull requests welcome.

## Troubleshooting

- **Nothing types in some apps** — apps running as Administrator ignore
  input from normal processes; run WhispLocal as admin too.
- **Paste blocked in an app** — switch Insert method to `type` in Settings.
- **Wrong microphone** — pick it in Settings → Microphone.
- **Won't start** — run `debug.bat` and read the error, or check `whisp.log`.

## License

[MIT](LICENSE) © ROHITCRAFTSYT
