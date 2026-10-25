"""clock_panel.py (the clock card the bar's time opens): finding a zone from
what was typed, the offset and day words, durations, the world-clock file,
and the timers.py command lines it runs. Pure: no window is opened and no
timer is armed; the zones file is a scratch path."""
import datetime as dt
import importlib.util
import os
import sys
import tempfile
import unittest

import helpers  # noqa: F401  (scratch HOME, paths)

WAYBAR_SCRIPTS = os.path.expanduser("~/.config/waybar/scripts")
sys.path.insert(0, WAYBAR_SCRIPTS)
_spec = importlib.util.spec_from_file_location("clock_panel", os.path.join(WAYBAR_SCRIPTS, "clock_panel.py"))
C = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(C)

ZONES = {"America/New_York", "America/Mexico_City", "Asia/Tokyo", "Europe/Lisbon", "UTC"}


class Zones(unittest.TestCase):
    def test_find_zone(self):
        self.assertEqual(C.find_zone("Europe/Lisbon", ZONES), "Europe/Lisbon")
        self.assertEqual(C.find_zone("europe/lisbon", ZONES), "Europe/Lisbon")
        self.assertEqual(C.find_zone("tokyo", ZONES), "Asia/Tokyo")
        self.assertEqual(C.find_zone("  Mexico City ", ZONES), "America/Mexico_City")
        self.assertIsNone(C.find_zone("Atlantis", ZONES))
        self.assertIsNone(C.find_zone("", ZONES))

    def test_names(self):
        self.assertEqual(C.zone_name("America/Mexico_City"), "Mexico City")
        self.assertEqual(C.zone_name("UTC"), "UTC")

    def test_file_and_default(self):
        folder = tempfile.mkdtemp(dir=helpers.SCRATCH)
        path, C.ZONES_FILE = C.ZONES_FILE, os.path.join(folder, "world-clocks.json")
        try:
            self.assertEqual(C.load_zones(), C.DEFAULT_ZONES)          # nothing saved yet
            C.write_json(C.ZONES_FILE, [])
            self.assertEqual(C.load_zones(), [])                       # emptied on purpose stays empty
            C.write_json(C.ZONES_FILE, ["Asia/Tokyo", 3])
            self.assertEqual(C.load_zones(), ["Asia/Tokyo"])
        finally:
            C.ZONES_FILE = path


class Words(unittest.TestCase):
    def test_offsets(self):
        self.assertEqual(C.offset_text(7 * 3600), "+7 h")
        self.assertEqual(C.offset_text(-5.5 * 3600), "−5:30 h")
        self.assertEqual(C.offset_text(0), "same time")
        self.assertEqual(C.utc_offset(dt.timedelta(hours=-6)), "UTC−6")
        self.assertEqual(C.utc_offset(dt.timedelta(hours=5, minutes=30)), "UTC+5:30")
        self.assertEqual(C.utc_offset(dt.timedelta(0)), "UTC")

    def test_day_words(self):
        here = dt.datetime(2026, 10, 24, 22, 0)
        self.assertEqual(C.day_word(dt.datetime(2026, 10, 25, 13, 0), here), "tomorrow")
        self.assertEqual(C.day_word(dt.datetime(2026, 10, 23, 23, 0), here), "yesterday")
        self.assertEqual(C.day_word(here, here), "")

    def test_spans(self):
        self.assertEqual(C.span(65), "1:05")
        self.assertEqual(C.span(3725.37, tenths=True), "1:02:05.3")
        self.assertEqual(C.span(-4), "0:00")

    def test_repeat_words(self):
        self.assertEqual(C.repeat_text({"repeat": ""}), "once")
        if C.timers is not None:
            self.assertEqual(C.repeat_text({"repeat": "Mon,Tue,Wed,Thu,Fri", "days": [0, 1, 2, 3, 4]}),
                             "weekdays")


class Commands(unittest.TestCase):
    def test_alarm(self):
        self.assertEqual(C.alarm_command(" 7:30 ", "weekdays", "wake up"),
                         [C.TIMERS, "alarm", "7:30", "weekdays", "wake", "up"])
        self.assertEqual(C.alarm_command("19:45", "", ""), [C.TIMERS, "alarm", "19:45"])

    def test_timer(self):
        self.assertEqual(C.timer_command("1h30m tea"), [C.TIMERS, "timer", "1h30m", "tea"])


if __name__ == "__main__":
    unittest.main()
