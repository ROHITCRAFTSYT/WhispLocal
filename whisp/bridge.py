"""Browser bridge — a localhost WebSocket server that lets the voice engine
act inside a web page via the companion extension.

On-device only: it binds to 127.0.0.1, never makes an outbound request, and
authenticates every client with a per-machine token plus an extension-origin
allowlist. The daemon keeps the mic, STT, grammar, learning, and guardrails;
the extension is a remote executor for page ops (CommandEngine kind == "page").

See docs/BRIDGE_SPEC.md for the protocol. If the optional ``websockets``
package is not installed, the bridge degrades to a no-op — PageProxy.connected()
returns False and page commands simply report a hint, so nothing else breaks.
"""
import asyncio
import json
import os
import secrets
import threading
import time
import uuid
from concurrent.futures import Future
from urllib.parse import urlparse

BRIDGE_HOST = "127.0.0.1"
BRIDGE_PORT = 48918          # distinct from the 48917 single-instance guard
PROTOCOL_VERSION = 1
MAX_FRAME = 4 * 1024 * 1024  # 4 MB — bounds page_text / pcm payloads

try:
    import websockets
    from websockets.exceptions import ConnectionClosed
    _HAVE_WS = True
except Exception:  # pragma: no cover - exercised only without the dep
    _HAVE_WS = False

    class ConnectionClosed(Exception):
        pass


def _domain(url):
    """Bare registrable-ish host for per-domain tweak storage ('www.' dropped)."""
    try:
        net = urlparse(url).netloc.lower()
    except Exception:
        return ""
    return net[4:] if net.startswith("www.") else net


class Bridge:
    def __init__(self, app_dir, config=None, log=None):
        self.app_dir = app_dir
        self.config = config or {}
        self._log = log or (lambda *_: None)
        self.token = self._load_or_create_token()
        self.tweaks_path = os.path.join(app_dir, "tweaks.json")
        self._tweaks = self._load_tweaks()
        self._loop = None
        self._thread = None
        self._server = None
        self._clients = set()   # authenticated websockets
        self._pending = {}      # request id -> concurrent.futures.Future
        self._running = False

    # ----- token & tweak persistence (plain local files, user-owned) ------
    def _token_path(self):
        base = os.environ.get("APPDATA")
        if base:
            d = os.path.join(base, "WhispLocal")
            try:
                os.makedirs(d, exist_ok=True)
                return os.path.join(d, "bridge_token")
            except OSError:
                pass
        return os.path.join(self.app_dir, "bridge_token")

    def _load_or_create_token(self):
        path = self._token_path()
        try:
            with open(path, encoding="utf-8") as f:
                tok = f.read().strip()
            if tok:
                return tok
        except OSError:
            pass
        tok = secrets.token_hex(32)
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(tok)
        except OSError:
            pass
        return tok

    def _load_tweaks(self):
        try:
            with open(self.tweaks_path, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save_tweaks(self):
        try:
            with open(self.tweaks_path, "w", encoding="utf-8") as f:
                json.dump(self._tweaks, f, ensure_ascii=False, indent=2)
        except OSError:
            pass

    def rules_for(self, url):
        return list(self._tweaks.get(_domain(url), []))

    def add_rule(self, url, rule):
        dom = _domain(url)
        if not dom or not isinstance(rule, dict):
            return
        rules = self._tweaks.setdefault(dom, [])
        if rule not in rules:
            rules.append(rule)
            self._save_tweaks()

    # ----- lifecycle ------------------------------------------------------
    def start(self):
        if not _HAVE_WS:
            self._log("bridge disabled: install 'websockets' to enable the "
                      "browser extension")
            return
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        self._log(f"bridge listening on ws://{BRIDGE_HOST}:{BRIDGE_PORT}")

    def stop(self):
        self._running = False
        if self._loop:
            self._loop.call_soon_threadsafe(self._loop.stop)

    def _run_loop(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._serve())
            self._loop.run_forever()
        except Exception as e:
            self._log(f"bridge loop error: {e}")

    async def _serve(self):
        self._server = await websockets.serve(
            self._handle, BRIDGE_HOST, BRIDGE_PORT, max_size=MAX_FRAME)

    # ----- connection handling -------------------------------------------
    def _origin_ok(self, origin):
        if not origin:
            return False
        allow = self.config.get("bridge_allowed_ext_ids") or []
        if allow:
            return any(origin in (f"chrome-extension://{i}",
                                  f"moz-extension://{i}") for i in allow)
        # No allowlist configured (dev): accept any extension origin. The
        # per-message token below is still required, so a random web page
        # cannot drive the daemon.
        return origin.startswith(("chrome-extension://", "moz-extension://"))

    @staticmethod
    def _headers(ws):
        """Header access across websockets versions (>=12 vs older)."""
        req = getattr(ws, "request", None)
        if req is not None and getattr(req, "headers", None) is not None:
            return req.headers
        return getattr(ws, "request_headers", {}) or {}

    async def _handle(self, ws):
        origin = self._headers(ws).get("Origin")
        if not self._origin_ok(origin):
            self._log(f"bridge rejected origin: {origin!r}")
            await ws.close(code=4403, reason="origin not allowed")
            return
        authed = False
        try:
            async for raw in ws:
                try:
                    msg = json.loads(raw)
                except ValueError:
                    continue
                if not authed:
                    if msg.get("type") == "hello" and \
                            msg.get("token") == self.token:
                        authed = True
                        self._clients.add(ws)
                        await self._send(ws, {
                            "type": "welcome",
                            "payload": {
                                "daemonVersion": PROTOCOL_VERSION,
                                "capabilities": ["page", "tweaks", "context"],
                            }})
                        self._log("bridge client authenticated")
                    else:
                        await ws.close(code=4401, reason="unauthorized")
                        return
                    continue
                if msg.get("token") != self.token:
                    continue  # ignore any frame carrying the wrong token
                self._dispatch(msg)
        except ConnectionClosed:
            pass
        finally:
            self._clients.discard(ws)

    def _dispatch(self, msg):
        mtype = msg.get("type")
        mid = msg.get("id")
        if mtype in ("page_result", "context") and mid in self._pending:
            fut = self._pending.pop(mid)
            if not fut.done():
                fut.set_result(msg.get("payload") or {})
        elif mtype == "tweaks_for":
            self._reply_tweaks((msg.get("payload") or {}).get("url", ""))
        # 'pong' and anything else are ignored.

    def _reply_tweaks(self, url):
        self._broadcast({"type": "tweaks",
                         "payload": {"rules": self.rules_for(url)}})

    # ----- sending --------------------------------------------------------
    def _envelope(self, msg):
        return {"v": PROTOCOL_VERSION, "token": self.token,
                "id": msg.get("id") or uuid.uuid4().hex,
                **msg}

    async def _send(self, ws, msg):
        await ws.send(json.dumps(self._envelope(msg), ensure_ascii=False))

    def _broadcast(self, msg):
        if not self._loop:
            return
        data = json.dumps(self._envelope(msg), ensure_ascii=False)
        for ws in list(self._clients):
            asyncio.run_coroutine_threadsafe(ws.send(data), self._loop)

    def has_client(self):
        return bool(self._clients)

    def send_and_wait(self, msg, timeout):
        """Send a request to the first connected client; return a Future that
        resolves with the client's reply payload. Thread-safe: called from the
        command pipeline thread and scheduled onto the bridge's asyncio loop."""
        fut = Future()
        if not self._clients or not self._loop:
            fut.set_result({"ok": False, "feedback": "no browser connected"})
            return fut
        mid = uuid.uuid4().hex
        env = self._envelope({**msg, "id": mid})
        self._pending[mid] = fut
        ws = next(iter(self._clients))
        asyncio.run_coroutine_threadsafe(
            ws.send(json.dumps(env, ensure_ascii=False)), self._loop)

        # Backstop: resolve the future if the extension never replies, so the
        # caller's fut.result() cannot hang past the timeout.
        def _expire():
            time.sleep(timeout + 0.5)
            f = self._pending.pop(mid, None)
            if f and not f.done():
                f.set_result({"ok": False,
                              "feedback": "the page didn't respond"})
        threading.Thread(target=_expire, daemon=True).start()
        return fut

    def overlay(self, state, message="", ok=True):
        """Mirror a tray overlay state into the active page (optional)."""
        self._broadcast({"type": "overlay",
                         "payload": {"state": state, "message": message,
                                     "ok": ok}})


class PageProxy:
    """Synchronous view of the bridge for CommandEngine._execute. run() sends a
    page_action and blocks until the extension replies (or the timeout fires)."""

    def __init__(self, bridge):
        self._bridge = bridge

    def connected(self):
        return self._bridge is not None and self._bridge.has_client()

    def run(self, directive, timeout=4.0):
        if not self.connected():
            return False, "no browser connected", None
        fut = self._bridge.send_and_wait(
            {"type": "page_action", "payload": directive}, timeout)
        try:
            res = fut.result(timeout + 1.0)
        except Exception:
            return False, "the page didn't respond", None
        ok = bool(res.get("ok"))
        feedback = res.get("feedback", "")
        data = res.get("data")
        # When the directive asked to persist and the extension returned the
        # concrete selector/CSS it used, save it as a per-domain rule.
        if ok and directive.get("persist") and isinstance(data, dict) \
                and data.get("css") and data.get("url"):
            self._bridge.add_rule(
                data["url"],
                {"op": directive.get("op"), "css": data["css"]})
        return ok, feedback, data
