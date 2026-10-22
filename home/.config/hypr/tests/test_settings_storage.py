"""storage.py and automount.py's conf (Settings > Storage): the findmnt and
du readers, which trash items and temporary files the daily clean-up would
take, the snapper reading, the automount choices. Pure functions and
scratch folders only: nothing real is deleted, no gsettings or timer is
touched."""
import datetime
import json
import os
import tempfile
import time
import unittest

import helpers

storage = helpers.import_script("storage.py")
automount = helpers.import_script("automount.py")

FINDMNT = json.dumps({"filesystems": [
    {"target": "/", "source": "/dev/nvme0n1p3[/root]", "fstype": "btrfs", "label": "fedora",
     "size": 2000, "used": 640, "avail": 1350},
    {"target": "/home", "source": "/dev/nvme0n1p3[/home]", "fstype": "btrfs", "label": "fedora",
     "size": 2000, "used": 640, "avail": 1350},
    {"target": "/tmp", "source": "tmpfs", "fstype": "tmpfs", "size": 100, "used": 1, "avail": 99},
    {"target": "/mnt/Andromeda", "source": "/dev/mapper/vg-lv", "fstype": "btrfs", "label": None,
     "size": 8000, "used": 7755, "avail": 244},
    {"target": "/mnt/Cache", "source": "/dev/nvme1n1p1", "fstype": "btrfs", "size": 4096, "used": 3390,
     "avail": 703},
]})


class Filesystems(unittest.TestCase):
    def test_one_row_per_device(self):
        fs = storage.parse_findmnt(FINDMNT)
        self.assertEqual([f["targets"] for f in fs], [["/", "/home"], ["/mnt/Andromeda"], ["/mnt/Cache"]])

    def test_percent_like_df(self):
        fs = {f["device"]: f for f in storage.parse_findmnt(FINDMNT)}
        self.assertEqual(fs["/dev/mapper/vg-lv"]["percent"], 97)     # 96.9 rounds up, as df
        self.assertEqual(fs["/dev/mapper/vg-lv"]["level"], "critical")
        self.assertEqual(fs["/dev/nvme1n1p1"]["level"], "")          # 83 %
        self.assertEqual(storage.level(85), "warning")
        self.assertEqual(storage.level(90), "critical")
        self.assertEqual(storage.percent(0, 0), 0)

    def test_bad_input(self):
        self.assertEqual(storage.parse_findmnt(""), [])
        self.assertEqual(storage.parse_findmnt("not json"), [])


class Du(unittest.TestCase):
    def test_parse_and_home_entries(self):
        sizes = storage.parse_du("10\t/h/a\n30\t/h/b c\nbad line\n45\t/h\n")
        total, rows = storage.home_entries(sizes, home="/h")
        self.assertEqual(total, 45)
        self.assertEqual(rows, [{"name": "b c", "size": 30}, {"name": "a", "size": 10}])

    def test_human(self):
        self.assertEqual(storage.human(244_624_064_512), "244.6 G")
        self.assertEqual(storage.human(0), "0 B")


class Trash(unittest.TestCase):
    def make(self, root, name, date):
        os.makedirs(os.path.join(root, "info"), exist_ok=True)
        os.makedirs(os.path.join(root, "files"), exist_ok=True)
        with open(os.path.join(root, "info", name + ".trashinfo"), "w") as f:
            f.write(f"[Trash Info]\nPath=/x/{name}\nDeletionDate={date}\n")
        open(os.path.join(root, "files", name), "w").close()

    def test_old_items_only(self):
        with tempfile.TemporaryDirectory() as root:
            self.make(root, "old", "2026-08-01T10:00:00")
            self.make(root, "new", "2026-10-19T10:00:00")
            self.make(root, "nodate", "garbage")
            got = storage.old_trash(root, 30, datetime.datetime(2026, 10, 20))
            self.assertEqual([os.path.basename(i) for _info, i in got], ["old"])

    def test_deletion_date(self):
        self.assertEqual(storage.deletion_date("DeletionDate=2026-01-02T03:04:05"),
                         datetime.datetime(2026, 1, 2, 3, 4, 5))
        self.assertIsNone(storage.deletion_date("Path=/x"))

    def test_deletion_date_with_a_zone_still_compares(self):
        # Off-spec but seen in the wild: a zone on the date. Comparing an
        # aware date with "now" would raise and stop the whole clean-up.
        when = storage.deletion_date("DeletionDate=2026-01-02T03:04:05Z")
        self.assertIsNone(when.tzinfo)
        self.assertLess(when, datetime.datetime(2026, 10, 20))


class Temp(unittest.TestCase):
    def test_old_own_files_deepest_first(self):
        with tempfile.TemporaryDirectory() as root:
            os.makedirs(os.path.join(root, "d"))
            for p in ("d/old", "young"):
                open(os.path.join(root, p), "w").close()
            past = time.time() - 40 * 86400
            os.utime(os.path.join(root, "d", "old"), (past, past))
            os.utime(os.path.join(root, "d"), (past, past))
            os.mkfifo(os.path.join(root, "pipe"))
            # ctime cannot be set back, so judge from 40 days on.
            got = storage.old_temp(root, 30, time.time() + 40 * 86400)
            names = [os.path.relpath(p, root) for p, _d in got]
            self.assertNotIn("pipe", names)
            self.assertLess(names.index(os.path.join("d", "old")), names.index("d"))
            self.assertEqual(storage.old_temp(root, 30, time.time()), [])

    def test_other_users_files_skipped(self):
        with tempfile.TemporaryDirectory() as root:
            open(os.path.join(root, "f"), "w").close()
            self.assertEqual(storage.old_temp(root, 1, time.time() + 9 * 86400, uid=os.getuid() + 1), [])


class Caches(unittest.TestCase):
    def test_cache_folder_names(self):
        os.makedirs(os.path.join(storage.CACHE_HOME, "thing"), exist_ok=True)
        self.assertTrue(storage.cache_folder("thing"))
        for bad in ("", "..", ".", "a/b", "../x", "missing"):
            self.assertIsNone(storage.cache_folder(bad), bad)

    def test_clear_folder_keeps_the_folder(self):
        with tempfile.TemporaryDirectory() as root:
            os.makedirs(os.path.join(root, "sub"))
            with open(os.path.join(root, "sub", "f"), "w") as f:
                f.write("x" * 5000)
            _freed, problems = storage.clear_folder(root)
            self.assertEqual(problems, [])
            self.assertTrue(os.path.isdir(root))
            self.assertEqual(os.listdir(root), [])

    def test_holders_sees_own_open_file(self):
        with tempfile.TemporaryDirectory() as root:
            with open(os.path.join(root, "f"), "w"):
                # Our own pid is skipped on purpose; a sleeping child holds it.
                import subprocess
                child = subprocess.Popen(["sleep", "5"], cwd=root)
                try:
                    self.assertIn("sleep", storage.holders(root))
                finally:
                    child.kill()
                    child.wait()


class HomeScan(unittest.TestCase):
    def test_failed_du_is_not_kept(self):
        # du cut off by its timeout prints nothing: that must not be kept as
        # "your home folder is empty" for the next 6 hours.
        real = storage.du
        storage.du = lambda *_a, **_k: {}
        try:
            if os.path.exists(storage.HOME_CACHE):
                os.unlink(storage.HOME_CACHE)
            self.assertIsNone(storage.home(max_age=0))
            self.assertFalse(os.path.exists(storage.HOME_CACHE))
        finally:
            storage.du = real


class Cli(unittest.TestCase):
    def test_deleting_commands_refuse_extra_arguments(self):
        # Nothing may reach gio or rm when the command line is not exactly right.
        real_run, real_clear = storage.run, storage.clear_cache
        def boom(*_a, **_k):
            raise AssertionError("would have deleted")
        storage.run, storage.clear_cache = boom, boom
        try:
            for argv in (["empty-trash", "--help"], ["empty-trash", "x"], ["clear-thumbnails", "-h"],
                         ["clear-cache", "pip", "--help"], ["clear-cache", "pip", "more"], ["help"]):
                with self.assertRaises(SystemExit, msg=argv):
                    storage.main(argv)
        finally:
            storage.run, storage.clear_cache = real_run, real_clear


class Snapper(unittest.TestCase):
    def test_used_space(self):
        text = json.dumps({"root": [{"number": 0}, {"number": 1, "used-space": 10}, {"number": 2, "used-space": 5}]})
        self.assertEqual(storage.parse_snapper(text), {"count": 2, "used": 15})

    def test_quota_off(self):
        text = json.dumps({"root": [{"number": 1}, {"number": 2, "used-space": 5}]})
        self.assertEqual(storage.parse_snapper(text), {"count": 2, "used": None})
        self.assertIsNone(storage.parse_snapper("nope"))


class Cleanup(unittest.TestCase):
    def test_both_off_touches_nothing(self):
        storage.auto_settings, real = (lambda: {"trash": False, "temp": False, "days": 1}), storage.auto_settings
        try:
            r = storage.cleanup(dry_run=True)
        finally:
            storage.auto_settings = real
        self.assertEqual(r["removed"], 0)
        self.assertFalse(storage.want_timer({"trash": False, "temp": False}))
        self.assertTrue(storage.want_timer({"trash": True, "temp": False}))


class AutomountConf(unittest.TestCase):
    def test_defaults_and_parse(self):
        self.assertEqual(automount.parse_conf(""), {"mount": True, "open": False})
        self.assertEqual(automount.parse_conf("# c\nmount = off\nopen=ON\nbogus=on\nopen2=x"),
                         {"mount": False, "open": True})
        self.assertEqual(automount.parse_conf("mount=maybe"), {"mount": True, "open": False})

    def test_round_trip(self):
        conf = {"mount": False, "open": True}
        self.assertEqual(automount.parse_conf(automount.format_conf(conf)), conf)


if __name__ == "__main__":
    unittest.main()
