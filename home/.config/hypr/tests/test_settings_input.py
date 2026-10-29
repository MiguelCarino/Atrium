"""input-settings.py: the pure parts (defaults from lua/input.lua, the xkb
list, checking values, editing the layout list) and the state file, in the
scratch XDG_STATE_HOME. Hyprland is never asked: apply() is stubbed."""
import os
import unittest

import helpers

ins = helpers.import_script("input-settings.py")

XKB = """! model
  pc105           Generic 105-key PC

! layout
  us              English (US)
  latam           Spanish (Latin American)
  de              German

! variant
  intl            us: English (US, intl., with dead keys)
  deadtilde       latam: Spanish (Latin American, dead tilde)

! option
  grp                  Switching to another layout
  grp:win_space_toggle Win+Space
  grp:alt_shift_toggle Alt+Shift
  grp:ctrl_space_toggle Ctrl+Space
  grp:switch           Right Alt (while pressed)
  caps:escape          Make Caps Lock an additional Esc
  ctrl:nocaps          Caps Lock as Ctrl
  compose:102          The "&lt; &gt;" key
"""
CAT = ins.parse_xkb(XKB)


class Defaults(unittest.TestCase):
    def test_every_key_has_a_default_in_lua(self):
        defs = ins.defaults()
        self.assertEqual(set(defs), set(ins.KEYS))

    def test_lua_defaults_pass_the_checks(self):
        real = ins.xkb()
        for key, value in ins.defaults().items():
            self.assertEqual(ins.check(key, value, real) if value else value, value, key)

    def test_parse_stops_at_the_end_marker(self):
        text = '-- INPUT-DEFAULTS-BEGIN\n    ["a"] = "1",\n-- INPUT-DEFAULTS-END\n    ["b"] = "2",\n'
        self.assertEqual(ins.parse_defaults(text), {"a": "1"})


class Xkb(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(CAT["layouts"]["de"], "German")
        self.assertEqual(CAT["variants"][("us", "intl")], "English (US, intl., with dead keys)")
        self.assertEqual(CAT["options"]["compose:102"], 'The "< >" key')
        self.assertNotIn("grp", CAT["options"])          # the group header is not an option

    def test_layouts_round_trip(self):
        pairs = ins.parse_layouts("us, latam(deadtilde)")
        self.assertEqual(pairs, [("us", ""), ("latam", "deadtilde")])
        self.assertEqual(ins.format_layouts(pairs), "us,latam(deadtilde)")

    def test_search_puts_exact_code_first(self):
        hits = ins.search_layouts(["us"], CAT)
        self.assertEqual(hits[0][0], "us")
        self.assertIn("us(intl)", [t for t, _ in hits])

    def test_search_needs_every_word(self):
        self.assertEqual([t for t, _ in ins.search_layouts(["spanish", "tilde"], CAT)], ["latam(deadtilde)"])

    def test_switch_options_leave_out_hold_keys(self):
        opts = dict(ins.options("switch", CAT))
        self.assertIn("grp:win_space_toggle", opts)
        self.assertNotIn("grp:switch", opts)

    def test_caps_options_include_the_ctrl_ones_named(self):
        self.assertEqual(set(dict(ins.options("caps", CAT))), {"caps:escape", "ctrl:nocaps"})

    def test_say_keys(self):
        self.assertEqual(ins.say_keys("Win+Space"), "Super+Space")


class Check(unittest.TestCase):
    def test_bool(self):
        self.assertEqual(ins.check("numlock", "yes", CAT), "on")
        self.assertEqual(ins.check("numlock", "0", CAT), "off")
        with self.assertRaises(ValueError):
            ins.check("numlock", "maybe", CAT)

    def test_numbers(self):
        self.assertEqual(ins.check("repeat_rate", "30.4", CAT), "30")
        self.assertEqual(ins.check("sensitivity", "-0.25", CAT), "-0.25")
        self.assertEqual(ins.check("scroll_factor", "1", CAT), "1")
        for key, bad in (("repeat_rate", "0"), ("repeat_delay", "5000"), ("sensitivity", "2"), ("repeat_rate", "x")):
            with self.assertRaises(ValueError):
                ins.check(key, bad, CAT)

    def test_choices(self):
        self.assertEqual(ins.check("accel", "flat", CAT), "flat")
        with self.assertRaises(ValueError):
            ins.check("follow_mouse", "3", CAT)

    def test_xkb_options(self):
        self.assertEqual(ins.check("switch", "none", CAT), "")
        self.assertEqual(ins.check("switch", "grp:alt_shift_toggle", CAT), "grp:alt_shift_toggle")
        with self.assertRaises(ValueError):
            ins.check("switch", "caps:escape", CAT)       # right list, wrong key
        self.assertEqual(ins.check("xkb_extra", "caps:escape  compose:102", CAT), "caps:escape,compose:102")

    def test_layouts(self):
        self.assertEqual(ins.check("layouts", "us,latam(deadtilde)", CAT), "us,latam(deadtilde)")
        for bad in ("", "xx", "us(nope)", "us,us", "us,de,latam,us(intl),latam(deadtilde)"):
            with self.assertRaises(ValueError, msg=bad):
                ins.check("layouts", bad, CAT)

    def test_unknown_key(self):
        with self.assertRaises(ValueError):
            ins.check("volume", "3", CAT)


class EditLayouts(unittest.TestCase):
    def test_add_remove_move(self):
        self.assertEqual(ins.edit_layouts("us,latam", "add", "de"), "us,latam,de")
        self.assertEqual(ins.edit_layouts("us,latam,de", "remove", "latam"), "us,de")
        self.assertEqual(ins.edit_layouts("us,latam", "up", "latam"), "latam,us")
        self.assertEqual(ins.edit_layouts("us,latam", "down", "latam"), "us,latam")   # already last

    def test_refusals(self):
        with self.assertRaises(ValueError):
            ins.edit_layouts("us", "remove", "us")
        with self.assertRaises(ValueError):
            ins.edit_layouts("us,latam", "add", "us")
        with self.assertRaises(ValueError):
            ins.edit_layouts("us,latam,de,es", "add", "fr")
        with self.assertRaises(ValueError):
            ins.edit_layouts("us", "remove", "de")


class Warnings(unittest.TestCase):
    def test_alt_based_switches_warn(self):
        for opt in ("grp:alt_shift_toggle", "grp:lalt_toggle", "grp:toggle", "grp:alts_toggle",
                    "grp:alt_altgr_toggle", "grp:ctrl_alt_toggle"):
            self.assertIn("ALT", ins.switch_warning(opt), opt)

    def test_the_default_is_quiet(self):
        self.assertEqual(ins.switch_warning("grp:win_space_toggle"), "")
        self.assertEqual(ins.switch_warning("grp:shifts_toggle"), "")
        self.assertEqual(ins.switch_warning("grp:menu_toggle"), "")

    def test_ctrl_shift_warns_about_app_shortcuts(self):
        for opt in ("grp:ctrl_shift_toggle", "grp:lctrl_lshift_toggle", "grp:ctrl_shift_toggle_bidir"):
            self.assertIn("Ctrl+Shift+T", ins.switch_warning(opt), opt)

    def test_a_lone_modifier_switch_warns(self):
        self.assertIn("Shift", ins.switch_warning("grp:lshift_toggle"))
        self.assertIn("Ctrl", ins.switch_warning("grp:rctrl_toggle"))
        for opt in ("grp:lwin_toggle", "grp:win_menu_select", "grp:lctrl_lwin_rctrl_menu"):
            self.assertIn("Super", ins.switch_warning(opt), opt)

    def test_key_clash_with_caps_and_compose(self):
        self.assertIn("Caps Lock", ins.key_clash({"switch": "grp:shift_caps_toggle", "caps": "caps:escape"}))
        self.assertEqual(ins.key_clash({"switch": "grp:shift_caps_toggle", "caps": ""}), "")
        self.assertIn("Compose", ins.key_clash({"switch": "grp:menu_toggle", "compose": "compose:menu"}))
        self.assertEqual(ins.key_clash({"switch": "grp:menu_toggle", "compose": "compose:rctrl"}), "")
        self.assertEqual(ins.key_clash({"switch": "", "caps": "caps:escape", "compose": "compose:menu"}), "")


class StateFile(unittest.TestCase):
    def setUp(self):
        self.applied = 0
        self.orig_apply = ins.apply
        ins.apply = self.fake_apply
        self.assertTrue(ins.STATE.startswith(helpers.SCRATCH))
        if os.path.exists(ins.STATE):
            os.remove(ins.STATE)

    def tearDown(self):
        ins.apply = self.orig_apply

    def fake_apply(self):
        self.applied += 1
        return None

    def test_set_unset_reset(self):
        self.assertEqual(ins.main(["set", "repeat_rate", "40"]), 0)
        self.assertEqual(ins.read_state(), {"repeat_rate": "40"})
        self.assertEqual(ins.effective()["repeat_rate"], "40")
        self.assertEqual(ins.main(["unset", "repeat_rate"]), 0)
        self.assertEqual(ins.read_state(), {})
        self.assertEqual(ins.effective()["repeat_rate"], ins.defaults()["repeat_rate"])
        ins.main(["set", "numlock", "on"])
        self.assertEqual(ins.main(["reset"]), 0)
        self.assertFalse(os.path.exists(ins.STATE))
        self.assertEqual(self.applied, 4)

    def test_the_default_value_is_not_saved_as_a_change(self):
        ins.main(["set", "repeat_rate", "40"])
        ins.main(["set", "repeat_rate", ins.defaults()["repeat_rate"]])
        self.assertEqual(ins.read_state(), {})

    def test_a_bad_value_writes_nothing(self):
        self.assertEqual(ins.main(["set", "repeat_rate", "fast"]), 1)
        self.assertFalse(os.path.exists(ins.STATE))
        self.assertEqual(self.applied, 0)

    def test_saves_from_two_processes_at_once_keep_both_keys(self):
        # What two quick clicks in Settings do: two writers at the same time.
        # Each child waits on a pipe so both are past fork before either saves.
        r, w = os.pipe()
        kids = []
        for key, value in (("repeat_rate", "40"), ("numlock", "on"), ("accel", "flat"), ("left_handed", "on")):
            pid = os.fork()
            if pid == 0:
                os.close(w)
                os.read(r, 1)
                ins.save(key, value)
                os._exit(0)
            kids.append(pid)
        os.close(r)
        os.write(w, b"go!!")
        os.close(w)
        for pid in kids:
            os.waitpid(pid, 0)
        self.assertEqual(ins.read_state(), {"repeat_rate": "40", "numlock": "on", "accel": "flat",
                                            "left_handed": "on"})

    def test_comments_in_the_file_are_ignored(self):
        ins.write_state({"accel": "flat"})
        with open(ins.STATE) as handle:
            self.assertTrue(handle.readline().startswith("#"))
        self.assertEqual(ins.read_state(), {"accel": "flat"})


if __name__ == "__main__":
    unittest.main()
