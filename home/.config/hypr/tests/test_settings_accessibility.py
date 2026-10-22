"""accessibility.py (Settings > Accessibility): the zoom steps, the state
file, and the plans for reduce motion / reduce transparency (what ON sets,
what OFF puts back). Pure functions only, and write_state into the scratch
XDG_STATE_HOME: nothing reaches Hyprland, gsettings or the other scripts."""
import os
import unittest

import helpers

a11y = helpers.import_script("accessibility.py")


def names(cmds):
    """The commands as (script basename, args...) for readable asserts."""
    return [(os.path.basename(c[0]), *c[1:]) for c in cmds]


class Zoom(unittest.TestCase):
    def test_steps(self):
        self.assertEqual(a11y.next_zoom(1.0, "in"), 1.25)
        self.assertEqual(a11y.next_zoom(2.0, "in"), 2.5)
        self.assertEqual(a11y.next_zoom(2.5, "out"), 2.0)
        self.assertEqual(a11y.next_zoom(3.0, "reset"), 1.0)

    def test_out_snaps_to_off(self):
        self.assertEqual(a11y.next_zoom(1.25, "out"), 1.0)
        self.assertEqual(a11y.next_zoom(1.3, "out"), 1.0)

    def test_clamped(self):
        self.assertEqual(a11y.next_zoom(9.0, "in"), 10.0)
        self.assertEqual(a11y.next_zoom(1.0, "0.5"), 1.0)
        self.assertEqual(a11y.next_zoom(1.0, "250%"), 2.5)
        self.assertEqual(a11y.next_zoom(1.0, "3x"), 3.0)

    def test_garbage_exits(self):
        with self.assertRaises(SystemExit):
            a11y.next_zoom(1.0, "huge")

    def test_saved_zoom_reads_bad_values_as_off(self):
        self.assertEqual(a11y.saved_zoom({}), 1.0)
        self.assertEqual(a11y.saved_zoom({"zoom": "x"}), 1.0)
        self.assertEqual(a11y.saved_zoom({"zoom": "40"}), 10.0)

    def test_zoom_binds_by_description(self):
        binds = [{"modmask": 64, "key": "equal", "description": "Accessibility: Zoom in", "arg": "7"},
                 {"modmask": 64, "key": "minus", "description": "Accessibility: Zoom out", "arg": "8"},
                 {"modmask": 64 | 4, "key": "0", "description": "Accessibility: Zoom off", "arg": "9"},
                 {"modmask": 8, "key": "Q", "description": "Apps: Terminal", "arg": "6"}]
        self.assertEqual(a11y.zoom_binds(binds), [
            {"keys": "SUPER + =", "what": "zooms in"}, {"keys": "SUPER + -", "what": "zooms out"},
            {"keys": "SUPER + CTRL + 0", "what": "turns zoom off"}])
        self.assertEqual(a11y.zoom_binds(None), [])


class StateFile(unittest.TestCase):
    def test_round_trip(self):
        values = {"zoom": "2", "before.anim": "fancy"}
        self.assertEqual(a11y.parse_kv("# comment\n" + a11y.format_kv(values)), values)

    def test_empty_state_removes_the_file(self):
        a11y.write_state({"zoom": "2"})
        self.assertTrue(os.path.exists(a11y.STATE))
        self.assertEqual(a11y.read_state(), {"zoom": "2"})
        a11y.write_state({})
        self.assertFalse(os.path.exists(a11y.STATE))
        self.assertEqual(a11y.read_state(), {})


MOVING = {"anim": "fancy", "wallpaper": True, "react": True, "apps": True}
STILL = {"anim": "calm", "wallpaper": False, "react": False, "apps": False}


class Motion(unittest.TestCase):
    def test_reduced_only_when_every_part_is_still(self):
        self.assertFalse(a11y.motion_reduced(MOVING))
        self.assertTrue(a11y.motion_reduced(STILL))
        self.assertFalse(a11y.motion_reduced({**STILL, "apps": True}))
        # A part that could not be read does not count against it.
        self.assertTrue(a11y.motion_reduced({**STILL, "react": None}))

    def test_on_keeps_what_was_there(self):
        cmds, state = a11y.motion_plan(True, MOVING, {})
        self.assertEqual(names(cmds), [("display.py", "anim", "calm"), ("wallpaper-slideshow.py", "motion", "off"),
                                       ("wallpaper-motion.py", "react", "off"),
                                       ("gsettings", "set", a11y.IFACE, "enable-animations", "false")])
        self.assertEqual(state, {"before.anim": "fancy", "before.wallpaper": "on", "before.react": "on",
                                 "before.apps": "on"})

    def test_on_twice_keeps_the_first_before(self):
        _cmds, state = a11y.motion_plan(True, MOVING, {})
        cmds, again = a11y.motion_plan(True, STILL, state)
        self.assertEqual(cmds, [])
        self.assertEqual(again, state)

    def test_off_puts_it_back(self):
        _cmds, state = a11y.motion_plan(True, {**MOVING, "react": False}, {})
        cmds, after = a11y.motion_plan(False, STILL, state)
        self.assertEqual(names(cmds), [("display.py", "anim", "fancy"), ("wallpaper-slideshow.py", "motion", "on"),
                                       ("gsettings", "set", a11y.IFACE, "enable-animations", "true")])
        self.assertEqual(after, {})

    def test_off_with_nothing_kept_is_the_desktop_default(self):
        cmds, _ = a11y.motion_plan(False, STILL, {})
        self.assertEqual(names(cmds)[0], ("display.py", "anim", "smooth"))
        self.assertEqual(len(cmds), 4)

    def test_off_never_restores_calm(self):
        cmds, _ = a11y.motion_plan(False, STILL, {"before.anim": "calm"})
        self.assertEqual(names(cmds)[0], ("display.py", "anim", "smooth"))


GLASSY = {"theme": "aero", "glass": 22, "glass_own": "22", "blur": "yes", "blur_own": "",
          "inactive_opacity": "0.90", "inactive_own": "0.9"}
SOLID = {"theme": "aero", "glass": 0, "glass_own": "0", "blur": "no", "blur_own": "no",
         "inactive_opacity": "1.00", "inactive_own": "1.0"}


class Transparency(unittest.TestCase):
    def test_reduced(self):
        self.assertFalse(a11y.transparency_reduced(GLASSY))
        self.assertTrue(a11y.transparency_reduced(SOLID))
        self.assertFalse(a11y.transparency_reduced({**SOLID, "blur": "yes"}))

    def test_on(self):
        cmds, state = a11y.transparency_plan(True, GLASSY, {})
        self.assertEqual(names(cmds), [("theme.py", "glass", "0"), ("window-look.py", "set", "blur", "no"),
                                       ("window-look.py", "set", "inactive_opacity", "1.0")])
        self.assertEqual(state["before.glass"], "22")
        self.assertEqual(state["before.blur"], "")
        self.assertEqual(state["before.inactive_opacity"], "0.9")

    def test_round_trip(self):
        _cmds, state = a11y.transparency_plan(True, GLASSY, {})
        cmds, after = a11y.transparency_plan(False, SOLID, state)
        self.assertEqual(names(cmds), [("theme.py", "glass", "22"), ("window-look.py", "unset", "blur"),
                                       ("window-look.py", "set", "inactive_opacity", "0.9")])
        self.assertEqual(after, {})

    def test_theme_default_glass_comes_back_as_default(self):
        _cmds, state = a11y.transparency_plan(True, {**GLASSY, "glass_own": None, "blur_own": "yes"}, {})
        cmds, _ = a11y.transparency_plan(False, SOLID, state)
        self.assertIn(("theme.py", "glass", "default"), names(cmds))
        self.assertIn(("window-look.py", "set", "blur", "yes"), names(cmds))

    def test_after_a_theme_switch_the_glass_is_the_new_themes_default(self):
        _cmds, state = a11y.transparency_plan(True, GLASSY, {})
        cmds, _ = a11y.transparency_plan(False, {**SOLID, "theme": "matrix"}, state)
        self.assertIn(("theme.py", "glass", "default"), names(cmds))

    def test_opacity_chosen_since_is_left_alone(self):
        _cmds, state = a11y.transparency_plan(True, {**GLASSY, "inactive_opacity": "1.00", "inactive_own": ""}, {})
        cmds, _ = a11y.transparency_plan(False, {**SOLID, "inactive_own": "0.8", "inactive_opacity": "0.80"},
                                         state)
        self.assertNotIn("inactive_opacity", " ".join(" ".join(c) for c in names(cmds)))


class Alerts(unittest.TestCase):
    def test_wired(self):
        self.assertFalse(a11y.alerts_wired("notify|switch)\n  pw-play x\n"))
        self.assertFalse(a11y.alerts_wired("# accessibility.py alert, some day\n"))
        self.assertTrue(a11y.alerts_wired('    [[ $1 == notify ]] && ~/.config/hypr/scripts/accessibility.py alert\n'))

    def test_onoff(self):
        self.assertTrue(a11y.onoff("toggle", False))
        self.assertFalse(a11y.onoff("off", True))
        with self.assertRaises(SystemExit):
            a11y.onoff("maybe", True)


class Reader(unittest.TestCase):
    """stop_orca with the commands faked: nothing is signalled for real."""

    def fake(self, alive_after_term):
        sent = []
        alive = [True]

        def change(*cmd):
            sent.append(cmd)
            if "-KILL" in cmd or not alive_after_term:
                alive[0] = False
            return ""
        saved = a11y.change, a11y.orca_running, a11y.DRYRUN
        a11y.change, a11y.orca_running, a11y.DRYRUN = change, (lambda: alive[0]), False

        def restore():
            a11y.change, a11y.orca_running, a11y.DRYRUN = saved
        self.addCleanup(restore)
        return sent

    def test_a_polite_quit_is_enough(self):
        sent = self.fake(alive_after_term=False)
        self.assertEqual(a11y.stop_orca(wait=0.3), "")
        self.assertEqual(sent, [("pkill", "-x", "orca")])

    def test_an_orca_that_ignores_sigterm_is_killed(self):
        sent = self.fake(alive_after_term=True)
        self.assertEqual(a11y.stop_orca(wait=0.3), "")
        self.assertEqual(sent[-1], ("pkill", "-KILL", "-x", "orca"))


if __name__ == "__main__":
    unittest.main()
