# Whisp Web — Full Product & Build Plan

Working codename: **Cue** (placeholder — see §11 naming). Public name TBD.
Foundation: the existing WhispLocal daemon (v2.x). Bridge design: `docs/BRIDGE_SPEC.md`.
Benchmark to beat: Mirage (`trymirage.app`) — a cloud, text-command, page-appearance agent.

---

## 1. One-line thesis

> **Mirage changes how the web *looks*, by typing, in the cloud.
> Cue changes what the web *does* — by voice, on your own machine.**

We are not building a Mirage clone. We are building a **voice-first, on-device
operator** for the browser *and* the whole computer, on top of an engine that
already does the hard part (mic, speech-to-text, a 1,800-line intent grammar,
local learning, and real safety guardrails). Mirage would have to rebuild its
entire architecture to match the two things that matter most here — voice and
privacy. That is the moat.

---

## 2. Why this wins (the structural argument)

Mirage's architecture forces three permanent constraints. Each is a lane we own:

| Mirage is structurally… | …so Cue is |
|---|---|
| **Cloud** (page content goes to their model) | **On-device** — nothing leaves the machine |
| **Text-command** (you type each tweak) | **Voice-first** — you speak, hands-free |
| **Browser-only** (touches the current page) | **Browser + OS** — one mic drives page *and* system |

These aren't features Mirage can bolt on in a sprint — they're the opposite of
its foundations. That's what makes the advantage durable rather than cosmetic.

---

## 3. The 10 ways Cue outperforms Mirage

Each is concrete, distinct from Mirage, and already backed by code you own.

### 1. Voice-first, not type-first
Mirage makes you *type* every instruction. Cue's primary surface is push-to-talk
(your existing global hotkey) — "hide the sidebar," "summarize this," "reply
saying I'll send it Friday." Reuses `audio.py` + `transcriber.py` end to end.
**Why it's 10x:** speaking a change is faster than composing a prompt, and works
while your hands are on other things. It also unlocks the three markets below
(accessibility, multitasking, mobile-adjacent) that a text box can't.

### 2. 100% on-device / private
Mirage is a cloud agent — your page content, and what you're doing on it, is sent
to their servers. Cue runs Whisper and the intent engine locally; the page text
for "summarize this" goes only to an on-device model. **Why it's 10x:** it's the
one claim Mirage cannot make. "Nothing you say or read leaves your computer" is a
headline, a trust wedge, and a compliance story (works for lawyers, clinicians,
finance) — and it's already true in your `SECURITY.md` / README "Why local."

### 3. One mic, three targets (browser + OS unification)
Mirage stops at the page boundary. Cue already controls the *system* —
`commands.py` opens apps, manages windows, controls media/volume/brightness,
takes notes, locks/restarts. The same push-to-talk that reshapes a web page can
open Spotify or save a note. **Why it's 10x:** users don't think in terms of
"browser vs OS"; they think "do the thing." Cue is the only one that spans both.

### 4. Instant, offline latency
Mirage waits on a cloud LLM round-trip for every tweak. Cue's pattern matcher
(`parse()`) resolves the common cases in microseconds with no network; the local
LLM is only a background fallback for novel phrasing (`locallm.py`), and even
then its output must parse. **Why it's 10x:** the difference between "spoke →
done" and "typed → spinner → maybe."

### 5. Adaptive local learning that compounds
Mirage regenerates from scratch each time. Cue's `adaptive.json` already learns
your vocabulary, which apps you mean, the languages you speak, and corrections
you teach in History — and it gets *more* accurate the more you use it, all on
disk, all private. **Why it's 10x:** personalization that accrues and never
leaves your machine, vs stateless cloud calls.

### 6. Deterministic and safe by default
Mirage's "the agent rewrites the page" is nondeterministic and can silently
break a site. Cue is a deterministic intent engine with hard guardrails
(`GUARDRAILS.md`): never transacts, never deletes, never auto-submits a form,
refuses credential/payment fields. The LLM never executes directly. **Why it's
10x:** trust. An agent you can predict is an agent you'll actually leave on.

### 7. Voice routines (persist actions, not looks)
Mirage persists a page's *appearance*. Cue persists *behavior*: extend the
existing compound-command splitter (`_split_commands`) into named, replayable
routines — "my morning" = open inbox + hide newsletters + summarize the top
three. Stored in `adaptive.json`, triggered by voice. **Why it's 10x:** a saved
workflow is worth far more than a saved skin, and it's a primitive Mirage
doesn't have.

### 8. Context-aware dictation (a category Mirage lacks entirely)
Mirage does no dictation. Cue dictates into *any* field, and because the bridge
can read page context, "reply saying I'll send it Friday" becomes a full,
appropriate reply — tone and length adjustable by voice. **Why it's 10x:** it's
not a better version of a Mirage feature, it's a whole capability they don't
offer, and it's your original product's core strength.

### 9. Hands-free / accessibility mode
A genuinely underserved market Mirage ignores: RSI, motor impairment,
multitasking, low-vision (pairs with "bigger text everywhere" + summarize).
Voice + local model + your guardrails make Cue credible here where a cloud text
agent isn't. **Why it's 10x:** a defensible, mission-aligned niche with low
competition and high loyalty — and it reads as principled, not derivative.

### 10. Multilingual, including Indian languages
`transcriber.py` already outputs native scripts (Hindi, Bengali, Tamil, Telugu,
Marathi, Gujarati, Urdu, Punjabi). Mirage is English-command only. **Why it's
10x:** a massive market that no comparable tool serves — dictate and command the
web in your own language, offline.

**Bonus structural edge — economics.** Because inference is local, Cue has ~no
per-use marginal cost. You can offer a genuinely generous free tier that a
cloud-metered competitor structurally cannot match, and charge for sync,
routines, and the system companion instead of for tokens.

---

## 4. Feature map

**Tier 0 — Foundation (already built, reused):** offline STT, dictation into any
field, the full voice-control grammar, adaptive learning, Obsidian notes,
guardrails, tray + settings + history.

**Tier 1 — Browser surface (Phase 0–1, the MVP):**
- Voice page tweaks: hide / restyle / bigger text / declutter.
- Summarize & read: on-device summary of the current page/article/selection.
- Context-aware dictation: page-aware replies and inserts.
- Persisted per-domain tweaks (`tweaks.json`), applied before paint.
- In-page overlay mirroring the tray recording/feedback states.

**Tier 2 — Agency (Phase 2):**
- Voice routines: record, name, replay multi-step workflows.
- Cross-tab actions with a preview/confirm + undo step.
- Skill/routine packs: export/import shareable bundles (action-based sharing).
- Ambient adaptation: Cue notices repeated behavior and *offers* a one-tap
  permanent tweak ("You always skip Shorts — hide them for good?").

**Tier 3 — Ecosystem (Phase 3+):**
- In-page push-to-talk (mic in the extension, Flow B of the bridge spec).
- Optional signed native companion for deeper system control.
- Routine marketplace with creator payouts.
- Cross-device sync of tweaks/routines (encrypted, opt-in).

---

## 5. Architecture (summary; full detail in BRIDGE_SPEC.md)

```
Browser Extension (MV3, TS)         WhispLocal daemon (Python, existing)
  service worker  ── WS 127.0.0.1:48918 ──  bridge.py  (WS server + PageProxy)
  content script  (ops, overlay, tweaks)     commands.py  ("page" kind)
  offscreen mic   (Phase 1 only)             audio.py / transcriber.py (mic+STT)
                                             adaptive.json / tweaks.json
```

Key point: the daemon keeps the mic, STT, grammar, learning, and safety. The
extension is hands + eyes + face. New surface = one module (`bridge.py`) + one
command kind (`page`) + a thin extension. See the spec for the protocol,
security (localhost + token + origin allowlist), and the file-by-file changes.

---

## 6. UX / interaction design

- **Primary surface:** push-to-talk (hold hotkey) — no UI to hunt for. An
  in-page pill overlay (reuse the tray overlay states: recording → thinking →
  done) shows what's happening, bottom-center by default (matches current app).
- **Confirm-before-act:** any page action tagged destructive/submitting shows a
  small inline confirm with a 1-click undo. Non-negotiable for trust.
- **Feedback:** spoken (existing `speak()`), plus the overlay. Optional silent
  mode.
- **Settings:** a "Browser bridge" panel (on/off, pairing token, connection
  status) added to the existing `settings.py` window — no new app to learn.
- **Discovery:** "what can I say?" already exists (`help` intent); extend it with
  page examples so users learn the browser verbs by voice.

Design language must be **distinct from Mirage** — voice/operator metaphor, own
color system, no mirror/"reshape/see-the-web" language (see §11).

---

## 7. Tech stack

| Layer | Choice | Note |
|---|---|---|
| Daemon | existing Python 3.11 + faster-whisper (int8, CPU) | unchanged core |
| Bridge | `websockets` on 127.0.0.1, token + origin auth | new `bridge.py` |
| Extension | Manifest V3, TypeScript, Shadow-DOM overlay | least-privilege perms |
| On-device summary | local GGUF via `llama-cpp-python` (already a backend in `locallm.py`) | reuse the backend, larger model optional |
| Persistence | JSON on disk (`tweaks.json`, `adaptive.json`) | user-owned, deletable |
| Sync (later) | end-to-end encrypted, opt-in | never required |

No cloud dependency is introduced anywhere in Tiers 0–2.

---

## 8. Data & privacy model (the moat, stated as policy)

- All speech, page text, and learning stay on the device by default.
- No account required to use the core product.
- Network is touched only to (a) download a model once and (b) opt-in sync.
- Everything user-generated is a plain local file the user can delete.
This is both the ethical stance and the single hardest thing for Mirage to copy.

---

## 9. Monetization

- **Free (local):** dictation, voice control, page tweaks, a cap of N saved
  routines. Generous — enabled by ~zero marginal cost.
- **Pro (~$8–15/mo):** unlimited routines, cross-tab agent, encrypted cross-device
  sync, premium/local large model, priority support.
- **Companion (higher tier):** signed native helper for deeper system control.
- **Marketplace (later):** revenue share on routine/skill packs.
Charge for sync, scale, and convenience — never for the privacy itself.

---

## 10. Roadmap

| Phase | Goal | Exit criteria |
|---|---|---|
| **0** | Bridge + `page` kind, no browser audio | "hide the cookie banner", "summarize this", "bigger text", persisted "hide shorts", all via global hotkey, offline (see BRIDGE_SPEC §10) |
| **1** | Polished MVP | Context-aware dictation, in-page overlay, settings panel, 10 solid page verbs, private beta waitlist |
| **2** | Agency | Voice routines, cross-tab + preview/undo, skill packs, ambient adaptation |
| **3** | Ecosystem | In-page push-to-talk, native companion, sync, marketplace |

Ship Phase 0 to a small waitlist fast — it already beats "install yet another
extension" on day one because the runtime exists.

---

## 11. Naming, brand, and anti-copy guardrails

- **You're clean:** Cue is built on your own MIT-licensed engine, not Mirage's
  code. Ideas/categories aren't ownable; your execution (voice + on-device) is
  genuinely different regardless.
- **Keep the surface distinct:** new name, logo, palette, and voice. Avoid
  mirror/reflection/"reshape"/"see the web your way" language entirely.
- **Name direction** (voice/operator, not optical): *Cue, Relay, Verse, Utter,
  Chime, Wield.* Run a trademark + domain check before committing.
- Don't import or reference their assets, copy, or design.

---

## 12. Metrics

- Activation: % of installs that complete a first successful voice action.
- Depth: page actions/day, routines saved, % using dictation.
- Retention: D7/D30, and % who keep it running at login.
- Trust: undo rate, confirm-decline rate (should trend down as trust builds).
- Market: language distribution, accessibility-mode adoption.

---

## 13. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Latency of voice+action feels slow | Pattern-match fast path (already there); on-device fallback bounded by timeout |
| Users distrust an "agent" | Deterministic engine + guardrails + confirm/undo, marketed as the product |
| Chrome Web Store scrutiny of broad host perms | Least-privilege manifest, clear rationale, activeTab where possible |
| Element resolution ("hide the X") is fragile | Heuristic in Phase 0, on-device embedding match in Phase 2; persist confirmed selectors |
| Scope creep into full OS agent | Win the browser voice niche first; native companion is a later, opt-in tier |
| Daemon install friction (vs one-click extension) | One-time setup already exists (`setup.bat`); pairing token flow kept simple; native-messaging auto-launch later |

---

## 14. Immediate next actions

1. Lock the `page` grammar + routing with pure `parse()` tests (`test_commands.py`).
2. Build `bridge.py` (WS + auth + `PageProxy`) against BRIDGE_SPEC.
3. Scaffold the `extension/` folder (manifest, `sw.js`, `content.js`) to load unpacked.
4. Wire the bridge into `app.py` and add the Settings panel.
5. Private beta: the four acceptance demos from BRIDGE_SPEC §10.
