"""scripts/automations.py: the rules' strict checking and their words, which
events fire which rules, the loop guards, the app / game tracking from
Hyprland's event lines, the rules file, and the plain-words path with the
model stubbed. Plus Settings > Automations' pure helpers.

Hermetic: the rules file is a scratch path (automations.RULES), the
daemon's control socket is helpers.py's scratch runtime dir (nothing listens
there), no action runs (the Engine's runner is a list), no model is asked,
and notify() is stubbed."""
import json
import os
import tempfile
import unittest

import helpers

A = helpers.import_script("automations.py", "automations")
A.notify = lambda *a: None
A.log = lambda text: None


def rule(**kw):
    base = {"id": "r1", "name": "R", "enabled": True, "when": {"event": "dnd-off"}, "do": [{"action": "digest"}]}
    base.update(kw)
    return base


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class Validate(unittest.TestCase):
    def test_good_rule_is_tidied(self):
        tidy, problems = A.validate(rule(when={"event": "time", "at": "7:05", "days": "weekdays"},
                                         do=[{"action": "dnd", "value": "ON"}], cooldown=10))
        self.assertEqual(problems, [])
        self.assertEqual(tidy["when"], {"event": "time", "at": "07:05", "days": "mon,tue,wed,thu,fri"})
        self.assertEqual(tidy["do"], [{"action": "dnd", "value": "on"}])
        self.assertNotIn("cooldown", tidy)                 # the default is not written out

    def test_strict_about_everything_unknown(self):
        _, problems = A.validate(rule(extra=1, when={"event": "app-open", "class": "x", "colour": "red"},
                                      do=[{"action": "dnd", "value": "maybe"}, {"action": "zap"},
                                          {"action": "notify", "value": "hi", "loud": True}]))
        text = " | ".join(problems)
        for bit in ("unknown key 'extra'", "no option 'colour'", "is on or off", "#2: action is one of",
                    "#3: only action and value"):
            self.assertIn(bit, text)

    def test_required_options_and_bad_values(self):
        self.assertIn("app-open needs when.class", A.validate(rule(when={"event": "app-open"}))[1])
        self.assertTrue(A.validate(rule(when={"event": "app-open", "class": "(("}))[1])
        self.assertTrue(A.validate(rule(when={"event": "time", "at": "25:00"}))[1])
        self.assertTrue(A.validate(rule(when={"event": "time", "at": "07:00", "days": "funday"}))[1])
        self.assertTrue(A.validate(rule(when={"event": "nope"}))[1])
        self.assertTrue(A.validate(rule(do=[]))[1])
        self.assertTrue(A.validate(rule(do=[{"action": "digest"}] * (A.MAX_ACTIONS + 1)))[1])
        self.assertTrue(A.validate(rule(do=[{"action": "digest", "value": "x"}]))[1])
        self.assertTrue(A.validate(rule(do=[{"action": "sound-profile", "value": "only-one"}]))[1])
        self.assertTrue(A.validate(rule(cooldown=-1))[1])
        self.assertTrue(A.validate(rule(cooldown=True))[1])
        self.assertTrue(A.validate(rule(id="Bad Id"))[1])

    def test_theme_must_exist(self):
        old = A.theme_names
        A.theme_names = lambda: ["aero", "matrix"]
        try:
            self.assertFalse(A.validate(rule(do=[{"action": "theme", "value": "matrix"}]))[1])
            self.assertTrue(A.validate(rule(do=[{"action": "theme", "value": "nope"}]))[1])
        finally:
            A.theme_names = old

    def test_underscore_notes_are_ignored(self):
        self.assertFalse(A.validate(rule(_note="mine", when={"event": "dnd-on", "_why": "x"}))[1])


class Words(unittest.TestCase):
    def test_describe(self):
        self.assertEqual(A.describe(rule(when={"event": "app-open", "class": "steam"},
                                         do=[{"action": "dnd", "value": "on"}, {"action": "theme", "value": "matrix"}])),
                         "When steam opens: turn Do Not Disturb on, then switch the theme to matrix")
        self.assertEqual(A.describe_when({"event": "time", "at": "09:00", "days": "mon,tue,wed,thu,fri"}),
                         "it is 09:00 on weekdays")
        self.assertEqual(A.describe_when({"event": "wifi-connected"}), "Wi-Fi connects")
        self.assertEqual(A.describe_when({"event": "wifi-connected", "ssid": "Home"}), "Wi-Fi connects to Home")

    def test_days(self):
        self.assertEqual(A.parse_days("weekends"), "56")
        self.assertEqual(A.parse_days("Monday, wed"), "02")
        self.assertEqual(A.days_text("0123456"), "every day")
        with self.assertRaises(ValueError):
            A.parse_days("")


class Matching(unittest.TestCase):
    def test_app_is_the_first_window_in_and_the_last_out(self):
        r = rule(when={"event": "app-open", "class": "firefox"})
        self.assertTrue(A.matches(r, "app-open", {"class": "firefox", "others": ["kitty"]}))
        self.assertFalse(A.matches(r, "app-open", {"class": "firefox", "others": ["Firefox"]}))
        self.assertFalse(A.matches(r, "app-open", {"class": "firefox-dev", "others": []}))   # whole class
        self.assertTrue(A.matches(rule(when={"event": "app-open", "class": "steam_app_.*"}),
                                  "app-open", {"class": "steam_app_42", "others": []}))

    def test_optional_options_match_anything(self):
        self.assertTrue(A.matches(rule(when={"event": "audio-output"}), "audio-output", {"name": "x"}))
        r = rule(when={"event": "audio-output", "device": "headphones"})
        self.assertTrue(A.matches(r, "audio-output", {"name": "alsa_output.usb", "description": "USB Headphones"}))
        self.assertFalse(A.matches(r, "audio-output", {"name": "hdmi", "description": "HDMI"}))
        self.assertTrue(A.matches(rule(when={"event": "wifi-connected", "ssid": "home"}),
                                  "wifi-connected", {"ssid": "Home"}))

    def test_time_and_days(self):
        r = rule(when={"event": "time", "at": "09:00", "days": "mon,tue,wed,thu,fri"})
        self.assertTrue(A.matches(r, "time", {"at": "09:00", "weekday": 0}))
        self.assertFalse(A.matches(r, "time", {"at": "09:00", "weekday": 6}))
        self.assertFalse(A.matches(r, "time", {"at": "09:01", "weekday": 0}))


class Guards(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.ran = []
        self.engine = A.Engine([rule(), rule(id="off", enabled=False)],
                               lambda r, e, f: self.ran.append(r["id"]), self.clock)

    def test_fires_and_skips_disabled(self):
        self.assertEqual(self.engine.emit("dnd-off"), ["r1"])
        self.assertEqual(self.ran, ["r1"])
        self.assertEqual(self.engine.needs(), {"dnd-off"})

    def test_not_fired_by_its_own_actions(self):
        self.engine.emit("dnd-off")
        self.clock.t += 60                      # past the cooldown, but the actions still run
        self.assertEqual(self.engine.emit("dnd-off"), [])
        self.engine.finished("r1")
        self.clock.t += A.ECHO_S - 1            # their echo
        self.assertEqual(self.engine.emit("dnd-off"), [])
        self.clock.t += 2
        self.assertEqual(self.engine.emit("dnd-off"), ["r1"])

    def test_cooldown(self):
        self.engine.emit("dnd-off")
        self.engine.finished("r1")
        self.clock.t += A.ECHO_S + 1
        self.assertEqual(self.engine.emit("dnd-off"), [])         # 10 s cooldown not over
        self.clock.t += A.COOLDOWN_S
        self.assertEqual(self.engine.emit("dnd-off"), ["r1"])

    def test_storm_pauses_until_resumed(self):
        fired = 0
        for _ in range(A.STORM_MAX + 3):
            fired += len(self.engine.emit("dnd-off"))
            self.engine.finished("r1")
            self.clock.t += A.COOLDOWN_S + A.ECHO_S
        self.assertEqual(fired, A.STORM_MAX)
        self.assertIn("r1", self.engine.paused)
        self.engine.resume("r1")
        self.assertEqual(self.engine.emit("dnd-off"), ["r1"])


class Windows(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.events = []
        engine = A.Engine([], None, self.clock)
        engine.emit = lambda event, **facts: self.events.append((event, facts))
        self.w = A.Windows(engine, {"aa": "kitty"})

    def test_open_close_carry_the_other_classes(self):
        self.w.event("openwindow>>bb,1,firefox,Mozilla Firefox", self.clock)
        self.assertEqual(self.events[-1], ("app-open", {"class": "firefox", "others": ["kitty"]}))
        self.w.event("closewindow>>bb", self.clock)
        self.assertEqual(self.events[-1], ("app-close", {"class": "firefox", "others": ["kitty"]}))
        self.w.event("closewindow>>unknown", self.clock)          # a window from before: nothing
        self.assertEqual(len(self.events), 2)

    def test_game_end_waits_for_the_next_window(self):
        self.w.event("openwindow>>g1,3,steam_app_42,Launcher", self.clock)
        self.assertIn(("game-start", {"appid": "42"}), self.events)
        self.w.event("closewindow>>g1", self.clock)
        self.clock.t += 1
        self.w.event("openwindow>>g2,3,steam_app_42,Game", self.clock)    # launcher -> game window
        self.clock.t += A.RELEASE_S + 1
        self.w.tick(self.clock)
        self.assertNotIn("game-end", [e for e, _ in self.events])
        self.w.event("closewindow>>g2", self.clock)
        self.w.tick(self.clock)
        self.assertNotIn("game-end", [e for e, _ in self.events])
        self.clock.t += A.RELEASE_S
        self.w.tick(self.clock)
        self.assertEqual([e for e, _ in self.events].count("game-start"), 1)
        self.assertEqual([e for e, _ in self.events].count("game-end"), 1)


class RulesFile(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        os.remove(self.path)
        self.old, A.RULES = A.RULES, self.path
        self.addCleanup(lambda: setattr(A, "RULES", self.old))
        self.addCleanup(lambda: os.path.exists(self.path) and os.remove(self.path))

    BUILT = ["dnd-digest", "daily-brief", "end-of-day"]     # in BUILTIN's order, ahead of the file's own

    def test_builtin_digest_ships_on(self):
        good, bad = A.load()
        self.assertEqual([r["id"] for r in good], self.BUILT)
        self.assertTrue(all(r["enabled"] and r["builtin"] for r in good))
        self.assertEqual(bad, [])

    def test_builtin_brief_and_journal_rules(self):
        good, _ = A.load()
        brief, journal = A.find(good, "daily-brief"), A.find(good, "end-of-day")
        self.assertEqual((brief["when"]["event"], brief["do"]), ("idle-end", [{"action": "brief"}]))
        self.assertEqual((journal["when"]["event"], journal["do"]), ("work-end", [{"action": "journal"}]))
        argv, how = A.action_argv({"action": "brief"})
        self.assertEqual((argv[0], argv[-2:], how), ("systemd-run", ["auto", "--rule"], "wait"))
        argv, _ = A.action_argv({"action": "journal"})
        self.assertEqual(argv[-2:], ["journal", "--notify"])

    def test_add_switch_delete_and_notes_kept(self):
        A.ensure_file()
        with open(self.path) as handle:
            data = json.load(handle)
        data["_mine"] = "keep me"
        with open(self.path, "w") as handle:
            json.dump(data, handle)
        added = A.add({"name": "Quiet Steam", "when": {"event": "app-open", "class": "steam"},
                       "do": [{"action": "dnd", "value": "on"}]})
        self.assertEqual(added["id"], "quiet-steam")
        self.assertEqual(A.add(dict(added))["id"], "quiet-steam-2")       # ids stay unique
        self.assertTrue(A.update_raw("Quiet Steam", lambda r, _raw: r.__setitem__("enabled", False)))
        self.assertFalse(A.find(A.load()[0], "quiet-steam")["enabled"])
        A.update_raw("quiet-steam-2", lambda r, raw: raw.remove(r))
        with open(self.path) as handle:
            data = json.load(handle)
        self.assertEqual(data["_mine"], "keep me")
        self.assertIn("_doc", data)
        self.assertEqual([r["id"] for r in data["rules"]], self.BUILT + ["quiet-steam"])

    def test_broken_rule_skipped_rest_kept(self):
        with open(self.path, "w") as handle:
            json.dump({"rules": [rule(id="ok"), rule(id="bad", when={"event": "nope"}), rule(id="ok")]}, handle)
        good, bad = A.load()
        self.assertEqual([r["id"] for r in good], self.BUILT + ["ok"])
        self.assertEqual([b[0] for b in bad], ["bad", "ok"])

    def test_not_json_keeps_builtins_and_says_so(self):
        with open(self.path, "w") as handle:
            handle.write("{nope")
        good, bad = A.load()
        self.assertEqual([r["id"] for r in good], self.BUILT)
        self.assertEqual(bad[0][0], "file")
        with self.assertRaises(ValueError):
            A.add(rule(id=None))


class PlainWords(unittest.TestCase):
    def test_model_rule_checked_strictly(self):
        answer = json.dumps({"name": "Quiet Steam", "when": {"event": "app-open", "class": "steam"},
                             "do": [{"action": "dnd", "value": "on"}]})
        r, why = A.from_text("when steam opens turn on dnd", ask=lambda prompt: answer)
        self.assertIsNone(why)
        self.assertEqual(r["when"], {"event": "app-open", "class": "steam"})

    def test_invented_things_are_refused(self):
        bad = json.dumps({"name": "Pizza", "when": {"event": "rain"}, "do": [{"action": "order-pizza"}]})
        r, why = A.from_text("when it rains order pizza", ask=lambda p: bad)
        self.assertIsNone(r)
        self.assertIn("does not check out", why)
        r, why = A.from_text("x", ask=lambda p: '{"error": "no weather event"}')
        self.assertIn("no weather event", why)
        r, why = A.from_text("x", ask=lambda p: "sorry, I can't")
        self.assertIsNone(r)

    def test_model_failure_is_a_reason(self):
        def boom(_prompt):
            raise OSError("connection refused")
        r, why = A.from_text("x", ask=boom)
        self.assertIsNone(r)
        self.assertIn("connection refused", why)

    def test_prompt_names_every_event_and_action(self):
        prompt = A.model_prompt("anything")
        for name in list(A.EVENTS) + list(A.ACTIONS):
            self.assertIn(name, prompt)


class Actions(unittest.TestCase):
    def test_argv_for_each(self):
        self.assertEqual(A.action_argv({"action": "dnd", "value": "on"})[0][-2:], ["dnd", "on"])
        self.assertIn('require("lua.gamemode").set(true', A.action_argv({"action": "gamemode", "value": "on"})[0][-1])
        self.assertEqual(A.action_argv({"action": "shell", "value": "echo hi"}), (["sh", "-c", "echo hi"], "wait"))
        argv, how = A.action_argv({"action": "open", "value": "kitty --title x"})
        self.assertEqual((argv[-3:], how), (["kitty", "--title", "x"], "detach"))
        self.assertEqual(A.action_argv({"action": "digest"})[0][:2], ["systemd-run", "--user"])

    def test_shell_gets_the_event_details(self):
        env = A.facts_env(rule(), "app-open", {"class": "firefox", "others": ["a"]})
        self.assertEqual((env["AUTOMATION_RULE"], env["AUTOMATION_CLASS"]), ("r1", "firefox"))
        self.assertNotIn("AUTOMATION_OTHERS", env)


class SettingsPage(unittest.TestCase):
    """settings_pages/automations.py's pure helpers (no window is built)."""

    @classmethod
    def setUpClass(cls):
        from settings_pages import automations as page
        cls.page = page

    def test_picked_rule_is_valid(self):
        r = self.page.picked_rule("", "app-open", "class", " steam ", "dnd", "on")
        self.assertEqual(A.validate(r)[1], [])
        self.assertEqual(r["name"], "My rule")
        r = self.page.picked_rule("x", "dnd-off", None, "", "digest", "")
        self.assertEqual(r["do"], [{"action": "digest"}])

    def test_last_ran(self):
        self.assertIn("not run", self.page.last_ran(None))
        self.assertEqual(self.page.last_ran(1000, now=1030), "ran just now")
        self.assertEqual(self.page.last_ran(1000, now=1000 + 600), "ran 10 min ago")

    def test_rule_sub_says_paused(self):
        sub = self.page.rule_sub({"words": "When x", "enabled": True, "paused": "fired 5 times", "last": None})
        self.assertIn("Paused: fired 5 times", sub)


if __name__ == "__main__":
    unittest.main()
