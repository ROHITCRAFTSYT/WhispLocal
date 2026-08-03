# Changelog

## 2.22.0 — 2026-08-03

### Fixed
- "Search mr beast in youtube" can no longer open a Google search for
  the whole phrase "mr. beast in youtube" under ANY whisper phrasing.
  The YouTube search grammar now accepts every way speech-to-text can
  phrase it: "google X in youtube", "look for X on youtube", "look up
  X in youtube", "find X in youtube", "show me X in youtube", "in
  the youtube", "in youtube app", "in youtube.com", "you tube" split
  into two words, the short "yt", inverted "search in youtube X",
  "open youtube search X" (whisper drops the "and"), and even a bare
  "X in youtube" with the verb dropped (resolved via the fuzzy path).
  All open YouTube results directly; none can fall through to Google.
- "You tube" written as two words is now rejoined during normalization,
  so every youtube intent (open, search, play) sees the canonical token.

## 2.21.0 — 2026-08-02

### Fixed
- "Volume set to X%" no longer announces a change that never happened.
  The old implementation used winmm's waveOutSetVolume, which only
  drives the legacy WAVE_MAPPER device — on modern Windows that is often
  not the endpoint you actually hear, so the call could return success
  while the audible volume stayed put. Exact levels and "increase/
  decrease volume by N%" now use the Windows Core Audio API
  (IAudioEndpointVolume) — the same control the volume flyout uses — and
  verify the change by reading the level back afterwards. If the volume
  did not actually move (endpoint missing, device rejecting the change,
  read-back not confirming), the app says so instead of claiming success.
- Volume is read back from the real endpoint too, so "increase volume
  by 20%" computes the delta from the level you actually hear, not the
  legacy wave device's.

## 2.20.0 — 2026-08-02

### Fixed
- "Search mr beast in youtube" no longer falls through to a bare Google
  search for the whole phrase "mr. beast in youtube". The YouTube
  search grammar now accepts whisper's "in youtube" (not just "on
  youtube"), plus "search in/on youtube for X" and "youtube search X"
  — all open YouTube results directly. The fuzzy fallback and the
  local-LLM prompt know these phrasings too.

## 2.19.0 — 2026-08-02

### Added
- Percentage volume changes: "increase volume by 20%", "lower the
  volume by 15", "volume up by 5%", "make it louder by 10%" — and the
  gerund forms whisper often produces ("increasing volume by 20%"). The
  current level is read via winmm and the delta is applied and clamped
  to 0-100, so the new level is real, not guessed.
- The same relative "by N" support for brightness: "increase brightness
  by 20%", "brightness down by 10".

### Fixed
- "Did not understand: increasing volume by 20%" no longer happens —
  that exact phrasing (and its siblings) now adjusts the volume.

## 2.18.0 — 2026-08-02

### Fixed
- "Open youtube and search for mr beast" no longer opens a mangled URL
  like `youtubeandsearchformr.beast`. The root cause was threefold:
  whisper's comma transcription ("open youtube, search for mr. beast")
  was not recognized as a compound sentence, so the whole phrase fell
  through to the generic "open" pattern; the period in "Mr." then made
  it look like a URL; and the URL executor stripped ALL spaces to build
  a domain. Compound splitting now handles commas (with or without a
  space before them), "and then", and "&"; a target with spaces is
  never treated as a URL; and a phrase that still reaches the URL path
  becomes a web search instead of a mangled address.
- Compound sentences now chain: "open youtube and search for mr beast"
  opens YouTube AND searches YouTube for the query (not a bare Google
  search). Works for youtube, google, amazon, flipkart, spotify, reddit,
  github, wikipedia, stack overflow, maps, and bing.

### Added
- Successful repairs are now remembered: if the engine fixes a misheard
  command (e.g. "oben chrome" -> "open chrome") and it works, the
  correction is learned via the same phrase-learning path, so the exact
  same mishearing resolves instantly next time.
- The local-LLM prompt now includes compound and "search X on youtube"
  examples so novel phrasings of these still resolve.

## 2.17.0 — 2026-08-02

### Added
- Natural volume control: "lower my computer's volume", "raise the
  volume", "set volume to 30", "volume 50 percent", "max/min volume",
  "mute/unmute" — the phrasings that previously answered "not
  understood" now actually change the system volume. Exact levels set
  the volume via winmm (no extra dependencies).
- Screen brightness: "brightness up/down", "set brightness to 50",
  "make it brighter/darker". Works on WMI-capable displays (typically
  laptops) and reports when it cannot.
- More computer tasks that used to be "not understood": "restart the
  computer" (delayed 60 s and cancellable like shutdown), "sleep",
  "hibernate", "check battery" (reports the charge level), "turn off
  the display" (blanks the screen; any key wakes it).
- Voice-reachable Windows Settings pages: "open wifi settings", "open
  bluetooth settings", "open display settings", "open night light
  settings", "open sound settings", and more, via ms-settings: URIs.
- The local-LLM fallback prompt now knows the new canonical commands
  (volume levels, brightness, battery, restart…), so novel phrasings of
  these still resolve through it.

## 2.16.0 — 2026-08-02

### Added
- Optional local-LLM fallback for genuinely novel commands. When every
  fast pattern match fails, the app can ask a local model (llama.cpp GGUF
  via llama-cpp-python, or an ONNX text-generation folder) to restate the
  phrase as a known command. Off by default; configure a model path in
  Settings (with a Test button) and enable the checkbox.
- The fallback cannot add latency: the model runs only after every fast
  path (learned phrases, parse, repair, fuzzy suggest) has failed, on a
  background thread with a timeout — the immediate reply is not held up.
  The model's answer must itself parse as a known command before anything
  runs, so it cannot gain powers the pattern matcher does not have, and
  nothing is ever sent off the machine.
- Successful resolutions are learned as phrases, so the same sentence is
  answered instantly from then on (no model call).

## 2.15.0 — 2026-08-02

### Added
- The brain learns from History corrections. When you correct a voice
  command that was misunderstood (e.g. "open chrom" → "open chrome"),
  the heard phrase is stored and resolved automatically next time —
  exactly, or fuzzy-close ("open chrrm"). Command corrections are
  detected in the History window and taught as whole phrases (heard →
  corrected), separate from dictation's word-level corrections.
- Learned phrases persist in adaptive.json, survive restarts, count
  toward the learning profile, and their words become transcription
  hotwords so the phrase is heard correctly in the first place.
- The History correction dialog now shows only the heard command (not
  its result note) and confirms "…will now work" for commands.

## 2.14.0 — 2026-08-02

### Added
- "Order X from Y" commands for any site you name: "order monster from
  instamart", "buy milk on blinkit", "add monster to my cart on amazon".
  Known ordering sites get a deep link straight to their product search
  with your item pre-filled (Amazon, Flipkart, BigBasket, Instamart/
  Swiggy, Blinkit, Zepto, Meesho, JioMart), and any other site falls
  back to a web search — so the phrase always lands somewhere useful.
  Compound orders work too: "order monster from instamart and red bull
  from blinkit" opens both.
- The site you name is learned in your profile (Settings → learning),
  so ambiguous mentions resolve to the site you use most.

### Guardrail
- Consistent with the app's no-autonomous-transactions rule, ordering
  opens the product search page and stops there — the item is one tap
  from your cart, but WhispLocal never clicks checkout or submits an
  order. See GUARDRAILS.md.

## 2.13.0 — 2026-08-02

### Added
- A smarter command brain that understands more of what you actually say,
  instead of answering "Did not understand":
  - Compound commands: "switch tab and open settings" now runs both
    actions (previously rejected as a single unknown phrase). "Open
    notepad and open paint" launches both apps, and a bare noun inherits
    the verb ("open paint and notepad" opens both); "take a note buy
    milk and eggs" is still one note.
  - Tab navigation: "switch tab", "next tab", "previous tab", "go back
    a tab", "switch to tab 3" (Ctrl+1..9), "switch to the last tab".
  - "Open settings" now opens WhispLocal's own Settings window (the
    assistant's settings); "open windows/system settings" still opens
    Windows Settings.
  - "Open a new tab" and "close this tab" are recognized shortcuts.
- Fuzzy fallback instead of a blind refusal: unparseable phrases are
  matched to the closest known command ("switch to the next tab please"
  lands on tab switching), and truly unknown ones get a helpful reply
  listing real commands rather than a flat rejection.

### Performance
- The brain is pure string matching (precompiled regex + dict lookups,
  no I/O, no network, no model) and runs on the already-backgrounded
  command thread — a latency test parses ~24 phrases in well under
  50 ms, so the reply path is unchanged.

## 2.12.0 — 2026-08-02

### Added
- Automatic microphone selection: at startup the app now probes every
  input device with a short recording and picks the first one that
  delivers real audio (above the silence threshold) instead of trusting
  the system default — which can be a dead port or a muted device. The
  chosen mic is saved to Settings, and a new "Scan for best…" button in
  Settings re-runs the scan on demand. Toggle with the
  "Auto-select a working microphone at startup" option.
- `scan_mics()` in the audio module (used by both the startup scan and
  the Settings button); `mic_test.py --all` now reuses the same device
  filtering so the diagnostic and the app always agree.

### Fixed
- The auto-select scan never overrides a microphone the user chose
  manually, and never blocks startup — it runs in the background while
  the model loads.

## 2.11.0 — 2026-08-02

### Fixed
- Voice not being heard at all: the recorder previously demanded 16 kHz
  from the mic, which many Windows devices refuse (USB headsets, built-in
  arrays often only do 44.1/48 kHz). It now falls back to the device's
  native rate and resamples to 16 kHz for Whisper.
- A configured microphone name that no longer matches any device (it was
  renamed or unplugged) no longer fails every recording — it falls back
  to the system default.
- If the mic delivers no signal at all (muted, wrong device, or Windows
  privacy blocking access), the overlay now says "No voice detected — is
  the mic on?" instead of silently doing nothing, and the reason is
  logged to whisp.log.
- Microphone failures now log the full traceback and show a clear overlay
  message pointing at Settings → Microphone and Windows privacy.
- A failed stream open no longer leaves the recorder in a dead state —
  the next hotkey press retries instead of silently doing nothing until
  restart.
- Overlay messages wrap onto up to three lines instead of being cut off
  mid-sentence, so mic diagnostics stay fully readable.
- `rms()` treats NaN/inf levels as silence, so broken or loopback devices
  can never masquerade as a working mic.

### Added
- `mic_test.py`: a diagnostic that lists your input devices, records
  2 seconds from any of them, and prints the measured signal level — run
  it to see whether the mic works and at which sample rate.
- `mic_test.py --all` scans every microphone (skipping speakers and
  loopbacks) and names the best working device to pick in Settings.

## 2.10.0 — 2026-08-02

### Fixed
- Recording no longer loses the tail of your speech: the audio callback
  now synchronizes with stop(), and the frame list is swapped atomically
  instead of being cleared under the recorder thread.
- Two quick dictations can no longer interleave. Transcription runs are
  serialized, so a new clip never hits the model while the previous one
  is still inserting text.
- Hotwords (Claude, GitHub, your learned vocabulary…) are no longer
  dropped for Hindi, Bengali, Tamil and other primer languages; they are
  folded into the recognition prompt so names still transcribe correctly.
- "Take a note …" after a polite prefix ("please take a note …") no
  longer garbles the note body — the body is extracted from the original
  text, keeping your casing.
- "Press the escape key", "hit the enter key" and similar phrasings now
  work instead of being rejected as unparseable.
- "Turn up the volume" / "turn down the volume" are recognized.
- Closing an app no longer closes a whole browser window when the name
  only appears in a tab title ("close notepad" with a Notepad tab open
  in Chrome now closes Notepad, not Chrome). The browser itself is still
  closable ("close chrome").
- "Open chrome" (or any browser) now focuses the open browser window
  instead of launching a second instance, while still ignoring browser
  tabs that merely mention another app's name.
- Clipboard failures during insert now fall back to simulated typing
  instead of silently dropping the dictation.

## 2.9.0 — 2026-07-05

### Added
- "What's open" / "list windows" reports your open windows out loud.
- "Help" / "what can you do" lists the main things you can say.
- "Search YouTube for X" and "search X on YouTube" open YouTube results.
- Natural volume phrasings: "louder", "quieter", "turn it up/down".
- Media transport: "stop the music", "pause music", "resume".

### Changed
- The command pipeline waits briefly for the app index (which now
  includes Microsoft Store apps) to finish building, so a command issued
  right after startup no longer misses an installed app.

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
