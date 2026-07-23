# Security Policy

For what WhispLocal will and will not do by design — no purchases, no file
deletion, no force-kill, notes confined to the vault — see
[GUARDRAILS.md](GUARDRAILS.md). This file covers reporting a defect in those
guarantees.

## Supported versions

Fixes land on `main`. There are no maintained release branches.

## Reporting a vulnerability

Report privately through GitHub's
[security advisory form](https://github.com/ROHITCRAFTSYT/WhispLocal/security/advisories/new)
rather than opening a public issue. Expect an acknowledgement within seven days.

Include the affected module, the spoken phrase or config value that triggers
it, and what it caused. A recording is not needed — the transcribed text is
enough.

## Scope

In scope, in rough order of how much they matter:

- Any transcript that escapes the fixed command patterns in
  `whisp/commands.py` and reaches a shell, an interpreter, or a process
  launch. Command recognition is meant to be a closed set; anything that
  makes it open-ended is the most serious bug this project can have.
- A note path that resolves outside the configured Obsidian vault
  (`whisp/obsidian.py`), despite the containment check.
- A command that deletes or overwrites a file, force-kills a process, or
  performs an uncancellable shutdown — all four are supposed to be
  impossible.
- Clipboard handling in `whisp/inject.py`. The default strategy copies
  transcribed text over the clipboard and restores the previous contents
  afterwards; a path that leaks the saved clipboard, or leaves the
  transcript on it, is in scope.
- Anything written to `config.json`, the history file, or the learning
  profile that is later read back and executed rather than treated as data.
- Any outbound network request other than a model download or a browser
  navigation the user asked for.

Out of scope:

- Vulnerabilities in faster-whisper, CTranslate2, or the Windows APIs used
  for injection — report those to their maintainers.
- Transcription accuracy, including a misheard word that triggers a
  legitimate command. That is a recognition-quality issue; open a normal
  issue for it.
- Anyone with physical access to an unlocked machine being able to speak
  a command. WhispLocal is not a defence against someone at your keyboard.

## Model downloads

Selecting a model downloads weights from the Hugging Face Hub on first use.
Those weights are executable data from a third party. WhispLocal does not
verify them beyond what the Hub client does, so choose the standard published
models rather than an arbitrary repository name.

## Transcripts on disk

History and the learning profile are plain unencrypted files next to the
app, and they contain everything you dictated. On a shared or backed-up
machine, treat them as you would a notes file — delete them if you do not
want them kept. This is documented behaviour, not a vulnerability.
