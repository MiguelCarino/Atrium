"""brief.py (the daily brief and the end-of-day journal): its settings, the
activity history's periods and tally, which repo a window title names, when
the morning brief is due, the journal's merge (your notes kept), the time
sheet; Settings > Daily brief & journal's pure helpers.

Hermetic: brief.conf and brief-state.json are helpers.py's scratch
XDG_STATE_HOME, the activity history is a list built here, no git, model,
notification or systemd call is made."""
import datetime as dt
import os
import tempfile
import unittest

import helpers

brief = helpers.import_script("brief.py")

REPOS = sorted(["dotfiles", "Atlas", "TV", "Law", "Pixel-Lab"], key=len, reverse=True)


def row(t, cls, title=""):
    return {"t": t, "class": cls, "title": title}


class Settings(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".conf")
        os.close(fd)
        os.remove(self.path)
        self.addCleanup(lambda: os.path.exists(self.path) and os.remove(self.path))

    def test_defaults_then_set(self):
        self.assertEqual(brief.settings(self.path), brief.DEFAULTS)
        self.assertEqual(brief.set_setting("after", "6:00", self.path), "06:00")
        self.assertEqual(brief.set_setting("sections", "weather, repos", self.path), "repos,weather")
        conf = brief.settings(self.path)
        self.assertEqual((conf["after"], conf["sections"]), ("06:00", "repos,weather"))
        self.assertEqual(brief.sections(conf), ["repos", "weather"])

    def test_bad_values_refused(self):
        for key, value in (("after", "25:00"), ("morning", "noon"), ("sections", "repos,horoscope"),
                           ("titles", "maybe"), ("nope", "x"), ("journal_dir", "")):
            with self.assertRaises(ValueError, msg=key):
                brief.set_setting(key, value, self.path)


class Activity(unittest.TestCase):
    def test_periods_cap_and_gaps(self):
        rows = [row(0, "kitty", "a"), row(100, "", ""), row(200, "firefox", "b"),
                row(200 + brief.MAX_PERIOD_S + 500, "kitty", "c")]
        got = brief.periods(rows, 0, 10 ** 9, now=200 + brief.MAX_PERIOD_S + 600)
        self.assertEqual([(a, b, c) for a, b, c, _t in got],
                         [(0, 100, "kitty"), (200, 200 + brief.MAX_PERIOD_S, "firefox"),
                          (200 + brief.MAX_PERIOD_S + 500, 200 + brief.MAX_PERIOD_S + 600, "kitty")])

    def test_periods_clipped_to_the_range(self):
        got = brief.periods([row(0, "kitty"), row(1000, "")], 400, 600, now=2000)
        self.assertEqual([(a, b) for a, b, _c, _t in got], [(400, 600)])

    def test_clean_title_and_app_name(self):
        self.assertEqual(brief.clean_title("◑ Settings toolbox — COSMIC Terminal"), "Settings toolbox — COSMIC Terminal")
        self.assertEqual(brief.app_name("org.mozilla.firefox"), "firefox")
        self.assertEqual(brief.app_name("kitty"), "kitty")

    def test_project_of(self):
        self.assertEqual(brief.project_of("you@box:~/Projects/dotfiles — COSMIC Terminal", REPOS), "dotfiles")
        self.assertEqual(brief.project_of("viewer.js - Atlas - VSCodium", REPOS), "Atlas")
        self.assertEqual(brief.project_of("~/Projects/TV/index.html - Zed", REPOS), "TV")
        self.assertIsNone(brief.project_of("Law school rankings - Mozilla Firefox", REPOS))   # short: a path only
        self.assertIsNone(brief.project_of("Atlases of the world - Wikipedia", REPOS))
        self.assertIsNone(brief.project_of("", REPOS))

    def test_tally_groups_by_project_then_app(self):
        spans = [(0, 600, "code", "a.py - Atlas - VSCodium"), (600, 900, "kitty", "~/Projects/Atlas"),
                 (900, 1200, "org.mozilla.firefox", "News"), (1200, 1300, "private", "")]
        t = brief.tally(spans, REPOS)
        self.assertEqual(t["projects"], [("Atlas", 900), ("firefox", 300), ("private", 100)])
        self.assertEqual(t["total"], 1300)
        self.assertEqual(t["end"], ("firefox", "News"))         # the last one that is not private
        self.assertNotIn("private", [app for app, _t, _s in t["titles"]])

    def test_last_active_day(self):
        today = dt.date(2026, 10, 21)
        two_back, _ = brief.day_bounds(today - dt.timedelta(days=2))
        rows = [row(two_back + 3600, "kitty"), row(two_back + 7200, "")]
        self.assertEqual(brief.last_active_day(rows, today), today - dt.timedelta(days=2))
        self.assertIsNone(brief.last_active_day([], today))
        self.assertEqual(brief.day_word(today - dt.timedelta(days=1), today), "yesterday")


class Due(unittest.TestCase):
    CONF = dict(brief.DEFAULTS)

    def at(self, hm):
        return dt.datetime(2026, 10, 21, *map(int, hm.split(":")))

    def test_unlock_mode(self):
        c = self.CONF
        self.assertFalse(brief.due(c, self.at("04:30"), False, None, 99)[0])          # before "after"
        self.assertTrue(brief.due(c, self.at("07:00"), False, None, 99999)[0])        # back after being away
        self.assertTrue(brief.due(c, self.at("07:00"), True, None, 60)[0])            # a fresh login
        self.assertFalse(brief.due(c, self.at("07:00"), True, None, 99999)[0])        # the timer, mid-session
        self.assertFalse(brief.due(c, self.at("07:00"), False, "2026-10-21", 60)[0])  # once a day

    def test_time_mode(self):
        c = dict(self.CONF, morning="time", at="08:30")
        self.assertFalse(brief.due(c, self.at("08:00"), True, None, 60)[0])
        self.assertTrue(brief.due(c, self.at("08:31"), True, None, 99999)[0])
        self.assertTrue(brief.due(c, self.at("08:31"), True, "2026-10-20", None)[0])


class Journal(unittest.TestCase):
    def facts(self, **kw):
        t = brief.tally([(0, 3600, "kitty", "~/Projects/dotfiles"), (3600, 4500, "private", "")], REPOS)
        base = {"day": dt.date(2026, 10, 21), "tally": t, "commits": {"dotfiles": [("10:00", "abc1234", "Fix x")]},
                "loose": [], "titles": False, "activity_off": False}
        return {**base, **kw}

    def test_merge_keeps_notes(self):
        day = dt.date(2026, 10, 21)
        first = brief.merge_entry("", brief.entry_block(self.facts(), "First.", "plain"), day)
        self.assertIn("## Notes", first)
        edited = first.replace("## Notes\n", "## Notes\nmy own words\n")
        second = brief.merge_entry(edited, brief.entry_block(self.facts(), "Second.", "plain"), day)
        self.assertIn("my own words", second)
        self.assertIn("Second.", second)
        self.assertNotIn("First.", second)
        self.assertEqual(second.count(brief.START), 1)

    def test_entry_lists_projects_and_commits_not_titles(self):
        block = brief.entry_block(self.facts(), "S.", "plain")
        self.assertIn("| dotfiles | 1 h 00 min |", block)
        self.assertIn("- 10:00 `abc1234` Fix x", block)
        self.assertNotIn("~/Projects/dotfiles", block)            # titles off
        on = brief.entry_block(self.facts(titles=True), "S.", "plain")
        self.assertIn("~/Projects/dotfiles", on)

    def test_activity_off_said(self):
        self.assertIn("activity history is off", brief.entry_block(self.facts(tally=None, activity_off=True), "S.", "p"))

    def test_timesheet_rows(self):
        rows = brief.timesheet_rows(self.facts())
        self.assertEqual(rows, [("2026-10-21", "dotfiles", 1.0)])          # private left out
        self.assertEqual(brief.quarter_hours(20 * 60), 0.25)
        self.assertIn("2026-10-21,dotfiles,1.00,", brief.timesheet_csv(self.facts()))

    def test_plain_summary(self):
        text = brief.plain_summary(self.facts())
        self.assertIn("dotfiles (1 h 00 min)", text)
        self.assertIn("1 commit in dotfiles.", text)
        self.assertIn("Nothing was logged", brief.plain_summary(self.facts(tally=None, commits={})))

    def test_model_notes_never_titles_unless_on(self):
        self.assertNotIn("~/Projects/dotfiles", brief.notes_for_model(self.facts()))
        self.assertIn("Commits in dotfiles: Fix x", brief.notes_for_model(self.facts()))


class Brief(unittest.TestCase):
    def test_short_body_escapes_and_counts(self):
        body = brief.short_body([{"id": "repos", "title": "Repos", "lines": ["a <b>", "c"]}])
        self.assertEqual(body, "<b>Repos</b>: a &lt;b&gt; (+1)")
        self.assertIn("Nothing to report", brief.short_body([]))

    def test_a_failing_section_says_so(self):
        old = brief.GATHER["weather"]
        brief.GATHER["weather"] = lambda _today: 1 / 0
        try:
            got = brief.gather(dict(brief.DEFAULTS, sections="weather"))
        finally:
            brief.GATHER["weather"] = old
        self.assertEqual(got[0]["id"], "weather")
        self.assertIn("could not be read", got[0]["lines"][0])


class Auto(unittest.TestCase):
    """auto(): once a day, one check at a time; a hand-made brief does not
    use up the morning's."""

    def stub(self, **values):
        for key, value in values.items():
            old = getattr(brief, key)
            self.addCleanup(setattr, brief, key, old)
            setattr(brief, key, value)

    def setUp(self):
        for path in (brief.STATE, brief.AUTO_LOCK):
            if os.path.exists(path):
                os.remove(path)
        self.shown = []
        self.stub(rule_on=lambda rid: True, session_age=lambda: 60, locked=lambda: False,
                  detach=lambda argv: self.shown.append(argv))

    def test_once_then_shown_today(self):
        now = dt.datetime.now().replace(hour=9, minute=0)
        self.assertTrue(brief.auto(tick=True, now=now).startswith("shown"))
        self.assertEqual(brief.auto(tick=True, now=now), "shown today already")
        self.assertEqual(len(self.shown), 1)

    def test_one_check_at_a_time(self):
        import fcntl
        now = dt.datetime.now().replace(hour=9, minute=0)
        os.makedirs(brief.STATE_DIR, exist_ok=True)
        with open(brief.AUTO_LOCK, "w") as held:
            fcntl.flock(held, fcntl.LOCK_EX)
            self.assertEqual(brief.auto(from_rule=True, now=now), "another check is running")
        self.assertEqual(self.shown, [])

    def test_show_by_hand_leaves_the_morning(self):
        self.stub(gather=lambda: [], write_cache=lambda b: None)
        old = brief.subprocess.run
        brief.subprocess.run = lambda *a, **k: type("R", (), {"stdout": ""})()
        try:
            brief.show()
        finally:
            brief.subprocess.run = old
        self.assertNotIn("shown", brief.load_state())

    def test_no_email_no_commits(self):
        self.stub(run=lambda *a, **k: "")          # no user.email anywhere; git log never asked
        self.assertEqual(brief.commits_in("/nowhere", 0, 1, ""), [])


class PageHelpers(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from settings_pages import brief as page            # needs GTK, not a display
        except Exception as exc:                                 # noqa: BLE001
            raise unittest.SkipTest(f"settings_pages.brief not importable: {exc}")
        cls.page = page

    def test_toggled_keeps_order(self):
        order = list(brief.SECTIONS)
        self.assertEqual(self.page.toggled("weather,repos", "yesterday", True, order), "yesterday,repos,weather")
        self.assertEqual(self.page.toggled("repos,weather", "repos", False, order), "weather")

    def test_workhours_text(self):
        self.assertIn("18:00, weekdays", self.page.workhours_text({"end": "18:00", "days": [0, 1, 2, 3, 4]}))
        self.assertIn("never comes", self.page.workhours_text({"end": "18:00", "days": []}))
        self.assertIn("Mon, Sat", self.page.workhours_text({"end": "17:00", "days": [0, 5]}))

    def test_clock_chips(self):
        self.assertEqual(self.page.clock_chips(["05:00", "06:00"], "05:30"),
                         [("05:00", "05:00"), ("05:30", "05:30"), ("06:00", "06:00")])


if __name__ == "__main__":
    unittest.main()
