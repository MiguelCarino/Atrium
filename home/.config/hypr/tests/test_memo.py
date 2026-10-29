"""memo.py (voice memos): file names, the recorder command, the inbox line
(quicknote.py's shape, linking the sound), and the pid file read as live only
while its ffmpeg is."""
import datetime
import os
import unittest
from unittest import mock

import helpers

memo = helpers.import_script("memo.py")
WHEN = datetime.datetime(2026, 10, 28, 9, 41, 12)


class Pure(unittest.TestCase):
    def test_name(self):
        self.assertEqual(memo.memo_name(WHEN), "2026-10-28_09-41-12")

    def test_recorder_is_opus_from_pulse(self):
        cmd = memo.recorder_cmd("/x/m.opus")
        self.assertEqual(cmd[0], "ffmpeg")
        self.assertIn("libopus", cmd)
        self.assertEqual(cmd[cmd.index("-f") + 1], "pulse")
        self.assertEqual(cmd[-1], "/x/m.opus")

    def test_inbox_line(self):
        home = os.path.expanduser("~")
        line = memo.inbox_line(WHEN, os.path.join(home, "Documents/Memos/a.opus"), "  buy\n milk ")
        self.assertEqual(line, "- 2026-10-28 09:41  [memo](~/Documents/Memos/a.opus) buy milk\n")
        self.assertIn("(no words heard)", memo.inbox_line(WHEN, "/tmp/a.opus", ""))
        long = memo.inbox_line(WHEN, "/tmp/a.opus", "word " * 200)
        self.assertTrue(long.rstrip().endswith("…"))

    def test_clock(self):
        self.assertEqual(memo.clock(75), "1:15")
        self.assertEqual(memo.clock(-3), "0:00")


class Newest(unittest.TestCase):
    def test_newest_by_name(self):
        folder = os.path.join(helpers.SCRATCH, "memos-newest")
        os.makedirs(folder, exist_ok=True)
        for n in ("2026-10-27_10-00-00.opus", "2026-10-28_09-00-00.opus", "2026-10-28_09-00-00.txt"):
            open(os.path.join(folder, n), "w").close()
        self.assertTrue(memo.newest(folder).endswith("2026-10-28_09-00-00.opus"))
        self.assertIsNone(memo.newest(folder + "-none"))


class PidFile(unittest.TestCase):
    def setUp(self):
        self.pidfile = os.path.join(helpers.SCRATCH, "memo-test.pid")
        with open(self.pidfile, "w") as fh:
            fh.write("4242\n/home/x/m.opus\nmemo\n")

    def tearDown(self):
        os.remove(self.pidfile)

    def comm(self, name):
        real = open

        def fake(path, *a, **k):
            if path == "/proc/4242/comm":
                if name is None:
                    raise FileNotFoundError(path)
                import io
                return io.StringIO(name + "\n")
            return real(path, *a, **k)
        return mock.patch("builtins.open", fake)

    def test_live_only_while_ffmpeg(self):
        with self.comm("ffmpeg"):
            pid, out, _started = memo.read_pid(self.pidfile)
        self.assertEqual((pid, out), (4242, "/home/x/m.opus"))
        with self.comm("bash"):
            self.assertIsNone(memo.read_pid(self.pidfile))     # the pid was reused
        with self.comm(None):
            self.assertIsNone(memo.read_pid(self.pidfile))     # gone

    def test_no_file(self):
        self.assertIsNone(memo.read_pid(self.pidfile + ".none"))


if __name__ == "__main__":
    unittest.main()
