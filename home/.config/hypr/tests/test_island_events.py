"""island_events.py (pushing to the dynamic island) and its two hooks: a
real datagram on a scratch island.sock carries v=1, the source and the cut
strings; no socket, or a stale one nobody listens on, is False and never an
error; scripts/notify and mascot_notify.send copy to the island except for
Railguard, which railguard.notify sends itself even with its own
notifications off."""
import json
import os
import socket
import unittest
from unittest import mock

import helpers

import island_events as ie  # noqa: E402  (scripts/ is on the path: helpers)
import mascot_notify as mn  # noqa: E402

rg = helpers.import_script("railguard.py")


def gone():
    if os.path.lexists(ie.SOCK):
        os.remove(ie.SOCK)


class Listening(unittest.TestCase):
    def setUp(self):
        gone()
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        self.sock.bind(ie.SOCK)
        self.sock.settimeout(2)

    def tearDown(self):
        self.sock.close()
        gone()

    def received(self):
        return json.loads(self.sock.recv(8192))

    def test_sock_is_in_the_runtime_dir(self):
        self.assertEqual(ie.SOCK, os.path.join(os.environ["XDG_RUNTIME_DIR"], "island.sock"))

    def test_notify(self):
        self.assertTrue(ie.notify("Tea", "is ready", app="Timer", urgency="critical"))
        self.assertEqual(self.received(), {"v": 1, "src": "notify", "summary": "Tea",
                                           "body": "is ready", "app": "Timer",
                                           "urgency": "critical"})

    def test_notify_defaults(self):
        ie.notify("Saved")
        msg = self.received()
        self.assertEqual((msg["body"], msg["app"], msg["urgency"]), ("", "", "normal"))

    def test_railguard_and_the_cut(self):
        self.assertTrue(ie.railguard("Memory", "x" * 1000, mood="relieved"))
        msg = self.received()
        self.assertEqual((msg["v"], msg["src"], msg["title"], msg["mood"]),
                         (1, "railguard", "Memory", "relieved"))
        self.assertEqual(len(msg["body"]), ie.LIMIT)

    def test_send_adds_the_version(self):
        ie.send({"src": "notify", "v": 7})
        self.assertEqual(self.received()["v"], 1)


class NotThere(unittest.TestCase):
    def setUp(self):
        gone()

    def tearDown(self):
        gone()

    def test_no_socket_is_false(self):
        self.assertFalse(ie.notify("Hi"))
        self.assertFalse(ie.railguard("Hi"))

    def test_stale_socket_is_false(self):
        s = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        s.bind(ie.SOCK)
        s.close()                                   # the file stays, nobody listens
        self.assertTrue(os.path.exists(ie.SOCK))
        self.assertFalse(ie.notify("Hi"))

    def test_a_plain_file_is_false(self):
        open(ie.SOCK, "w").close()
        self.assertFalse(ie.railguard("Hi", "there"))


class Hooks(unittest.TestCase):
    def test_drop_in_copies_to_the_island(self):
        with mock.patch.object(mn.os, "execvp") as ex, \
                mock.patch.object(ie, "notify") as isl:
            mn.drop_in(["-a", "Timer", "-u", "low", "--mood", "calm", "Tea", "is ready"])
        isl.assert_called_once_with("Tea", "is ready", "Timer", "low")
        ex.assert_called_once()

    def test_drop_in_not_for_railguard(self):
        with mock.patch.object(mn.os, "execvp"), mock.patch.object(ie, "notify") as isl:
            mn.drop_in(["-a", "Railguard", "-u", "critical", "Memory", "held"])
        isl.assert_not_called()

    def test_a_broken_island_still_sends(self):
        with mock.patch.object(mn.os, "execvp") as ex, \
                mock.patch.object(ie, "notify", side_effect=RuntimeError("boom")):
            mn.drop_in(["Hi"])
        ex.assert_called_once()

    def test_send_copies_but_not_railguard(self):
        with mock.patch.object(mn.subprocess, "Popen") as popen, \
                mock.patch.object(ie, "notify") as isl:
            mn.send("Tea", "ready", app="Timer", urgency="normal")
            mn.send("Memory", "held", app="Railguard", urgency="critical")
        isl.assert_called_once_with("Tea", "ready", "Timer", "normal")
        self.assertEqual(popen.call_count, 2)

    def test_railguard_sends_with_its_notifications_off(self):
        saved = rg.CFG["notify"]
        rg.CFG["notify"] = False
        try:
            with mock.patch.object(ie, "railguard") as isl, \
                    mock.patch.object(rg.subprocess, "Popen") as popen, \
                    mock.patch("builtins.print"):
                rg.notify("Memory", "cc1plus held 14 GB", mood="relieved")
        finally:
            rg.CFG["notify"] = saved
        isl.assert_called_once_with("Memory", "cc1plus held 14 GB", "relieved")
        popen.assert_not_called()


if __name__ == "__main__":
    unittest.main()
