<p align="center">
  <img src="docs/banner.png" alt="WhispLocal" width="820">
</p>

<p align="center">
  <a href="https://github.com/ROHITCRAFTSYT/WhispLocal/actions/workflows/ci.yml"><img src="https://github.com/ROHITCRAFTSYT/WhispLocal/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="MIT license">
  <img src="https://img.shields.io/badge/python-3.11+-blue" alt="Python 3.11+">
  <img src="https://img.shields.io/badge/platform-Windows%2010%2F11-lightgrey" alt="Windows 10/11">
</p>

WhispLocal is a dictation app for Windows that runs entirely on your own
computer. Hold a key, say what you want to type, release, and the text
appears at your cursor in whatever app you were using. There is no cloud
service behind it: the speech recognition model runs on your CPU, so
nothing you say ever leaves the machine.

<p align="center">
  <img src="docs/waveform.gif" alt="Recording indicator with live waveform" width="340">
</p>

## How it works

<p align="center">
  <img src="docs/architecture.svg" alt="Pipeline: hotkey, microphone, faster-whisper, cleanup, active window" width="820">
</p>

Audio is captured at 16 kHz while you hold the hotkey, then transcribed
by [faster-whisper](https://github.com/SYSTRAN/faster-whisper), a
CTranslate2 port of OpenAI's Whisper quantized to int8 so it performs
well on CPUs without a GPU. A cleanup pass strips filler words (um, uh),
fixes capitalization, and applies your personal dictionary of
corrections, for example `jason => JSON`. The result is pasted at the
cursor, and your previous clipboard contents are restored afterwards.

## What it does

- Types into anything that accepts text: browsers, editors, chat apps, terminals.
- Hold to talk, or tap the key once to lock recording on for longer dictation.
- Shows a live waveform while recording, so you know it is listening.
- An optional second hotkey transcribes speech in other languages directly to English text.
- Six recognition models, switchable from the tray without restarting.
- Runs from the system tray with no console window. Starting it twice will not launch a second copy.
- Sound cues, a pause switch, and a dictation history you can search and copy from.

Settings and history are regular windows, not config files you have to edit:

<table>
  <tr>
    <td align="center"><img src="docs/settings.png" alt="Settings window" width="420"></td>
    <td align="center"><img src="docs/history.png" alt="History window" width="420"></td>
  </tr>
  <tr>
    <td align="center">Settings</td>
    <td align="center">History</td>
  </tr>
</table>

## Performance

<p align="center">
  <img src="docs/benchmark.svg" alt="Benchmark: tiny 1.5s, base.en 1.9s, base 2.9s for a 14 second dictation" width="820">
</p>

These numbers come from a two-core laptop CPU (Intel i3-1005G1) with no
GPU, so they are close to a worst case. On newer hardware the wait is
shorter. The model stays loaded in RAM between dictations; only the
first dictation after startup pays a loading cost of a couple of
seconds.

## Install

```
git clone https://github.com/ROHITCRAFTSYT/WhispLocal.git
cd WhispLocal
setup.bat
install_shortcuts.bat
```

You need Windows 10 or 11 and [Python 3.11+](https://www.python.org/downloads/).
`setup.bat` creates a virtual environment, installs dependencies, and
downloads the default model (about 75 MB). `install_shortcuts.bat` adds
WhispLocal to your Desktop and Start Menu. After that, launch it from
the Start Menu and look for the microphone icon in the tray.

To start it automatically at login, press `Win+R`, type `shell:startup`,
and copy the WhispLocal shortcut into that folder.

## Everyday use

| Action | Result |
|---|---|
| Hold `Right Ctrl`, speak, release | Text is typed at your cursor |
| Tap `Right Ctrl` once | Recording locks on; tap again to stop |
| Translate hotkey (set one in Settings) | Speech in any language becomes English text |
| Tray menu → Settings | Model, language, microphone, hotkeys, dictionary |
| Tray menu → History | Past dictations, double-click to copy |
| Tray menu → Pause dictation | Hotkeys ignored until you unpause |

## Choosing a model

| Model | 14 s dictation takes | Notes |
|---|---|---|
| `tiny` / `tiny.en` | 1.5 s | Fastest, makes more mistakes |
| `base` / `base.en` | 1.9 to 2.9 s | Default, good balance |
| `small` / `small.en` | about 7 s (estimated) | Most accurate |

The `.en` variants are faster and more accurate but only understand
English. Translate mode needs a multilingual model (one without the
`.en` suffix). Picking a model you have not used before downloads it
once, which is the only situation where the app needs a network
connection.

## Voice control mode

WhispLocal has two modes. Dictation is the default. Switch to voice
control from the tray (Mode menu) and the same hotkey stops typing what
you say and starts doing what you say. If you want both at once, give
voice control its own hotkey in Settings and keep dictating on the main
one. Confirmations are spoken back through the built-in Windows voice;
turn that off in Settings if it gets chatty.

Commands are matched locally against a fixed set of patterns. Apps are
found by indexing your Start Menu, so "open OBS Studio" works for
anything installed. What you can say:

| Say | Happens |
|---|---|
| "open obs", "launch discord" | Opens the app if installed (fuzzy matching included) |
| "open spotify" (not installed) | Opens the web version instead |
| "open spotify in web" | Forces the web version even if the app is installed |
| "download spotify" | Opens its official download page |
| "close chrome", "quit spotify" | Closes the app gracefully (save prompts still appear) |
| "open downloads", "open documents" | Opens the folder |
| "open youtube.com", "go to github" | Opens the site |
| "search for python tutorials", "look up the capital of Japan" | Web search |
| "play some music" | Opens YouTube Music |
| "play despacito", "play X on spotify" | Plays the song on YouTube Music or Spotify |
| "what do you know about me" | Writes a profile of what it has learned to Obsidian |
| "find market data for Tesla", "stock price of Apple" | Opens the market/stock page |
| "book a table at Bukhara" | Opens reservation options (you confirm it) |
| "take a note buy milk tomorrow" | Saves a formatted note to your Obsidian vault |
| "type hello there" | Types the text at the cursor |
| "press control shift s", "press enter" | Sends the key combination |
| "volume up", "mute", "next song", "pause" | Audio and media control |
| "close window", "maximize", "switch window" | Window management |
| "scroll down", "click", "right click" | Pointer control |
| "take a screenshot" | Saves a PNG to Pictures |
| "lock the screen" | Locks Windows |
| "shut down the computer" | Shutdown after 60 s; "cancel shutdown" aborts |
| "what time is it", "what's the date" | Answers on screen and out loud |

If a command is slightly misheard, WhispLocal makes a second pass: it
corrects the leading verb ("oben chrome" becomes "open chrome") or
matches the whole phrase to the closest known command before giving up.
It also feeds your command words and app names into the recognizer, so
the more you use it, the better it hears you.

It stays out of your way on purpose. It will not delete files, and it
will not make purchases, payments, or bookings on your behalf: booking
and market commands open the right page so you finish the action
yourself. Closing an app is a graceful request, so unsaved work still
prompts you to save. See [GUARDRAILS.md](GUARDRAILS.md) for the full
list of what it will and will not do. Command recognition is
English-only for now.

## Notes go to Obsidian

Point WhispLocal at your [Obsidian](https://obsidian.md) vault in
Settings (Obsidian vault, Browse) and you can say "take a note ..." in
voice control mode. Notes are appended to a dated file in a `WhispLocal`
folder inside your vault, with YAML frontmatter and timestamped bullets,
so they are tidy and easy to find:

```markdown
---
created: 2026-07-05
source: WhispLocal
tags: [whisplocal, voice-note]
---

# Voice notes — 2026-07-05

- **18:32** Buy milk tomorrow.
- **18:41** Call Dr. Mehta about the report.
```

The writer only ever touches files inside the vault folder you chose.

## Where the bar sits

By default the recording bar sits at the bottom-center of the screen. If
it gets in the way, Settings has an "On-screen bar position" option with
seven placements (each corner, each edge center, or screen center).

## It learns how you talk

WhispLocal keeps a small local profile (`adaptive.json`) and uses it to
get more accurate the more you dictate:

- Words you use often become recognition hints. Names, project terms,
  and jargon that a generic model would fumble start coming out right
  because the recognizer is told to expect them.
- When a transcription comes out wrong, open History, select it, and
  press Correct. The app diffs your fix against what it heard and
  applies that correction automatically from then on.
- It notices which languages you actually dictate in. Automatic language
  detection is unreliable on short clips, so when detection is unsure,
  WhispLocal retries with your usual language.

In voice control mode it also learns your habits: which apps you open,
what you look up, and which commands you use. Say "what do you know about
me" and it writes a profile to your Obsidian vault (`WhispLocal/
Profile.md`), refreshed automatically as you go. Your most-used app names
are fed back into the recognizer so they transcribe better over time.

This is a personalization layer on top of the recognizer, not neural
network training, which no laptop CPU could do. In practice it is the
part of accuracy you can actually feel: your own words, apps, and
languages. It stays on your disk, can be turned off in Settings, and
deleting `adaptive.json` resets it.

## Dictating in other languages

Pick your language from the tray (Language menu) or Settings instead of
relying on auto-detection; it is faster and much more reliable for short
dictations. For Hindi, Bengali, Tamil, Telugu, Marathi, Gujarati, Urdu,
and Punjabi, WhispLocal prompts the model in the native script, so you
get देवनागरी rather than a Latin transliteration. The multilingual
models (`tiny`, `base`, `small`, no `.en` suffix) handle non-English
speech, and `small` is noticeably better than `base` for Hindi if you
can accept the extra couple of seconds.

## Privacy

- Transcription happens on your CPU. The app has no telemetry, no
  account system, and makes no network requests while running.
- Models are downloaded from Hugging Face once, when you first select
  them. Nothing is uploaded.
- History is stored in plain text in `history.jsonl` next to the app,
  so the History window can show it. Turn it off in Settings or delete
  the file whenever you want.
- The personalization profile in `adaptive.json` contains word
  frequencies, language counts, and your corrections. Same rules: local
  only, optional, deletable.
- The default insert method puts the dictated text on the clipboard
  briefly and then restores what was there before. If you turn off
  clipboard restore, the dictated text stays on the clipboard. The
  `type` insert method avoids the clipboard entirely.
- Push-to-talk anywhere in the OS requires a keyboard hook. The hook is
  only used to watch for the hotkeys you configured; keystrokes are not
  recorded or stored.

## Development

```
venv\Scripts\python.exe -m unittest discover -s tests
```

`debug.bat` runs the app with a console attached so you can watch for
errors. At runtime, errors go to `whisp.log`, which rotates itself.
Pull requests are welcome.

## Troubleshooting

- Text does not appear in some apps: programs running as Administrator
  ignore input from normal processes. Run WhispLocal as administrator too.
- An app blocks pasting: switch the insert method to `type` in Settings.
- Wrong microphone: pick the right one in Settings.
- It will not start: run `debug.bat` and read the error, or check `whisp.log`.

## License

[MIT](LICENSE), © ROHITCRAFTSYT
