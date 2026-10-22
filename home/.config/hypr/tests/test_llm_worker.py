"""scripts/llm-worker.py: the local worker MCP server."""

import os
import shutil
import tempfile
import unittest

import helpers

worker = helpers.import_script("llm-worker.py", "llm_worker")


class Files(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir)

    def write(self, name, data):
        path = os.path.join(self.dir, name)
        with open(path, "wb") as handle:
            handle.write(data)
        return path

    def test_secret_looking_files_are_never_read(self):
        for name in ("id_rsa", ".env", "prod.env", "aws_credentials", "api-token.txt", "server.pem"):
            text, why = worker.read_file(self.write(name, b"hunter2"))
            self.assertIsNone(text, name)
            self.assertIn("secret", why)
        self.assertTrue(worker.looks_secret(os.path.expanduser("~/.ssh/config")))

    def test_text_read_binary_refused(self):
        self.assertEqual(worker.read_file(self.write("notes.txt", b"hello"))[0], "hello")
        self.assertIn("binary", worker.read_file(self.write("blob.bin", b"\0\1\2"))[1])

    def test_prompt_stays_within_budget(self):
        big = "x" * (worker.MAX_CHARS * 3)
        prompt = worker.prompt_for("summarise", [("a", big), ("b", big)])
        self.assertLess(len(prompt), worker.MAX_CHARS + 500)
        self.assertIn("characters cut", prompt)


class Protocol(unittest.TestCase):
    def test_handshake_and_list(self):
        init = worker.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                              "params": {"protocolVersion": "2025-03-26"}})
        self.assertEqual(init["result"]["protocolVersion"], "2025-03-26")
        self.assertIsNone(worker.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}))
        tools = worker.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})["result"]["tools"]
        self.assertEqual([t["name"] for t in tools], ["local_worker"])

    def test_unknown_method_and_tool(self):
        self.assertEqual(worker.handle({"jsonrpc": "2.0", "id": 3, "method": "nope"})["error"]["code"], -32601)
        bad = worker.handle({"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "x"}})
        self.assertEqual(bad["error"]["code"], -32602)

    def test_nothing_to_do_is_an_error_without_touching_the_gpu(self):
        worker.ready = lambda: self.fail("must not load a model")
        text, err = worker.run({"task": "summarise", "files": ["/nonexistent/file"]})
        self.assertTrue(err)
        self.assertIn("nothing to work on", text)

    def test_refusal_is_reported(self):
        worker.ready = lambda: (None, "gamemode is on")
        text, err = worker.run({"task": "summarise", "text": "hello"})
        self.assertTrue(err)
        self.assertIn("refused: gamemode is on", text)


if __name__ == "__main__":
    unittest.main()
