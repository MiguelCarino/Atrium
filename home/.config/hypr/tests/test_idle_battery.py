"""idle-settings.py on a laptop: the laptop defaults (`laptop-defaults`, and
`init` on the first run, which must never undo a choice), the shorter
timings on battery (listeners that run `battery-idle`, which acts only
while power_state.on_battery()), and the Power page's battery helpers.

Nothing here touches the live desktop: hypridle.conf, the record and the
flags are in scratch folders (helpers.py), every systemctl call goes to a
stub, and battery-idle's exec is replaced by a list. The power supplies are
fake trees (helpers.fake_power_supply); with none, power_state sees a
desktop."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import helpers

idle = helpers.import_script("idle-settings.py")
import power_state  # noqa: E402  (scripts/ is on sys.path via helpers)

# The repo's shipped hypridle.conf: everything "never", lock before sleep on.
SHIPPED = os.path.join(os.path.dirname(helpers.SCRIPTS), "hypridle.conf")
BARE = "general {\n    lock_cmd = pidof hyprlock || hyprlock\n}\n"


class Scratch(unittest.TestCase):
    """A scratch hypridle.conf / state / runtime, a stubbed run(), and a
    power-supply folder: a laptop on battery, a laptop on the charger, or
    (the default) none at all."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(dir=helpers.SCRATCH)
        self.addCleanup(shutil.rmtree, self.dir, True)
        state = os.path.join(self.dir, "state")
        patches = {"CONF": os.path.join(self.dir, "hypridle.conf"), "STATE": state,
                   "PREV": os.path.join(state, "hypridle.conf.prev"),
                   "RECORD": os.path.join(state, "idle-settings.json"),
                   "WELCOME_DONE": os.path.join(state, "welcome-done"),
                   "BATTERY_FLAGS": os.path.join(self.dir, "run", "idle-battery")}
        for name, value in patches.items():
            p = mock.patch.object(idle, name, value)
            p.start()
            self.addCleanup(p.stop)
        self.calls = []
        p = mock.patch.object(idle, "run", lambda *cmd, timeout=5: self.calls.append(cmd) or "")
        p.start()
        self.addCleanup(p.stop)
        self.supply = os.path.join(self.dir, "power_supply")
        p = mock.patch.dict(os.environ, {"ATRIUM_POWER_SUPPLY": self.supply})
        p.start()
        self.addCleanup(p.stop)
        power_state.reset_cache()

    def laptop(self, on_battery=True):
        helpers.fake_power_supply(self.supply, battery={"status": "Discharging" if on_battery else "Charging"},
                                  ac=not on_battery)

    def desktop_with_mouse(self):
        helpers.fake_power_supply(self.supply, extra={"hidpp_battery_0": {
            "type": "Battery", "scope": "Device", "status": "Discharging", "capacity": 50}})

    def write(self, text):
        with open(idle.CONF, "w") as handle:
            handle.write(text)

    def read(self):
        with open(idle.CONF) as handle:
            return handle.read()


# ------------------------------ the laptop defaults ------------------------------

class LaptopDefaults(unittest.TestCase):
    def test_the_values(self):
        self.assertEqual(idle.LAPTOP, {"dim": 120, "lock": 300, "screens_off": 600, "suspend": 1800,
                                       "lock_before_sleep": True})

    def test_pairs_give_exactly_them(self):
        v = idle.apply_changes(idle.DEFAULTS, idle.laptop_pairs())
        for key, value in idle.LAPTOP.items():
            self.assertEqual(v[key], value, key)
        # The rest is left as it was.
        self.assertEqual((v["grace"], v["off_after_lock"], v["battery_dim"]), (0, 0, 0))

    def test_they_round_trip_and_raise_nothing(self):
        parsed = idle.parse(BARE)
        v = idle.apply_changes(idle.values_from(parsed), idle.laptop_pairs())
        again = idle.values_from(idle.parse(idle.render(v, parsed)))
        self.assertEqual(again, v)
        self.assertEqual(idle.problems(v), [])

    def test_they_do_not_unlink_a_moving_screens_off(self):
        # 600 + 30 = 630 follows the lock; the defaults set screens_off
        # themselves, so 600 it is, not 300 + 30.
        v = dict(idle.DEFAULTS, lock=600, off_after_lock=30, screens_off=630)
        self.assertEqual(idle.apply_changes(v, idle.laptop_pairs())["screens_off"], 600)


class Init(Scratch):
    def test_fresh_laptop_gets_the_defaults(self):
        self.laptop()
        with open(SHIPPED) as handle:
            self.write(handle.read())
        out = idle.init()
        self.assertEqual(out["init"], "laptop")
        v = idle.values_from(idle.parse(self.read()))
        for key, value in idle.LAPTOP.items():
            self.assertEqual(v[key], value, key)
        # Never "restart": install.sh may run in GNOME, where that would
        # start hypridle.
        self.assertIn(("systemctl", "--user", "try-restart", "hypridle.service"), self.calls)
        self.assertNotIn(("systemctl", "--user", "restart", "hypridle.service"), self.calls)
        # The listeners of other scripts are kept.
        self.assertIn("presence-idle on", self.read())
        self.assertIn("automations.py event idle-start", self.read())

    def test_no_file_at_all_is_fresh_too(self):
        self.laptop(on_battery=False)
        self.assertEqual(idle.init()["init"], "laptop")
        self.assertEqual(idle.values_from(idle.parse(self.read()))["lock"], 300)

    def test_runs_once(self):
        self.laptop()
        self.assertEqual(idle.init()["init"], "laptop")
        self.write(BARE)                    # the user sets it all back to never by hand
        self.assertEqual(idle.init()["init"], "already")
        self.assertEqual(self.read(), BARE)

    def test_desktop_sees_no_change(self):
        for setup in (lambda: None, self.desktop_with_mouse):
            setup()
            with open(SHIPPED) as handle:
                self.write(handle.read())
            before = self.read()
            self.assertEqual(idle.init()["init"], "desktop")
            self.assertEqual(self.read(), before)
            self.assertEqual(self.calls, [])
            os.remove(idle.RECORD)

    def test_used_machine_keeps_never(self):
        """This laptop's own case: never/never/never/never, set by nobody
        through `set`, but the first login happened long ago."""
        self.laptop()
        with open(SHIPPED) as handle:
            self.write(handle.read())
        before = self.read()
        os.makedirs(idle.STATE, exist_ok=True)
        open(idle.WELCOME_DONE, "w").close()
        out = idle.init()
        self.assertEqual(out["init"], "kept")
        self.assertEqual(self.read(), before)
        self.assertEqual(self.calls, [])
        # ...and decided for good: no later run changes it either.
        os.remove(idle.WELCOME_DONE)
        self.assertEqual(idle.init()["init"], "already")
        self.assertEqual(self.read(), before)

    def test_desktop_is_not_final(self):
        """No battery seen once (a VM, a driver not bound yet) does not make
        a laptop a desktop for good."""
        with open(SHIPPED) as handle:
            self.write(handle.read())
        self.assertEqual(idle.init()["init"], "desktop")
        self.laptop()
        self.assertEqual(idle.init()["init"], "laptop")

    def test_page_used_before_keeps_never(self):
        """No welcome marker, no record, but the page has written the file:
        "never" may be meant."""
        self.laptop()
        with open(SHIPPED) as handle:
            self.write(handle.read())
        before = self.read()
        os.makedirs(idle.STATE, exist_ok=True)
        with open(idle.PREV, "w") as handle:
            handle.write(BARE)
        self.assertEqual(idle.init()["init"], "kept")
        self.assertEqual(self.read(), before)

    def test_update_overwrite_is_put_back(self):
        """install.sh copies the shipped file over the laptop timings on every
        update; the next init puts them back."""
        self.laptop()
        with open(SHIPPED) as handle:
            shipped = handle.read()
        self.write(shipped)
        self.assertEqual(idle.init()["init"], "laptop")
        self.write(shipped)                                             # the update
        self.calls.clear()
        out = idle.init()
        self.assertEqual(out["init"], "restored")
        v = idle.values_from(idle.parse(self.read()))
        self.assertEqual((v["dim"], v["lock"], v["screens_off"], v["suspend"]), (120, 300, 600, 1800))
        self.assertEqual(self.calls, [("systemctl", "--user", "try-restart", "hypridle.service")])
        self.assertIn("presence-idle on", self.read())                  # the shipped companions stay
        self.assertEqual(idle.init()["init"], "already")                # and once is enough

    def test_update_overwrite_of_a_choice_is_put_back(self):
        """The same for timings chosen with `set`, battery ones included, on
        a desktop too."""
        with open(SHIPPED) as handle:
            shipped = handle.read()
        self.write(shipped)
        with mock.patch.object(sys, "argv", ["idle-settings.py", "set", "lock", "45", "battery_dim", "1"]), \
                mock.patch("builtins.print"):
            idle.main()
        self.write(shipped)
        self.assertEqual(idle.init()["init"], "restored")
        v = idle.values_from(idle.parse(self.read()))
        self.assertEqual((v["lock"], v["battery_dim"]), (2700, 60))

    def test_chosen_never_is_not_put_back(self):
        self.laptop()
        with open(SHIPPED) as handle:
            shipped = handle.read()
        self.write(shipped)
        idle.init()
        with mock.patch.object(sys, "argv", ["idle-settings.py", "set", "dim", "never", "lock", "never",
                                             "screens_off", "never", "suspend", "never"]), \
                mock.patch("builtins.print"):
            idle.main()
        self.write(shipped)
        self.assertEqual(idle.init()["init"], "already")
        self.assertEqual(self.read(), shipped)

    def test_hand_edit_to_never_is_kept(self):
        """Listeners deleted by hand from a written file: the "# Now:" line
        no longer matches, so it is a choice, not the shipped copy."""
        self.laptop()
        idle.init()
        text = self.read()
        parsed = idle.parse(text)
        edited = "\n".join(line for lst in parsed["listeners"] if not lst["kind"] for line in lst["raw"])
        edited = text[:text.index("listener")] + edited + "\n"
        self.write(edited)
        self.assertEqual(idle.values_from(idle.parse(edited))["lock"], 0)
        self.assertEqual(idle.init()["init"], "already")
        self.assertEqual(self.read(), edited)

    def test_own_timings_are_kept(self):
        self.laptop()
        own = idle.render(idle.apply_changes(idle.DEFAULTS, ["lock", "45"]), idle.parse(BARE))
        self.write(own)
        self.assertEqual(idle.init()["init"], "kept")
        self.assertEqual(self.read(), own)

    def test_a_set_is_final(self):
        self.laptop()
        idle.write_record(chosen_at=1)
        self.write(BARE)
        self.assertEqual(idle.init()["init"], "already")
        self.assertEqual(self.read(), BARE)

    def test_cli_set_records_the_choice(self):
        self.laptop()
        self.write(BARE)
        with mock.patch.object(sys, "argv", ["idle-settings.py", "set", "lock", "never"]), \
                mock.patch("builtins.print"):
            idle.main()
        self.assertTrue(idle.read_record().get("chosen_at"))
        self.assertEqual(idle.init()["init"], "already")
        self.assertEqual(idle.values_from(idle.parse(self.read()))["lock"], 0)

    def test_bare_set_is_not_a_choice(self):
        """Settings > Screen time runs a bare `set` to add its listener."""
        self.write(BARE)
        with mock.patch.object(sys, "argv", ["idle-settings.py", "set"]), mock.patch("builtins.print"):
            idle.main()
        self.assertEqual(idle.read_record(), {})
        self.assertIn("screentime-idle on", self.read())

    def test_cli_laptop_defaults(self):
        self.write(BARE)                    # works on a desktop too, when asked for
        with mock.patch.object(sys, "argv", ["idle-settings.py", "laptop-defaults"]), \
                mock.patch("builtins.print"):
            idle.main()
        v = idle.values_from(idle.parse(self.read()))
        self.assertEqual((v["dim"], v["lock"], v["screens_off"], v["suspend"]), (120, 300, 600, 1800))
        self.assertIn(("systemctl", "--user", "restart", "hypridle.service"), self.calls)
        self.assertTrue(idle.read_record().get("chosen_at"))

    def test_bad_set_writes_nothing(self):
        self.write(BARE)
        with mock.patch.object(sys, "argv", ["idle-settings.py", "set", "battery_dim", "soon"]):
            with self.assertRaises(SystemExit):
                idle.main()
        self.assertEqual(self.read(), BARE)
        self.assertEqual(idle.read_record(), {})


# ------------------------------ the battery timings ------------------------------

class BatteryListeners(unittest.TestCase):
    def render(self, pairs, base=BARE):
        parsed = idle.parse(base)
        v = idle.apply_changes(idle.values_from(parsed), pairs)
        return v, idle.render(v, parsed)

    def test_never_is_no_listener(self):
        _v, text = self.render(idle.laptop_pairs())
        self.assertNotIn("battery-idle", text)

    def test_round_trip(self):
        v, text = self.render(idle.laptop_pairs() + ["battery_dim", "1", "battery_screens_off", "3",
                                                     "battery_suspend", "10", "password_on_wake", "on"])
        self.assertEqual(idle.values_from(idle.parse(text)), v)
        kinds = [lst["kind"] for lst in idle.parse(text)["listeners"] if lst["kind"]]
        self.assertEqual(kinds, ["battery_dim", "dim", "battery_screens_off", "lock", "screens_off",
                                 "battery_suspend", "suspend"])           # in time order

    def test_commands(self):
        _v, text = self.render(["dim_level", "30", "battery_dim", "1", "battery_screens_off", "2",
                                "battery_suspend", "5", "password_on_wake", "on"])
        self.assertIn("on-timeout = python3 ~/.config/hypr/scripts/idle-settings.py battery-idle dim 30", text)
        self.assertIn("battery-idle screens_off lock\n", text)
        self.assertIn("on-resume = python3 ~/.config/hypr/scripts/idle-settings.py battery-idle screens_off resume",
                      text)
        self.assertIn("battery-idle suspend\n", text)
        # hyprlang would take $ for a variable and # for a comment.
        for line in text.splitlines():
            if not line.strip().startswith("#"):
                self.assertNotIn("$", line)
                self.assertNotIn("#", line)

    def test_battery_only_dim_and_lock_read_back(self):
        """A laptop that dims and turns off only on battery: the dim level and
        "ask for the password" live in the battery listeners then."""
        v, text = self.render(["dim_level", "60", "battery_dim", "2", "battery_screens_off", "5",
                               "password_on_wake", "on"])
        again = idle.values_from(idle.parse(text))
        self.assertEqual((again["dim_level"], again["password_on_wake"]), (60, True))
        self.assertEqual(again, v)

    def test_shared_screens_off_when_both_exist(self):
        v, text = self.render(idle.laptop_pairs() + ["battery_screens_off", "2"])
        self.assertIn("battery-idle screens_off always\n", text)
        self.assertEqual(text.count("battery-idle screens_off resume"), 2)
        self.assertNotIn("on-resume = hyprctl", text)                      # no unguarded dpms-on
        kinds = [lst["kind"] for lst in idle.parse(text)["listeners"] if lst["kind"]]
        self.assertEqual(kinds.count("screens_off"), 1)
        self.assertEqual(idle.values_from(idle.parse(text)), v)
        # With "ask for the password" too.
        v, text = self.render(idle.laptop_pairs() + ["battery_screens_off", "2", "password_on_wake", "on"])
        self.assertIn("battery-idle screens_off always lock\n", text)
        self.assertEqual(idle.values_from(idle.parse(text)), v)
        # Without a battery one, the charger's is as before.
        _v, text = self.render(idle.laptop_pairs())
        self.assertIn("on-resume = " + idle.DPMS_ON, text)

    def test_prelock_before_the_idle_lock(self):
        v, text = self.render(idle.laptop_pairs() + ["battery_screens_off", "2"])
        self.assertIn("battery-idle screens_off prelock\n", text)
        again = idle.values_from(idle.parse(text))
        self.assertFalse(again["password_on_wake"])
        self.assertEqual(again, v)
        self.assertEqual(idle.problems(v), [])
        # Only the battery one: still not "ask for the password".
        v, text = self.render(["lock", "5", "battery_screens_off", "2"])
        self.assertIn("prelock", text)
        self.assertEqual(idle.values_from(idle.parse(text)), v)
        # After the lock, or with no idle lock at all: no lock first.
        for pairs in (["lock", "1", "battery_screens_off", "2"], ["battery_screens_off", "2"]):
            _v, text = self.render(pairs)
            self.assertIn("battery-idle screens_off\n", text)

    def test_not_mistaken_for_the_plugged_in_ones(self):
        text = ("listener {\n    timeout = 60\n"
                "    on-timeout = python3 ~/.config/hypr/scripts/idle-settings.py battery-idle dim 40\n}\n"
                "listener {\n    timeout = 90\n"
                "    on-timeout = python3 ~/.config/hypr/scripts/idle-settings.py battery-idle screens_off lock\n}\n"
                "listener {\n    timeout = 99\n"
                "    on-timeout = python3 ~/.config/hypr/scripts/idle-settings.py battery-idle suspend\n}\n")
        kinds = [lst["kind"] for lst in idle.parse(text)["listeners"]]
        self.assertEqual(kinds, ["battery_dim", "battery_screens_off", "battery_suspend"])
        v = idle.values_from(idle.parse(text))
        self.assertEqual((v["dim"], v["lock"], v["screens_off"], v["suspend"]), (0, 0, 0, 0))

    def test_shipped_file_is_valid_and_all_never(self):
        with open(SHIPPED) as handle:
            parsed = idle.parse(handle.read())
        v = idle.values_from(parsed)
        for key in ("dim", "lock", "screens_off", "suspend") + tuple(idle.BATTERY):
            self.assertEqual(v[key], 0, key)
        self.assertEqual(idle.values_from(idle.parse(idle.render(v, parsed))), v)

    def test_summary(self):
        v = dict(idle.DEFAULTS, battery_screens_off=120)
        self.assertIn("on battery screens off 2 min", idle.summary(v))
        self.assertNotIn("on battery", idle.summary(idle.DEFAULTS))


class BatteryTimes(unittest.TestCase):
    def test_on_battery_times(self):
        v = dict(idle.DEFAULTS, dim=120, screens_off=600, battery_dim=60, battery_suspend=900)
        self.assertEqual(idle.on_battery_times(v), {"dim": 60, "screens_off": 600, "suspend": 900})
        # Longer than plugged in: the plugged-in one fires first anyway.
        v = dict(idle.DEFAULTS, dim=120, battery_dim=300)
        self.assertEqual(idle.on_battery_times(v)["dim"], 120)


class BatteryProblems(unittest.TestCase):
    def test_none_without_battery_timings(self):
        v = idle.apply_changes(idle.DEFAULTS, idle.laptop_pairs())
        self.assertEqual(idle.problems(v, has_battery=False), [])

    def test_no_battery(self):
        v = dict(idle.DEFAULTS, battery_dim=60)
        self.assertTrue(any("no battery" in p for p in idle.problems(v, has_battery=False)))
        self.assertFalse(any("no battery" in p for p in idle.problems(v)))

    def test_not_sooner(self):
        v = dict(idle.DEFAULTS, dim=120, battery_dim=300)
        self.assertTrue(any("changes nothing" in p for p in idle.problems(v)))

    def test_battery_suspend_without_lock(self):
        v = dict(idle.DEFAULTS, battery_suspend=600)
        self.assertTrue(any("on battery the computer sleeps" in p for p in idle.problems(v)))
        v["lock_before_sleep"] = True
        self.assertEqual(idle.problems(v), [])
        # Said once, not twice, when the plugged-in suspend already says it.
        v = dict(idle.DEFAULTS, suspend=1800, battery_suspend=600)
        self.assertEqual(sum("without locking" in p for p in idle.problems(v)), 1)

    def test_battery_screens_off_unlocked(self):
        # No idle lock at all: nothing locks before the battery screens-off.
        v = dict(idle.DEFAULTS, battery_screens_off=120)
        self.assertTrue(any("on battery the screens go off without a lock" in p for p in idle.problems(v)))
        v["password_on_wake"] = True
        self.assertFalse(any("without a lock" in p for p in idle.problems(v)))

    def test_sooner_than_the_lock_is_not_unlocked(self):
        """Sooner than the idle lock, it locks first (prelock): no warning."""
        v = dict(idle.DEFAULTS, lock=600, battery_screens_off=120)
        self.assertFalse(any("without a lock" in p for p in idle.problems(v)))

    def test_password_on_wake_with_battery_screens_off_only(self):
        v = dict(idle.DEFAULTS, password_on_wake=True, battery_screens_off=120)
        self.assertFalse(any("needs \"Turn the screens off\"" in p for p in idle.problems(v)))

    def test_battery_dim_after_screens_off(self):
        v = dict(idle.DEFAULTS, lock=60, screens_off=120, battery_dim=300, dim=600)
        self.assertTrue(any("on battery the screens turn off before they would dim" in p
                            for p in idle.problems(v)))


class BatteryIdle(Scratch):
    def act(self, *args, on=True):
        ran = []
        out = idle.battery_idle(list(args), on_battery=lambda: on, execute=ran.append)
        self.assertEqual(ran, [out] if out else [])
        return out

    def test_on_the_charger_nothing(self):
        for args in (["dim", "40"], ["screens_off"], ["screens_off", "lock"], ["suspend"]):
            self.assertIsNone(self.act(*args, on=False), args)
        self.assertFalse(os.path.exists(os.path.join(idle.BATTERY_FLAGS, "screens_off")))

    def test_on_battery(self):
        self.assertEqual(self.act("dim", "30"), "~/.config/hypr/scripts/screen-color.py dim 30")
        self.assertEqual(self.act("dim", "1"), "~/.config/hypr/scripts/screen-color.py dim 10")   # clamped
        self.assertEqual(self.act("suspend"), "systemctl suspend")
        self.assertEqual(self.act("screens_off"), idle.DPMS_OFF)
        os.remove(os.path.join(idle.BATTERY_FLAGS, "screens_off"))        # as a resume would
        self.assertEqual(self.act("screens_off", "lock"), "loginctl lock-session; sleep 1; " + idle.DPMS_OFF)
        os.remove(os.path.join(idle.BATTERY_FLAGS, "screens_off"))
        self.assertEqual(self.act("screens_off", "prelock"), "loginctl lock-session; sleep 1; " + idle.DPMS_OFF)

    def age_tombstone(self):
        tomb = os.path.join(idle.BATTERY_FLAGS, "resumed")
        if os.path.exists(tomb):
            old = os.path.getmtime(tomb) - idle.RACE - 60
            os.utime(tomb, (old, old))

    def test_resume_only_after_it_turned_them_off(self):
        self.assertIsNone(self.act("screens_off", "resume"))
        self.age_tombstone()                                       # an earlier idle stretch
        self.act("screens_off")
        # Plugged in while the screens were off: they still come back on.
        self.assertEqual(self.act("screens_off", "resume", on=False), idle.DPMS_ON)
        self.assertIsNone(self.act("screens_off", "resume"))      # once

    def test_resume_racing_the_timeout(self):
        """Input just as the timeout fires: hypridle's on-resume runs before
        the on-timeout's Python has started. The timeout must then do
        nothing -- no dpms-off under an active user, no stale flag."""
        self.assertIsNone(self.act("screens_off", "resume"))
        self.assertIsNone(self.act("screens_off", "lock"))
        # The tombstone is used up: the next timeout is one of its own.
        self.assertEqual(self.act("screens_off", "always"), idle.DPMS_OFF)

    def test_race_leaves_nothing_behind(self):
        self.assertIsNone(self.act("screens_off", "resume"))
        self.assertIsNone(self.act("screens_off"))
        self.assertFalse(os.path.exists(os.path.join(idle.BATTERY_FLAGS, "screens_off")))
        self.assertFalse(os.path.exists(os.path.join(idle.BATTERY_FLAGS, "resumed")))
        # The next stretch's resume has nothing to undo: no unguarded dpms-on.
        self.assertIsNone(self.act("screens_off", "resume"))

    def test_both_listeners_one_dpms_on(self):
        """On battery past both the battery and the charger screens-off: one
        flag, one dpms-off, and exactly one dpms-on from the two resumes."""
        self.assertEqual(self.act("screens_off"), idle.DPMS_OFF)
        self.assertIsNone(self.act("screens_off", "always"))             # already off
        self.assertEqual(self.act("screens_off", "always", "lock"), "loginctl lock-session")
        resumes = [self.act("screens_off", "resume"), self.act("screens_off", "resume")]
        self.assertEqual(resumes.count(idle.DPMS_ON), 1)
        self.assertEqual(resumes.count(None), 1)

    def test_always_acts_on_the_charger(self):
        self.assertEqual(self.act("screens_off", "always", on=False), idle.DPMS_OFF)
        self.assertEqual(self.act("screens_off", "resume", on=False), idle.DPMS_ON)

    def test_stale_flag_of_an_earlier_hypridle(self):
        with mock.patch.object(idle, "hypridle_pid", lambda: 111):
            self.act("screens_off")
        with open(os.path.join(idle.BATTERY_FLAGS, "screens_off")) as handle:
            self.assertEqual(handle.read(), "111")
        with mock.patch.object(idle, "hypridle_pid", lambda: 222):          # restarted since
            self.assertIsNone(self.act("screens_off", "resume"))
            self.assertFalse(os.path.exists(os.path.join(idle.BATTERY_FLAGS, "screens_off")))
            self.age_tombstone()
            # ...and a stale flag does not count as "already off" either.
            with mock.patch.object(idle, "hypridle_pid", lambda: 111):
                self.act("screens_off")
            self.assertEqual(self.act("screens_off", "always"), idle.DPMS_OFF)
            self.assertEqual(self.act("screens_off", "resume"), idle.DPMS_ON)

    def test_lock_held_through_the_command(self):
        """The dpms command runs with the flag lock held (inherited through
        exec), so a racing resume waits for it."""
        held = []

        def execute(cmd):
            with open(os.path.join(idle.BATTERY_FLAGS, "lock"), "w") as other:
                try:
                    import fcntl
                    fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    held.append(False)
                except BlockingIOError:
                    held.append(True)
        idle.battery_idle(["screens_off"], on_battery=lambda: True, execute=execute)
        self.assertEqual(held, [True])

    def test_hypridle_pid_outside_hypridle(self):
        self.assertIsNone(idle.hypridle_pid())

    def test_bad_word(self):
        with self.assertRaises(ValueError):
            idle.battery_idle(["lock"], on_battery=lambda: True, execute=lambda c: None)

    def test_real_power_state(self):
        """The default ON_BATTERY is power_state's, reading the fake tree."""
        ran = []
        self.assertIsNone(idle.battery_idle(["suspend"], execute=ran.append))          # no supplies: a desktop
        self.desktop_with_mouse()
        self.assertIsNone(idle.battery_idle(["suspend"], execute=ran.append))          # a mouse is not a laptop
        self.laptop(on_battery=False)
        self.assertIsNone(idle.battery_idle(["suspend"], execute=ran.append))
        self.laptop(on_battery=True)
        self.assertEqual(idle.battery_idle(["suspend"], execute=ran.append), "systemctl suspend")
        self.assertEqual(ran, ["systemctl suspend"])

    def test_cli_on_a_desktop_does_nothing(self):
        """The command hypridle runs, as a process: no supplies (helpers.py's
        missing folder), so it exits at once without running anything."""
        env = dict(os.environ, ATRIUM_POWER_SUPPLY=os.path.join(self.dir, "none"),
                   XDG_RUNTIME_DIR=os.path.join(self.dir, "run"), PATH="/nonexistent")
        out = subprocess.run([sys.executable, os.path.join(helpers.SCRIPTS, "idle-settings.py"),
                              "battery-idle", "screens_off", "lock"],
                             capture_output=True, text=True, timeout=20, env=env)
        self.assertEqual((out.returncode, out.stdout, out.stderr), (0, "", ""))


class Status(Scratch):
    def test_power_section(self):
        self.write(BARE)
        self.laptop()
        data = idle.status()
        self.assertEqual(data["power"]["has_battery"], True)
        self.assertEqual(data["power"]["on_battery"], True)
        self.assertEqual(data["power"]["on_battery_times"], {"dim": 0, "screens_off": 0, "suspend": 0})
        self.assertEqual(data["laptop_defaults"], idle.LAPTOP)
        self.assertIn("battery_dim", data["values"])
        json.dumps(data)                                  # what `status` prints

    def test_desktop(self):
        self.write(BARE)
        data = idle.status()
        self.assertEqual(data["power"], {"has_battery": False, "on_battery": False, "on_battery_times": None})
        for key in ("values", "problems", "kept", "hypridle", "dim_ready", "awake", "holders", "profile",
                    "logind", "conf"):
            self.assertIn(key, data)                      # the keys the page already reads


# ---------------------------------- the page ----------------------------------

class Page(unittest.TestCase):
    def setUp(self):
        try:
            from settings_pages import common  # noqa: F401  (Gtk 3 first, as settings.py does)
            from settings_pages import power
        except Exception as exc:                         # noqa: BLE001
            self.skipTest(f"settings_pages.power not importable: {exc}")
        self.power = power

    def test_keywords(self):
        for word in ("idle", "lock", "suspend", "battery", "laptop defaults"):
            self.assertIn(word, self.power.PAGE["keywords"])

    def test_battery_rows(self):
        self.assertEqual([k for k, *_ in self.power.BATTERY_TIMINGS], list(idle.BATTERY))
        for key, same, *_ in self.power.BATTERY_TIMINGS:
            self.assertEqual(idle.BATTERY[key], same)

    def test_battery_sub(self):
        self.assertEqual(self.power.battery_sub(0, 600), "as when plugged in: 10 min")
        self.assertEqual(self.power.battery_sub(0, 0), "as when plugged in: never")
        self.assertEqual(self.power.battery_sub(120, 600), "after 2 min on battery, 10 min plugged in")
        self.assertIn("changes nothing", self.power.battery_sub(900, 600))

    def test_battery_section_only_on_a_laptop(self):
        """The page built and drawn from a status (no window shown): ON
        BATTERY and the defaults button on a laptop, neither on a desktop."""
        data = {"values": dict(idle.DEFAULTS, battery_dim=60), "problems": [], "kept": [],
                "hypridle": {"state": "active", "since": "now", "ignores_systemd_inhibit": False},
                "dim_ready": True, "awake": {"on": False, "until": None, "minutes": None}, "holders": [],
                "profile": {"active": None, "profiles": [], "degraded": ""}, "logind": {},
                "conf": "/x/hypridle.conf", "laptop_defaults": idle.LAPTOP,
                "power": {"has_battery": True, "on_battery": False}}
        with mock.patch.object(self.power, "background", lambda work, done: None):
            try:
                page = self.power.Page()
            except Exception as exc:                     # noqa: BLE001  (no display to build widgets on)
                self.skipTest(f"no GTK display: {exc}")
            page.show(data)
            self.assertTrue(page.battery.get_visible() and page.laptop.get_visible())
            self.assertTrue(all(c.get_visible() for c in page.battery.get_children() + page.laptop.get_children()))
            self.assertEqual(page.subs["battery_dim"].get_text(), "after 1 min on battery, never plugged in")
            self.assertTrue(page.dim_level.widget.get_visible())
            page.show(dict(data, power={"has_battery": False, "on_battery": False}))
            self.assertFalse(page.battery.get_visible() or page.laptop.get_visible())
            page.show({k: v for k, v in data.items() if k != "power"})    # an older idle-settings.py
            self.assertFalse(page.battery.get_visible())

    def test_hidden_before_the_first_status(self):
        """A desktop must see no change: before status answers (or when it
        never does), the window's show_all() leaves both hidden."""
        with mock.patch.object(self.power, "background", lambda work, done: None):
            try:
                page = self.power.Page()
            except Exception as exc:                     # noqa: BLE001
                self.skipTest(f"no GTK display: {exc}")
            page.widget.show_all()
            self.assertFalse(page.battery.get_visible() or page.laptop.get_visible())
            page.show(None)                                                # did not answer
            page.widget.show_all()
            self.assertFalse(page.battery.get_visible() or page.laptop.get_visible())

    def test_laptop_text(self):
        v = idle.apply_changes(idle.DEFAULTS, idle.laptop_pairs())
        self.assertEqual(self.power.laptop_text(idle.LAPTOP, v),
                         "Laptop defaults are what is set: dim 2 min, lock 5 min, screens off 10 min, "
                         "suspend 30 min, lock before sleep.")
        self.assertTrue(self.power.laptop_text(idle.LAPTOP, idle.DEFAULTS, True).startswith(
            "Laptop defaults (on battery now): "))


if __name__ == "__main__":
    unittest.main()
