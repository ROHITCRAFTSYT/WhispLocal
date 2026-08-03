# Guardrails and data protection

WhispLocal voice control can act on your machine, so it is built to be
predictable and to protect your data. Here is exactly what it will and
will not do.

## What stays on your machine

- Audio is transcribed locally. No speech or text is uploaded.
- The app makes no network requests on its own. The only time a browser
  opens is when you ask it to (open a site, search, look something up,
  open a download page) or when it downloads a speech model you selected.
- Notes are written only into your own Obsidian vault. History and the
  learning profile are plain files next to the app that you can delete.

## Actions that are intentionally limited

- **No autonomous purchases, payments, or bookings.** "Book a table at
  X", "find market data for Y", and "order monster from instamart" all
  open the relevant page — with the product already searched — so *you*
  review and complete the action. WhispLocal never enters payment
  details, clicks checkout, or submits an order. Ordering works for any
  site you name: known sites (Amazon, Flipkart, Instamart, Blinkit,
  Zepto, BigBasket, Swiggy, Meesho, JioMart…) get a direct product
  search; anything else falls back to a web search so the phrase always
  lands somewhere useful.
- **Closing an app is graceful, never a force-kill.** "Close Chrome"
  sends a normal close request, so if you have unsaved work the app
  still shows its save prompt. The Windows shell and taskbar and
  WhispLocal itself are never targeted.
- **No file deletion.** There is no voice command that deletes files.
- **Shutdown and restart are delayed and cancellable.** "Shut down the
  computer" / "restart the computer" wait 60 seconds and announce that
  "cancel shutdown" stops it. Sleep, hibernate, and turning off the
  display are instant but fully reversible — the machine comes back with
  nothing lost.
- **Notes cannot escape the vault.** The note writer refuses any path
  that would resolve outside the folder you configured, and it will not
  create a vault in an arbitrary place.

## Things to know

- Voice control only runs while you are in voice control mode (or holding
  the voice control hotkey). It is not always listening.
- Compound sentences ("open youtube and search for mr beast") are split
  into their individual actions, and the search is chained to the site
  that was opened — the app never strips spaces out of a sentence to
  build a URL, so a phrase can never be sent to a mangled domain.
- Command recognition is a fixed set of patterns, not an open-ended
  agent. If it does not recognize a phrase it says so and does nothing,
  rather than guessing at a destructive action.
- **Optional local-LLM fallback (off by default).** You can point Settings
  at a local model file (llama.cpp GGUF or an ONNX folder) to understand
  genuinely novel phrasing. The model runs entirely on this machine — it
  never sends your speech or commands anywhere — and it only runs after
  every fast pattern match has failed, on a background thread, so normal
  replies are never slowed. Critically, the model's reply must itself
  parse as a known command before anything happens: it cannot execute
  anything directly, so it cannot gain powers (purchases, deletions,
  force-kills…) that the pattern matcher does not have. Successful
  resolutions are remembered as learned phrases, so the same sentence is
  instant from then on.
- If you want to review what was done, every command and its result is
  written to `whisp.log` and to your dictation history.

## Turning things off

- Voice replies: Settings, "Speak confirmations".
- History: Settings, "Save dictation history".
- Learning profile: Settings, "Learn my vocabulary and languages", or
  delete `adaptive.json`.
- Local LLM fallback: uncheck "Use the local LLM…" in Settings (or clear
  the model path).
- Notes: leave the Obsidian vault path blank in Settings.
- Display controls (volume, brightness, turning off the display) apply
  to this machine only and always report what they did.

## What the system commands do

- **Volume**: "lower/raise the volume", "volume up/down", "set volume
  to 30", "increase volume by 20%" (reads the current level, applies
  the delta, clamped to 0-100), "mute/unmute". Volume steps use the
  media keys; exact and percentage levels set the volume via the
  Windows Core Audio API (the same control the volume flyout uses) and
  verify the change by reading it back — the app never announces a
  volume change that did not actually happen.
- **Brightness**: "brightness up/down", "set brightness to 50", "make
  it brighter/darker". Works on displays that report brightness through
  WMI (typically laptops); otherwise it says it cannot.
- **Battery**: "check battery" / "battery level" reads the charge and
  reports it — it never disables charging or the battery.
- **Display off**: "turn off the display" blanks just the screen; any
  keypress wakes it.
- **Sleep / hibernate / restart**: reversible (sleep/hibernate) or
  delayed-and-cancellable (restart), never a hard power cut.
