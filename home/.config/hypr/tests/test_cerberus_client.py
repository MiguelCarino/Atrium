"""cerberus_client.py against a fake Cerberus on a free port of its own: the
model list read keyless from /v1/models, the control API's actions with the
token from a scratch config.json, Cerberus' refusals passed on, and the
address taken from $CERBERUS_URL or the config's server.listen. Never the
real service, nothing loaded."""
import http.server
import json
import os
import tempfile
import threading
import unittest
from unittest import mock

import helpers  # noqa: F401

PORT = 0

import cerberus_client as cc  # noqa: E402

SEEN = []


def closed_port():
    """A port nothing listens on (bound, then let go)."""
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Fake(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def reply(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        SEEN.append(("GET", self.path, self.headers.get("Authorization")))
        if self.path == "/v1/models":
            self.reply(200, {"object": "list", "data": [
                {"id": "openai/gpt-x", "owned_by": "openai", "local": False, "loaded": False},
                {"id": "qwen/qwen3-8b", "owned_by": "lmstudio", "local": True, "loaded": True,
                 "context_length": 32768, "vision": True},
                {"id": "tiny", "owned_by": "llamacpp", "local": True, "loaded": False,
                 "cerberus": {"ctx": 4096}}, "junk", {"no": "id"}]})
        else:
            self.reply(404, {"error": {"message": "nope"}})

    def do_POST(self):
        SEEN.append(("POST", self.path, self.headers.get("Authorization")))
        if self.headers.get("Authorization") != "Bearer tok":
            return self.reply(401, {"error": "unauthorized"})
        if self.path.endswith("/load"):
            return self.reply(409, {"error": "not enough memory for this model"})
        self.reply(200, {"ok": True})


class Client(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        global PORT
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Fake)
        PORT = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        SEEN.clear()
        self.dir = tempfile.TemporaryDirectory()
        self.conf = os.path.join(self.dir.name, "config.json")
        for p in (mock.patch.object(cc, "CONFIG", self.conf),
                  mock.patch.dict(os.environ, {"CERBERUS_URL": f"http://127.0.0.1:{PORT}/v1"})):
            p.start()
            self.addCleanup(p.stop)

    def tearDown(self):
        self.dir.cleanup()

    def write_conf(self, server):
        with open(self.conf, "w") as handle:
            json.dump({"server": server}, handle)

    def test_models_keyless_local_first(self):
        self.write_conf({"token": "tok"})
        got = cc.models()
        self.assertEqual([m["id"] for m in got], ["tiny", "qwen/qwen3-8b", "openai/gpt-x"])
        qwen = got[1]
        self.assertEqual((qwen["engine_label"], qwen["loaded"], qwen["ctx"], qwen["vision"]),
                         ("LM Studio", True, 32768, True))
        self.assertEqual(got[0]["ctx"], 4096)
        self.assertEqual(SEEN, [("GET", "/v1/models", None)])      # the list never sends the token

    def test_actions_carry_the_token_and_refusals(self):
        self.write_conf({"token": "tok"})
        self.assertTrue(cc.can_control())
        self.assertEqual(cc.action("qwen/qwen3-8b", "unload"), {"ok": True})
        self.assertEqual(SEEN[-1], ("POST", "/api/models/qwen/qwen3-8b/unload", "Bearer tok"))
        with self.assertRaisesRegex(cc.CerberusError, "not enough memory"):
            cc.action("tiny", "load")
        with self.assertRaises(ValueError):
            cc.action("tiny", "rm")

    def test_no_token_no_control(self):
        self.write_conf({})
        self.assertFalse(cc.can_control())
        with self.assertRaisesRegex(cc.CerberusError, "no Cerberus token"):
            cc.action("tiny", "unload")
        self.assertEqual(SEEN, [])

    def test_address(self):
        self.assertEqual(cc.base(), f"http://127.0.0.1:{PORT}")
        self.assertEqual(cc.chat_url(), f"http://127.0.0.1:{PORT}/v1")
        with mock.patch.dict(os.environ, {"CERBERUS_URL": ""}):
            self.write_conf({"listen": "0.0.0.0:7400"})
            self.assertEqual(cc.base(), "http://127.0.0.1:7400")
            self.write_conf({})
            self.assertEqual(cc.base(), cc.DEFAULT)

    def test_down_is_an_error(self):
        with mock.patch.dict(os.environ, {"CERBERUS_URL": f"http://127.0.0.1:{closed_port()}"}):
            with self.assertRaisesRegex(cc.CerberusError, "did not answer"):
                cc.models()


if __name__ == "__main__":
    unittest.main()
