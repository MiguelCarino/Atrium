"""idle-settings.py (Settings > Power & screen lock): reading hypridle.conf,
writing it back from the template, and the small parsers. Pure functions
only: no file is written, hypridle is never restarted."""
import unittest

import helpers

idle = helpers.import_script("idle-settings.py")

# The hand-written hypridle.conf this machine had before idle-settings.py,
# trimmed, plus a listener of the user's own that must survive a write.
HAND = """\
# header comment
general {
    lock_cmd = pidof hyprlock || hyprlock
    before_sleep_cmd = loginctl lock-session
    after_sleep_cmd = hyprctl dispatch 'hl.dsp.dpms({ on = true })'
    ignore_dbus_inhibit = false
}

# 10 min: lock.
listener {
    timeout = 600
    on-timeout = pidof hyprlock || hyprlock --grace 3
}

# Displays off once locked.
listener {
    timeout = 30
    on-timeout = pidof hyprlock && hyprctl dispatch 'hl.dsp.dpms({ on = false })'
    on-resume = pidof hyprlock && hyprctl dispatch 'hl.dsp.dpms({ on = true })'
}

listener {
    timeout = 630
    on-timeout = hyprctl dispatch 'hl.dsp.dpms({ on = false })'
    on-resume = hyprctl dispatch 'hl.dsp.dpms({ on = true })'
}

# my own: pause music after 20 min
listener {
    timeout = 1200
    on-timeout = playerctl pause
}
"""


class Reading(unittest.TestCase):
    def test_hand_written_file(self):
        v = idle.values_from(idle.parse(HAND))
        self.assertEqual(v["lock"], 600)
        self.assertEqual(v["grace"], 3)
        self.assertEqual(v["off_after_lock"], 30)
        self.assertEqual(v["screens_off"], 630)
        self.assertEqual(v["dim"], 0)
        self.assertEqual(v["suspend"], 0)
        self.assertTrue(v["lock_before_sleep"])
        self.assertFalse(v["password_on_wake"])

    def test_unknown_listener_is_not_ours(self):
        kinds = [lst["kind"] for lst in idle.parse(HAND)["listeners"]]
        self.assertEqual(kinds, ["lock", "off_after_lock", "screens_off", None])

    def test_marker_wins_over_commands(self):
        text = "listener {\n    # idle-settings: suspend\n    timeout = 60\n    on-timeout = something\n}\n"
        self.assertEqual(idle.parse(text)["listeners"][0]["kind"], "suspend")

    def test_empty_file_is_hypridle_doing_nothing(self):
        self.assertEqual(idle.values_from(idle.parse("")), idle.DEFAULTS)


class Writing(unittest.TestCase):
    def test_round_trip_keeps_every_value(self):
        parsed = idle.parse(HAND)
        v = idle.values_from(parsed)
        again = idle.values_from(idle.parse(idle.render(v, parsed)))
        self.assertEqual(again, v)

    def test_changes_round_trip(self):
        parsed = idle.parse(HAND)
        v = idle.apply_changes(idle.values_from(parsed), [
            "dim", "5", "lock", "never", "suspend", "1h", "password_on_wake", "on", "grace", "0",
            "dim_level", "30", "lock_before_sleep", "off"])
        again = idle.values_from(idle.parse(idle.render(v, parsed)))
        self.assertEqual(again, v)
        self.assertEqual(again["dim"], 300)
        self.assertEqual(again["suspend"], 3600)

    def test_own_listener_and_general_keys_are_kept(self):
        parsed = idle.parse(HAND)
        text = idle.render(idle.values_from(parsed), parsed)
        self.assertIn("# my own: pause music after 20 min\nlistener {\n    timeout = 1200\n"
                      "    on-timeout = playerctl pause\n}", text)
        self.assertIn("ignore_dbus_inhibit = false", text)
        self.assertEqual(text.count("playerctl pause"), 1)

    def test_managed_listener_keeps_extra_keys(self):
        hand = HAND.replace("hyprlock --grace 3\n", "hyprlock --grace 3\n    ignore_inhibit = true\n")
        parsed = idle.parse(hand)
        text = idle.render(idle.apply_changes(idle.values_from(parsed), ["lock", "15"]), parsed)
        block = text[text.index("idle-settings: lock"):]
        self.assertIn("ignore_inhibit = true", block[:block.index("}")])

    def test_never_drops_the_listener(self):
        parsed = idle.parse(HAND)
        v = idle.apply_changes(idle.values_from(parsed), ["lock", "never", "off_after_lock", "never"])
        text = idle.render(v, parsed)
        self.assertNotIn("hyprlock --grace", text)
        self.assertNotIn("pidof hyprlock && hyprctl", text)

    def test_listeners_in_time_order(self):
        parsed = idle.parse("")
        v = idle.apply_changes(idle.DEFAULTS, ["suspend", "60", "lock", "10", "dim", "5"])
        text = idle.render(v, parsed)
        self.assertLess(text.index("idle-settings: dim"), text.index("idle-settings: lock"))
        self.assertLess(text.index("idle-settings: lock"), text.index("idle-settings: suspend"))

    def test_braces_balance(self):
        parsed = idle.parse(HAND)
        text = idle.render(idle.apply_changes(idle.values_from(parsed), ["dim", "2", "suspend", "2h"]), parsed)
        body = "\n".join(l for l in text.splitlines() if not l.strip().startswith("#"))
        self.assertEqual(body.count("{") - body.count("{ on"), body.count("}") - body.count(" })"))


class Parsing(unittest.TestCase):
    def test_durations(self):
        self.assertEqual(idle.parse_duration("never"), 0)
        self.assertEqual(idle.parse_duration("10"), 600)
        self.assertEqual(idle.parse_duration("90s"), 90)
        self.assertEqual(idle.parse_duration("1.5h"), 5400)
        self.assertEqual(idle.parse_duration("15m"), 900)
        with self.assertRaises(ValueError):
            idle.parse_duration("soon")

    def test_off_after_lock_is_seconds_by_default(self):
        self.assertEqual(idle.apply_changes(idle.DEFAULTS, ["off_after_lock", "30"])["off_after_lock"], 30)

    def test_bad_input(self):
        for pairs in (["lock"], ["volume", "3"], ["lock_before_sleep", "maybe"]):
            with self.assertRaises(ValueError):
                idle.apply_changes(idle.DEFAULTS, pairs)

    def test_screens_off_follows_the_lock(self):
        v = idle.values_from(idle.parse(HAND))           # 600 + 30 = 630: linked
        self.assertEqual(idle.apply_changes(v, ["lock", "15"])["screens_off"], 930)
        self.assertEqual(idle.apply_changes(v, ["off_after_lock", "60"])["screens_off"], 660)
        # Set together, screens_off is what was asked.
        self.assertEqual(idle.apply_changes(v, ["lock", "15", "screens_off", "20"])["screens_off"], 1200)
        # Lock to never: nothing to follow, it stays where it was.
        self.assertEqual(idle.apply_changes(v, ["lock", "never"])["screens_off"], 630)

    def test_unlinked_screens_off_stays(self):
        v = dict(idle.DEFAULTS, lock=600, off_after_lock=30, screens_off=1800)
        self.assertEqual(idle.apply_changes(v, ["lock", "15"])["screens_off"], 1800)

    def test_own_before_sleep_cmd_that_locks_is_kept(self):
        parsed = idle.parse(HAND.replace("before_sleep_cmd = loginctl lock-session",
                                         "before_sleep_cmd = loginctl lock-session; playerctl pause"))
        v = idle.values_from(parsed)
        self.assertTrue(v["lock_before_sleep"])
        self.assertIn("before_sleep_cmd = loginctl lock-session; playerctl pause", idle.render(v, parsed))
        off = idle.apply_changes(v, ["lock_before_sleep", "off"])
        self.assertNotIn("before_sleep_cmd", dict(idle.parse(idle.render(off, parsed))["general"]))

    def test_clamps(self):
        v = idle.apply_changes(idle.DEFAULTS, ["grace", "999", "dim_level", "1"])
        self.assertEqual((v["grace"], v["dim_level"]), (60, 10))


class Problems(unittest.TestCase):
    def test_current_setup_is_fine(self):
        self.assertEqual(idle.problems(idle.values_from(idle.parse(HAND))), [])

    def test_suspend_without_any_lock(self):
        v = dict(idle.DEFAULTS, suspend=3600)
        self.assertTrue(any("without locking" in p for p in idle.problems(v)))

    def test_screens_off_before_lock_unlocked(self):
        v = dict(idle.DEFAULTS, lock=1800, screens_off=600)
        self.assertTrue(any("open desktop" in p for p in idle.problems(v)))
        v["password_on_wake"] = True
        self.assertFalse(any("open desktop" in p for p in idle.problems(v)))

    def test_password_on_wake_without_screens_off(self):
        v = dict(idle.DEFAULTS, password_on_wake=True)
        self.assertTrue(any("needs \"Turn the screens off\"" in p for p in idle.problems(v)))


class ScreenColorDim(unittest.TestCase):
    """screen-color.py's `dim`, which the dim listener calls. Scratch
    XDG_RUNTIME_DIR (helpers.py); poke() is stubbed so no daemon is told."""

    def setUp(self):
        self.sc = helpers.import_script("screen-color.py")
        self.pokes = []
        self.real_poke, self.sc.poke = self.sc.poke, lambda: self.pokes.append(1)
        self.assertTrue(self.sc.DIMFILE.startswith(helpers.SCRATCH))

    def tearDown(self):
        self.sc.set_dim("off")
        self.sc.poke = self.real_poke

    def test_dim_and_back(self):
        self.assertEqual(self.sc.dim_factor(), 1.0)
        self.sc.set_dim("40")
        self.assertEqual(self.sc.dim_factor(), 0.4)
        self.sc.set_dim("off")
        self.assertEqual(self.sc.dim_factor(), 1.0)
        self.assertEqual(len(self.pokes), 2)

    def test_off_when_not_dimmed_does_not_poke(self):
        self.sc.set_dim("off")
        self.assertEqual(self.pokes, [])

    def test_clamped(self):
        self.sc.set_dim("0")
        self.assertEqual(self.sc.dim_factor(), 0.05)


if __name__ == "__main__":
    unittest.main()
