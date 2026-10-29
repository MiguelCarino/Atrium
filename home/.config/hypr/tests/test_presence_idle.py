"""scripts/presence-idle: hypridle's 20 s listener for presence.py, in sh.
No socket (presence off): nothing at all. A socket: the same datagram
`presence.py idle on|off` sends. A bad word: usage, exit 2."""
import os
import shutil
import socket
import subprocess
import tempfile
import unittest

import helpers

CLIENT = os.path.join(helpers.SCRIPTS, "presence-idle")


class PresenceIdle(unittest.TestCase):
    def setUp(self):
        self.run_dir = tempfile.mkdtemp(dir=os.environ["XDG_RUNTIME_DIR"])
        self.addCleanup(shutil.rmtree, self.run_dir, True)
        # HOME points at an empty folder: the python3 fallback finds no
        # presence.py there and fails quietly instead of reaching the real one.
        self.env = dict(os.environ, XDG_RUNTIME_DIR=self.run_dir, HOME=self.run_dir)

    def call(self, *args):
        return subprocess.run([CLIENT, *args], capture_output=True, text=True, timeout=10, env=self.env)

    def test_no_socket_is_a_no_op(self):
        out = self.call("on")
        self.assertEqual((out.returncode, out.stdout, out.stderr), (0, "", ""))

    def test_bad_word(self):
        self.assertEqual(self.call("maybe").returncode, 2)
        self.assertEqual(self.call().returncode, 2)

    @unittest.skipUnless(shutil.which("ncat"), "ncat is not installed")
    def test_sends_the_word_to_the_socket(self):
        path = os.path.join(self.run_dir, "presence.sock")
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as srv:
            srv.bind(path)
            srv.settimeout(5)
            self.assertEqual(self.call("on").returncode, 0)
            self.assertEqual(srv.recv(64), b"idle on")
            self.assertEqual(self.call("off").returncode, 0)
            self.assertEqual(srv.recv(64), b"idle off")


class HypridleUsesIt(unittest.TestCase):
    def test_listener_calls_the_client_not_python(self):
        with open(os.path.join(os.path.dirname(helpers.SCRIPTS), "hypridle.conf")) as handle:
            text = handle.read()
        self.assertIn("scripts/presence-idle on", text)
        self.assertIn("scripts/presence-idle off", text)
        self.assertNotIn("presence.py idle", text)


if __name__ == "__main__":
    unittest.main()
