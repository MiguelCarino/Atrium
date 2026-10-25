"""clock_panel.py (the clock card the bar's time opens): finding a zone from
what was typed, the offset and day words, durations, the world-clock file
and its pin (with clock.py's side: the code, the reading, the mtime-cached
read), the meeting planner's hours and overlap, and the timers.py command
lines it runs. Pure: no window is opened and no timer is armed; the zones
file is a scratch path."""
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
            self.assertEqual(C.load_zones(), (C.DEFAULT_ZONES, None))  # nothing saved yet
            C.write_json(C.ZONES_FILE, [])
            self.assertEqual(C.load_zones(), ([], None))               # emptied on purpose stays empty
            C.write_json(C.ZONES_FILE, ["Asia/Tokyo", 3])              # the old plain list
            self.assertEqual(C.load_zones(), (["Asia/Tokyo"], None))
            C.save_zones(["Asia/Tokyo", "Europe/Lisbon"], "Europe/Lisbon")
            self.assertEqual(C.load_zones(), (["Asia/Tokyo", "Europe/Lisbon"], "Europe/Lisbon"))
            C.save_zones(["Asia/Tokyo"], "Europe/Lisbon")              # a pin that is not a zone: dropped
            self.assertEqual(C.load_zones(), (["Asia/Tokyo"], None))
        finally:
            C.ZONES_FILE = path


class Pin(unittest.TestCase):
    def test_codes(self):
        K = C.clock.zone_code
        self.assertEqual(K("Asia/Tokyo"), "TYO")
        self.assertEqual(K("America/New_York"), "NYC")
        self.assertEqual(K("Europe/Lisbon"), "LIS")
        self.assertEqual(K("Pacific/Port_Moresby"), "PM")
        self.assertEqual(K("UTC"), "UTC")

    def test_parse_zones(self):
        P = C.clock.parse_zones
        self.assertEqual(P(["Asia/Tokyo"]), (["Asia/Tokyo"], None))
        self.assertEqual(P({"zones": ["Asia/Tokyo"], "pin": "Asia/Tokyo"}), (["Asia/Tokyo"], "Asia/Tokyo"))
        self.assertEqual(P({"zones": ["Asia/Tokyo"], "pin": "Europe/Paris"}), (["Asia/Tokyo"], None))
        self.assertEqual(P({"pin": "x"}), (None, None))
        self.assertEqual(P(None), (None, None))

    def test_pinned_zone_reads_on_mtime(self):
        folder = tempfile.mkdtemp(dir=helpers.SCRATCH)
        path = os.path.join(folder, "world-clocks.json")
        self.assertIsNone(C.clock.pinned_zone(path))
        C.write_json(path, {"zones": ["Asia/Tokyo"], "pin": "Asia/Tokyo"})
        self.assertEqual(C.clock.pinned_zone(path), "Asia/Tokyo")
        reads = []
        real_open = open

        def counting_open(*a, **k):
            reads.append(a[0])
            return real_open(*a, **k)
        C.clock.open = counting_open            # a module global shadows the builtin
        try:
            self.assertEqual(C.clock.pinned_zone(path), "Asia/Tokyo")
            self.assertEqual(reads, [])         # unchanged file: only a stat()
        finally:
            del C.clock.open
        stamp = os.stat(path).st_mtime_ns + 10 ** 9
        C.write_json(path, {"zones": ["Asia/Tokyo"], "pin": None})
        os.utime(path, ns=(stamp, stamp))
        self.assertIsNone(C.clock.pinned_zone(path))

    def test_pin_text(self):
        now = dt.datetime(2026, 10, 24, 2, 26, 30, tzinfo=dt.timezone.utc)
        self.assertEqual(C.clock.pin_text("Asia/Tokyo", {"clock": "24"}, now), " · TYO 11:26")
        self.assertEqual(C.clock.pin_text("Asia/Tokyo", {"clock": "12"}, now), " · TYO 11:26 AM")
        self.assertEqual(C.clock.pin_text(None, {}, now), "")
        self.assertEqual(C.clock.pin_text("Mars/Olympus", {}, now), "")


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


class Alarms(unittest.TestCase):
    def test_repeat_choice(self):
        self.assertEqual(C.repeat_choice({}), "")
        self.assertEqual(C.repeat_choice({"repeat": "x", "days": list(range(7))}), "daily")
        self.assertEqual(C.repeat_choice({"repeat": "x", "days": [4, 3, 2, 1, 0]}), "weekdays")
        self.assertEqual(C.repeat_choice({"repeat": "x", "days": [5, 6]}), "weekends")
        self.assertIsNone(C.repeat_choice({"repeat": "x", "days": [0, 2, 4]}))     # kept as it is

    def test_edit_command(self):
        self.assertEqual(C.edit_command("12", " 8:00 ", "weekdays", "wake up"),
                         [C.TIMERS, "edit", "12", "8:00", "weekdays", "--", "wake", "up"])
        self.assertEqual(C.edit_command("12", "8:00", "", ""), [C.TIMERS, "edit", "12", "8:00", "once", "--"])
        self.assertEqual(C.edit_command("12", "8:00", None, "x"), [C.TIMERS, "edit", "12", "8:00", "--", "x"])
        if C.timers is not None:                # what the card sends, timers.py reads back
            self.assertEqual(C.timers.parse_edit(C.edit_command("1", "8:00", None, "")[3:]),
                             ((8, 0), C.timers.KEEP, ""))

    def test_countdown_command(self):
        self.assertEqual(C.countdown_command("2027-01-01 00:00", "New Year", True),
                         [C.TIMERS, "countdown", "add", "--alarm", "2027-01-01", "00:00", "--", "New", "Year"])
        self.assertEqual(C.countdown_command("2027-01-01", "", False),
                         [C.TIMERS, "countdown", "add", "2027-01-01", "--"])
        # The label after "--": not the time of a bare date, not the flag.
        self.assertEqual(C.countdown_command("2027-01-01", "5:00 --alarm shift", False)[-4:],
                         ["--", "5:00", "--alarm", "shift"])

    def test_countdown_sub(self):
        at = dt.datetime(2027, 1, 1, 0, 0).timestamp()
        self.assertEqual(C.countdown_sub(at, {"clock": "24"}), "Fri 01 Jan 2027, 00:00")


@unittest.skipIf(C.ZoneInfo is None, "no zoneinfo")
class Planner(unittest.TestCase):
    DAY = dt.date(2026, 10, 24)

    def zones(self):
        return C.ZoneInfo("America/Chicago"), C.ZoneInfo("Europe/Lisbon")

    def test_in_hours(self):
        self.assertTrue(C.in_hours(9.5, (9, 17)))
        self.assertFalse(C.in_hours(17.5, (9, 17)))
        self.assertTrue(C.in_hours(0.5, (22, 26)))          # past midnight
        self.assertTrue(C.in_hours(23.5, (-2, 6)))          # from the evening before

    def test_cells_and_overlap(self):
        here, there = self.zones()                          # Lisbon is +6 h on this day (CDT, WEST)
        cells = C.planner(self.DAY, here, there)
        self.assertEqual(len(cells), 24)
        self.assertEqual(cells[9]["there"].hour, 15)
        self.assertEqual([c["hour"] for c in cells if c["mine"]], list(range(9, 17)))
        self.assertEqual([c["hour"] for c in cells if c["theirs"]], list(range(3, 11)))
        self.assertEqual([c["hour"] for c in cells if c["both"]], [9, 10])
        (run,) = C.overlap_runs(cells)
        self.assertEqual((run[0]["hour"], run[1]["hour"]), (9, 10))
        self.assertEqual(C.overlap_text(cells, "Lisbon", {"clock": "24"}),
                         "Overlap 09:00–11:00 here = 15:00–17:00 in Lisbon  ·  2 h")

    def test_no_overlap_and_runs(self):
        here = C.ZoneInfo("America/Chicago")
        cells = C.planner(self.DAY, here, C.ZoneInfo("Asia/Tokyo"))
        self.assertEqual(C.overlap_runs(cells), [])
        self.assertIn("No working hours in common with Tokyo", C.overlap_text(cells, "Tokyo"))
        same = C.planner(self.DAY, here, here, mine=(8, 12), theirs=(10, 18))
        runs = C.overlap_runs(same)
        self.assertEqual([(a["hour"], b["hour"]) for a, b in runs], [(10, 11)])

    def test_half_hour_zone(self):
        here = C.ZoneInfo("UTC")
        cells = C.planner(self.DAY, here, C.ZoneInfo("Asia/Kolkata"))      # +5:30
        self.assertEqual((cells[3]["there"].hour, cells[3]["there"].minute), (8, 30))
        self.assertTrue(cells[3]["theirs"])                 # 08:30-09:30: its middle is 9:00
        self.assertFalse(cells[2]["theirs"])

    def test_my_work_hours(self):
        here, _ = self.zones()
        self.assertEqual(C.my_work_hours(None, self.DAY, here), C.DEFAULT_WORK)
        if C.workhours is None:
            return
        self.assertEqual(C.my_work_hours({"start": "08:30", "end": "18:00"}, self.DAY, here), (8.5, 18.0))
        # Work hours kept in New York time (EDT, UTC-4) seen from Chicago (CDT, UTC-5).
        conf = {"start": "09:00", "end": "17:00", "timezone": "America/New_York"}
        self.assertEqual(C.my_work_hours(conf, self.DAY, here), (8.0, 16.0))

    def test_my_work_hours_on_a_clock_change_day(self):
        """Wall-clock hours, not time since midnight: on 2027-03-14 Chicago
        and New York both spring forward, and 09:00-17:00 New York is
        08:00-16:00 on Chicago's clock (elapsed time said 7-15)."""
        if C.workhours is None or C.ZoneInfo is None:
            self.skipTest("no workhours module")
        here, day = C.ZoneInfo("America/Chicago"), dt.date(2027, 3, 14)
        conf = {"start": "09:00", "end": "17:00", "timezone": "America/New_York"}
        self.assertEqual(C.my_work_hours(conf, day, here), (8.0, 16.0))
        conf = {"start": "10:00", "end": "17:00", "timezone": "America/New_York"}
        self.assertEqual(C.my_work_hours(conf, day, here)[0], 9.0)
        # A zone far enough away still runs off either end of the day.
        conf = {"start": "09:00", "end": "23:00", "timezone": "Asia/Tokyo"}
        self.assertEqual(C.my_work_hours(conf, day, here), (-6.0, 9.0))

    def test_words(self):
        self.assertEqual(C.hour_text(9, {"clock": "24"}), "09")
        self.assertEqual(C.hour_text(0, {"clock": "12"}), "12")
        self.assertEqual(C.hour_text(15, {"clock": "12"}), "3")
        here, there = self.zones()
        cells = C.planner(self.DAY, here, there)
        self.assertEqual(C.cell_text(cells[9], "Lisbon", {"clock": "24"}),
                         "09:00 here = 15:00 Sat in Lisbon  ·  both working")
        self.assertIn("(tomorrow)", C.cell_text(cells[20], "Lisbon", {"clock": "24"}))
        self.assertIn("they're working, you're not", C.cell_text(cells[3], "Lisbon"))


class Commands(unittest.TestCase):
    def test_alarm(self):
        self.assertEqual(C.alarm_command(" 7:30 ", "weekdays", "wake up"),
                         [C.TIMERS, "alarm", "7:30", "weekdays", "--", "wake", "up"])
        self.assertEqual(C.alarm_command("19:45", "", ""), [C.TIMERS, "alarm", "19:45", "--"])
        if C.timers is not None:                # what the card sends, timers.py reads back
            now = dt.datetime(2026, 10, 20, 6, 0)
            when, days, label, then = C.timers.parse_alarm(
                C.alarm_command("7:00", "", "take meds then sleep")[2:], now)
            self.assertEqual((when.hour, days, label, then), (7, None, "take meds then sleep", None))
            self.assertEqual(C.timers.parse_alarm(C.alarm_command("7:00", "", "mon review")[2:], now)[1:3],
                             (None, "mon review"))
            self.assertEqual(C.timers.parse_alarm(C.alarm_command("7:00", "daily", "x")[2:], now)[1:3],
                             (tuple(range(7)), "x"))

    def test_timer(self):
        self.assertEqual(C.timer_command("1h30m tea"), [C.TIMERS, "timer", "1h30m", "tea"])


if __name__ == "__main__":
    unittest.main()
