"""Settings > Privacy: privacy_settings.py (privacy.conf, cliphist's config,
the recently-used list), activity-log.py's forget / hide / private rules and
ask-desktop.py's per-source permissions.

Every path is pointed at a scratch folder and every systemctl / gsettings /
cliphist call is stubbed: nothing here touches the real histories."""
import datetime
import json
import os
import tempfile
import time
import unittest
from unittest import mock

import helpers

import privacy_settings as ps  # noqa: E402  (helpers put scripts/ on the path)

al = helpers.import_script("activity-log.py")
ask = helpers.import_script("ask-desktop.py")


class Scratch(unittest.TestCase):
    """Each test gets its own privacy.conf, cliphist config, recently-used
    list and activity log."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(dir=helpers.SCRATCH)
        paths = {"CONF": os.path.join(self.dir, "hypr", "privacy.conf"),
                 "CLIPHIST_CONF": os.path.join(self.dir, "cliphist", "config"),
                 "RECENT": os.path.join(self.dir, "recently-used.xbel")}
        for name, path in paths.items():
            patcher = mock.patch.object(ps, name, path)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.state = os.path.join(self.dir, "activity.jsonl")
        patcher = mock.patch.object(al, "STATE", self.state)
        patcher.start()
        self.addCleanup(patcher.stop)
        # A stray systemctl / gsettings / cliphist call fails the test.
        for name in ("run", "run_ok"):
            patcher = mock.patch.object(ps, name, side_effect=AssertionError(f"unexpected {name}"))
            patcher.start()
            self.addCleanup(patcher.stop)

    def write_log(self, rows):
        with open(self.state, "w") as handle:
            for row in rows:
                handle.write(json.dumps(row) + "\n")

    def read_log(self):
        with open(self.state) as handle:
            return [json.loads(line) for line in handle]


class Conf(Scratch):
    def test_missing_file_is_the_defaults(self):
        self.assertEqual(ps.load(), ps.DEFAULTS)
        self.assertEqual(ps.ask_sources(ps.load()), set(ps.SOURCES))
        self.assertEqual(ps.keep_days(ps.load()), 30)

    def test_round_trip_keeps_unknown_keys(self):
        ps.save(dict(ps.DEFAULTS, ask_files="off", extra="x"))
        conf = ps.load()
        self.assertEqual(conf["ask_files"], "off")
        self.assertEqual(conf["extra"], "x")
        with open(ps.CONF) as handle:
            self.assertTrue(handle.read().startswith("# Privacy settings"))

    def test_parse_skips_comments_and_junk(self):
        conf = ps.parse_conf("# c\n\nnot a setting\n ask = off \nactivity_keep_days=7\n")
        self.assertEqual(conf["ask"], "off")
        self.assertEqual(conf["activity_keep_days"], "7")

    def test_cache_sees_a_rewrite(self):
        ps.set_key("ask", "off")
        self.assertFalse(ps.ask_on(ps.load()))
        time.sleep(0.01)
        ps.set_key("ask", "on")
        self.assertTrue(ps.ask_on(ps.load()))

    def test_keep_days_is_clamped(self):
        self.assertEqual(ps.keep_days({"activity_keep_days": "0"}), 1)
        self.assertEqual(ps.keep_days({"activity_keep_days": "9999"}), 365)
        self.assertEqual(ps.keep_days({"activity_keep_days": "junk"}), 30)

    def test_excluded_is_lower_case_and_unique(self):
        self.assertEqual(ps.excluded({"activity_exclude": "Foo, bar,,foo"}), ["foo", "bar"])

    def test_ask_off_reads_nothing(self):
        self.assertEqual(ps.ask_sources(dict(ps.DEFAULTS, ask="off")), set())
        self.assertEqual(ps.ask_sources(dict(ps.DEFAULTS, ask_clipboard="off")), {"files", "activity"})

    def test_clean_class(self):
        self.assertEqual(ps.clean_class("  Org.Telegram.Desktop \n"), "org.telegram.desktop")
        self.assertEqual(ps.clean_class("a,b"), "ab")
        self.assertEqual(ps.clean_class("   "), "")


class Commands(Scratch):
    def test_exclude_then_include(self):
        with mock.patch.object(ps, "run") as run:
            ps.cmd_activity(["exclude", "Signal"])
            ps.cmd_activity(["exclude", "foot"])
        self.assertEqual(ps.excluded(ps.load()), ["signal", "foot"])
        run.assert_any_call(ps.sys.executable, ps.ACTIVITY_LOG, "hide", "signal")
        with mock.patch.object(ps, "run"):
            ps.cmd_activity(["include", "SIGNAL"])
        self.assertEqual(ps.excluded(ps.load()), ["foot"])

    def test_keep_saves_and_prunes(self):
        with mock.patch.object(ps, "run") as run:
            ps.cmd_activity(["keep", "7"])
        self.assertEqual(ps.keep_days(ps.load()), 7)
        run.assert_called_once_with(ps.sys.executable, ps.ACTIVITY_LOG, "prune")

    def test_keep_out_of_range_changes_nothing(self):
        with self.assertRaises(SystemExit):
            ps.cmd_activity(["keep", "0"])
        self.assertFalse(os.path.exists(ps.CONF))

    def test_on_off_enable_the_units(self):
        with mock.patch.object(ps, "run_ok", return_value=(True, "")) as run_ok:
            ps.cmd_clipboard(["off"])
            ps.cmd_activity(["on"])
        run_ok.assert_any_call("systemctl", "--user", "disable", "--now", *ps.CLIP_UNITS)
        run_ok.assert_any_call("systemctl", "--user", "enable", "--now", ps.ACTIVITY_UNIT)

    def test_clear_runs_cliphist_wipe(self):
        with mock.patch.object(ps, "run_ok", return_value=(True, "")) as run_ok:
            ps.cmd_clipboard(["clear"])
        run_ok.assert_called_once_with("cliphist", "wipe")

    def test_ask_sources(self):
        ps.cmd_ask(["clipboard", "off"])
        ps.cmd_ask(["off"])
        conf = ps.load()
        self.assertEqual(conf["ask_clipboard"], "off")
        self.assertFalse(ps.ask_on(conf))
        with self.assertRaises(SystemExit):
            ps.cmd_ask(["passwords", "on"])

    def test_recent_age_never(self):
        with mock.patch.object(ps, "run_ok", return_value=(True, "")) as run_ok:
            ps.cmd_recent(["age", "never"])
        run_ok.assert_called_once_with("gsettings", "set", ps.PRIVACY_GSCHEMA, "recent-files-max-age", "-1")


class Cliphist(Scratch):
    TEXT = ("# Keeps the newest 500 copies for SUPER+V.\n"
            "max-items 500\n")

    def test_read(self):
        self.assertEqual(ps.cliphist_max(self.TEXT), 500)
        self.assertIsNone(ps.cliphist_max("# nothing\n"))

    def test_replace_in_place_keeps_the_comment_in_step(self):
        out = ps.set_cliphist_max(self.TEXT, 100)
        self.assertEqual(out, "# Keeps the newest 100 copies for SUPER+V.\nmax-items 100\n")

    def test_added_when_missing(self):
        self.assertEqual(ps.set_cliphist_max("# c\n", 50), "# c\nmax-items 50\n")
        self.assertEqual(ps.set_cliphist_max("", 50), "max-items 50\n")

    def test_cmd_max_writes_the_file(self):
        os.makedirs(os.path.dirname(ps.CLIPHIST_CONF))
        with open(ps.CLIPHIST_CONF, "w") as handle:
            handle.write(self.TEXT)
        ps.cmd_clipboard(["max", "1000"])
        self.assertEqual(ps.cliphist_max(ps.read(ps.CLIPHIST_CONF)), 1000)
        with self.assertRaises(SystemExit):
            ps.cmd_clipboard(["max", "3"])

    def test_version(self):
        self.assertTrue(ps.version_at_least("0.7.0", (0, 6)))
        self.assertFalse(ps.version_at_least("0.5.1", (0, 6)))


class Recent(Scratch):
    XBEL = ('<?xml version="1.0" encoding="UTF-8"?>\n<xbel version="1.0">'
            '<bookmark href="file:///a"/><bookmark href="file:///b"/></xbel>')

    def test_count(self):
        self.assertEqual(ps.xbel_count(self.XBEL), 2)
        self.assertEqual(ps.xbel_count("not xml"), 0)

    def test_clear_leaves_a_valid_empty_list(self):
        with open(ps.RECENT, "w") as handle:
            handle.write(self.XBEL)
        ps.clear_recent()
        self.assertEqual(ps.xbel_count(ps.read(ps.RECENT)), 0)
        self.assertIn("<xbel", ps.read(ps.RECENT))

    def test_clear_without_a_list_creates_none(self):
        ps.clear_recent()
        self.assertFalse(os.path.exists(ps.RECENT))


class Live(unittest.TestCase):
    def node(self, cls, name):
        return {"type": "PipeWire:Interface:Node", "info": {"props": {"media.class": cls, "node.name": name}}}

    def test_screen_share(self):
        self.assertIsNone(ps.screen_shared(None))
        self.assertFalse(ps.screen_shared([self.node("Audio/Sink", "xdph-x"), self.node("Video/Source", "cam")]))
        self.assertTrue(ps.screen_shared([self.node("Video/Source", "xdph-streaming-1")]))

    def test_unit_states_parses_blocks(self):
        out = ("Id=a.service\nActiveState=active\nUnitFileState=enabled\n\n"
               "Id=b.service\nActiveState=inactive\nUnitFileState=disabled\n")
        with mock.patch.object(ps, "run", return_value=out):
            states = ps.unit_states(["a.service", "b.service", "c.service"])
        self.assertEqual(states["a.service"], ("active", "enabled"))
        self.assertEqual(states["b.service"], ("inactive", "disabled"))
        self.assertEqual(states["c.service"], ("?", "?"))

    def test_who_is_sent_the_alerts_place(self):
        """Only the sources that are on and put the coordinates in their URL
        (nws, emsc) count; a broken answer is None, not "nobody"."""
        def sources(*on):
            rows = [{"id": s, "on": s in on} for s in ("sasmex", "gdacs", "usgs", "emsc", "nws")]
            return json.dumps({"country": "MX", "sources": rows})
        with mock.patch.object(ps, "run", return_value=sources("sasmex", "gdacs", "usgs")):
            self.assertEqual(ps.alerts_sent_place(), [])
        with mock.patch.object(ps, "run", return_value=sources("usgs", "emsc", "nws")):
            self.assertEqual(sorted(ps.alerts_sent_place()), sorted(ps.SENDS_PLACE.values()))
        for broken in ("", "not json", "{}", '{"sources": 3}'):
            with mock.patch.object(ps, "run", return_value=broken):
                self.assertIsNone(ps.alerts_sent_place())

    def test_place_senders_exist_in_emergency_alerts(self):
        """SENDS_PLACE names real emergency-alerts.py sources whose fetcher
        puts the coordinates in the URL -- fails if one is renamed."""
        with open(ps.EMERGENCY) as handle:
            src = handle.read()
        for name in ps.SENDS_PLACE:
            self.assertRegex(src, rf'"{name}":\s*\(')
            body = src.split(f"def {name}(", 1)[1].split("\ndef ", 1)[0]
            self.assertIn("conf['lat']", body)


class ActivityLog(Scratch):
    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(al.subprocess, "run")      # the SIGUSR1 to the service
        self.sub = patcher.start()
        self.addCleanup(patcher.stop)

    def test_private_rules(self):
        self.assertTrue(al.is_private("org.keepassxc.KeePassXC", "db"))
        self.assertTrue(al.is_private("firefox", "x — Private Browsing"))
        self.assertTrue(al.is_private("Signal", "chat", ["signal"]))
        self.assertFalse(al.is_private("signal-desktop", "chat", ["signal"]))
        self.assertFalse(al.is_private("kitty", "~"))

    def test_log_write_honours_the_conf(self):
        ps.set_key("activity_exclude", "signal")
        log = al.Log()
        log.write("Signal", "a chat")
        log.write("kitty", "~")
        rows = self.read_log()
        self.assertEqual((rows[0]["class"], rows[0]["title"]), ("private", ""))
        self.assertEqual(rows[1]["class"], "kitty")

    def test_forget_hour_cuts_and_ends_the_open_period(self):
        now = time.time()
        self.write_log([{"t": now - 7200, "class": "kitty", "title": "a"},
                        {"t": now - 600, "class": "firefox", "title": "b"}])
        al.forget("hour")
        rows = self.read_log()
        self.assertEqual([r["class"] for r in rows], ["kitty", ""])
        self.assertAlmostEqual(rows[1]["t"], now - 3600, delta=5)
        self.assertIn("USR1", self.sub.call_args[0][0])

    def test_forget_lines_no_gap_after_a_gap(self):
        lines = [json.dumps({"t": 10, "class": ""}) + "\n", json.dumps({"t": 50, "class": "x"}) + "\n"]
        self.assertEqual(al.forget_lines(lines, 20), lines[:1])
        self.assertEqual(al.forget_lines(lines, 5), [])

    def test_forget_all_removes_the_file(self):
        self.write_log([{"t": time.time(), "class": "kitty", "title": "a"}])
        al.forget("all")
        self.assertFalse(os.path.exists(self.state))
        al.forget("all")        # nothing there: still fine

    def test_hide_makes_past_lines_private(self):
        lines = [json.dumps({"t": 1, "class": "Signal", "title": "chat"}) + "\n",
                 json.dumps({"t": 2, "class": "kitty", "title": "~"}) + "\n"]
        rows = [json.loads(line) for line in al.hide_lines(lines, "signal")]
        self.assertEqual((rows[0]["class"], rows[0]["title"]), ("private", ""))
        self.assertEqual(rows[1]["title"], "~")

    def test_prune_uses_the_kept_days(self):
        now = time.time()
        self.write_log([{"t": now - 3 * 86400, "class": "a"}, {"t": now - 3600, "class": "b"}])
        ps.set_key("activity_keep_days", "2")
        al.prune()
        self.assertEqual([r["class"] for r in self.read_log()], ["b"])

    def test_info_counts_without_contents(self):
        self.write_log([{"t": 100.0, "class": "a", "title": "secret"}, {"t": 200.0, "class": "b"}])
        data = al.info()
        self.assertEqual((data["entries"], data["since"]), (2, 100.0))
        self.assertNotIn("secret", json.dumps(data))


class AskDesktop(Scratch):
    def test_tools_follow_the_sources(self):
        names = [t["function"]["name"] for t in ask.allowed_tools({"files"})]
        self.assertEqual(names, ["search_files"])

    def test_a_refused_tool_runs_nothing(self):
        with mock.patch.dict(ask.SEARCHES, {"search_clipboard": mock.Mock(side_effect=AssertionError)}):
            self.assertIn("note", ask.call_search("search_clipboard", {"query": "x"}, {"files"}))

    def test_fallback_skips_what_is_off(self):
        with mock.patch.object(ask, "search_activity") as act, \
                mock.patch.object(ask, "search_files") as files, \
                mock.patch.object(ask, "search_clipboard") as clip:
            ctx = ask.fallback_context("find invoices yesterday", datetime.datetime.now(), {"activity"})
        act.assert_called_once()
        files.assert_not_called()
        clip.assert_not_called()
        self.assertEqual(ctx["files"].get("files", []), [])

    def test_off_answers_without_a_model(self):
        ps.set_key("ask", "off")
        with mock.patch.object(ask, "pick_model", side_effect=AssertionError):
            self.assertEqual(ask.ask("what was I doing"), (ask.OFF_ANSWER, []))
        ps.save(dict(ps.DEFAULTS, ask_files="off", ask_clipboard="off", ask_activity="off"))
        with mock.patch.object(ask, "pick_model", side_effect=AssertionError):
            self.assertEqual(ask.ask("what was I doing"), (ask.NO_SOURCES, []))

    def test_prompt_names_what_is_off(self):
        now = datetime.datetime.now()
        self.assertNotIn("not allowed", ask.system_prompt(now))
        self.assertIn("clipboard history", ask.system_prompt(now, {"files", "activity"}))


if __name__ == "__main__":
    unittest.main()
