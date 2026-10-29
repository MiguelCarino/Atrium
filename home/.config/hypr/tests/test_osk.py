"""osk.py (the on-screen keyboard): its settings file, which keyboard is
picked from what is installed, the "nothing installed" text, the wvkbd pid
file (only a live wvkbd counts) and the signals it is sent, and gdbus'
Visible answer. Hermetic: no keyboard is started, no signal reaches a real
process (a fake kill), the pid file and osk.conf are scratch paths."""
import os
import signal
import tempfile
import unittest

import helpers

osk = helpers.import_script("osk.py")


class Settings(unittest.TestCase):
    def test_conf_round_trip_and_bad_lines(self):
        with tempfile.TemporaryDirectory(dir=helpers.SCRATCH) as d:
            path = os.path.join(d, "osk.conf")
            self.assertEqual(osk.read_conf(path), {"prefer": "auto", "auto": "off"})
            osk.write_conf({"prefer": "squeekboard", "auto": "on"}, path)
            self.assertEqual(osk.read_conf(path), {"prefer": "squeekboard", "auto": "on"})
            with open(path, "a") as handle:
                handle.write("prefer=onboard\nnoise\n")
            self.assertEqual(osk.read_conf(path)["prefer"], "squeekboard")
        self.assertEqual(osk.check("auto", "on"), "on")
        with self.assertRaises(ValueError):
            osk.check("auto", "maybe")
        with self.assertRaises(ValueError):
            osk.check("size", "big")


class Pick(unittest.TestCase):
    def test_installed_and_pick(self):
        have = osk.installed(lambda b: "/usr/bin/" + b if b in ("wvkbd", "squeekboard") else None)
        self.assertEqual(have, {"wvkbd": "wvkbd", "squeekboard": "squeekboard"})
        self.assertEqual(osk.pick(have), "wvkbd")
        self.assertEqual(osk.pick(have, "squeekboard"), "squeekboard")
        only_sq = {"wvkbd": None, "squeekboard": "squeekboard"}
        self.assertEqual(osk.pick(only_sq, "wvkbd"), "squeekboard")
        none = osk.installed(lambda b: None)
        self.assertIsNone(osk.pick(none))
        self.assertIn("wvkbd", osk.missing_text(none))
        self.assertEqual(osk.missing_text(have), "")
        self.assertEqual(osk.installed(lambda b: b if b == "wvkbd-mobintl" else None)["wvkbd"], "wvkbd-mobintl")


class Wvkbd(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(dir=helpers.SCRATCH)
        self.pidfile = os.path.join(self.dir, "osk.pid")
        self.proc = os.path.join(self.dir, "proc")
        os.makedirs(os.path.join(self.proc, "4242"))

    def comm(self, name):
        with open(os.path.join(self.proc, "4242", "comm"), "w") as handle:
            handle.write(name + "\n")

    def test_pid_only_while_wvkbd(self):
        osk.wvkbd_mark(4242, True, self.pidfile)
        self.comm("wvkbd-mobintl")
        self.assertEqual(osk.wvkbd_pid(self.pidfile, self.proc), 4242)
        self.assertTrue(osk.wvkbd_shown(self.pidfile))
        self.comm("bash")          # the pid was reused: not ours to signal
        self.assertIsNone(osk.wvkbd_pid(self.pidfile, self.proc))
        self.assertIsNone(osk.wvkbd_pid(os.path.join(self.dir, "none"), self.proc))

    def test_signals(self):
        sent = []
        old = osk.PID_FILE, osk.wvkbd_pid
        self.addCleanup(lambda: (setattr(osk, "PID_FILE", old[0]), setattr(osk, "wvkbd_pid", old[1])))
        osk.wvkbd_pid = lambda *a, **k: 4242
        # wvkbd_set marks through the default pidfile argument: point it here.
        mark = osk.wvkbd_mark
        osk.wvkbd_mark = lambda pid, shown, pidfile=self.pidfile: mark(pid, shown, pidfile)
        self.addCleanup(setattr, osk, "wvkbd_mark", mark)
        self.assertTrue(osk.wvkbd_set("wvkbd", True, kill=lambda p, s: sent.append((p, s))))
        self.assertFalse(osk.wvkbd_set("wvkbd", False, kill=lambda p, s: sent.append((p, s))))
        self.assertEqual(sent, [(4242, signal.SIGUSR2), (4242, signal.SIGUSR1)])
        self.assertFalse(osk.wvkbd_shown(self.pidfile))


class Squeekboard(unittest.TestCase):
    def test_parse_visible(self):
        self.assertTrue(osk.parse_visible("(<true>,)\n"))
        self.assertFalse(osk.parse_visible("(<false>,)\n"))
        self.assertIsNone(osk.parse_visible(None))
        self.assertIsNone(osk.parse_visible("(<'x'>,)"))


class NothingToHide(unittest.TestCase):
    def test_hide_never_starts_a_keyboard(self):
        started = []
        old = osk.wvkbd_pid, osk.wvkbd_start, osk.sq_visible, osk.subprocess.Popen
        def restore():
            osk.wvkbd_pid, osk.wvkbd_start, osk.sq_visible, osk.subprocess.Popen = old
        self.addCleanup(restore)
        osk.wvkbd_start = lambda *a, **k: started.append("wvkbd") or 1
        osk.subprocess.Popen = lambda *a, **k: started.append("popen")
        # wvkbd gone between the pid check and the signal
        osk.wvkbd_pid = lambda *a, **k: 4242

        def gone(_p, _s):
            raise ProcessLookupError
        self.assertFalse(osk.wvkbd_set("wvkbd", False, kill=gone))
        # squeekboard not running
        osk.sq_visible = lambda: None
        self.assertFalse(osk.sq_set(False))
        self.assertEqual(started, [])


class Key(unittest.TestCase):
    def test_bound_key_by_description(self):
        binds = [{"modmask": 8, "key": "Q", "description": "Apps: Terminal", "submap": ""},
                 {"modmask": 68, "key": "k", "description": "Accessibility: On-screen keyboard", "submap": ""}]
        self.assertEqual(osk.bound_key(binds), "SUPER+CTRL+K")
        self.assertEqual(osk.bound_key(binds[:1]), "")
        self.assertEqual(osk.bound_key(None), "")


if __name__ == "__main__":
    unittest.main()
