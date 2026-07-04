# Changelog

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
