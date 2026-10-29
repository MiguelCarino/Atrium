"""The bar's calendar card (calendar_panel.py) and the clock card's NEXT
rows (clock_panel.upcoming_rows): the day cell with its dot, the grid's
date range, the selected day's heading, and the upcoming lines built from
calendar_events' occurrences. Pure: no window is opened, no calendar read."""
import datetime as dt
import importlib.util
import os
import sys
import unittest

import helpers  # noqa: F401  (scratch XDG dirs)

WAYBAR_SCRIPTS = os.path.expanduser("~/.config/waybar/scripts")
sys.path.insert(0, WAYBAR_SCRIPTS)


def load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(WAYBAR_SCRIPTS, f"{name}.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


P = load("calendar_panel")
C = load("clock_panel")
UTC = dt.timezone.utc


class CalendarCard(unittest.TestCase):
    def test_cell_markup_keeps_height(self):
        self.assertEqual(P.cell_markup(7, True), "7\n<span size='6000'>•</span>")
        self.assertEqual(P.cell_markup(7, False), "7\n<span size='6000'> </span>")

    def test_grid_range_is_six_weeks(self):
        start, end = P.grid_range(dt.date(2026, 9, 28))
        self.assertEqual((start, end), (dt.date(2026, 9, 28), dt.date(2026, 11, 9)))

    def test_day_heading(self):
        today = dt.date(2026, 10, 28)
        self.assertEqual(P.day_heading(today, today), "Today")
        self.assertEqual(P.day_heading(dt.date(2026, 10, 29), today), "Tomorrow")
        self.assertEqual(P.day_heading(dt.date(2026, 10, 27), today), "Yesterday")
        self.assertEqual(P.day_heading(dt.date(2026, 10, 31), today), "Saturday 31 October")

    def test_panel_reads_events_module(self):
        self.assertIsNotNone(P.calendar_events)


class ClockNext(unittest.TestCase):
    def test_upcoming_rows(self):
        ce = C.calendar_events
        now = dt.datetime(2026, 10, 28, 12, 0, tzinfo=UTC)
        occs = [
            {"summary": "Gone", "location": "", "all_day": False, "start": now - dt.timedelta(hours=3),
             "end": now - dt.timedelta(hours=2), "uid": "a", "source": "x"},
            {"summary": "Dentist", "location": "Clinic\nFloor 2", "all_day": False,
             "start": now + dt.timedelta(hours=4), "end": now + dt.timedelta(hours=5), "uid": "b", "source": "x"},
            {"summary": "Holiday", "location": "", "all_day": True, "start": dt.date(2026, 10, 29),
             "end": dt.date(2026, 10, 30), "uid": "c", "source": "x"},
        ]
        self.assertIsNotNone(ce)
        self.assertEqual(C.upcoming_rows(occs, now),
                         [("today 16:00", "Dentist  ·  Clinic"), ("tomorrow, all day", "Holiday")])
        self.assertEqual(C.upcoming_rows(occs, now, twelve=True)[0][0], "today 4:00 PM")
        self.assertEqual(C.upcoming_rows([], now), [])


class LoadOrder(unittest.TestCase):
    """load(): one read from disk, then -- only when a subscription is
    stale -- a fetch and a second read, in that order in one thread (so an
    older read never lands after a newer one)."""
    def run_load(self, stale):
        calls, drawn = [], []

        class FakeEvents:
            @staticmethod
            def read_conf():
                return (["https://cal.example.org/a.ics"], {})

            @staticmethod
            def load_events():
                calls.append("read")
                return [len(calls)]

            @staticmethod
            def khal_paths():
                return []

            @staticmethod
            def is_url(_s):
                return True

            @staticmethod
            def stale(_p):
                return stale

            @staticmethod
            def cache_path(s):
                return s

            @staticmethod
            def refresh():
                calls.append("fetch")

        class Inline:
            def __init__(self, target, daemon=True):
                self.target = target

            def start(self):
                self.target()
        old = P.calendar_events, P.threading.Thread, P.GLib.idle_add
        self.addCleanup(lambda: (setattr(P, "calendar_events", old[0]), setattr(P.threading, "Thread", old[1]),
                                 setattr(P.GLib, "idle_add", old[2])))
        P.calendar_events, P.threading.Thread = FakeEvents, Inline
        P.GLib.idle_add = lambda fn, events, has: drawn.append((events, has))
        panel = P.Calendar.__new__(P.Calendar)
        panel.load()
        return calls, drawn

    def test_fresh_reads_once(self):
        calls, drawn = self.run_load(stale=False)
        self.assertEqual(calls, ["read"])
        self.assertEqual(drawn, [([1], True)])

    def test_stale_fetches_then_reads_again(self):
        calls, drawn = self.run_load(stale=True)
        self.assertEqual(calls, ["read", "fetch", "read"])
        self.assertEqual([d[0] for d in drawn], [[1], [3]])


if __name__ == "__main__":
    unittest.main()
