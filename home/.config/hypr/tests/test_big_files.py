"""big_files.py (the disk panel's BIGGEST FILES): find's lines to the biggest
files, and one scan at a time. Pure: nothing walks a real drive."""
import fcntl
import importlib.util
import json
import os
import sys
import tempfile
import time
import unittest

import helpers  # noqa: F401  (scratch HOME and XDG_CACHE_HOME)

WAYBAR_SCRIPTS = os.path.expanduser("~/.config/waybar/scripts")
sys.path.insert(0, WAYBAR_SCRIPTS)
_spec = importlib.util.spec_from_file_location("big_files", os.path.join(WAYBAR_SCRIPTS, "big_files.py"))
B = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(B)


class BigFilesTest(unittest.TestCase):
    def test_biggest_first_each_path_once(self):
        lines = ["5\t/a", "9\t/b", "bad line", "x\t/c", "9\t/b", "7\t/d e"]
        self.assertEqual(B.biggest(lines, keep=3), [(9, "/b"), (7, "/d e"), (5, "/a")])

    def test_a_second_scan_waits_and_reads_the_first_ones_result(self):
        cache = os.path.join(os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"),
                             "hypr", "big-files-test.json")
        os.makedirs(os.path.dirname(cache), exist_ok=True)
        old = B.CACHE
        B.CACHE = cache
        try:
            with open(cache, "w") as handle:
                json.dump({"scanned": 1, "drives": []}, handle)
            walked = []
            B.walk_all = lambda: walked.append(1) or {"scanned": 2, "drives": []}
            self.assertEqual(B.scan()["scanned"], 2)            # free: it walks
            with open(cache + ".lock", "w") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                pid = os.fork()
                if pid == 0:                                    # another scan, while this one holds it
                    os._exit(0 if B.scan()["scanned"] == 1 and not walked[1:] else 1)
                time.sleep(0.3)                                 # the child is waiting by now
                fcntl.flock(lock, fcntl.LOCK_UN)
            self.assertEqual(os.waitstatus_to_exitcode(os.waitpid(pid, 0)[1]), 0)
        finally:
            B.CACHE = old


class DeleteTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.file = os.path.join(self.dir, "big.mkv")
        with open(self.file, "w") as handle:
            handle.write("x" * 100)
        self.old = B.CACHE
        B.CACHE = os.path.join(self.dir, "big-files.json")
        self.list(100)

    def tearDown(self):
        B.CACHE = self.old

    def list(self, size):
        with open(B.CACHE, "w") as handle:
            json.dump({"scanned": 1, "drives": [{"drive": "d", "mounts": ["/"],
                                                 "files": [{"path": self.file, "size": size}]}]}, handle)

    def test_refusals(self):
        self.assertIn("not in the last scan", B.delete(os.path.join(self.dir, "other"), True))
        self.list(5)
        self.assertIn("changed since the scan", B.delete(self.file, True))
        self.list(100)
        with open(self.file):                                   # this test holds it open
            self.assertIn("in use by", B.delete(self.file, True))
        link = os.path.join(self.dir, "link")
        os.symlink(self.file, link)
        old, self.file = self.file, link
        self.list(100)
        self.assertIn("no longer a plain file", B.delete(link, True))
        self.file = old
        self.assertTrue(os.path.exists(old))

    def test_for_good_and_out_of_the_list(self):
        self.assertIsNone(B.delete(self.file, True))
        self.assertFalse(os.path.exists(self.file))
        self.assertEqual(B.cached()["drives"][0]["files"], [])

    def test_trash_goes_through_gio(self):
        calls, real = [], B.subprocess.run
        B.subprocess.run = lambda cmd, **kw: calls.append(cmd) or real(["true"])
        try:
            self.assertIsNone(B.delete(self.file, False))
        finally:
            B.subprocess.run = real
        self.assertEqual(calls, [["gio", "trash", self.file]])
        self.assertTrue(os.path.exists(self.file))              # gio was not really asked here


if __name__ == "__main__":
    unittest.main()
