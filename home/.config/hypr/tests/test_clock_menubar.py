"""waybar/scripts/clock.py's menu-bar layout (a theme's bar.clock=menubar,
read from waybar/generated/bar.conf): the one reading at the far right
("Tue 27 Oct  21:21"), its 12-hour and Japanese forms, the centre's day and
clock going blank under it, and custom/logo's glyph. Hermetic: bar.conf is
a scratch file per test, the language is passed in or patched, and the
region preferences are given -- nothing reads the live generated folder."""
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from unittest import mock

import helpers

CLOCK = os.path.join(os.path.expanduser("~"), ".config", "waybar", "scripts", "clock.py")
clock = None


def setUpModule():
    global clock
    import importlib.util
    spec = importlib.util.spec_from_file_location("waybar_clock", CLOCK)
    clock = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(clock)


MOMENT = datetime(2026, 10, 27, 21, 21, 7, tzinfo=timezone(timedelta(hours=-6)))
MORNING = datetime(2026, 3, 1, 9, 5, 0, tzinfo=timezone.utc)


class Text(unittest.TestCase):
    def test_24h(self):
        self.assertEqual(clock.menubar_text(MOMENT, {"clock": "24", "seconds": "on"}, "en"),
                         "Tue 27 Oct  21:21")

    def test_12h_no_leading_zero_no_seconds(self):
        self.assertEqual(clock.menubar_text(MOMENT, {"clock": "12", "seconds": "on"}, "en"),
                         "Tue 27 Oct  9:21 PM")
        self.assertEqual(clock.menubar_text(MORNING, {"clock": "24", "seconds": "off"}, "en"),
                         "Sun 1 Mar  09:05")

    def test_ja(self):
        self.assertEqual(clock.menubar_text(MOMENT, {"clock": "24"}, "ja"), "10月27日(火)  21:21")


class Layout(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(dir=helpers.SCRATCH)
        self.addCleanup(shutil.rmtree, self.root, True)
        self.conf = os.path.join(self.root, "bar.conf")
        patcher = mock.patch.object(clock, "BAR_CONF", self.conf)
        patcher.start()
        self.addCleanup(patcher.stop)
        clock._bar.update(mtime=None, conf={})

    def write(self, text):
        with open(self.conf, "w") as handle:
            handle.write(text)
        # a new mtime even within the same clock tick
        st = os.stat(self.conf)
        os.utime(self.conf, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))

    def emit(self, kind):
        out = io.StringIO()
        with redirect_stdout(out), mock.patch.object(clock, "lang", return_value="en"), \
                mock.patch.object(clock, "prefs", return_value={"clock": "24", "seconds": "on"}):
            clock.emit(kind)
        return json.loads(out.getvalue())

    def test_missing_file_is_the_usual_bar(self):
        self.assertEqual(clock.bar_style(), {})
        self.assertEqual(self.emit("menubar")["text"], "")
        self.assertEqual(self.emit("logo")["text"], "")
        self.assertNotEqual(self.emit("day")["text"], "")
        self.assertNotEqual(self.emit("clock")["text"], "")

    def test_menubar_moves_the_reading(self):
        self.write("# GENERATED\nclock=menubar\nlogo=\n")
        self.assertEqual(clock.bar_style(), {"clock": "menubar", "logo": ""})
        got = self.emit("menubar")
        self.assertEqual(got["class"], "menubar")
        self.assertRegex(got["text"], r"^[A-Z][a-z]{2} \d{1,2} [A-Z][a-z]{2}  \d{2}:\d{2}$")
        self.assertEqual(self.emit("day")["text"], "")
        self.assertEqual(self.emit("clock")["text"], "")
        logo = self.emit("logo")
        self.assertEqual((logo["text"], logo["class"]), ("", "logo"))

    def test_back_to_the_centre(self):
        self.write("clock=menubar\nlogo=\n")
        self.assertEqual(self.emit("clock")["text"], "")
        self.write("clock=\nlogo=\n")
        self.assertNotEqual(self.emit("clock")["text"], "")
        self.assertEqual(self.emit("menubar")["text"], "")


if __name__ == "__main__":
    unittest.main()
