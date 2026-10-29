"""notify-settings.py (values, quiet hours, mako's fragment, the reload that
rolls back) and auto-dnd.py's Watch with its three switchable reasons.

Hermetic: the settings file is in helpers' scratch XDG_STATE_HOME, the
fragment and the waybar config are scratch files, and every makoctl /
systemctl / hyprctl call is stubbed."""
import datetime
import json
import os
import subprocess
import tempfile
import unittest
from unittest import mock

import helpers

ns = helpers.import_script("notify-settings.py")
ad = helpers.import_script("auto-dnd.py")

D = datetime.datetime


def conf(**over):
    c = dict(ns.DEFAULTS)
    c.update(over)
    return c


class Values(unittest.TestCase):
    def test_bools(self):
        for text, want in (("on", True), ("OFF", False), ("1", True), ("no", False), (True, True)):
            self.assertIs(ns.coerce("group", text), want)
        with self.assertRaises(ValueError):
            ns.coerce("group", "maybe")

    def test_anchor_and_output(self):
        self.assertEqual(ns.coerce("anchor", "Top-Centre"), "top-center")
        with self.assertRaises(ValueError):
            ns.coerce("anchor", "sideways")
        self.assertEqual(ns.coerce("output", "follow"), "")
        self.assertEqual(ns.coerce("output", "HDMI-A-1"), "HDMI-A-1")
        with self.assertRaises(ValueError):
            ns.coerce("output", "DP-1\nexec=rm")      # nothing can smuggle a line into mako's config

    def test_numbers(self):
        self.assertEqual(ns.coerce("timeout-normal", "8"), 8)
        self.assertEqual(ns.coerce("max_visible", "-1"), -1)
        for key, bad in (("max_visible", "0"), ("max_visible", "21"), ("timeout_low", "-2"),
                         ("max_history", "x"), ("timeout_critical", "99999")):
            with self.assertRaises(ValueError, msg=f"{key}={bad}"):
                ns.coerce(key, bad)

    def test_times_and_days(self):
        self.assertEqual(ns.coerce("quiet_from", "7"), "07:00")
        self.assertEqual(ns.coerce("quiet_to", "6:30"), "06:30")
        for bad in ("24:00", "7:60", "seven", ""):
            with self.assertRaises(ValueError):
                ns.coerce("quiet_from", bad)
        self.assertEqual(ns.coerce("quiet_days", "weekdays"), "01234")
        self.assertEqual(ns.coerce("quiet_days", "5165"), "156")
        for bad in ("7", "mon", ""):
            with self.assertRaises(ValueError):
                ns.coerce("quiet_days", bad)

    def test_unknown_key(self):
        with self.assertRaises(ValueError):
            ns.coerce("volume", "3")


class LoadSave(unittest.TestCase):
    def tearDown(self):
        if os.path.exists(ns.CONF):
            os.remove(ns.CONF)

    def test_missing_and_broken_file_give_defaults(self):
        self.assertEqual(ns.load(), ns.DEFAULTS)
        os.makedirs(os.path.dirname(ns.CONF), exist_ok=True)
        with open(ns.CONF, "w") as fh:
            fh.write("{not json")
        self.assertEqual(ns.load(), ns.DEFAULTS)

    def test_bad_values_fall_back_one_by_one(self):
        os.makedirs(os.path.dirname(ns.CONF), exist_ok=True)
        with open(ns.CONF, "w") as fh:
            json.dump({"anchor": "nowhere", "max_visible": 3, "stray": 1}, fh)
        c = ns.load()
        self.assertEqual(c["anchor"], "top-right")
        self.assertEqual(c["max_visible"], 3)
        self.assertNotIn("stray", c)

    def test_round_trip(self):
        ns.save(conf(quiet=True, quiet_from="22:30"))
        self.assertEqual(ns.load(), conf(quiet=True, quiet_from="22:30"))


class QuietHours(unittest.TestCase):
    # 2026-10-19 is a Monday.
    def test_off_and_empty(self):
        self.assertFalse(ns.quiet_now(conf(), D(2026, 10, 19, 23, 30)))
        self.assertFalse(ns.quiet_now(conf(quiet=True, quiet_from="07:00", quiet_to="07:00"),
                                      D(2026, 10, 19, 7, 0)))
        self.assertIsNone(ns.next_change(conf(), D(2026, 10, 19, 12, 0)))

    def test_overnight(self):
        c = conf(quiet=True)                                      # 23:00-07:00 every day
        self.assertTrue(ns.quiet_now(c, D(2026, 10, 19, 23, 0)))
        self.assertTrue(ns.quiet_now(c, D(2026, 10, 20, 6, 59)))
        self.assertFalse(ns.quiet_now(c, D(2026, 10, 20, 7, 0)))
        self.assertFalse(ns.quiet_now(c, D(2026, 10, 19, 22, 59)))

    def test_same_day_window(self):
        c = conf(quiet=True, quiet_from="13:00", quiet_to="14:30")
        self.assertTrue(ns.quiet_now(c, D(2026, 10, 19, 14, 29)))
        self.assertFalse(ns.quiet_now(c, D(2026, 10, 19, 14, 30)))

    def test_days_are_the_starting_day(self):
        c = conf(quiet=True, quiet_days="01234")                 # Monday night .. Friday night
        self.assertTrue(ns.quiet_now(c, D(2026, 10, 24, 6, 0)))   # Saturday morning: Friday's night
        self.assertFalse(ns.quiet_now(c, D(2026, 10, 24, 23, 30)))  # Saturday night
        self.assertFalse(ns.quiet_now(c, D(2026, 10, 19, 6, 0)))  # Monday morning: Sunday's night

    def test_next_change(self):
        c = conf(quiet=True)
        self.assertEqual(ns.next_change(c, D(2026, 10, 19, 12, 0, 30)), D(2026, 10, 19, 23, 0))
        self.assertEqual(ns.next_change(c, D(2026, 10, 19, 23, 0)), D(2026, 10, 20, 7, 0))
        weekends = conf(quiet=True, quiet_days="56")
        self.assertEqual(ns.next_change(weekends, D(2026, 10, 19, 12, 0)), D(2026, 10, 24, 23, 0))

    def test_describe_days(self):
        self.assertEqual(ns.describe_days("0123456"), "every day")
        self.assertEqual(ns.describe_days("024"), "Mon, Wed, Fri")


class Fragment(unittest.TestCase):
    def test_defaults(self):
        text = ns.render_fragment(conf(), ["DP-1"])
        for line in ("anchor=top-right", "output=DP-1", "max-visible=5", "default-timeout=5000",
                     "ignore-timeout=0", "group-by=app-name", "max-history=50"):
            self.assertIn(line + "\n", text)
        self.assertNotIn("outer-margin", text)
        self.assertNotIn("invisible", text)
        lines = text.splitlines()
        low = lines.index("[urgency=low]")
        self.assertEqual(lines[low + 1], "default-timeout=3000")
        crit = lines.index("[urgency=critical]")
        self.assertEqual(lines[crit + 1], "default-timeout=0")

    def test_globals_before_sections(self):
        text = ns.render_fragment(conf(output="HDMI-A-1", group=False, critical_in_dnd=False), ["DP-1"])
        lines = [l for l in text.splitlines() if l and not l.startswith("#")]
        first = next(i for i, l in enumerate(lines) if l.startswith("["))
        self.assertTrue(all("=" in l and not l.startswith("[") for l in lines[:first]))
        self.assertIn("outer-margin=14", lines[:first])
        self.assertIn("group-by=", lines[:first])
        self.assertEqual(lines[-2:], ["[mode=do-not-disturb urgency=critical]", "invisible=1"])

    def test_margin_only_for_top_on_a_screen_without_bar(self):
        self.assertNotIn("outer-margin", ns.render_fragment(conf(output="", anchor="top-left"), ["DP-1"]))
        self.assertNotIn("outer-margin", ns.render_fragment(conf(output="DP-2", anchor="bottom-right"), ["DP-1"]))
        self.assertIn("outer-margin", ns.render_fragment(conf(output="DP-2", anchor="top-center"), ["DP-1"]))

    def test_bar_outputs(self):
        with tempfile.NamedTemporaryFile("w", suffix=".jsonc", delete=False) as fh:
            fh.write('{\n  // bar\n  "output": "DP-1",\n  "layer": "top"\n}\n')
        try:
            self.assertEqual(ns.bar_outputs(fh.name), ["DP-1"])
        finally:
            os.remove(fh.name)
        self.assertEqual(ns.bar_outputs("/nonexistent/config"), [])


class Apply(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(dir=helpers.SCRATCH)
        self.patches = [mock.patch.object(ns, "FRAGMENT", os.path.join(self.dir, "settings")),
                        mock.patch.object(ns, "bar_outputs", lambda path=None: ["DP-1"]),
                        mock.patch.object(ns, "mako_running", lambda: True)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def read(self):
        with open(ns.FRAGMENT) as fh:
            return fh.read()

    def test_rejected_reload_puts_the_old_fragment_back(self):
        calls, codes = [], []

        def fake_run(*cmd, timeout=5):
            calls.append(cmd)
            code = codes.pop(0) if codes else 0
            return subprocess.CompletedProcess(cmd, code, "", "Failed to parse" if code else "")
        with mock.patch.object(ns, "run", fake_run):
            self.assertIsNone(ns.apply(conf(anchor="center")))
            calls.clear()
            codes[:] = [1, 0]                     # mako refuses the new one, takes the old one back
            complaint = ns.apply(conf(anchor="bottom-left"))
        self.assertEqual(complaint, "Failed to parse")
        self.assertIn("anchor=center", self.read())
        self.assertEqual(calls, [("makoctl", "reload")] * 2)

    def test_ensure_writes_only_a_missing_file(self):
        with mock.patch.object(ns, "run", lambda *a, **k: self.fail("ensure must not reload")):
            ns.ensure()
            self.assertIn("anchor=top-right", self.read())
            with open(ns.FRAGMENT, "w") as fh:
                fh.write("# mine\n")
            ns.ensure()
        self.assertEqual(self.read(), "# mine\n")


class SetDnd(unittest.TestCase):
    def test_says_so_when_mako_did_not_take_it(self):
        with mock.patch.object(ns, "makoctl", lambda *a: "default\n"), \
                mock.patch.object(ns, "bell", lambda: None), \
                mock.patch.object(ns, "poke_auto_dnd", lambda: None):
            with self.assertRaises(RuntimeError):
                ns.set_dnd("on")
            self.assertFalse(ns.set_dnd("off"))


class AutoDnd(unittest.TestCase):
    """Watch with the outside world stubbed: `dnd` is mako's mode."""

    def setUp(self):
        self.dnd = False
        self.log = []

        def set_dnd(on, why):
            self.dnd = on
            self.log.append((on, why))
        self.patches = [mock.patch.object(ad, "games", lambda: 0),
                        mock.patch.object(ad, "dnd_on", lambda: self.dnd),
                        mock.patch.object(ad, "set_dnd", set_dnd),
                        mock.patch.object(ad, "focus_running", lambda: False)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def test_quiet_hours_turn_it_on_and_off(self):
        w = ad.Watch(conf(quiet=True))
        w.tick(D(2026, 10, 19, 23, 5))
        self.assertTrue(self.dnd)
        self.assertEqual(self.log[-1], (True, "quiet hours"))
        w.tick(D(2026, 10, 20, 7, 1))
        self.assertIsNotNone(w.release_at)       # lets go after RELEASE_S, like a game
        w.release()
        self.assertFalse(self.dnd)

    def test_switched_off_trigger_does_not_count(self):
        w = ad.Watch(conf(dnd_games=False))
        w.event("openwindow>>x")                  # games() says 0 anyway; force the fact
        w.game = True
        w.update()
        self.assertFalse(self.dnd)
        w.conf = conf(dnd_games=True)
        w.update()
        self.assertTrue(self.dnd)
        w.conf = conf(dnd_games=False)            # switched off while it holds DND on
        w.update()
        self.assertIsNotNone(w.release_at)

    def test_share_switch(self):
        # a share counts once it has lasted SHARE_ENGAGE_S (blips do not)
        now = [1000.0]
        with mock.patch.object(ad.time, "monotonic", lambda: now[0]), \
                mock.patch.object(ad, "share_owner", lambda: ""):
            w = ad.Watch(conf(dnd_share=False))
            w.event("screencast>>1,0")
            now[0] += ad.SHARE_ENGAGE_S + 1
            w.due(now[0])
            self.assertFalse(self.dnd)
            w.event("screencast>>0,0")                # let the first share go
            now[0] += ad.SHARE_GRACE_S + 1
            w.due(now[0])
            w.conf = conf()
            w.event("screencast>>1,0")
            w.due(now[0] + 1)
            self.assertEqual(self.log, [])            # a blip: not yet
            now[0] += ad.SHARE_ENGAGE_S + 1
            w.due(now[0])
        self.assertEqual(self.log, [(True, "screen share")])

    def test_you_turning_it_off_is_respected(self):
        w = ad.Watch(conf(quiet=True))
        w.tick(D(2026, 10, 19, 23, 5))
        self.dnd = False                          # you, by hand
        w.tick(D(2026, 10, 19, 23, 6))
        self.assertTrue(w.declined)
        w.tick(D(2026, 10, 19, 23, 7))
        self.assertFalse(self.dnd)
        self.assertEqual(len(self.log), 1)

    def test_already_on_is_left_alone(self):
        self.dnd = True
        w = ad.Watch(conf(quiet=True))
        w.tick(D(2026, 10, 19, 23, 5))
        w.tick(D(2026, 10, 20, 8, 0))
        self.assertIsNone(w.release_at)
        self.assertTrue(self.dnd)
        self.assertEqual(self.log, [])

    def test_report_file(self):
        w = ad.Watch(conf(quiet=True))
        w.tick(D(2026, 10, 19, 23, 5))
        with open(ns.AUTO_STATE) as fh:
            self.assertEqual(json.load(fh), {"ours": True, "declined": False, "reasons": "quiet hours"})
        self.assertTrue(ns.AUTO_STATE.startswith(helpers.SCRATCH))

    def test_mako_not_up_is_not_read_as_you_declining(self):
        """mako not answering yet (login) when the quiet hours start: it must
        try again, not mark DND as "ours" and then "declined" for the night."""
        def deaf(on, why):
            self.log.append((on, why))           # makoctl went nowhere: dnd stays off
        with mock.patch.object(ad, "set_dnd", deaf):
            w = ad.Watch(conf(quiet=True))
            w.tick(D(2026, 10, 19, 23, 5))
            self.assertFalse(w.ours)
            w.tick(D(2026, 10, 19, 23, 6))
            self.assertFalse(w.declined)
        w.tick(D(2026, 10, 19, 23, 7))           # mako is up now
        self.assertTrue(self.dnd)
        self.assertTrue(w.ours)

    def test_until_change(self):
        w = ad.Watch(conf(quiet=True))
        self.assertEqual(w.until_change(D(2026, 10, 19, 22, 0)), 3600)
        w.conf = conf()
        self.assertIsNone(w.until_change(D(2026, 10, 19, 22, 0)))


if __name__ == "__main__":
    unittest.main()
