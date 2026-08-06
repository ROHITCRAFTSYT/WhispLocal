# WhispLocal ↔ Browser Bridge — Phase 0 Spec

Status: draft · Target: WhispLocal v2.x → first browser-extension release
Scope: the smallest change that lets the existing voice engine act **inside a web page**, while keeping everything on-device.

---

## 0. The key insight that makes Phase 0 small

The daemon **already owns the microphone and speech-to-text** (`whisp/audio.py`,
`whisp/transcriber.py`) and already runs persistently in the tray with a
localhost socket (`app.py`, port `48917`). The browser extension therefore does
**not** need to capture audio, run Whisper, or hold any model in Phase 0.

The extension is only three things:

1. **Hands** — apply a directive to the active tab (hide/restyle/click/fill).
2. **Eyes** — hand the daemon the current page's context when asked.
3. **Face** — render the same overlay/feedback the tray app speaks.

The mic, STT, intent grammar, learning, and guardrails all stay in the Python
daemon, unchanged. We add one new command *kind* (`page`) and one new module
(`bridge.py`). Nothing existing is rewritten.

```
┌─ Browser Extension (MV3, TypeScript) ─┐        ┌─ WhispLocal daemon (Python, existing) ─┐
│  service worker  ── WebSocket ────────┼──────► │  bridge.py  (NEW: WS server + PageProxy)│
│    holds the socket, routes ops       │ 127.   │       │                                 │
│  content script                       │ 0.0.1  │  commands.py  ("page" kind → PageProxy) │
│    applies ops, reads DOM, overlay    │ :48918 │  audio.py / transcriber.py  (mic + STT) │
│  tweak cache (per-domain)             │ ◄──────┤  adaptive.json / tweaks.json (learning) │
└───────────────────────────────────────┘        └─────────────────────────────────────────┘
```

---

## 1. Two data flows

### Flow A — global hotkey (Phase 0 primary; reuses everything)

```
user presses global hotkey anywhere
  → daemon records + transcribes            (audio.py, transcriber.py — unchanged)
  → CommandEngine.run(text)                 (commands.py — unchanged path)
      → parse() yields ("page", directive)  (NEW intents)
      → _execute("page", directive)         (NEW: delegates to PageProxy)
          → bridge sends page_action to the extension, awaits page_result
  → speak(feedback)                          (commands.py speak() — unchanged)
```

No audio crosses the bridge. The browser is a remote executor for page ops only.

### Flow B — in-page push-to-talk (Phase 1, not required for Phase 0)

The extension captures mic audio in an offscreen document and streams PCM to the
daemon over the same socket (`transcribe` message). Everything downstream is
identical to Flow A. Deferred — listed here so the protocol below already
reserves the message type.

---

## 2. Transport & security

- **WebSocket server** bound to `127.0.0.1:48918` only (never `0.0.0.0`), run in
  a dedicated thread with its own asyncio loop (the tk main loop is untouched).
  Recommend the `websockets` package. Keep the existing `48917` single-instance
  TCP guard as-is; the WS port is separate.
- **Origin allowlist**: reject any handshake whose `Origin` is not
  `chrome-extension://<our-id>` (and the Firefox/Edge equivalents). Store the
  allowed IDs in `config.json`.
- **Shared token**: on first launch the daemon writes a random 32-byte hex token
  to `%APPDATA%\WhispLocal\bridge_token`. The extension reads it once during a
  user-initiated "Connect" action (the user pastes it, or we expose it via a
  local `GET /pair` one-time endpoint). Every WS message after `hello` must carry
  the token. This stops any other localhost page from driving the daemon.
- **Local only, no network**: the bridge never makes an outbound request. This
  preserves the project's core promise (README "Why local", `SECURITY.md`).

---

## 3. Message envelope

All frames are JSON text. One envelope, correlated by `id`:

```jsonc
{
  "v": 1,               // protocol version
  "id": "c7f3…",        // uuid; responses echo the request id
  "type": "page_action",// see table below
  "token": "…",         // required on every frame after welcome
  "payload": { … }      // type-specific
}
```

| type           | dir      | payload                                             | reply         |
|----------------|----------|-----------------------------------------------------|---------------|
| `hello`        | ext → d  | `{ extId, version }`                                 | `welcome`     |
| `welcome`      | d → ext  | `{ daemonVersion, capabilities[] }`                  | —             |
| `ping`/`pong`  | both     | `{}`                                                 | `pong`        |
| `get_context`  | d → ext  | `{ want: ["url","title","selection","main_text"] }` | `context`     |
| `context`      | ext → d  | `{ url, title, selection, main_text }`              | —             |
| `page_action`  | d → ext  | **directive** (see §4)                              | `page_result` |
| `page_result`  | ext → d  | `{ ok, feedback, data? }`                            | —             |
| `tweaks_for`   | ext → d  | `{ url }`  (on navigation)                          | `tweaks`      |
| `tweaks`       | d → ext  | `{ rules: Rule[] }`  (persisted per-domain)         | —             |
| `overlay`      | d → ext  | `{ state, message, ok }`  (mirror of tray overlay)  | —             |
| `speak`        | d → ext  | `{ text }`  (optional in-page TTS; off by default)  | —             |
| `transcribe`   | ext → d  | `{ pcm16, sampleRate }`  (Flow B, Phase 1)          | `command`ack  |

Timeouts: the daemon abandons a `page_action` after **4 s** and returns
`(False, "the page didn't respond")`. `get_context` after **1.5 s**.

---

## 4. The `page` command kind

### 4.1 Directive schema (daemon → extension)

```jsonc
{
  "op": "hide" | "restyle" | "read" | "click" | "fill" | "scroll" | "summarize",
  "target": "cookie banner",     // natural-language element description
  "value": "…",                  // op-specific (fill text, restyle spec)
  "persist": false,              // save as a per-domain rule?
  "confirm": true                // extension must get a user OK before acting
}
```

The extension resolves `target` to an element (Phase 0: heuristic —
`aria-label`/role/text match + a small set of known selectors for
cookie/nav/sidebar; Phase 2: an on-device embedding match). It returns
`page_result` with `ok`, a short `feedback` string the daemon speaks, and for
`read`/`summarize` the extracted `data`.

### 4.2 Grammar additions to `parse()` (commands.py)

Add these **before** the generic `open`/`search` fallbacks so page verbs win
when a browser is frontmost. Keep them pure (no side effects) like the rest of
`parse()`:

```python
# --- page tweaks (browser surface) -----------------------------------------
m = re.match(r"(?:hide|remove|get rid of)\s+(?:the\s+)?(.+)", t)
if m:
    return ("page", {"op": "hide", "target": m.group(1).strip(),
                     "persist": False}, None)

if re.match(r"(?:hide|remove)\s+.+\s+(?:for good|permanently|"
            r"on this site|everywhere)$", t):
    # same but persist=True — split out in the real impl
    ...

if re.match(r"(?:bigger|larger|increase the) text", t):
    return ("page", {"op": "restyle", "target": "body",
                     "value": "font-scale:+2"}, None)

if re.match(r"(?:summari[sz]e|tl;?dr)\s+(?:this\s+)?(?:page|article)?$", t):
    return ("page", {"op": "summarize", "target": "main"}, None)

m = re.match(r"(?:read|extract|copy)\s+(?:the\s+)?(.+)", t)
if m:
    return ("page", {"op": "read", "target": m.group(1).strip()}, None)
```

Note the ambiguity with existing intents (e.g. `read` vs `lookup`): resolve it by
**routing context**, not grammar — only treat these as `page` ops when the
bridge reports a connected, frontmost browser (see §5). Otherwise let the phrase
fall through to today's behavior. This keeps the desktop experience identical
when no browser is in front.

### 4.3 `_execute` integration (commands.py)

Add one branch. It delegates to a `PageProxy` injected the same way `note_saver`
and `llm` already are:

```python
if kind == "page":
    if self.page is None or not self.page.connected():
        return False, ("Open the browser with the WhispLocal extension "
                       "to change a web page")
    ok, feedback, _data = self.page.run(arg)   # blocks up to 4s
    return ok, feedback
```

`CommandEngine.__init__` gains a `page=None` parameter (mirrors `llm=None`).
`app.py` constructs the `PageProxy` from the bridge and passes it in, exactly
like it wires `note_saver=self._save_note` today.

### 4.4 PageProxy (bridge.py) — request/response over the socket

The engine is synchronous; the socket is async. Bridge the two with a future
keyed by message id:

```python
class PageProxy:
    """Synchronous view of the async bridge for CommandEngine._execute.
    run() sends a page_action and blocks on the extension's page_result."""
    def __init__(self, bridge):
        self._bridge = bridge

    def connected(self):
        return self._bridge.has_client()

    def run(self, directive, timeout=4.0):
        if not self.connected():
            return False, "no browser connected", None
        fut = self._bridge.send_and_wait(
            {"type": "page_action", "payload": directive}, timeout)
        try:
            res = fut.result(timeout)          # concurrent.futures.Future
        except TimeoutError:
            return False, "the page didn't respond", None
        return res.get("ok", False), res.get("feedback", ""), res.get("data")
```

`bridge.send_and_wait` stores `id → Future` in a dict; the WS receive loop pops
the future when a `page_result` with that id arrives and calls
`fut.set_result(payload)`. The receive loop runs in the bridge's own asyncio
thread, so it never blocks tk or the command pipeline's `_process_lock`.

---

## 5. Routing: when is a phrase a page op?

The daemon must decide "browser op" vs "desktop op" cheaply. Phase 0 rule:

1. `parse()` may return a `page` kind (grammar above).
2. Before executing a `page` kind, `_execute` checks `self.page.connected()`
   **and** that a browser is the foreground window (reuse `_enum_windows()` +
   the foreground hwnd; a browser exe is already enumerated in `_BROWSER_EXES`).
3. If both true → route to the extension. If not → return the "open the browser"
   hint, or (better) re-run the phrase through the desktop grammar by treating
   the `page` match as a miss. Keep this fallback conservative so nothing that
   works today regresses.

This means: **no browser in front → the app behaves exactly as it does now.**

---

## 6. Persistence (tweaks.json)

Persisted page rules live **daemon-side** (private, syncs with the learning
story, never uploaded), not in the extension:

```jsonc
// tweaks.json
{
  "youtube.com": [
    { "op": "hide", "target": "#shorts", "css": "ytd-rich-shelf-renderer[is-shorts]{display:none}" }
  ]
}
```

On navigation the extension sends `tweaks_for {url}`; the daemon replies with the
domain's `rules`, which the content script applies before paint. Rule capture:
when a `page` directive has `persist:true` and the op succeeds, the extension
returns the concrete selector/CSS it used in `page_result.data`, and the daemon
appends it to `tweaks.json`. Same on-disk, user-owned, deletable model as
`adaptive.json` and `history.jsonl`.

---

## 7. Guardrails on the new surface

Extend `GUARDRAILS.md` to the page. The existing "never transact / never delete"
stance maps directly:

- **Never auto-submit a form** and never click a control the heuristic tags as
  pay / buy / delete / confirm-destructive without an explicit in-page
  confirmation (`confirm:true` default for `fill`/`click`).
- **Never enter credentials or payment fields.** The `fill` op refuses targets
  typed `password`, or fields matched to card/SSN patterns — return
  `ok:false, feedback:"I won't fill that field"`.
- **Read/summarize stays local**: `main_text` goes only to the on-device model.
  Nothing is sent to a network endpoint.
- **Token + origin gate** (see §2) so no random page can drive the daemon.

---

## 8. File-by-file change list

| File | Change |
|------|--------|
| `whisp/bridge.py` | **NEW.** WS server thread, client registry, `send_and_wait`, `PageProxy`, token/origin auth, `tweaks.json` load/save. |
| `whisp/commands.py` | Add `page` intents to `parse()`; add `page=None` to `CommandEngine.__init__`; add the `page` branch to `_execute`; foreground-browser check for routing. |
| `whisp/app.py` | Construct the bridge + `PageProxy`, pass `page=` into `CommandEngine`; start the bridge thread in `run()` beside the tray/model threads; forward `overlay.post` states to the bridge `overlay` message. |
| `whisp/settings.py` | Add a "Browser bridge" section: on/off, show/copy pairing token, allowed extension IDs, connection status. |
| `GUARDRAILS.md` | Add the §7 page-surface rules. |
| `requirements.txt` | Add `websockets`. |
| `extension/` | **NEW.** MV3 manifest, service worker (WS client + reconnect), content script (op handlers, overlay, tweak apply), offscreen doc (Phase 1 mic only). |
| `tests/test_commands.py` | Add cases for the new `page` intents (pure `parse()` tests, no socket). |
| `tests/test_bridge.py` | **NEW.** Token/origin rejection, `send_and_wait` future resolution, timeout path. |

`parse()` stays pure and unit-testable — the new intents are covered by
`test_commands.py` with zero I/O, matching the existing test style.

---

## 9. Extension skeleton (Phase 0)

**manifest.json** (MV3, minimum permissions):

```jsonc
{
  "manifest_version": 3,
  "name": "WhispLocal for the Web",
  "version": "0.1.0",
  "permissions": ["scripting", "activeTab", "storage"],
  "host_permissions": ["<all_urls>"],       // needed to apply tweaks on any site
  "background": { "service_worker": "sw.js" },
  "content_scripts": [{ "matches": ["<all_urls>"], "js": ["content.js"],
                        "run_at": "document_start" }]
}
```

**sw.js** (service worker — owns the socket):

```js
let ws, token;
function connect() {
  ws = new WebSocket("ws://127.0.0.1:48918");
  ws.onopen  = () => send({ type: "hello", payload: { extId: chrome.runtime.id,
                                                      version: "0.1.0" } });
  ws.onmessage = (e) => route(JSON.parse(e.data));
  ws.onclose = () => setTimeout(connect, 1500);   // auto-reconnect
}
function route(msg) {
  if (msg.type === "page_action" || msg.type === "get_context" ||
      msg.type === "overlay" || msg.type === "tweaks") {
    chrome.tabs.query({ active: true, currentWindow: true }, ([tab]) =>
      chrome.tabs.sendMessage(tab.id, msg, (reply) => reply && send(reply)));
  }
}
function send(m) { ws.send(JSON.stringify({ v: 1, token, id: m.id || uuid(), ...m })); }
connect();
```

**content.js** (applies ops, reads DOM, overlay) — one handler per `op`:

```js
chrome.runtime.onMessage.addListener((msg, _s, respond) => {
  if (msg.type === "page_action") respond(applyOp(msg.payload, msg.id));
  else if (msg.type === "get_context") respond(readContext(msg.payload, msg.id));
  else if (msg.type === "tweaks") { msg.payload.rules.forEach(applyRule); }
  else if (msg.type === "overlay") { renderOverlay(msg.payload); }
  return true;   // async response
});

function applyOp(d, id) {
  const el = resolveTarget(d.target);          // heuristic in Phase 0
  switch (d.op) {
    case "hide":    el && (el.style.display = "none");
                    return result(id, !!el, el ? "Hidden" : "couldn't find it",
                                  el && { css: selectorFor(el) + "{display:none}" });
    case "restyle": document.documentElement.style.fontSize = "120%";
                    return result(id, true, "Text bigger");
    case "read":    return result(id, !!el, "Read it", { text: el?.innerText });
    case "summarize": return result(id, true, "", { text: mainText() });
    // fill/click gated behind confirm — see §7
  }
}
```

`summarize`/context return raw text to the daemon, which runs the on-device
model and speaks the result — the extension never calls a network model.

---

## 10. Phase 0 done = this checklist

- [ ] `bridge.py`: WS server on 127.0.0.1:48918, token + origin auth, client registry, `send_and_wait`, `PageProxy`.
- [ ] `tweaks.json` load/save + `tweaks_for`/`tweaks` round-trip.
- [ ] `commands.py`: `page` intents in `parse()`, `page=` param, `_execute` branch, foreground-browser routing guard.
- [ ] `app.py`: build + start bridge, wire `PageProxy`, mirror overlay states.
- [ ] `settings.py`: bridge on/off + pairing token UI.
- [ ] Extension: manifest, sw.js (socket + reconnect), content.js (`hide`, `restyle`, `read`, `summarize`, tweak apply, overlay).
- [ ] `GUARDRAILS.md` page rules; `fill`/`click` confirm + credential refusal.
- [ ] Tests: `test_commands.py` page-intent cases; `test_bridge.py` auth + timeout.
- [ ] Manual acceptance: with the browser frontmost, "hide the cookie banner",
      "summarize this page", "bigger text", and a persisted "hide shorts on this
      site" that survives reload — all via the existing global hotkey, all
      offline.

Everything above reuses the existing mic → STT → `parse()` → `_execute()` →
`speak()` pipeline. The only genuinely new surface is one module (`bridge.py`),
one command kind (`page`), and a thin extension.
