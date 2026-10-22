import datetime
import os
import unittest

import helpers

sched = helpers.import_script("theme-schedule.py")


def at(h, m=0, day=20):
    return datetime.datetime(2026, 10, day, h, m)


class Base(unittest.TestCase):
    def setUp(self):
        self._saved = {k: getattr(sched, k) for k in ("boundaries", "enabled", "current_theme",
                                                       "game_running")}
        sched.boundaries = lambda: ((20, 0), (7, 0))     # night from 20:00, day from 07:00
        sched.enabled = lambda: False
        for path in (sched.PICKS, sched.STATE):
            try:
                os.remove(path)
            except OSError:
                pass

    def tearDown(self):
        for k, v in self._saved.items():
            setattr(sched, k, v)


class Period(Base):
    def test_paths_are_scratch(self):
        self.assertTrue(sched.PICKS.startswith(helpers.SCRATCH))

    def test_day_and_night(self):
        self.assertEqual(sched.period(at(6, 30)), ("night", at(20, 0, 19)))
        self.assertEqual(sched.period(at(7, 0)), ("day", at(7, 0)))
        self.assertEqual(sched.period(at(19, 59)), ("day", at(7, 0)))
        self.assertEqual(sched.period(at(23)), ("night", at(20, 0)))

    def test_no_evening_without_a_pick(self):
        self.assertEqual(sched.period(at(18))[0], "day")

    def test_evening(self):
        sched.set_pick("evening", "matrix")
        self.assertEqual(sched.period(at(16, 59))[0], "day")
        self.assertEqual(sched.period(at(17, 0)), ("evening", at(17, 0)))
        self.assertEqual(sched.period(at(19, 30))[0], "evening")
        self.assertEqual(sched.period(at(20, 0))[0], "night")

    def test_evening_from(self):
        sched.set_pick("evening", "matrix")
        sched.set_evening_from("18:30")
        self.assertEqual(sched.period(at(18, 0))[0], "day")
        self.assertEqual(sched.period(at(18, 30))[0], "evening")

    def test_evening_off(self):
        sched.set_pick("evening", "matrix")
        sched.set_pick("evening", "off")
        self.assertEqual(sched.picks()["evening"], "")
        self.assertEqual(sched.period(at(18))[0], "day")

    def test_unknown_theme_refused(self):
        with self.assertRaises(SystemExit):
            sched.set_pick("day", "no-such-theme")


class Tick(Base):
    def run_tick(self, now_theme):
        calls = []
        sched.current_theme = lambda: now_theme
        sched.game_running = lambda: False
        real_run = sched.subprocess.run
        sched.subprocess.run = lambda argv, **kw: calls.append(argv)
        try:
            sched.tick()
        finally:
            sched.subprocess.run = real_run
        return [c for c in calls if "set" in c]

    def test_random_picks_another_theme(self):
        for part in sched.PARTS:
            if part != "evening":
                sched.set_pick(part, "random")
        sets = self.run_tick("matrix")
        self.assertEqual(len(sets), 1)
        self.assertNotEqual(sets[0][-1], "matrix")

    def test_switches_once_per_period(self):
        sched.set_pick("day", "aero")
        sched.set_pick("night", "aero")
        self.assertEqual(len(self.run_tick("matrix")), 1)
        self.assertEqual(self.run_tick("matrix"), [])       # same period: left alone

    def test_game_holds_the_switch(self):
        sched.current_theme = lambda: "matrix"
        sched.game_running = lambda: True
        sched.tick()
        self.assertFalse(os.path.exists(sched.STATE))


if __name__ == "__main__":
    unittest.main()
