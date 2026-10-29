"""screentime.py: the count (Tracker driven with made-up times: no clock,
socket or file of its own), the hour / day split, the idle listener's late
word taken back, breaks and snooze, the 20-20-20 reminder, and the readers
the Settings page uses. Nothing here starts the service."""
import datetime as dt
import unittest

import helpers

S = helpers.import_script("screentime.py")


def at(h, m=0, s=0, day=28):
    return dt.datetime(2026, 10, day, h, m, s).timestamp()


def conf(**kw):
    return dict(S.DEFAULTS, **kw)


class Settings(unittest.TestCase):
    def test_defaults_count_on_reminders_off(self):
        c = S.parse_conf("")
        self.assertEqual((c["count"], c["breaks"], c["eyes"], c["break_every"]), ("on", "off", "off", 50))

    def test_round_trip_and_bad_values(self):
        c = S.parse_conf("breaks=on\nbreak_every=30\nsnooze=abc\nbreak_len=999\nnope=1\n")
        self.assertEqual((c["breaks"], c["break_every"], c["snooze"], c["break_len"]), ("on", 30, 10, 5))
        self.assertEqual(S.parse_conf(S.render_conf(c)), c)

    def test_check_setting(self):
        self.assertEqual(S.check_setting("eyes", "ON"), "on")
        self.assertEqual(S.check_setting("keep", "30"), 30)
        for key, value in (("breaks", "maybe"), ("break_every", "5"), ("colour", "x")):
            with self.assertRaises(ValueError):
                S.check_setting(key, value)


class Counting(unittest.TestCase):
    def test_credit_splits_hours_and_days(self):
        days = {}
        S.credit(days, at(23, 50), at(0, 10, day=29), "kitty")
        self.assertEqual(days["2026-10-28"]["hours"][23], 600)
        self.assertEqual(days["2026-10-29"]["hours"][0], 600)
        self.assertEqual(days["2026-10-28"]["apps"], {"kitty": 600})

    def test_app_switches(self):
        t = S.Tracker(at(9), "firefox", conf())
        t.set_app("kitty", at(9, 10))
        t.set_app("kitty", at(9, 12))             # a title change: same class
        t.advance(at(9, 30))
        day = t.days["2026-10-28"]
        self.assertEqual(day["apps"], {"firefox": 600, "kitty": 1200})
        self.assertEqual(day["active_s"], 1800)

    def test_idle_is_not_counted_and_the_lag_is_taken_back(self):
        t = S.Tracker(at(9), "firefox", conf())
        t.set_idle(True, at(9, 10), lag=60)         # really idle since 9:09
        t.set_idle(False, at(9, 40))
        t.advance(at(9, 45))
        self.assertEqual(t.days["2026-10-28"]["active_s"], 9 * 60 + 5 * 60)

    def test_lock_pauses(self):
        t = S.Tracker(at(9), "x", conf())
        t.set_locked(True, at(9, 5))
        t.advance(at(9, 30))
        t.set_locked(False, at(9, 30))
        t.advance(at(9, 31))
        self.assertEqual(t.days["2026-10-28"]["active_s"], 6 * 60)

    def test_count_off_counts_nothing(self):
        t = S.Tracker(at(9), "x", conf(count="off"))
        t.advance(at(10))
        self.assertEqual(t.days, {})

    def test_uncredit_never_below_zero(self):
        days = {}
        S.credit(days, at(9), at(9, 0, 20), "x")
        S.uncredit(days, at(9, 0, 20), 60, "x")
        self.assertEqual(days["2026-10-28"]["active_s"], 0)
        S.uncredit({}, at(9), 60, "x")             # no day: nothing to do

    def test_parse_event(self):
        self.assertEqual(S.parse_event("activewindow>>firefox,Some, title"), "firefox")
        self.assertEqual(S.parse_event("activewindow>>,"), "")
        self.assertIsNone(S.parse_event("activewindowv2>>abc"))
        self.assertIsNone(S.parse_event("workspace>>2"))

    def test_locked_comm(self):
        self.assertTrue(S.is_locked_comm(["bash\n", "hyprlock\n"]))
        self.assertFalse(S.is_locked_comm(["hyprlockx\n", "kitty\n"]))


class Breaks(unittest.TestCase):
    def test_break_reminder_and_repeat(self):
        t = S.Tracker(at(9), "x", conf(breaks="on", break_every=50, snooze=10))
        t.advance(at(9, 49))
        self.assertEqual(t.due(), [])
        t.advance(at(9, 50))
        self.assertEqual(t.due(), ["break"])
        self.assertEqual(t.due(), [])
        t.advance(at(10, 0))
        self.assertEqual(t.due(), ["break"])        # no break taken: again after snooze minutes

    def test_snooze(self):
        t = S.Tracker(at(9), "x", conf(breaks="on", break_every=50, snooze=10))
        t.advance(at(9, 50))
        t.due()
        t.snooze(25)
        t.advance(at(10, 14))
        self.assertEqual(t.due(), [])
        t.advance(at(10, 15))
        self.assertEqual(t.due(), ["break"])

    def test_a_real_break_resets(self):
        t = S.Tracker(at(9), "x", conf(breaks="on", break_every=50, break_len=5))
        t.advance(at(9, 45))
        t.set_idle(True, at(9, 46), lag=60)
        t.set_idle(False, at(9, 52))                 # away since 9:45: 7 min
        t.advance(at(10, 30))
        self.assertEqual(t.due(), [])
        self.assertEqual(round(t.streak), 38 * 60)

    def test_a_short_pause_is_not_a_break(self):
        t = S.Tracker(at(9), "x", conf(breaks="on", break_every=50, break_len=5))
        t.advance(at(9, 40))
        t.set_idle(True, at(9, 41), lag=60)
        t.set_idle(False, at(9, 43))
        t.advance(at(9, 54))
        self.assertEqual(t.due(), ["break"])

    def test_breaks_off_never_remind(self):
        t = S.Tracker(at(9), "x", conf())
        t.advance(at(13))
        self.assertEqual(t.due(), [])

    def test_eyes_every_20_minutes(self):
        t = S.Tracker(at(9), "x", conf(eyes="on"))
        t.advance(at(9, 20))
        self.assertEqual(t.due(), ["eyes"])
        t.advance(at(9, 39))
        self.assertEqual(t.due(), [])
        t.advance(at(9, 40))
        self.assertEqual(t.due(), ["eyes"])

    def test_no_reminder_while_away(self):
        t = S.Tracker(at(9), "x", conf(breaks="on", break_every=10))
        t.advance(at(9, 30))
        t.set_locked(True, at(9, 30))
        self.assertEqual(t.due(), [])

    def test_a_suspend_is_not_counted_and_is_a_break(self):
        t = S.Tracker(at(9), "x", conf(breaks="on", break_every=50, break_len=5))
        t.advance(at(9, 40))
        t.skip(at(11))                          # asleep 9:40 -> 11:00
        t.advance(at(11, 10))
        self.assertEqual(round(t.days["2026-10-28"]["active_s"]), 50 * 60)
        self.assertEqual(round(t.streak), 10 * 60)

    def test_skip_while_locked_keeps_it_locked(self):
        t = S.Tracker(at(9), "x", conf())
        t.set_locked(True, at(9, 5))
        t.skip(at(10))
        self.assertTrue(t.locked)
        self.assertEqual(round(t.days["2026-10-28"]["active_s"]), 5 * 60)

    def test_live(self):
        t = S.Tracker(at(9), "kitty", conf(breaks="on"))
        t.advance(at(9, 20))
        live = t.live(at(9, 20))
        self.assertEqual((live["app"], live["streak_s"], live["next_break_s"]), ("kitty", 1200, 1800))


class Reading(unittest.TestCase):
    def test_top_apps_and_week(self):
        day = {"apps": {"a": 10, "b": 300, "c": 0.4}}
        self.assertEqual(S.top_apps(day), [("b", 300), ("a", 10)])
        got = S.week({"2026-10-28": {"active_s": 60}}, dt.date(2026, 10, 28), 3)
        self.assertEqual(got, [("2026-10-26", 0), ("2026-10-27", 0), ("2026-10-28", 60)])

    def test_hm(self):
        self.assertEqual(S.hm(0), "0 min")
        self.assertEqual(S.hm(42 * 60), "42 min")
        self.assertEqual(S.hm(3 * 3600 + 5 * 60), "3 h 05 min")

    def test_old_files(self):
        names = ["2026-01-01.json", "2026-10-27.json", "notes.txt", "bad.json"]
        self.assertEqual(S.old_files(names, dt.date(2026, 10, 28), 90), ["2026-01-01.json"])

    def test_idle_source(self):
        self.assertEqual(S.idle_source("on-timeout = ~/.config/hypr/scripts/screentime-idle on"), "hypridle")
        self.assertEqual(S.idle_source(""), "lock only")


if __name__ == "__main__":
    unittest.main()
