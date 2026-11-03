"""automations.py's power triggers -- power-unplugged, power-plugged and
battery-low (with "below") -- and the battery-saver action: their checking
and words, which warnings fire which rules (once per discharge with
"below", reset by the charger going or coming, kept across a daemon
restart while power-watch says the discharge goes on), the
percentage carried from power-watch.py's environment over the control
socket, and that a desktop's catalog, prompt and Settings pickers stay as
they were while a laptop's offer them. Plus Settings > Automations' bits.

Hermetic: no action runs (the Engine's runner is a list), poke() is
replaced by a recorder (nothing reaches a daemon), notify() and log() are
stubbed, and the battery is a fake power_supply tree in a scratch folder
(helpers.fake_power_supply); without one, helpers.py makes this a desktop."""
import os
import tempfile
import types
import unittest
from unittest import mock

import helpers

A = helpers.import_script("automations.py", "automations")
A.notify = lambda *a: None
A.log = lambda text: None


def rule(rid="r1", below=None, event="battery-low", do=None, cooldown=0):
    when = {"event": event} | ({"below": below} if below is not None else {})
    return {"id": rid, "name": rid.upper(), "enabled": True, "when": when,
            "do": do or [{"action": "battery-saver", "value": "on"}], "cooldown": cooldown}


def tidy(r):
    out, problems = A.validate(r)
    assert not problems, problems
    return out


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class Laptop:
    """A fake BATT + ACAD tree, pointed at by ATRIUM_POWER_SUPPLY for the
    test's length (power_state reads the variable on every call)."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(dir=helpers.SCRATCH)
        helpers.fake_power_supply(self.dir, battery={"status": "Discharging", "capacity": 30}, ac=False)
        patcher = mock.patch.dict(os.environ, {"ATRIUM_POWER_SUPPLY": self.dir})
        patcher.start()
        self.addCleanup(patcher.stop)


class Checking(unittest.TestCase):
    def test_below_is_a_percent_kept_as_a_number(self):
        for given in (20, "20", " 20 % ", "20%"):
            self.assertEqual(tidy(rule(below=given))["when"], {"event": "battery-low", "below": 20}, given)
        self.assertEqual(tidy(rule(below=100))["when"]["below"], 100)

    def test_bad_percents_are_problems(self):
        for given in (0, 101, -5, "x", "", "12.5", True, 20.0):
            _, problems = A.validate(rule(below=given))
            self.assertTrue(any("when.below is a percent" in p for p in problems), (given, problems))

    def test_below_left_out_and_the_plug_events_take_no_option(self):
        self.assertEqual(tidy(rule())["when"], {"event": "battery-low"})
        for event in ("power-unplugged", "power-plugged"):
            self.assertEqual(tidy(rule(event=event))["when"], {"event": event})
            _, problems = A.validate(rule(event=event, below=20))
            self.assertIn(f"{event} has no option 'below' (it takes none)", problems)
        _, problems = A.validate(rule(event="power-unplugged") | {"when": {"event": "power-unplugged", "x": 1}})
        self.assertTrue(problems)

    def test_battery_saver_action_is_on_or_off(self):
        self.assertEqual(tidy(rule(do=[{"action": "battery-saver", "value": "OFF"}]))["do"],
                         [{"action": "battery-saver", "value": "off"}])
        for bad in ("auto", "", None, "maybe"):
            _, problems = A.validate(rule(do=[{"action": "battery-saver", "value": bad}]))
            self.assertTrue(problems, bad)

    def test_accepted_on_a_desktop_too(self):
        # A rules file copied from the laptop: it checks out, it just never fires.
        self.assertFalse(A.has_battery())
        self.assertEqual(A.validate(rule(below=10))[1], [])


class Words(unittest.TestCase):
    def test_described(self):
        self.assertEqual(A.describe(tidy(rule(below=15))),
                         "When the battery runs low at or under 15%: turn the battery saver on")
        self.assertEqual(A.describe_when({"event": "battery-low"}), "the battery runs low")
        self.assertEqual(A.describe_when({"event": "power-unplugged"}), "the charger is unplugged")
        self.assertEqual(A.describe_when({"event": "power-plugged"}), "the charger is plugged in")

    def test_one_word_joiners_are_unchanged(self):
        # The joiner may now be several words; the old single ones still read the same.
        self.assertEqual(A.describe_when({"event": "wifi-connected", "ssid": "home"}), "Wi-Fi connects to home")
        self.assertEqual(A.describe_when({"event": "monitor-added", "name": "DP-1"}),
                         "a screen matching DP-1 is connected")


class Matching(unittest.TestCase):
    def test_below_against_the_warnings_percent(self):
        r = tidy(rule(below=15))
        self.assertFalse(A.matches(r, "battery-low", {"percent": 20}))
        self.assertTrue(A.matches(r, "battery-low", {"percent": 15}))
        self.assertTrue(A.matches(r, "battery-low", {"percent": 5}))
        self.assertFalse(A.matches(r, "battery-low", {}))          # no percent: not for a "below" rule
        self.assertTrue(A.matches(tidy(rule()), "battery-low", {}))  # but for one without
        self.assertFalse(A.matches(r, "power-unplugged", {}))

    def test_plug_events(self):
        self.assertTrue(A.matches(tidy(rule(event="power-unplugged")), "power-unplugged", {}))
        self.assertFalse(A.matches(tidy(rule(event="power-unplugged")), "power-plugged", {}))


class OncePerDischarge(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.ran = []
        self.engine = A.Engine([], lambda r, e, f: self.ran.append((r["id"], e, f)), clock=self.clock)

    def emit(self, event, **facts):
        self.clock.t += 600         # warnings are minutes apart: past any cooldown and echo
        fired = self.engine.emit(event, **facts)
        for rid in fired:
            self.engine.finished(rid)
        return fired

    def test_first_warning_at_or_under_below_only(self):
        self.engine.set_rules([tidy(rule("at15", below=15)), tidy(rule("at20", below=20))])
        self.assertEqual(self.emit("battery-low", percent=20), ["at20"])
        self.assertEqual(self.emit("battery-low", percent=10), ["at15"])
        self.assertEqual(self.emit("battery-low", percent=5), [])

    def test_plugging_in_resets(self):
        self.engine.set_rules([tidy(rule("at15", below=15))])
        self.assertEqual(self.emit("battery-low", percent=10), ["at15"])
        self.assertEqual(self.emit("power-plugged"), [])
        self.assertEqual(self.emit("power-unplugged"), [])
        self.assertEqual(self.emit("battery-low", percent=5), ["at15"])

    def test_a_higher_warning_is_not_a_new_discharge(self):
        # warn_at gains 15 mid-discharge (10 warned): power-watch sends 15 -- no re-arm.
        self.engine.set_rules([tidy(rule("at12", below=12))])
        self.assertEqual(self.emit("battery-low", percent=20), [])
        self.assertEqual(self.emit("battery-low", percent=10), ["at12"])
        self.assertEqual(self.emit("battery-low", percent=15), [])
        self.assertEqual(self.emit("battery-low", percent=5), [])

    def test_unplugging_resets_after_a_missed_plug_in(self):
        # power-watch restarted while plugged in: no power-plugged, but the unplug comes.
        self.engine.set_rules([tidy(rule("at15", below=15))])
        self.assertEqual(self.emit("battery-low", percent=10), ["at15"])
        self.assertEqual(self.emit("power-unplugged"), [])
        self.assertEqual(self.emit("battery-low", percent=10), ["at15"])

    def test_the_unplugs_own_warning_may_come_first(self):
        # One check: power-unplugged and battery-low 20, two processes, either order.
        self.engine.set_rules([tidy(rule("at20", below=20))])
        self.assertEqual(self.emit("battery-low", percent=20), ["at20"])
        self.clock.t += 0.2
        self.assertEqual(self.engine.emit("power-unplugged"), [])
        self.assertEqual(self.engine.low_state(), {"fired": ["at20"], "last": 20})
        self.assertEqual(self.emit("battery-low", percent=10), [])

    def test_the_lowest_of_several_fires_every_level(self):
        # Resume at 4 %: power-watch sends only battery-low 5 for 20, 10 and 5.
        self.engine.set_rules([tidy(rule("at20", below=20)), tidy(rule("at5", below=5)),
                               tidy(rule("each"))])
        self.assertEqual(self.emit("battery-low", percent=5), ["at20", "at5", "each"])
        self.assertEqual(self.emit("battery-low", percent=5), ["each"])

    def test_without_below_every_warning(self):
        self.engine.set_rules([tidy(rule("each"))])
        self.assertEqual([self.emit("battery-low", percent=p) for p in (20, 10, 5)], [["each"]] * 3)

    def test_a_rule_held_back_by_its_cooldown_is_not_spent(self):
        self.engine.set_rules([tidy(rule("slow", below=20, cooldown=3600))])
        self.engine.last["slow"] = self.clock.t + 600        # "fired" just before the next emit
        self.assertEqual(self.emit("battery-low", percent=20), [])
        self.clock.t += 3600
        self.assertEqual(self.emit("battery-low", percent=10), ["slow"])

    def restarted(self, power):
        """A new Engine from what this one would leave in automations-state.json."""
        engine = A.Engine(self.engine.rules, lambda r, e, f: self.ran.append((r["id"], e, f)), clock=self.clock)
        engine.restore_low(self.engine.low_state(), power)
        self.engine = engine

    def test_a_restart_mid_discharge_does_not_fire_again(self):
        self.engine.set_rules([tidy(rule("at15", below=15))])
        self.assertEqual(self.emit("battery-low", percent=10), ["at15"])
        self.restarted({"on_battery": True, "warned": [20, 10]})
        self.assertEqual(self.emit("battery-low", percent=5), [])
        self.assertEqual(self.emit("power-unplugged"), [])           # restored marks are old ones
        self.assertEqual(self.emit("battery-low", percent=10), ["at15"])

    def test_a_restart_after_the_discharge_ended_starts_afresh(self):
        self.engine.set_rules([tidy(rule("at15", below=15))])
        self.emit("battery-low", percent=10)
        for power in ({"on_battery": False, "warned": [20, 10]},   # plugged in while down
                      {"on_battery": True, "warned": []},          # ...and out again
                      {"on_battery": True, "warned": [20]},        # a new discharge, not at 10 yet
                      {}, "junk"):
            self.restarted(power)
            self.assertEqual(self.engine.low_state(), {"fired": [], "last": None}, power)

    def test_restore_ignores_a_broken_state(self):
        for saved in (None, [], {"fired": "at15", "last": 10}, {"fired": ["at15"], "last": True},
                      {"fired": [3, "at15"], "last": "10"}):
            engine = A.Engine([], lambda *a: None)
            engine.restore_low(saved, {"on_battery": True, "warned": [10, 1]})
            self.assertTrue(engine.low_state()["fired"] in ([], ["at15"]), saved)
        engine = A.Engine([], lambda *a: None)
        engine.restore_low({"fired": [3, "at15"], "last": 10}, {"on_battery": True, "warned": [10]})
        self.assertEqual(engine.low_state(), {"fired": ["at15"], "last": 10})

    def test_percent_reaches_the_actions_environment(self):
        self.engine.set_rules([tidy(rule("at20", below=20))])
        self.emit("battery-low", percent=10)
        rid, event, facts = self.ran[-1]
        env = A.facts_env(tidy(rule("at20", below=20)), event, facts)
        self.assertEqual((env["AUTOMATION_EVENT"], env["AUTOMATION_PERCENT"]), ("battery-low", "10"))


class Pokes(unittest.TestCase):
    """power-watch.py -> `automations.py event NAME` (AUTOMATION_PERCENT in
    its environment) -> the poke's text -> Daemon.control -> the Engine."""

    def setUp(self):
        self.sent = []
        patcher = mock.patch.object(A, "poke", lambda msg: self.sent.append(msg) or True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def event(self, *args, percent=None):
        env = {k: v for k, v in os.environ.items() if k != "AUTOMATION_PERCENT"}
        if percent is not None:
            env["AUTOMATION_PERCENT"] = percent
        with mock.patch.dict(os.environ, env, clear=True):
            return A.main(["event", *args])

    def test_percent_from_the_environment_or_the_argument(self):
        self.assertEqual(self.event("battery-low", percent="20"), 0)
        self.assertEqual(self.event("battery-low", "10", percent="20"), 0)   # the argument wins
        self.assertEqual(self.event("battery-low"), 0)
        self.assertEqual(self.event("battery-low", percent="lots"), 0)
        self.assertEqual(self.sent, ["event battery-low 20", "event battery-low 10",
                                     "event battery-low", "event battery-low"])

    def test_plug_events_and_unknown_ones(self):
        self.assertEqual(self.event("power-unplugged"), 0)
        self.assertEqual(self.event("power-plugged"), 0)
        self.assertEqual(self.sent, ["event power-unplugged", "event power-plugged"])
        self.assertIn("power-unplugged", self.event("power-off"))   # the error lists them
        self.assertEqual(len(self.sent), 2)

    def test_power_watch_calls_it_this_way(self):
        # power-watch.py's own argv and environment for a warning, run here.
        pw = helpers.import_script("power-watch.py")
        calls = []
        watch = pw.Watch(spawn=lambda argv, env=None: calls.append((argv, env)), root=helpers.SCRATCH)
        watch.event("battery-low", percent=10)
        (argv, env), = calls
        self.assertEqual(os.path.basename(argv[1]), "automations.py")
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(A.main(argv[2:]), 0)
        self.assertEqual(self.sent, ["event battery-low 10"])

    def test_control_hands_the_percent_to_the_engine(self):
        got = []
        fake = types.SimpleNamespace(engine=types.SimpleNamespace(emit=lambda e, **f: got.append((e, f))),
                                     write_state=lambda: got.append("saved"))
        for msg in ("event battery-low 10", "event battery-low", "event battery-low 0",
                    "event power-unplugged", "event power-plugged"):
            A.Daemon.control(fake, msg)
        self.assertEqual(got, [("battery-low", {"percent": 10}), "saved", ("battery-low", {}), "saved",
                               ("battery-low", {}), "saved", ("power-unplugged", {}), "saved",
                               ("power-plugged", {}), "saved"])

    def test_the_daemon_saves_and_restores_the_memory(self):
        folder = tempfile.mkdtemp(dir=helpers.SCRATCH)
        state, power = os.path.join(folder, "automations-state.json"), os.path.join(folder, "power-state.json")
        # The fired rule's action must never run: its default is battery-saver
        # on, and the real script switches the live power profile (tuned-ppd
        # is on the system bus, which no scratch folder fences off). The
        # daemon's worker thread outlives any patch of do_actions, so the job
        # is never queued at all.
        with mock.patch.object(A, "STATE", state), \
                mock.patch.object(A.Daemon, "queue_job", lambda self, *job: None):
            d = A.Daemon()
            d.engine.set_rules([tidy(rule("at15", below=15))])
            d.engine.emit("battery-low", percent=10)
            d.write_state()
            with open(power, "w") as handle:
                handle.write('{"on_battery": true, "warned": [20, 10]}')
            again = A.Daemon()
            again.restore_low(power=power)
        self.assertEqual(again.engine.low_state(), {"fired": ["at15"], "last": 10})


class BatterySaverAction(unittest.TestCase):
    def test_argv_when_the_script_is_there(self):
        here = tempfile.mkdtemp(dir=helpers.SCRATCH)
        with mock.patch.object(A, "HERE", here):
            argv, why = A.action_argv({"action": "battery-saver", "value": "on"})
            self.assertIsNone(argv)
            self.assertIn("battery-saver.py is not there", why)
            open(os.path.join(here, "battery-saver.py"), "w").close()
            argv, how = A.action_argv({"action": "battery-saver", "value": "off"})
        self.assertEqual((argv[1:], how), ([os.path.join(here, "battery-saver.py"), "off"], "wait"))

    def test_a_rule_says_so_when_the_saver_takes_a_reason(self):
        here = tempfile.mkdtemp(dir=helpers.SCRATCH)
        path = os.path.join(here, "battery-saver.py")
        with open(path, "w") as handle:
            handle.write('REASONS = ("manual", "auto", "unplug", "rule")\n')
        with mock.patch.object(A, "HERE", here):
            argv, _ = A.action_argv({"action": "battery-saver", "value": "on"})
        self.assertEqual(argv[1:], [path, "on", "--why", "rule"])

    def test_the_real_saver_gets_what_it_accepts(self):
        # Whatever battery-saver.py ships now: "--why rule" only if it lists the reason.
        real = os.path.join(os.path.dirname(A.__file__), "battery-saver.py")
        if not os.path.exists(real):
            self.skipTest("no battery-saver.py yet")
        with open(real) as handle:
            takes = '"rule"' in handle.read().split("REASONS", 1)[-1].split("\n", 1)[0]
        self.assertEqual(A.saver_takes_reason(real), takes)


class Desktop(unittest.TestCase):
    """helpers.py's power_supply folder does not exist: a desktop PC."""

    def test_nothing_new_offered(self):
        cat = A.catalog()
        events = [e["event"] for e in cat["events"]]
        actions = [a["action"] for a in cat["actions"]]
        for name in A.POWER_EVENTS:
            self.assertNotIn(name, events)
        self.assertNotIn("battery-saver", actions)
        self.assertEqual(events, [e for e in A.EVENTS if e not in A.POWER_EVENTS])
        prompt = A.model_prompt("x")
        for word in ("battery", "charger", "below"):
            self.assertNotIn(word, prompt)
        doc = " ".join(A.doc_lines())
        self.assertNotIn("battery", doc)

    def test_builtin_rules_unchanged(self):
        self.assertEqual([b["id"] for b in A.BUILTIN], ["dnd-digest", "daily-brief", "end-of-day"])

    def test_power_state_missing_is_a_desktop(self):
        with mock.patch.dict("sys.modules", {"power_state": None}):    # import fails
            self.assertFalse(A.has_battery())
            self.assertNotIn("battery-low", A.offered(A.EVENTS))


class OnALaptop(Laptop, unittest.TestCase):
    def test_offered(self):
        self.assertTrue(A.has_battery())
        cat = A.catalog()
        low = next(e for e in cat["events"] if e["event"] == "battery-low")
        self.assertEqual((low["options"], low["required"], low["words"]),
                         (["below"], [], "the battery runs low"))
        self.assertIn("battery-saver", [a["action"] for a in cat["actions"]])
        self.assertEqual(len(cat["events"]), len(A.EVENTS))

    def test_the_model_is_told(self):
        prompt = A.model_prompt("when I unplug the laptop turn on the battery saver")
        for word in ("power-unplugged", "power-plugged", "battery-low (options: below)",
                     "below is a battery percent", "battery-saver (value: on|off)"):
            self.assertIn(word, prompt)

    def test_model_rule_checks_out(self):
        answer = ('{"name": "Saver at 15", "when": {"event": "battery-low", "below": 15}, '
                  '"do": [{"action": "battery-saver", "value": "on"}]}')
        r, why = A.from_text("x", ask=lambda prompt: answer)
        self.assertIsNone(why)
        self.assertEqual(r["when"], {"event": "battery-low", "below": 15})

    def test_doc_lines_name_them(self):
        doc = " ".join(A.doc_lines())
        self.assertIn("battery-low (below)", doc)
        self.assertIn("battery-saver on|off", doc)


class SettingsPage(Laptop, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from settings_pages import automations as page
        cls.page = page

    def test_picked_battery_rule_checks_out(self):
        r = self.page.picked_rule("", "battery-low", "below", " 20 ", "battery-saver", "on")
        self.assertEqual(r["when"], {"event": "battery-low", "below": "20"})
        self.assertEqual(tidy(r)["when"]["below"], 20)
        r = self.page.picked_rule("Unplugged", "power-unplugged", None, "", "battery-saver", "on")
        self.assertEqual(A.validate(r)[1], [])

    def test_labels_and_hints(self):
        labels = {e["event"]: self.page.event_label(e) for e in A.catalog()["events"]}
        self.assertEqual(labels["battery-low"], "the battery runs low")
        self.assertEqual(labels["power-unplugged"], "the charger is unplugged")
        self.assertEqual(labels["app-open"], "[app] opens")          # as before
        self.assertEqual(labels["time"], "it is [time]")
        self.assertIn("percent", self.page.OPTION_HINTS["below"])
        self.assertIn("battery-saver", self.page.ACTION_HINTS)

    def test_found_by_search(self):
        from settings_pages import _catalog
        pages = _catalog.read_pages()
        for words in ("unplugged", "charger", "low battery"):
            self.assertIn("automations", [p["id"] for p in _catalog.search(pages, words)], words)


if __name__ == "__main__":
    unittest.main()
