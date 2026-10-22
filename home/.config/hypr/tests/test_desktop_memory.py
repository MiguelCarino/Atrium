"""desktop-memory.py (Desktop memory): the time words in English and Spanish,
what is never kept, each source's taking-in (activity stretches, copies,
notifications, captions, screenshots' planning), the time-filtered search,
forgetting / wiping / retention, and recall's answer without a model; plus
voice.py's caption hook and the privacy switches it all follows.

Scratch stores only: privacy.conf is never read (privacy_settings.load is
stubbed), LM Studio is never asked (use_model=False, the worker is a stub),
and cliphist / makoctl / grim / hyprctl are never run (their results are
handed in or stubbed)."""
import datetime
import json
import os
import shutil
import tempfile
import time
import unittest
from unittest import mock

from helpers import SCRATCH, import_script

dm = import_script("desktop-memory.py")
voice = import_script("voice.py")
ps = dm.privacy_settings

NOW = datetime.datetime(2026, 10, 21, 16, 30)      # a Wednesday


def conf(**changes):
    c = dict(ps.DEFAULTS)
    c.update(changes)
    return c


def span(text, now=NOW):
    got = dm.time_words(text, now)
    return None if got is None else (got[0].strftime("%Y-%m-%d %H:%M"), got[1].strftime("%Y-%m-%d %H:%M"))


class TimeWords(unittest.TestCase):
    def test_days_in_english_and_spanish(self):
        self.assertEqual(span("what was that error yesterday"), ("2026-10-20 00:00", "2026-10-21 00:00"))
        self.assertEqual(span("lo que vi ayer"), ("2026-10-20 00:00", "2026-10-21 00:00"))
        self.assertEqual(span("today"), ("2026-10-21 00:00", "2026-10-21 16:30"))
        self.assertEqual(span("anteayer"), ("2026-10-19 00:00", "2026-10-20 00:00"))
        self.assertEqual(span("anoche"), ("2026-10-20 18:00", "2026-10-21 04:00"))

    def test_weekdays_are_the_last_one_before_today(self):
        self.assertEqual(span("what link did someone send on Tuesday"), ("2026-10-20 00:00", "2026-10-21 00:00"))
        self.assertEqual(span("¿qué enlace me mandaron el martes?"), ("2026-10-20 00:00", "2026-10-21 00:00"))
        self.assertEqual(span("el lunes pasado"), ("2026-10-19 00:00", "2026-10-20 00:00"))
        # today's own weekday: a week ago, unless "this"
        self.assertEqual(span("el miércoles"), ("2026-10-14 00:00", "2026-10-15 00:00"))
        self.assertEqual(span("this wednesday"), ("2026-10-21 00:00", "2026-10-21 16:30"))

    def test_weeks_months_and_ago(self):
        self.assertEqual(span("last week"), ("2026-10-12 00:00", "2026-10-19 00:00"))
        self.assertEqual(span("la semana pasada"), ("2026-10-12 00:00", "2026-10-19 00:00"))
        self.assertEqual(span("el mes pasado"), ("2026-09-01 00:00", "2026-10-01 00:00"))
        self.assertEqual(span("this month"), ("2026-10-01 00:00", "2026-10-21 16:30"))
        self.assertEqual(span("hace 3 días"), ("2026-10-18 00:00", "2026-10-19 00:00"))
        self.assertEqual(span("3 days ago"), ("2026-10-18 00:00", "2026-10-19 00:00"))
        self.assertEqual(span("en las últimas 2 horas"), ("2026-10-21 14:30", "2026-10-21 16:30"))
        self.assertEqual(span("the past 2 days"), ("2026-10-19 16:30", "2026-10-21 16:30"))

    def test_dates(self):
        self.assertEqual(span("20 de octubre"), ("2026-10-20 00:00", "2026-10-21 00:00"))
        self.assertEqual(span("on Oct 15"), ("2026-10-15 00:00", "2026-10-16 00:00"))
        self.assertEqual(span("2026-10-01"), ("2026-10-01 00:00", "2026-10-02 00:00"))
        self.assertEqual(span("el 15/10"), ("2026-10-15 00:00", "2026-10-16 00:00"))
        self.assertEqual(span("Dec 25"), ("2025-12-25 00:00", "2025-12-26 00:00"))   # not yet: last year's

    def test_time_of_day(self):
        self.assertEqual(span("yesterday at 3pm"), ("2026-10-20 14:15", "2026-10-20 15:45"))
        self.assertEqual(span("ayer a las 3"), ("2026-10-20 14:15", "2026-10-20 15:45"))
        self.assertEqual(span("a las 3 de la mañana"), ("2026-10-21 02:15", "2026-10-21 03:45"))
        self.assertEqual(span("ayer en la tarde"), ("2026-10-20 12:00", "2026-10-20 19:00"))
        self.assertEqual(span("at 9 in the morning"), ("2026-10-21 08:15", "2026-10-21 09:45"))
        # an hour still to come today: yesterday's
        self.assertEqual(span("at 5:30pm"), ("2026-10-20 16:45", "2026-10-20 18:15"))

    def test_no_time_words(self):
        self.assertIsNone(dm.time_words("when did I last look at that dcmjs bug", NOW))
        self.assertIsNone(dm.time_words("look at 5 tabs", NOW))
        self.assertIsNone(dm.time_words("may I see it", NOW))

    def test_rest_is_what_to_search_for(self):
        self.assertEqual(dm.time_words("the error in the terminal yesterday", NOW)[2], "the error in the terminal")
        self.assertEqual(dm.time_words("ayer a las 10 en firefox", NOW)[2], "en firefox")


class Secrets(unittest.TestCase):
    def test_secret_things_are_never_kept(self):
        for text in ("Your verification code is 482913", "482913 is your Instagram code",
                     "Tu código de acceso: 5521", "password: hunter2", "4111 1111 1111 1111",
                     "ghp_abcdefghijklmnopqrstuvwxyz0123456789"):
            self.assertTrue(dm.looks_secret(text), text)
        for text in ("Build finished in 42 s", "https://example.com/a/b", "Meeting at 15:30 tomorrow"):
            self.assertFalse(dm.looks_secret(text), text)

    def test_scrub_drops_lines_or_everything(self):
        self.assertEqual(dm.scrub("TypeError: x is undefined\npassword: hunter2\nat line 4"),
                         "TypeError: x is undefined\nat line 4")
        self.assertIsNone(dm.scrub("hello\n-----BEGIN OPENSSH PRIVATE KEY-----\nabc"))


class Store(unittest.TestCase):
    """A scratch store, activity log and captions log for each test; the
    privacy switches are a dict the test sets."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(dir=SCRATCH)
        self.conf = conf()
        for name, value in (("DB", os.path.join(self.dir, "m.sqlite3")), ("THUMBS", os.path.join(self.dir, "thumbs")),
                            ("CAPTIONS", os.path.join(self.dir, "captions.jsonl")),
                            ("ACTIVITY", os.path.join(self.dir, "activity.jsonl"))):
            patcher = mock.patch.object(dm, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = mock.patch.object(ps, "load", side_effect=lambda *a: dict(self.conf))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.con = dm.connect()
        self.addCleanup(self.con.close)
        self.addCleanup(shutil.rmtree, self.dir, True)

    def write_jsonl(self, path, rows):
        with open(path, "w") as handle:
            handle.writelines(json.dumps(r) + "\n" for r in rows)

    def count(self, source=None):
        if source:
            return self.con.execute("select count(*) from entries where source=?", (source,)).fetchone()[0]
        return self.con.execute("select count(*) from entries").fetchone()[0]

    def search(self, query, start=None, end=None, **kw):
        return dm.search(query, start, end, con=self.con, use_model=False, conf=self.conf, **kw)


class Activity(Store):
    def test_stretches_merge_spinners_and_drop_short_and_private(self):
        rows = [{"t": 0, "class": "term", "title": "◑ build — Terminal"},
                {"t": 1, "class": "term", "title": "◐ build — Terminal"},
                {"t": 40, "class": "private", "title": ""},
                {"t": 100, "class": "firefox", "title": "News"},
                {"t": 105, "class": "term", "title": "◑ build — Terminal"},     # 5 s: too short
                {"t": 110, "class": "", "title": ""}]
        # the spinner frames are one stretch; private is skipped; News and the
        # short return to the terminal last 5 s; the last row is still open
        self.assertEqual(dm.activity_stretches(rows), [(0, 40, "term", "build — Terminal")])

    def test_ingest_once_skips_excluded_and_merges_across_runs(self):
        base = time.time() - 3600
        self.write_jsonl(dm.ACTIVITY, [{"t": base, "class": "code", "title": "dcmjs bug — VS Code"},
                                       {"t": base + 300, "class": "telegram", "title": "Chat"},
                                       {"t": base + 600, "class": "code", "title": "dcmjs bug — VS Code"},
                                       {"t": base + 900, "class": "", "title": ""}])
        self.conf["memory_exclude"] = "telegram"
        self.assertEqual(dm.ingest_activity(self.con, self.conf), 2)
        self.assertEqual(dm.ingest_activity(self.con, self.conf), 0)          # nothing twice
        self.assertEqual(self.con.execute("select count(*) from entries where app='telegram'").fetchone()[0], 0)
        # the open stretch goes on in a later run: the same memory grows
        with open(dm.ACTIVITY, "a") as handle:
            handle.write(json.dumps({"t": base + 950, "class": "code", "title": "dcmjs bug — VS Code"}) + "\n")
            handle.write(json.dumps({"t": base + 1500, "class": "", "title": ""}) + "\n")
        dm.ingest_activity(self.con, self.conf)
        self.assertEqual(self.count("activity"), 2)
        self.assertEqual(self.con.execute("select max(t_end) from entries").fetchone()[0], base + 1500)


class Clipboard(Store):
    def lines(self, *items):
        return [(cid, f"{cid}\t{text}", text) for cid, text in items]

    def test_no_backlog_then_new_text_copies(self):
        self.assertEqual(dm.ingest_clipboard(self.con, self.conf, 1000.0, self.lines((5, "old copy"))), 0)
        texts = {6: "https://example.com/report", 7: "password: hunter2", 8: "a note to self"}
        with mock.patch.object(dm, "cliphist_text", side_effect=lambda line: texts[int(line.split("\t")[0])]):
            n = dm.ingest_clipboard(self.con, self.conf, 1400.0,
                                    self.lines((5, "old copy"), (6, "https://example.com/report"),
                                               (7, "password: hunter2"), (8, "a note to self"),
                                               (9, "[[ binary data 2 KiB png 10x10 ]]")))
        self.assertEqual(n, 2)
        row = self.con.execute("select url, approx from entries where text like 'https%'").fetchone()
        self.assertEqual(row[0], "https://example.com/report")
        self.assertIn("copied between", row[1])
        self.assertFalse(self.con.execute("select 1 from entries where text like '%hunter2%'").fetchone())


class Notifications(Store):
    def note(self, i, summary, body="", app="Slack", urgency="normal"):
        return {"id": i, "app_name": app, "summary": summary, "body": body, "urgency": urgency}

    def test_first_run_marks_then_new_ones_without_noise_or_codes(self):
        self.assertEqual(dm.ingest_notifications(self.con, self.conf, 1000.0, [self.note(1, "old")]), 0)
        notes = [self.note(1, "old"), self.note(2, "Ana", "mira https://example.org/x"),
                 self.note(3, "Volume 40%", app="OSD", urgency="low"),
                 self.note(4, "Your code", "482913 is your login code"),
                 self.note(5, "Remembering…", app="Desktop memory")]
        self.assertEqual(dm.ingest_notifications(self.con, self.conf, 1300.0, notes), 1)
        self.assertEqual(dm.ingest_notifications(self.con, self.conf, 1600.0, notes), 0)
        url, title = self.con.execute("select url, title from entries").fetchone()
        self.assertEqual((url, title), ("https://example.org/x", "Ana"))


class Captions(Store):
    def test_paragraphs_only_once_quiet(self):
        now = time.time()
        self.write_jsonl(dm.CAPTIONS, [{"t": now - 600, "text": "hello there"},
                                       {"t": now - 590, "text": "the build failed"},
                                       {"t": now - 10, "text": "still talking"}])
        self.assertEqual(dm.ingest_captions(self.con, self.conf, now), 1)
        self.assertEqual(self.con.execute("select text from entries").fetchone()[0], "hello there the build failed")
        self.assertEqual(dm.ingest_captions(self.con, self.conf, now + 200), 1)
        self.assertEqual(self.count("captions"), 2)

    def test_voice_writes_only_when_the_switch_is_on(self):
        path = os.path.join(self.dir, "cap.jsonl")
        self.assertFalse(voice.remember_caption("secret meeting", path))            # off as shipped
        self.assertFalse(os.path.exists(path))
        self.conf["memory_captions"] = "on"
        self.assertTrue(voice.remember_caption("hello", path))
        self.conf["memory"] = "off"
        self.assertFalse(voice.remember_caption("again", path))
        with open(path) as handle:
            self.assertEqual([json.loads(line)["text"] for line in handle], ["hello"])


class Screen(Store):
    MON = {"name": "DP-1", "activeWorkspace": {"id": 1}, "specialWorkspace": {"id": 0}, "dpmsStatus": True}

    def test_plan_skips_private_empty_and_off_screens(self):
        mons = [dict(self.MON), dict(self.MON, name="DP-2", activeWorkspace={"id": 2}),
                dict(self.MON, name="HDMI-A-1", activeWorkspace={"id": 3}), dict(self.MON, name="DP-3", dpmsStatus=False)]
        clients = [{"class": "code", "title": "x", "workspace": {"id": 1}, "focusHistoryID": 0},
                   {"class": "org.keepassxc.KeePassXC", "title": "db", "workspace": {"id": 2}}]
        take, why = dm.screen_plan(mons, clients, self.conf)
        self.assertEqual([m["name"] for m, _ in take], ["DP-1"])
        self.assertEqual(sorted(w.split(":")[0] for w in why), ["DP-2", "DP-3", "HDMI-A-1"])

    def test_off_locked_or_busy_takes_nothing(self):
        with mock.patch.object(dm.subprocess, "run", side_effect=AssertionError("grim ran")):
            self.assertEqual(dm.snap(self.con, self.conf, 1000.0, force=True), "screen source off")
        self.conf["memory_screen"] = "on"
        with mock.patch.object(dm, "locked", return_value=True):
            self.assertEqual(dm.snap(self.con, self.conf, 1000.0, force=True), "screen locked")
        with mock.patch.object(dm, "locked", return_value=False), \
                mock.patch.object(dm.index(), "busy", return_value="game mode is on"):
            self.assertEqual(dm.snap(self.con, self.conf, 1000.0, force=True), "game mode is on")

    def test_a_snap_keeps_text_and_thumbnail_not_the_screenshot(self):
        self.conf["memory_screen"] = "on"
        made = []

        def fake_run(argv, **kw):
            made.append(argv[-1])
            open(argv[-1], "wb").close()
            return mock.Mock(returncode=0)

        def fake_thumb(png, out):
            os.makedirs(os.path.dirname(out), exist_ok=True)
            open(out, "wb").close()
        with mock.patch.object(dm, "locked", return_value=False), \
                mock.patch.object(dm.index(), "busy", return_value=None), \
                mock.patch.object(dm, "hyprctl_json", side_effect=lambda what: [self.MON] if what == "monitors" else
                                  [{"class": "kitty", "title": "make", "workspace": {"id": 1}}]), \
                mock.patch.object(dm.subprocess, "run", side_effect=fake_run), \
                mock.patch.object(dm, "RUNTIME", self.dir), \
                mock.patch.object(dm, "ocr", return_value="error: undefined reference to main\nld returned 1"), \
                mock.patch.object(dm, "make_thumb", side_effect=fake_thumb):
            self.assertIn("1 screenshot", dm.snap(self.con, self.conf, 1000.0))
            self.assertIn("not due", dm.snap(self.con, self.conf, 1060.0))
            self.assertIn("unchanged", dm.snap(self.con, self.conf, 5000.0))
        self.assertFalse(any(os.path.exists(p) for p in made))           # the PNG is gone
        thumb, app = self.con.execute("select thumb, app from entries").fetchone()
        self.assertTrue(os.path.exists(thumb))
        self.assertEqual(app, "kitty")


class Search(Store):
    def fill(self):
        day = datetime.datetime(2026, 10, 20, 15, 0).timestamp()
        dm.add(self.con, "notifications", day, "mira https://dcmjs.org/issue/42", app="Slack", title="Ana", key="n1")
        dm.add(self.con, "activity", day - 3600, "dcmjs bug — VS Code", app="code", title="dcmjs bug — VS Code",
               key="a1", t_end=day - 3000)
        dm.add(self.con, "activity", day - 86400, "dcmjs bug — VS Code", app="code", title="dcmjs bug — VS Code",
               key="a2", t_end=day - 86000)
        dm.add(self.con, "clipboard", day + 600, "TypeError: cannot read property of undefined", key="c1")
        self.con.commit()
        return day

    def test_time_range_and_keywords(self):
        day = self.fill()
        res = self.search("dcmjs", day - 7200, day + 3600)
        self.assertEqual({r["source"] for r in res["results"]}, {"notifications", "activity"})
        everything = self.search("dcmjs")
        windows = [r for r in everything["results"] if r["source"] == "activity"]
        self.assertEqual(len(windows), 1)                            # folded into one ...
        self.assertEqual(windows[0]["times"], 2)                     # ... seen twice

    def test_link_words_want_a_link(self):
        day = self.fill()
        res = self.search("what link did someone send", day - 86400 * 2, day + 86400)
        self.assertEqual([r["source"] for r in res["results"]], ["notifications"])
        self.assertEqual(res["results"][0]["url"], "https://dcmjs.org/issue/42")

    def test_only_time_words_is_a_timeline(self):
        day = self.fill()
        res = self.search("", day - 7200, day + 3600)
        self.assertEqual(res["mode"], "timeline")
        self.assertEqual(len(res["results"]), 3)

    def test_switches(self):
        self.fill()
        self.conf["memory_notifications"] = "off"
        self.assertNotIn("notifications", {r["source"] for r in self.search("dcmjs")["results"]})
        self.conf["memory"] = "off"
        self.assertTrue(self.search("dcmjs").get("off"))


class Forget(Store):
    def test_forget_day_blocks_taking_it_in_again(self):
        t = datetime.datetime(2026, 10, 20, 12, 0).timestamp()
        self.write_jsonl(dm.ACTIVITY, [{"t": t, "class": "code", "title": "secret project"},
                                       {"t": t + 600, "class": "", "title": ""}])
        dm.ingest_activity(self.con, self.conf)
        self.assertEqual(dm.forget_day(self.con, datetime.date(2026, 10, 20)), 1)
        dm.meta(self.con, "activity_upto", 0)                          # even read from the start again
        dm.ingest_activity(self.con, self.conf)
        self.assertEqual(self.count(), 0)

    def test_forget_app_deletes_and_excludes(self):
        dm.add(self.con, "activity", time.time(), "x", app="Telegram", title="x", key="k")
        with mock.patch.object(ps, "set_key") as set_key:
            self.assertEqual(dm.forget_app(self.con, "telegram"), 1)
        set_key.assert_called_once_with("memory_exclude", "telegram")

    def test_prune_and_screenshot_retention(self):
        now = time.time()
        thumb = os.path.join(dm.THUMBS, "2026-10-01", "x.jpg")
        os.makedirs(os.path.dirname(thumb))
        open(thumb, "wb").close()
        dm.add(self.con, "screen", now - 10 * 86400, "old screen", key="s", thumb=thumb)
        dm.add(self.con, "clipboard", now - 10 * 86400, "kept copy", key="c")
        dm.add(self.con, "clipboard", now - 40 * 86400, "old copy", key="o")
        self.assertEqual(dm.prune(self.con, self.conf, now), 2)
        self.assertFalse(os.path.exists(thumb))
        self.assertFalse(os.path.exists(os.path.dirname(thumb)))
        self.assertEqual(self.count(), 1)

    def test_wipe_starts_after_now(self):
        self.write_jsonl(dm.ACTIVITY, [{"t": time.time() - 900, "class": "code", "title": "a"},
                                       {"t": time.time() - 100, "class": "", "title": ""}])
        self.con.close()
        with mock.patch.object(dm, "cliphist_lines", return_value=[]), mock.patch.object(dm, "mako", return_value=[]):
            dm.wipe()
        self.con = dm.connect()
        self.assertEqual(dm.ingest_activity(self.con, self.conf), 0)


class Recall(Store):
    def setUp(self):
        super().setUp()
        dm.add(self.con, "notifications", time.time() - 60, "mira https://example.org/a", app="Slack", title="Ana",
               key="n")
        self.con.commit()
        self.con.close()
        self.con = dm.connect()

    def test_no_model_lists_what_was_found_with_links(self):
        worker = mock.Mock(ready=mock.Mock(return_value=(None, "gamemode is on")))
        with mock.patch.object(dm.index(), "embedding_model", return_value=None):
            answer, results, links = dm.recall("the link Ana sent", worker=worker)
        self.assertIn("gamemode is on", answer)
        self.assertIn("https://example.org/a", answer)
        self.assertEqual(links[0][1], "https://example.org/a")
        worker.ask.assert_not_called()

    def test_the_model_answer_and_its_citations(self):
        worker = mock.Mock(ready=mock.Mock(return_value=(mock.Mock(), None)),
                           ask=mock.Mock(return_value="Ana sent https://example.org/a [1]"))
        with mock.patch.object(dm.index(), "embedding_model", return_value=None):
            answer, results, links = dm.recall("the link Ana sent", worker=worker)
        self.assertEqual(answer, "Ana sent https://example.org/a [1]")
        self.assertIn("[1]", worker.ask.call_args[0][1])
        self.assertEqual(links, [("Open example.org", "https://example.org/a")])

    def test_off(self):
        self.conf["memory"] = "off"
        self.assertEqual(dm.recall("anything")[0], dm.OFF_TEXT)


class Hardening(Store):
    """The review's fixes: a source's time off stays out, forgetting today
    does not block the rest of it, the captions log empties, pinned private
    windows, stray thumbnails."""

    def test_activity_while_off_is_not_taken_in_when_turned_on(self):
        base = time.time() - 7200
        self.write_jsonl(dm.ACTIVITY, [{"t": base, "class": "code", "title": "before"},
                                       {"t": base + 600, "class": "", "title": ""}])
        self.assertEqual(dm.ingest_activity(self.con, self.conf), 1)
        dm.hold(self.con, ["activity"], base + 700)                     # a collect while it is off
        with open(dm.ACTIVITY, "a") as handle:
            for t, cls, title in ((base + 1000, "firefox", "private matter"), (base + 1600, "", ""),
                                  (base + 4000, "code", "after"), (base + 4600, "", "")):
                handle.write(json.dumps({"t": t, "class": cls, "title": title}) + "\n")
        conf_file = os.path.join(self.dir, "privacy.conf")
        open(conf_file, "w").close()
        os.utime(conf_file, (base + 3000, base + 3000))                 # turned on again then
        with mock.patch.object(ps, "CONF", conf_file):
            self.assertEqual(dm.ingest_activity(self.con, self.conf), 1)
        titles = [r[0] for r in self.con.execute("select title from entries order by t")]
        self.assertEqual(titles, ["before", "after"])

    def test_copies_and_notifications_while_off_are_not_taken_in(self):
        lines = [(1, "1\tfirst", "first")]
        dm.ingest_clipboard(self.con, self.conf, 1000.0, lines)
        dm.ingest_notifications(self.con, self.conf, 1000.0, [{"id": 1, "summary": "a"}])
        dm.hold(self.con, ["clipboard", "notifications"], 1300.0)
        lines += [(2, "2\tcopied while off", "copied while off")]
        with mock.patch.object(dm, "cliphist_text", side_effect=AssertionError("decoded")):
            self.assertEqual(dm.ingest_clipboard(self.con, self.conf, 1600.0, lines), 0)
        self.assertEqual(dm.ingest_notifications(self.con, self.conf, 1600.0,
                                                 [{"id": 1, "summary": "a"}, {"id": 2, "summary": "while off"}]), 0)
        with mock.patch.object(dm, "cliphist_text", return_value="new copy"):
            self.assertEqual(dm.ingest_clipboard(self.con, self.conf, 1900.0,
                                                 lines + [(3, "3\tnew copy", "new copy")]), 1)
        self.assertEqual(self.count(), 1)

    def test_captions_log_keeps_only_what_is_still_to_come(self):
        now = time.time()
        self.write_jsonl(dm.CAPTIONS, [{"t": now - 600, "text": "said earlier"}, {"t": now - 10, "text": "talking"}])
        self.assertEqual(dm.ingest_captions(self.con, self.conf, now), 1)
        self.assertEqual([r["text"] for r in dm.read_jsonl(dm.CAPTIONS)], ["talking"])
        self.assertEqual(oct(os.stat(dm.CAPTIONS).st_mode & 0o777), "0o600")
        dm.hold(self.con, ["captions"], now)                            # turned off: the rest goes
        self.assertFalse(os.path.exists(dm.CAPTIONS))

    def test_forgetting_today_does_not_block_the_rest_of_it(self):
        today = datetime.date.today()
        dm.forget_day(self.con, today)
        self.assertTrue(dm.blocked(self.con, time.time() - 5))
        self.assertTrue(dm.add(self.con, "clipboard", time.time() + 5, "later today", key="later"))

    def test_a_pinned_private_window_skips_its_screen(self):
        mon = {"id": 0, "name": "DP-1", "activeWorkspace": {"id": 1}, "specialWorkspace": {"id": 0}}
        clients = [{"class": "code", "title": "x", "workspace": {"id": 1}, "monitor": 0},
                   {"class": "org.keepassxc.KeePassXC", "title": "db", "workspace": {"id": 4}, "monitor": 0,
                    "pinned": True}]
        take, why = dm.screen_plan([mon], clients, self.conf)
        self.assertEqual(take, [])
        self.assertIn("private", why[0])

    def test_prune_drops_thumbnails_no_memory_points_at(self):
        stray = os.path.join(dm.THUMBS, "2026-10-21", "stray.jpg")
        kept = os.path.join(dm.THUMBS, "2026-10-21", "kept.jpg")
        os.makedirs(os.path.dirname(stray))
        for path in (stray, kept):
            open(path, "wb").close()
            os.utime(path, (time.time() - 7200, time.time() - 7200))
        dm.add(self.con, "screen", time.time(), "some text here", key="s", thumb=kept)
        dm.prune(self.con, self.conf)
        self.assertFalse(os.path.exists(stray))
        self.assertTrue(os.path.exists(kept))

    def test_notify_send_takes_a_dash_question_as_text(self):
        calls = []
        with mock.patch.object(dm.subprocess, "run", side_effect=lambda argv, **kw: calls.append(argv)
                               or mock.Mock(stdout="")), \
                mock.patch.object(dm, "recall", return_value=("answer", [], [])):
            dm.notify_recall("-u critical")
        for argv in calls:
            self.assertLess(argv.index("--"), argv.index("-u critical"))


class Switches(unittest.TestCase):
    def test_invasive_sources_ship_off(self):
        self.assertEqual(ps.memory_sources(dict(ps.DEFAULTS)), {"activity", "clipboard", "notifications"})
        self.assertEqual(ps.memory_sources(dict(ps.DEFAULTS, memory="off")), set())
        self.assertEqual(ps.memory_screen_minutes(dict(ps.DEFAULTS, memory_screen_minutes="1")), 5)
        self.assertEqual(ps.memory_excluded(dict(ps.DEFAULTS, memory_exclude="A, b", activity_exclude="c")),
                         ["a", "b", "c"])


if __name__ == "__main__":
    unittest.main()
