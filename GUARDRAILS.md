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
  X" and "find market data for Y" open the relevant page so *you*
  complete the action. WhispLocal never enters payment details or
  submits an order.
- **Closing an app is graceful, never a force-kill.** "Close Chrome"
  sends a normal close request, so if you have unsaved work the app
  still shows its save prompt. The Windows shell and taskbar and
  WhispLocal itself are never targeted.
- **No file deletion.** There is no voice command that deletes files.
- **Shutdown is delayed and cancellable.** "Shut down the computer"
  waits 60 seconds and announces that "cancel shutdown" stops it.
- **Notes cannot escape the vault.** The note writer refuses any path
  that would resolve outside the folder you configured, and it will not
  create a vault in an arbitrary place.

## Things to know

- Voice control only runs while you are in voice control mode (or holding
  the voice control hotkey). It is not always listening.
- Command recognition is a fixed set of patterns, not an open-ended
  agent. If it does not recognize a phrase it says so and does nothing,
  rather than guessing at a destructive action.
- If you want to review what was done, every command and its result is
  written to `whisp.log` and to your dictation history.

## Turning things off

- Voice replies: Settings, "Speak confirmations".
- History: Settings, "Save dictation history".
- Learning profile: Settings, "Learn my vocabulary and languages", or
  delete `adaptive.json`.
- Notes: leave the Obsidian vault path blank in Settings.
