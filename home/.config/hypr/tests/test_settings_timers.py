"""Settings > Timers & alarms: timers.py's settings (timers.conf), the sound
choice, the old constants that now follow the settings, the calendar skip
list; workhours.py's workhours.conf (off, hours, days, label, time zone,
holidays, personal repos); the page's pure helpers.

Hermetic: timers.conf is in helpers.py's scratch XDG_STATE_HOME and
workhours.conf is its scratch HYPR_WORKHOURS_CONF; no timer is armed, no sound played, no calendar read
(calendar_use only edits the setting), and refresh_bar is never called."""
import datetime as dt
import os
import unittest

import helpers

timers = helpers.import_script("timers.py", "timers")
workhours = helpers.import_script("workhours.py")


class TimerSettings(unittest.TestCase):
    def setUp(self):
        for path in (timers.CONF,):
            if os.path.exists(path):
                os.remove(path)

    tearDown = setUp

    def test_defaults_are_the_old_behaviour(self):
        v = timers.settings()
        self.assertEqual((v["focus_min"], v["break_min"], v["long_break_min"], v["long_every"]), (25, 5, 15, 4))
        self.assertEqual((v["snooze_min"], v["sound"], v["volume"], v["cal_lead_min"]), (5, "theme", 100, 10))
        self.assertEqual(timers.FOCUS_MIN, 25)
        self.assertEqual(timers.SNOOZE_S, 300)
        self.assertEqual(timers.play_argv("x.oga"), ["pw-play", "x.oga"])        # no --volume at 100 %
        self.assertEqual(timers.sounds_for("alarm.wav", None), ("alarm.wav", None))
        self.assertEqual(timers.cal_ahead_min(), 30)

    def test_set_and_read_back(self):
        timers.set_setting("focus_min", "50")
        timers.set_setting("volume", "60%")
        self.assertEqual(timers.FOCUS_MIN, 50)                 # what launcher.py reads
        self.assertEqual(timers.play_argv("x"), ["pw-play", "--volume=0.60", "x"])
        timers.set_setting("focus_min", "25")                  # back at the default: dropped from the file
        with open(timers.CONF) as handle:
            text = handle.read()
        self.assertNotIn("focus_min", text)
        self.assertIn("volume=60", text)

    def test_refuses_bad_values(self):
        for key, value in (("sound", "bell"), ("volume", "300"), ("focus_min", "0"), ("focus_min", "ten"),
                           ("nope", "1")):
            with self.assertRaises(ValueError, msg=(key, value)):
                timers.set_setting(key, value)
        self.assertFalse(os.path.exists(timers.CONF))

    def test_hand_edit_falls_back(self):
        os.makedirs(os.path.dirname(timers.CONF), exist_ok=True)
        with open(timers.CONF, "w") as handle:
            handle.write("# x\nfocus_min=abc\nsnooze_min=10\nsound=loud\ngarbage\n")
        v = timers.settings()
        self.assertEqual((v["focus_min"], v["snooze_min"], v["sound"]), (25, 10, "theme"))

    def test_sound_choice(self):
        timers.set_setting("sound", "chime")
        self.assertEqual(timers.sounds_for("alarm.wav", None), (timers.CHIME, None))
        self.assertEqual(timers.sounds_for(None, timers.SOUND), (None, timers.CHIME))
        timers.set_setting("sound", "none")
        self.assertEqual(timers.sounds_for("alarm.wav", timers.SOUND), (None, None))

    def test_calendar_skip_list(self):
        timers.calendar_use("a", False)
        timers.calendar_use("b", False)
        timers.calendar_use("a", False)                        # twice: listed once
        self.assertEqual(timers.setting("cal_skip"), "b,a")
        timers.calendar_use("b", True)
        self.assertEqual(timers.setting("cal_skip"), "a")

    def test_long_lead_looks_further_ahead(self):
        timers.set_setting("cal_lead_min", "60")
        self.assertEqual(timers.cal_ahead_min(), 70)

    def test_back_at_defaults_leaves_no_file(self):
        timers.set_setting("snooze_min", "10")
        self.assertTrue(os.path.exists(timers.CONF))
        timers.set_setting("snooze_min", "5")
        self.assertFalse(os.path.exists(timers.CONF))

    def test_unknown_attribute(self):
        with self.assertRaises(AttributeError):
            timers.NOT_A_THING


class WorkHours(unittest.TestCase):
    """workhours.conf (helpers.py's scratch HYPR_WORKHOURS_CONF): off with no
    file, the defaults once enabled, label / time zone / holidays / personal
    repos from its keys."""
    def setUp(self):
        for path in (workhours.CONF, workhours.CONF + ".off", workhours.OFF_FILE):
            if os.path.exists(path):
                os.remove(path)

    tearDown = setUp

    def write(self, text):
        with open(workhours.CONF, "w") as handle:
            handle.write(text)

    def test_no_file_is_off(self):
        self.assertIsNone(workhours.load())
        self.assertEqual(workhours.hours()[2], ())
        working, reason, _end = workhours.state(dt.datetime(2026, 10, 20, 10, 0))     # a Tuesday
        self.assertFalse(working)
        self.assertIn("off", reason)
        self.assertIsNone(workhours.holiday(dt.date(2026, 11, 16)))                   # no holidays either
        with self.assertRaises(ValueError):
            workhours.set_hours("start", "8:30")                                       # enable first
        self.assertFalse(os.path.exists(workhours.CONF))

    def test_enable_gives_the_defaults(self):
        workhours.enable()
        self.assertEqual(workhours.hours(), (dt.time(9), dt.time(18), (0, 1, 2, 3, 4)))
        self.assertEqual(workhours.label(), "Work")
        working, reason, _end = workhours.state(dt.datetime(2026, 10, 20, 10, 0))
        self.assertTrue(working)
        self.assertEqual(reason, "Work hours, 09:00-18:00")
        self.assertFalse(workhours.state(dt.datetime(2026, 10, 24, 10, 0))[0])      # a Saturday
        self.assertTrue(workhours.state(dt.datetime(2026, 11, 16, 10, 0))[0])       # no holidays by default

    def test_disable_keeps_the_settings(self):
        workhours.enable()
        workhours.set_hours("label", "Acme")
        workhours.disable()
        self.assertIsNone(workhours.load())
        workhours.enable()
        self.assertEqual(workhours.label(), "Acme")

    def test_set_hours_and_days(self):
        workhours.enable()
        workhours.set_hours("start", "8:30")
        workhours.set_hours("days", "mon,wed,sat")
        self.assertEqual(workhours.hours(), (dt.time(8, 30), dt.time(18), (0, 2, 5)))
        self.assertTrue(workhours.state(dt.datetime(2026, 10, 24, 8, 45))[0])       # Saturday now works
        working, reason, _end = workhours.state(dt.datetime(2026, 10, 20, 10, 0))   # Tuesday does not
        self.assertFalse(working)
        self.assertTrue(reason.startswith("day off"))          # mascot_mood counts it as a day off

    def test_set_keeps_other_lines(self):
        self.write("# mine\nlabel=Acme\nholidays=mx\nfoo=bar\n")
        workhours.set_hours("end", "17:00")
        with open(workhours.CONF) as handle:
            text = handle.read()
        for line in ("# mine", "label=Acme", "holidays=mx", "foo=bar", "end=17:00"):
            self.assertIn(line, text.splitlines())

    def test_refuses_end_before_start(self):
        workhours.enable()
        with self.assertRaises(ValueError):
            workhours.set_hours("end", "08:00")
        with self.assertRaises(ValueError):
            workhours.set_hours("days", "funday")

    def test_bad_lines_keep_the_defaults(self):
        self.write("start=nine\nend=25:99\ndays=funday\n")
        self.assertEqual(workhours.hours(), (dt.time(9), dt.time(18), (0, 1, 2, 3, 4)))

    def test_no_days(self):
        workhours.enable()
        workhours.set_hours("days", "none")
        self.assertEqual(workhours.hours()[2], ())
        self.assertFalse(workhours.state(dt.datetime(2026, 10, 20, 10, 0))[0])

    def test_label_and_mexican_holidays(self):
        self.write("label=Acme\nholidays=mx\n")
        self.assertEqual(workhours.state(dt.datetime(2026, 10, 20, 10, 0))[1], "Acme hours, 09:00-18:00")
        self.assertEqual(workhours.next_holiday(dt.date(2026, 10, 20))[0], dt.date(2026, 11, 16))
        working, reason, _end = workhours.state(dt.datetime(2026, 11, 16, 10, 0))
        self.assertFalse(working)
        self.assertTrue(reason.startswith("holiday"))

    def test_time_zone(self):
        # 10:00 in Mexico City (UTC-6) is 16:00 UTC: work time there, whatever
        # this computer's zone; 01:00 UTC is still the evening before there.
        self.write("timezone=America/Mexico_City\n")
        utc = dt.timezone.utc
        self.assertTrue(workhours.state(dt.datetime(2026, 10, 20, 16, 0, tzinfo=utc))[0])
        self.assertFalse(workhours.state(dt.datetime(2026, 10, 21, 1, 0, tzinfo=utc))[0])
        self.write("timezone=Not/AZone\n")                       # unknown: this computer's
        self.assertIsNone(workhours.zone())

    def test_personal_repos(self):
        conf = {"personal_owners": "you, gitlab.com/Team", "personal_dirs": "/srv/mine"}
        self.assertTrue(workhours.is_personal("/srv/mine/app", "", conf))
        self.assertTrue(workhours.is_personal("/elsewhere/x", "git@github.com:you/x.git", conf))
        self.assertTrue(workhours.is_personal("/elsewhere/x", "https://gitlab.com/team/x", conf))
        self.assertFalse(workhours.is_personal("/elsewhere/x", "https://github.com/younger/x", conf))
        self.assertFalse(workhours.is_personal("/srv/mineral/x", "", conf))
        self.assertFalse(workhours.is_personal("/srv/mine/app", "", None))           # off: never
        # personal_dirs empty: the projects folder (helpers.py: ~/Projects)
        self.assertTrue(workhours.is_personal(os.path.expanduser("~/Projects/atlas"), "", {}))


class PageHelpers(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import gi
            gi.require_version("Gtk", "3.0")           # settings.py does this before any page loads
            gi.require_version("Gdk", "3.0")
            from settings_pages import timers as page            # needs GTK, not a display
        except Exception as exc:                                    # noqa: BLE001
            raise unittest.SkipTest(f"settings_pages.timers not importable: {exc}")
        cls.page = page

    def test_work_note(self):
        self.assertIn("Off", self.page.work_note({"enabled": False}))
        on = self.page.work_note({"enabled": True, "label": "Acme", "holidays": "mx",
                                  "timezone": "America/Mexico_City", "conf": "/x/workhours.conf"})
        self.assertIn("\"Acme\" pill", on)
        self.assertIn("Mexico", on)
        self.assertIn("America/Mexico_City", on)
        self.assertIn("no public holidays", self.page.work_note({"enabled": True, "holidays": ""}))

    def test_minutes(self):
        self.assertEqual([self.page.minutes(n) for n in (5, 60, 90, 0)], ["5 min", "1 h", "1 h 30 min", "0 min"])

    def test_chips_keep_an_odd_value(self):
        self.assertEqual(self.page.minute_chips([5, 10], 7), [("5", "5 min"), ("7", "7 min"), ("10", "10 min")])
        self.assertEqual(self.page.minute_chips([0, 5], 5, zero="At the start")[0], ("0", "At the start"))
        self.assertEqual(self.page.clock_chips(["09:00"], "08:15"), [("08:15", "08:15"), ("09:00", "09:00")])

    def test_nth(self):
        self.assertEqual([self.page.nth(n) for n in (1, 2, 3, 4, 11, 12, 13, 21, 22)],
                         ["1st", "2nd", "3rd", "4th", "11th", "12th", "13th", "21st", "22nd"])

    def test_left_text(self):
        self.assertEqual([self.page.left_text(s) for s in (45, 245, 3723, 90000, -5)],
                         ["0:45", "4:05", "1:02:03", "1 d 1 h", "0:00"])

    def test_days_arg(self):
        self.assertEqual(self.page.days_arg(["mon", "fri"], "wed"), "mon,wed,fri")
        self.assertEqual(self.page.days_arg(["mon"], "mon"), "none")

    def test_item_text(self):
        now = dt.datetime(2026, 10, 20, 10, 0).timestamp()
        t = {"kind": "timer", "label": "tea", "name": "timer", "due": now + 300, "repeat": "",
             "then": "then suspending"}
        self.assertEqual(self.page.item_title(t), "tea")
        self.assertEqual(self.page.item_sub(t, now), "timer  ·  rings at 10:05  ·  then suspending")
        a = {"kind": "alarm", "label": "", "name": "alarm", "due": now + 86400, "repeat": "weekdays", "then": ""}
        self.assertEqual(self.page.item_title(a), "Alarm")
        self.assertEqual(self.page.item_sub(a, now), "rings at Wed 10:00  ·  weekdays")

    def test_calendar_sub(self):
        self.assertIn("off", self.page.calendar_sub({"on": False}))
        self.assertIn("not running", self.page.calendar_sub({"on": True, "timer_enabled": "disabled",
                                                              "timer_active": "inactive", "ahead_min": 30}))
        self.assertIn("30 min ahead", self.page.calendar_sub({"on": True, "timer_enabled": "enabled",
                                                              "timer_active": "active", "ahead_min": 30}))


if __name__ == "__main__":
    unittest.main()
