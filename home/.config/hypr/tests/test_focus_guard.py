"""Focus guard (focus-guard.py): the settings and lists, what a window is
(app / site / group), the scatter count, the stats brief.py reads, the
summary's words; the daemon's block -- tagging, parking, the card's answers,
the end -- and its offer; and the small hooks elsewhere: automations.py's
"focus" action and events, suggest.py's "focus" kind, timers.py's hand-over
and brief.py's Focus lines.

Hermetic: focus-guard.conf / -stats.json are helpers.py's scratch
XDG_STATE_HOME and the block's file its scratch runtime dir; every call
that would reach Hyprland (tag, move, the dim rule), timers.py's systemd
timer, makoctl, a notification or another daemon's socket is stubbed. No
window is touched, nothing is shown."""
import datetime as dt
import os
import unittest
from unittest import mock

import helpers

G = helpers.import_script("focus-guard.py", "focus_guard")
A = helpers.import_script("automations.py", "automations")
suggest = helpers.import_script("suggest.py")
timers = helpers.import_script("timers.py", "timers")
brief = helpers.import_script("brief.py", "brief")


def clean():
    for path in (G.CONF, G.STATS, G.LIVE):
        if os.path.exists(path):
            os.remove(path)


class Settings(unittest.TestCase):
    setUp = tearDown = staticmethod(clean)

    def test_defaults_and_checks(self):
        v = G.read_settings()
        self.assertEqual((v["style"], v["quiet"], v["breaks"], v["sensitivity"]), ("dim", "dnd", "on", "medium"))
        self.assertIn("discord", G.items(v, "apps"))
        self.assertIsNone(G.check_value("style", "block"))         # never "block"
        self.assertIsNone(G.check_value("dim_pct", "5"))
        self.assertEqual(G.check_value("apps", "Discord, steam,,bad name!,steam"), "discord,steam")

    def test_write_keeps_only_changes(self):
        G.write_setting("style", "both")
        G.write_setting("dim_pct", "40")
        G.write_setting("dim_pct", "55")                            # back at the default
        with open(G.CONF) as handle:
            text = handle.read()
        self.assertIn("style=both", text)
        self.assertNotIn("dim_pct", text)
        with self.assertRaises(ValueError):
            G.write_setting("delay_s", "99")

    def test_bad_lines_are_defaults(self):
        os.makedirs(os.path.dirname(G.CONF), exist_ok=True)
        with open(G.CONF, "w") as handle:
            handle.write("style=explode\nwindow_min=30\nnonsense\n")
        v = G.read_settings()
        self.assertEqual((v["style"], v["window_min"]), ("dim", "30"))


class Windows(unittest.TestCase):
    def test_distracting_app(self):
        self.assertTrue(G.distracting_app("discord", ["discord"]))
        self.assertTrue(G.distracting_app("com.discordapp.Discord", ["discord"]))
        self.assertFalse(G.distracting_app("steam_app_1091500", ["steam"]))     # a game is not "steam"
        self.assertFalse(G.distracting_app("", ["discord"]))

    def test_site_needs_a_browser_and_a_word(self):
        sites = ["youtube", "reddit"]
        self.assertEqual(G.site_of("firefox", "Lo-fi beats - YouTube — Mozilla Firefox", sites), "youtube")
        self.assertIsNone(G.site_of("kitty", "youtube-dl ~/Downloads", sites))   # not a browser
        self.assertIsNone(G.site_of("firefox", "myyoutubeclone docs", sites))   # not a word

    def test_groups(self):
        repos = ["Atlas", "Media"]
        po = brief.project_of
        self.assertEqual(G.group_of("com.system76.CosmicTerm", "~/Projects/Atlas", False, repos, "", po),
                         "project:Atlas")
        self.assertEqual(G.group_of("code", "app.js - Atlas - Visual Studio Code", False, repos, "", po),
                         "project:Atlas")
        self.assertEqual(G.group_of("com.system76.CosmicTerm", "~", False, repos, "", po), "terminal")
        # inside a context its terminals / editors are one group whatever they show
        self.assertEqual(G.group_of("kitty", "~/notes", False, repos, "Media", po), "project:Media")
        self.assertEqual(G.group_of("firefox", "Atlas — preview", False, repos, "Atlas", po), "project:Atlas")
        self.assertEqual(G.group_of("firefox", "News", False, repos, "", po), "firefox")
        self.assertEqual(G.group_of("keepassxc", "secret.kdbx", True, repos, "", po), "private")


class Scatter(unittest.TestCase):
    def hist(self, groups, start=0, every=30, dis=()):
        return [(start + i * every, g, g in dis) for i, g in enumerate(groups)]

    def test_back_and_forth_on_one_project_is_calm(self):
        h = self.hist(["project:Atlas", "firefox"] * 30)                      # 60 switches, 2 groups
        s = G.scatter(h, 1800, 1200, "medium")
        self.assertGreaterEqual(s["switches"], 30)
        self.assertFalse(s["scattered"])

    def test_hopping_is_scattered(self):
        groups = ["project:Atlas", "firefox", "discord", "nautilus", "project:Media", "spotify"] * 6
        s = G.scatter(self.hist(groups, every=30), 1100, 1200, "medium")
        self.assertTrue(s["scattered"])
        self.assertEqual(s["groups"], 6)

    def test_distractions_count_twice_and_sensitivity(self):
        groups = ["a", "b", "c", "d", "discord"] * 4                             # 19 switches
        h = self.hist(groups, every=50, dis=("discord",))
        medium = G.scatter(h, 1000, 1200, "medium")
        self.assertEqual(medium["weighted"], medium["switches"] + medium["distracting"])
        self.assertFalse(medium["scattered"])
        self.assertTrue(G.scatter(h, 1000, 1200, "high")["scattered"])

    def test_only_the_window_counts(self):
        h = self.hist(["a", "b", "c", "d", "e"] * 10, every=10)                 # all long ago
        s = G.scatter(h, 10_000, 1200)
        self.assertEqual((s["switches"], s["groups"]), (0, 1))                  # just what had the focus


class Stats(unittest.TestCase):
    setUp = tearDown = staticmethod(clean)

    def test_add_and_read(self):
        today = dt.date.today()
        self.assertIsNone(G.day_stats(today))
        G.add_stats(minutes=24.6, blocks=1)
        G.add_stats(minutes=10, blocks=1, offered=1)
        row = G.day_stats(today)
        self.assertEqual((row["minutes"], row["blocks"], row["offered"]), (34.6, 2, 1))
        week = G.recent_stats(7)
        self.assertEqual((len(week), week[-1]["blocks"]), (7, 2))
        self.assertEqual(brief.focus_stats(today)["blocks"], 2)                  # what brief.py reads
        self.assertEqual(brief.focus_text(row), "34 min in focus blocks (2 blocks)")

    def test_old_days_drop(self):
        G.add_stats(day=dt.date.today() - dt.timedelta(days=G.STATS_DAYS + 5), minutes=5)
        G.add_stats(minutes=1)
        self.assertEqual(len(G.load_stats()["days"]), 1)

    def test_summary_lines(self):
        tally = {"projects": [("Atlas", 1200), ("private", 300), ("firefox", 240)]}
        lines = G.summary_lines(tally, 14, {"Atlas": [("10:01", "abc", "Fix x")]}, ["Discord"])
        self.assertEqual(lines[0], "Mostly Atlas 20 min, firefox 4 min.")
        self.assertIn("14 window switches.", lines)
        self.assertIn("1 commit in Atlas.", lines)
        self.assertTrue(lines[-1].startswith("Waited for you: Discord"))


class FakeHypr:
    """tag / move / focus / the dim rule, recorded instead of done."""

    def __init__(self, test, clients):
        self.calls, self.clients = [], clients
        for name in ("tag", "move", "focus_window", "apply_dim", "automation_event", "spawn", "add_stats"):
            patcher = mock.patch.object(G, name, side_effect=lambda *a, n=name, **k: self.calls.append((n, a)) or True)
            patcher.start()
            test.addCleanup(patcher.stop)
        s = suggest
        for name, value in (("hyprctl_json", None), ("dnd_on", False), ("gamemode_on", False),
                            ("process_running", False), ("slept_offset", 0.0)):
            patcher = mock.patch.object(s, name, return_value=value)
            patcher.start()
            test.addCleanup(patcher.stop)
        s.hyprctl_json.side_effect = lambda what: (self.clients if what == "clients" else
                                                   {"name": "3"} if what == "activeworkspace" else None)
        patcher = mock.patch.object(s, "is_private", return_value=False)
        patcher.start()
        test.addCleanup(patcher.stop)
        patcher = mock.patch.object(G, "suggest", return_value=s)
        patcher.start()
        test.addCleanup(patcher.stop)

    def of(self, name):
        return [a for n, a in self.calls if n == name]


def client(addr, cls, title="", ws="2"):
    return {"address": addr, "class": cls, "title": title, "workspace": {"id": 2, "name": ws}}


class Block(unittest.TestCase):
    def setUp(self):
        clean()
        self.clock = [1000.0]
        self.hypr = FakeHypr(self, [client("0xaaa1", "discord"), client("0xaaa2", "firefox", "Docs - MDN"),
                                    client("0xaaa3", "kitty", "~/Projects/Atlas")])

    tearDown = staticmethod(clean)

    def daemon(self, **values):
        v = dict(G.DEFAULTS, **values)
        return G.Daemon(values=v, clock=lambda: self.clock[0])

    def test_begin_tags_the_distractions_only(self):
        d = self.daemon()
        d.begin({"id": "1", "due": 2500})
        self.assertEqual(self.hypr.of("tag"), [("0xaaa1", True)])
        self.assertEqual(d.block["tagged"], {"0xaaa1": "app"})
        self.assertEqual(self.hypr.of("apply_dim")[-1], (True, 55))
        self.assertEqual(self.hypr.of("automation_event"), [("focus-start",)])
        self.assertTrue(os.path.exists(G.LIVE))

    def test_a_tab_on_a_site_dims_and_leaving_it_undims(self):
        d = self.daemon()
        d.begin({"id": "1", "due": 2500})
        d.event("windowtitlev2>>aaa2,Cats - YouTube — Mozilla Firefox")
        self.assertEqual(d.block["tagged"]["0xaaa2"], "site:youtube")
        d.event("windowtitlev2>>aaa2,Docs - MDN")
        self.assertNotIn("0xaaa2", d.block["tagged"])
        self.assertEqual(self.hypr.of("tag")[-2:], [("0xaaa2", True), ("0xaaa2", False)])

    def test_delay_parks_a_new_window_and_open_brings_it_back(self):
        d = self.daemon(style="delay")
        d.begin({"id": "1", "due": 2500})
        self.assertEqual(self.hypr.of("tag"), [])                                 # delay: no dimming
        d.event("openwindow>>bbb1,4,discord,Discord")
        self.assertEqual(self.hypr.of("move")[-1], ("0xbbb1", G.PARK))
        self.assertEqual(d.block["parked"], {"0xbbb1": "4"})
        self.assertEqual(d.waiting[0][:2], ("app", "0xbbb1"))
        with mock.patch.object(d, "show_overlay") as show:
            d.maybe_card()
        card = show.call_args[0][0]
        self.assertEqual((card["kind"], card["delay_s"], card["left_min"]), ("app", 10, 25))
        d.answered(card, "open")
        self.assertEqual(self.hypr.of("move")[-1], ("0xbbb1", "4"))
        self.assertIn("0xbbb1", d.block["allowed"])
        self.assertEqual(self.hypr.of("focus_window")[-1], ("0xbbb1",))

    def test_end_gives_everything_back(self):
        d = self.daemon(style="both", summary="off")
        d.begin({"id": "1", "due": 2500})
        d.event("openwindow>>bbb1,4,discord,Discord")
        d.answered({"kind": "app", "addr": "0xbbb1"}, "later")
        self.clock[0] = 2600
        d.end("done")
        self.assertIsNone(d.block)
        self.assertIn(("0xaaa1", False), self.hypr.of("tag"))
        self.assertEqual(self.hypr.of("move")[-1], ("0xbbb1", "4"))
        self.assertEqual(self.hypr.of("apply_dim")[-1], (False, 55))
        self.assertTrue(self.hypr.of("add_stats"))                              # waited, then the minutes
        self.assertFalse(os.path.exists(G.LIVE))
        self.assertEqual(self.hypr.of("automation_event")[-1], ("focus-end",))

    def test_start_schedules_the_round_with_its_flags(self):
        d = self.daemon(breaks="off")
        with mock.patch.object(timers, "schedule", return_value={"id": "9", "due": 1000 + 1500}) as sched, \
                mock.patch.object(timers, "load", return_value={"timers": []}), \
                mock.patch.object(timers, "bell"), \
                mock.patch.object(G, "makoctl", return_value="default") as mako, \
                mock.patch.object(G, "timers", return_value=timers):
            reply = d.start(25)
        self.assertEqual((reply["ok"], reply["quiet"]), (True, "dnd"))
        mako.assert_any_call("mode", "-a", "do-not-disturb")
        kwargs = sched.call_args.kwargs
        self.assertEqual((kwargs["dnd"], kwargs["nobreak"], kwargs["guard"]), (True, True, True))
        self.assertEqual(d.block["id"], "9")

    def test_start_undoes_dnd_when_the_timer_cannot_be_armed(self):
        # systemd-run failing used to escape handle_client (CalledProcessError
        # is no OSError): the daemon died with Do Not Disturb left on for good
        d = self.daemon()
        err = G.subprocess.CalledProcessError(1, ["systemd-run"])
        with mock.patch.object(timers, "schedule", side_effect=err), \
                mock.patch.object(timers, "load", return_value={"timers": []}), \
                mock.patch.object(timers, "bell"), \
                mock.patch.object(G, "makoctl", return_value="default") as mako, \
                mock.patch.object(G, "timers", return_value=timers):
            reply = d.start(25)
        self.assertIn("error", reply)
        self.assertIsNone(d.block)
        mako.assert_any_call("mode", "-a", "do-not-disturb")
        self.assertEqual(mako.call_args, mock.call("mode", "-r", "do-not-disturb"))

    def test_start_refuses_a_second_block_and_bad_lengths(self):
        d = self.daemon()
        with mock.patch.object(G, "timers", return_value=timers), \
                mock.patch.object(timers, "load", return_value={"timers": [{"id": "1", "kind": "focus", "due": 5000}]}):
            self.assertIn("error", d.start(25))
        with mock.patch.object(G, "timers", return_value=timers), \
                mock.patch.object(timers, "load", return_value={"timers": []}):
            self.assertIn("error", d.start(999))


class Offer(unittest.TestCase):
    def setUp(self):
        clean()
        self.hypr = FakeHypr(self, [])
        patcher = mock.patch.object(G, "watch_on", return_value=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    tearDown = staticmethod(clean)

    def scattered_daemon(self):
        d = G.Daemon(values=dict(G.DEFAULTS), clock=lambda: 5000.0)
        d.watch_since = 0
        groups = ["a", "b", "c", "d", "e", "f"] * 7
        d.history = [(4000 + i * 20, g, False) for i, g in enumerate(groups)]
        return d

    def test_goes_to_the_strip_when_it_takes_it(self):
        d = self.scattered_daemon()
        with mock.patch.object(suggest, "ask_daemon", return_value={"taken": True}) as ask, \
                mock.patch.object(G, "timers", return_value=timers), \
                mock.patch.object(timers, "load", return_value={"timers": []}):
            self.assertEqual(d.maybe_offer(5000.0), "strip")
        self.assertEqual(ask.call_args[0][0]["op"], "focus")
        self.assertEqual(d.history, [])                                          # counting starts again
        with mock.patch.object(suggest, "ask_daemon") as ask:
            d.history = self.scattered_daemon().history
            self.assertIsNone(d.maybe_offer(5000.0))                            # the cooldown
            ask.assert_not_called()

    def test_else_a_notification(self):
        d = self.scattered_daemon()
        with mock.patch.object(suggest, "ask_daemon", return_value=None), \
                mock.patch.object(G, "timers", return_value=timers), \
                mock.patch.object(timers, "load", return_value={"timers": []}), \
                mock.patch.object(G.threading, "Thread") as thread:
            self.assertEqual(d.maybe_offer(5000.0), "notification")
        thread.assert_called_once()

    def test_switching_noticing_off_forgets_and_on_seeds(self):
        d = self.scattered_daemon()
        d.watching = True
        G.watch_on.return_value = False
        d.follow_switch(5000.0)
        self.assertEqual(d.history, [])                                          # nothing kept after "no"
        G.watch_on.return_value = True
        with mock.patch.object(d, "seed") as seed:
            d.follow_switch(5100.0)
        seed.assert_called_once_with(5100.0)
        self.assertEqual(d.watch_since, 5100.0)

    def test_quiet_when_dnd_or_in_a_block(self):
        d = self.scattered_daemon()
        with mock.patch.object(G, "timers", return_value=timers), \
                mock.patch.object(timers, "load", return_value={"timers": []}):
            suggest.dnd_on.return_value = True
            self.assertEqual(d.quiet_reason(5000.0), "do not disturb")
            suggest.dnd_on.return_value = False
            d.block = {"id": "1"}
            self.assertEqual(d.quiet_reason(5000.0), "in a focus block")


class Hooks(unittest.TestCase):
    def test_automations_focus_action(self):
        argv, how = A.action_argv({"action": "focus", "value": "50"})
        self.assertEqual((argv[-2:], how), (["start", "50"], "wait"))
        self.assertEqual(A.action_argv({"action": "focus", "value": "off"})[0][-1], "stop")
        self.assertEqual(A.action_argv({"action": "focus", "value": "focus"})[0][-1], "start")
        self.assertIsNone(A.action_argv({"action": "focus", "value": "999"})[0])
        self.assertIsNone(A.action_argv({"action": "focus", "value": "; rm -rf ~"})[0])
        rule = {"name": "r", "when": {"event": "focus-start"}, "do": [{"action": "focus", "value": "banana"}]}
        self.assertIsNone(A.validate(rule)[0])
        rule["do"] = [{"action": "notify", "value": "focused"}]
        self.assertIsNotNone(A.validate(rule)[0])
        self.assertIn("focus-end", A.POKED)

    def test_suggest_focus_kind(self):
        card = suggest.focus_candidate({"minutes": 50, "switches": 31, "groups": 6, "window_min": 20}, 0)
        self.assertEqual(card["actions"], [["focus_block", "Focus 50 min", "50"]])
        with mock.patch.object(suggest, "spawn") as spawn:
            self.assertEqual(suggest.run_action(card, "focus_block", "50; x"), "Not a length.")
            spawn.assert_not_called()
            suggest.run_action(card, "focus_block", "50")
            self.assertEqual(spawn.call_args[0][-3:], ("start", "50", "--suggested"))
        d = suggest.Daemon(values=dict(suggest.DEFAULTS), learn={})
        self.assertEqual(d.request({"op": "focus", "card": {"minutes": 25}}), {"taken": False})   # off as shipped
        d.values["focus"] = "on"
        self.assertEqual(d.request({"op": "focus", "card": {"minutes": 25}}), {"taken": True})
        self.assertIn("focus", d.pending)

    def test_timers_hands_over_only_when_the_guard_runs(self):
        self.assertIsNone(timers.guard_start(25))                               # no socket in the scratch dir

    def test_journal_has_a_focus_section(self):
        facts = {"tally": None, "activity_off": True, "commits": {}, "loose": [], "titles": False,
                 "focus": {"minutes": 50, "blocks": 2}}
        block = brief.entry_block(facts, "s", "how")
        self.assertIn("## Focus", block)
        self.assertIn("50 min in focus blocks (2 blocks)", block)
        facts["focus"] = None
        self.assertNotIn("## Focus", brief.entry_block(facts, "s", "how"))


if __name__ == "__main__":
    unittest.main()
