# Changelog

## 2.8.0 — 2026-07-05

### Added
- "Open X" jumps to an already-open window instead of opening a duplicate
  or searching for the phrase. For an installed app it focuses the app's
  own window (ignoring browser tabs that merely mention the name); for a
  site it focuses the open tab. New "switch to / focus X" intent.
- Trailing descriptions are stripped, so "open youtube which is already
  open", "open comet that is running", and "open youtube on chrome" all
  resolve to the bare name.
- Built-in proper-noun hints so names transcribe correctly. "Claude" is
  no longer heard as "cloud"; GitHub, OBS, Spotify, and others too.
- Many more recognized web services for "open X" (Reddit, LinkedIn,
  Wikipedia, Drive, Docs, Calendar, Outlook, Teams, Gemini, and more).

### Fixed
- Saying "open <app> which is already open" no longer web-searches the
  whole sentence.

## 2.7.0 — 2026-07-05

### Fixed
- Microsoft Store / UWP apps (Spotify, WhatsApp, and others) are now
  detected and launched. Previously only classic Start Menu shortcuts
  were indexed, so a Store-installed app was reported as "not installed"
  and opened on the web. The index now also reads Get-StartApps and
  launches UWP apps by their AppUserModelID.

### Added
- "Play <app>" opens the app when it is installed (so "play spotify"
  opens the Spotify app), and only searches for music when the name is
  not an installed app.
- Reinforcement: when a spoken name matches more than one app, the one
  you have opened most often wins, learned from your usage over time.

## 2.6.0 — 2026-07-05

### Added
- Music commands: "play some music", "play <song>", "play <song> on
  spotify/youtube". Bare "play"/"pause" still work as media keys.
- Self-correcting commands: a misheard command gets a second pass that
  fixes the leading verb ("oben" -> "open") or matches the whole phrase
  to the closest known command before giving up.
- Command recognition is biased toward command verbs and your own app
  names, so commands transcribe more reliably.
- Habit learning: WhispLocal records which apps you open, what you look
  up, and which commands you use (locally, in adaptive.json). Your app
  names feed back into the recognizer over time.
- "What do you know about me" / "update my profile" writes a formatted
  Profile.md to your Obsidian vault, and it refreshes automatically every
  20 commands. Sandboxed to the vault like notes.

### Fixed
- "Play music" and similar no longer report "did not understand".

## 2.5.0 — 2026-07-05

### Changed
- "Open X" now checks whether the app is installed first. If it is, the
  app opens; if it is not, it opens on the web (the known web version, or
  a web search). No popup.
- Downloading only happens when you explicitly say "download X" or
  "install X". Say "open X in web" (or "... website") to force the web
  version even when the app is installed.

### Removed
- The download confirmation popup, in favor of the simpler
  installed-then-app, otherwise-web behavior above.

## 2.4.0 — 2026-07-05

### Changed
- App-name matching is more accurate and no longer opens the wrong app.
  It matches whole words of a shortcut ("obs" -> OBS Studio, "code" ->
  Visual Studio Code) and only falls back to fuzzy matching for longer
  names, so genuinely missing apps are recognized as missing instead of
  resolving to something unrelated.
- When an app is not installed, WhispLocal now asks with a Yes/No popup
  before opening a download page, instead of opening a browser tab
  automatically.

### Fixed
- Installed apps that previously fell through to "not found" now launch.

## 2.3.0 — 2026-07-05

### Added
- Close apps by voice ("close chrome", "quit spotify"). Uses a graceful
  window close, never a force-kill, so unsaved-work prompts still appear.
  The shell, taskbar, and WhispLocal itself are never targeted.
- Download suggestions: asking to open an app that is not installed opens
  its official download page (or a download search) instead of failing.
- Obsidian integration: set a vault path in Settings and say "take a
  note ..." to append a formatted, timestamped note to a dated file
  inside the vault. Writing is sandboxed to the vault folder.
- Information commands: "look up ...", "find market data for ...",
  "stock price of ...", and "book a table at ..." open the relevant page.
  No autonomous purchases, payments, or bookings are ever made.
- Repositionable on-screen bar: choose from seven placements in Settings
  instead of always bottom-center.
- Fancier waveform: bars now use an amplitude gradient and the pill has a
  two-tone edge.
- GUARDRAILS.md documenting the data-protection rules.

### Fixed
- "close chrome" and similar no longer report "did not understand".

## 2.2.0 — 2026-07-04

### Added
- Voice control mode: a second mode next to dictation, switchable from
  the tray (Mode menu) or usable in parallel through its own hotkey.
  Spoken commands are parsed and executed locally: open apps (indexed
  from the Start Menu), open sites and folders, web and YouTube search,
  type text, press key combinations, volume and media control, window
  management, scrolling and clicking, screenshots, lock screen, and a
  delayed, voice-cancellable shutdown.
- Spoken confirmations through the built-in Windows speech engine
  (toggle in Settings).
- Command feedback messages in the on-screen pill; green indicator while
  listening for a command.

## 2.1.0 — 2026-07-04

### Added
- Local personalization engine (`adaptive.json`): learns your vocabulary
  from accepted dictations and feeds it to the recognizer as hotwords,
  learns corrections you teach it in the History window (Correct…), and
  learns which languages you dictate in. Runs entirely on disk; can be
  turned off in Settings; delete the file to reset.
- Language quick-switch in the tray menu.
- Low-confidence language detections retry pinned to your usual language.
- Native-script prompts for Hindi, Bengali, Tamil, Telugu, Marathi,
  Gujarati, Urdu, and Punjabi, so transcriptions come out in the right
  script instead of Latin transliteration.

### Fixed
- The `type` insert method now sends OS-level unicode events, so scripts
  not on your keyboard layout (Devanagari and others) type correctly.
- Vocabulary learning handles scripts with combining marks.
- Switching language or accuracy no longer reloads the model.

## 2.0.0 — 2026-07-04

### Added
- Live waveform visualization in the floating status pill, driven by real
  microphone levels, with per-mode status dots (hold / locked / translate).
- Translate mode: a second hotkey that transcribes speech in any language
  and types the English translation.
- Settings window (model, language, microphone, hotkeys, insert method,
  beam size, cleanup toggles, custom dictionary) — applies live.
- History window with double-click-to-copy.
- Tray quick-switch between all six Whisper model variants.
- Pause-dictation tray toggle.
- Single-instance guard.
- App icon plus Desktop / Start Menu shortcut installer
  (`install_shortcuts.bat`) — fully silent launch, no console window.

## 1.0.0 — 2026-07-04

- Initial release: hold-to-talk / tap-to-lock dictation with
  faster-whisper (int8, CPU), filler-word cleanup, custom dictionary,
  clipboard-paste insertion, tray icon, sound cues, dictation history.
