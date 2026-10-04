"""Unit tests for the browser bridge. The token/tweaks/origin/PageProxy logic
is exercised without opening a real socket; one asyncio round-trip test drives a
live client through the WebSocket server end to end."""
import asyncio
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "whisp"))

import bridge
from bridge import Bridge, PageProxy, _domain


class DomainTests(unittest.TestCase):
    def test_strips_www_and_scheme(self):
        self.assertEqual(_domain("https://www.youtube.com/watch?v=x"),
                         "youtube.com")
        self.assertEqual(_domain("http://reddit.com/r/all"), "reddit.com")
        self.assertEqual(_domain("not a url"), "")


class TokenAndTweakTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        # Force the token file into the temp dir, not %APPDATA%.
        self._appdata = os.environ.pop("APPDATA", None)
        self.b = Bridge(self.dir, config={}, log=lambda *_: None)

    def tearDown(self):
        if self._appdata is not None:
            os.environ["APPDATA"] = self._appdata

    def test_token_is_stable_and_persisted(self):
        self.assertTrue(self.b.token)
        again = Bridge(self.dir, config={}, log=lambda *_: None)
        self.assertEqual(self.b.token, again.token)

    def test_tweaks_round_trip_per_domain(self):
        self.b.add_rule("https://www.youtube.com/",
                        {"op": "hide", "css": "#shorts{display:none}"})
        self.assertEqual(
            self.b.rules_for("https://youtube.com/feed"),
            [{"op": "hide", "css": "#shorts{display:none}"}])
        # Unknown domain has no rules.
        self.assertEqual(self.b.rules_for("https://example.com"), [])
        # A reloaded bridge sees the persisted rule.
        reloaded = Bridge(self.dir, config={}, log=lambda *_: None)
        self.assertEqual(len(reloaded.rules_for("https://youtube.com")), 1)

    def test_duplicate_rule_not_stored_twice(self):
        rule = {"op": "hide", "css": "#ads{display:none}"}
        self.b.add_rule("https://site.com", rule)
        self.b.add_rule("https://site.com", rule)
        self.assertEqual(len(self.b.rules_for("https://site.com")), 1)


class OriginTests(unittest.TestCase):
    def test_allowlist_enforced_when_configured(self):
        b = Bridge(tempfile.mkdtemp(),
                   config={"bridge_allowed_ext_ids": ["abc123"]},
                   log=lambda *_: None)
        self.assertTrue(b._origin_ok("chrome-extension://abc123"))
        self.assertFalse(b._origin_ok("chrome-extension://other"))
        self.assertFalse(b._origin_ok("https://evil.com"))
        self.assertFalse(b._origin_ok(None))

    def test_dev_mode_accepts_any_extension_origin(self):
        b = Bridge(tempfile.mkdtemp(), config={}, log=lambda *_: None)
        self.assertTrue(b._origin_ok("chrome-extension://anything"))
        self.assertTrue(b._origin_ok("moz-extension://anything"))
        # A plain web page is still rejected.
        self.assertFalse(b._origin_ok("https://evil.com"))


class PageProxyTests(unittest.TestCase):
    def test_disconnected_reports_no_browser(self):
        class _NoClient:
            def has_client(self):
                return False
        p = PageProxy(_NoClient())
        self.assertFalse(p.connected())
        ok, feedback, data = p.run({"op": "hide", "target": "x"})
        self.assertFalse(ok)
        self.assertIsNone(data)

    def test_persists_rule_on_confirmed_op(self):
        recorded = {}

        class _Stub:
            def has_client(self):
                return True

            def send_and_wait(self, msg, timeout):
                from concurrent.futures import Future
                f = Future()
                f.set_result({"ok": True, "feedback": "Hidden",
                              "data": {"css": "#s{display:none}",
                                       "url": "https://youtube.com"}})
                return f

            def add_rule(self, url, rule):
                recorded["url"] = url
                recorded["rule"] = rule

        p = PageProxy(_Stub())
        ok, feedback, data = p.run(
            {"op": "hide", "target": "shorts", "persist": True})
        self.assertTrue(ok)
        self.assertEqual(recorded["url"], "https://youtube.com")
        self.assertEqual(recorded["rule"],
                         {"op": "hide", "css": "#s{display:none}"})

    def test_no_persist_when_not_requested(self):
        recorded = {}

        class _Stub:
            def has_client(self):
                return True

            def send_and_wait(self, msg, timeout):
                from concurrent.futures import Future
                f = Future()
                f.set_result({"ok": True, "feedback": "Hidden",
                              "data": {"css": "#s{display:none}",
                                       "url": "https://youtube.com"}})
                return f

            def add_rule(self, url, rule):
                recorded["called"] = True

        p = PageProxy(_Stub())
        p.run({"op": "hide", "target": "shorts", "persist": False})
        self.assertNotIn("called", recorded)


@unittest.skipUnless(bridge._HAVE_WS, "websockets not installed")
class LiveRoundTripTests(unittest.TestCase):
    """Drive the real WebSocket server with a real client on a spare port."""

    def test_auth_and_page_action_round_trip(self):
        import websockets

        async def scenario():
            b = Bridge(tempfile.mkdtemp(), config={}, log=lambda *_: None)
            # Serve on an ephemeral setup by reusing the bridge handler.
            server = await websockets.serve(
                b._handle, "127.0.0.1", 0)
            b._loop = asyncio.get_event_loop()
            port = server.sockets[0].getsockname()[1]

            async with websockets.connect(
                    f"ws://127.0.0.1:{port}",
                    additional_headers={
                        "Origin": "chrome-extension://testid"}) as ws:
                # Handshake: hello with the right token -> welcome.
                await ws.send(json.dumps({"type": "hello", "token": b.token,
                                          "payload": {}}))
                welcome = json.loads(await ws.recv())
                self.assertEqual(welcome["type"], "welcome")

                # Daemon -> extension request; client answers page_result.
                # send_and_wait returns immediately; the blocking .result() is
                # awaited off the event loop (in real use it runs on the
                # command pipeline thread, never the bridge loop).
                fut = b.send_and_wait(
                    {"type": "page_action",
                     "payload": {"op": "hide", "target": "banner"}}, 4.0)
                req = json.loads(await ws.recv())
                self.assertEqual(req["type"], "page_action")
                await ws.send(json.dumps({
                    "type": "page_result", "id": req["id"], "token": b.token,
                    "payload": {"ok": True, "feedback": "Hidden"}}))
                loop = asyncio.get_event_loop()
                res = await loop.run_in_executor(None, fut.result, 4.0)
                self.assertTrue(res["ok"])
                self.assertEqual(res["feedback"], "Hidden")

            server.close()
            await server.wait_closed()

        asyncio.run(scenario())

    def test_bad_token_is_rejected(self):
        import websockets
        from websockets.exceptions import ConnectionClosed

        async def scenario():
            b = Bridge(tempfile.mkdtemp(), config={}, log=lambda *_: None)
            server = await websockets.serve(b._handle, "127.0.0.1", 0)
            port = server.sockets[0].getsockname()[1]
            async with websockets.connect(
                    f"ws://127.0.0.1:{port}",
                    additional_headers={
                        "Origin": "chrome-extension://testid"}) as ws:
                await ws.send(json.dumps({"type": "hello", "token": "wrong",
                                          "payload": {}}))
                with self.assertRaises(ConnectionClosed):
                    await ws.recv()
            server.close()
            await server.wait_closed()

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
