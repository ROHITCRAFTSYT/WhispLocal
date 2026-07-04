# Changelog

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
