"""window-look.py: the value rules behind the Settings "Windows & workspaces"
page, its state-file edits (in the scratch XDG_STATE_HOME), and that its
defaults agree with lua/display.lua's LOOK_DEFAULTS. Hyprland is never
called: apply_display, theme_conf and the getoption reader are stubbed."""
import os
import re
import unittest
import unittest.mock

import helpers

look = helpers.import_script("window-look.py", "window_look")
display = look.display

LUA = os.path.join(os.path.dirname(helpers.SCRIPTS), "lua", "display.lua")
THEME = {"id": "aero", "name": "Aero", "hypr.gaps_out": "8", "hypr.gaps_in": "4", "hypr.blur": "yes",
         "hypr.rounding": "8"}


class Normalize(unittest.TestCase):
    def test_numbers_are_clamped(self):
        self.assertEqual(look.normalize("gaps_out", "12"), "12")
        self.assertEqual(look.normalize("gaps_out", "12.6"), "13")
        self.assertEqual(look.normalize("gaps_out", "999"), "60")
        self.assertEqual(look.normalize("border_size", "-3"), "0")

    def test_fractions_take_percentages(self):
        self.assertEqual(look.normalize("dim_strength", "0.3"), "0.30")
        self.assertEqual(look.normalize("dim_strength", "30%"), "0.30")
        self.assertEqual(look.normalize("dim_strength", "30"), "0.30")
        self.assertEqual(look.normalize("inactive_opacity", "10%"), "0.50")   # floor of the range
        self.assertEqual(look.normalize("inactive_opacity", "1"), "1.00")

    def test_switches_and_choices(self):
        self.assertEqual(look.normalize("blur", "On"), "yes")
        self.assertEqual(look.normalize("blur", "0"), "no")
        self.assertEqual(look.normalize("force_split", "right"), "2")
        self.assertEqual(look.normalize("new_status", "stack"), "slave")
        self.assertEqual(look.normalize("layout", "MASTER"), "master")

    def test_bad_values(self):
        for key, value in (("blur", "maybe"), ("layout", "spiral"), ("gaps_in", "wide"), ("nope", "1")):
            with self.assertRaises(ValueError):
                look.normalize(key, value)


class Values(unittest.TestCase):
    def test_theme_value(self):
        self.assertEqual(look.theme_value("gaps_out", THEME), "8")
        self.assertEqual(look.theme_value("layout", THEME), "dwindle")        # nobody sets it: the default
        self.assertEqual(look.theme_value("layout", {"hypr.layout": "bogus"}), "dwindle")
        self.assertEqual(look.theme_value("shadow", THEME), "")               # theme key missing everywhere

    def test_set_unset_and_same_as_theme(self):
        state = {"theme": "aero", "anim": "fancy"}
        s1 = look.changed_state(state, "gaps_out", "12", THEME)
        self.assertEqual(s1["hyprlook.gaps_out"], "12")
        self.assertEqual(s1["anim"], "fancy")
        self.assertNotIn("hyprlook.gaps_out", state)                         # the input is not touched
        s2 = look.changed_state(s1, "gaps_out", "8", THEME)                   # the theme's own value
        self.assertNotIn("hyprlook.gaps_out", s2)
        s3 = look.changed_state(s1, "gaps_out", None, THEME)
        self.assertNotIn("hyprlook.gaps_out", s3)
        self.assertEqual(look.changed_state(state, "dim_inactive", "no", THEME), state)   # = the default

    def test_reset_and_overrides(self):
        state = {"theme": "aero", "hyprlook.gaps_in": "9", "hyprlook.active_border": "rgb(ff0000)",
                 "hyprlook.blur": "sideways"}
        self.assertEqual(look.overrides(state), {"gaps_in": "9"})              # unknown / invalid skipped
        self.assertEqual(look.reset_state(state), {"theme": "aero"})          # hand-written ones go too

    def test_live_value(self):
        self.assertEqual(look.live_value("gaps_out", {"css": "8 8 8 8", "set": True}), "8")
        self.assertEqual(look.live_value("blur", {"bool": False}), "no")
        self.assertEqual(look.live_value("dim_strength", {"float": 0.5}), "0.50")
        self.assertEqual(look.live_value("rounding_power", {"float": 2.0}), "2")
        self.assertEqual(look.live_value("layout", {"str": "dwindle"}), "dwindle")
        self.assertEqual(look.live_value("gaps_out", None), "")

    def test_rows(self):
        rows = {r["key"]: r for r in look.rows({"hyprlook.gaps_out": "20"}, THEME, {"gaps_out": "20"}, True)}
        self.assertEqual(set(rows), set(look.KEYS))
        self.assertEqual((rows["gaps_out"]["value"], rows["gaps_out"]["theme"], rows["gaps_out"]["override"]),
                         ("20", "8", "20"))
        self.assertTrue(rows["gaps_out"]["held_by_gamemode"])
        self.assertFalse(rows["dim_inactive"]["held_by_gamemode"])
        self.assertEqual(rows["gaps_out"]["from"], "theme")
        self.assertEqual(rows["layout"]["from"], "default")


class AgreesWithLua(unittest.TestCase):
    def table(self, name):
        with open(LUA) as handle:
            text = handle.read()
        body = re.search(r"local %s = \{(.*?)\n\}" % name, text, re.S).group(1)
        return text, body

    def test_defaults(self):
        _, body = self.table("LOOK_DEFAULTS")
        lua = dict(re.findall(r"^\s*(\w+)\s*=\s*\"([^\"]*)\"", body, re.M))
        python = {k: s["default"] for k, s in look.KEYS.items() if "default" in s}
        self.assertEqual(lua, python)

    def test_choices(self):
        _, body = self.table("LOOK_CHOICES")
        for line in body.strip().splitlines():
            key = line.split("=")[0].strip()
            names = set(re.findall(r"(?:\[\")?(\w+)(?:\"\])? = true", line))
            self.assertEqual(names, set(look.KEYS[key]["choices"]), key)


class Commands(unittest.TestCase):
    """main() against the scratch state file, with Hyprland stubbed out."""

    def setUp(self):
        self.assertTrue(display.STATE.startswith(helpers.SCRATCH))
        self.applied = 0
        self.saved = (display.apply_display, look.theme_conf, look.notify)
        display.apply_display = lambda: setattr(self, "applied", self.applied + 1)
        look.theme_conf = lambda: dict(THEME)
        look.notify = lambda title: None
        display.write_state({"theme": "aero", "filter": "grayscale"})

    def tearDown(self):
        display.apply_display, look.theme_conf, look.notify = self.saved
        os.remove(display.STATE)

    def test_set_toggle_cycle_reset(self):
        look.main(["set", "gaps_out", "99"])
        self.assertEqual(display.read_state()["hyprlook.gaps_out"], "60")
        look.main(["toggle", "blur"])                                        # theme's yes -> no
        self.assertEqual(display.read_state()["hyprlook.blur"], "no")
        look.main(["toggle", "blur"])                                        # back to the theme's
        self.assertNotIn("hyprlook.blur", display.read_state())
        look.main(["cycle", "layout"])
        self.assertEqual(display.read_state()["hyprlook.layout"], "master")
        look.main(["unset", "gaps_out"])
        self.assertNotIn("hyprlook.gaps_out", display.read_state())
        look.main(["reset"])
        self.assertEqual(display.read_state(), {"theme": "aero", "filter": "grayscale"})
        self.assertEqual(self.applied, 6)

    def test_bad_input_changes_nothing(self):
        for argv in (["set", "gaps_out", "wide"], ["toggle", "gaps_out"], ["unset", "nope"]):
            with self.assertRaises(SystemExit):
                with open(os.devnull, "w") as null, unittest.mock.patch("sys.stderr", null):
                    look.main(argv)
        self.assertEqual(display.read_state(), {"theme": "aero", "filter": "grayscale"})
        self.assertEqual(self.applied, 0)



class WorkspaceRules(unittest.TestCase):
    """lua/rules.lua puts 1/2/3/5 on `monitor = P`, the primary screen."""
    RULES = (
        'local P = (mon_ok and MON.primary()) or "DP-1"\n'
        'hl.workspace_rule({ workspace = "1", monitor = P, default = true, persistent = true })\n'
        'hl.workspace_rule({ workspace = "4", monitor = "DP-2", default = true, persistent = true })\n'
        '-- hl.workspace_rule({ workspace = "9", monitor = "X" })\n'
        'hl.workspace_rule({ workspace = "7", persistent = true })\n')

    def test_variable_monitor_is_the_primary(self):
        rules = look.parse_workspace_rules(self.RULES, "HDMI-A-1")
        self.assertEqual([(r["workspace"], r["monitor"], r["default"]) for r in rules],
                         [("1", "HDMI-A-1", True), ("4", "DP-2", True), ("7", "", False)])

    def test_default_primary_and_grouping(self):
        data = look.workspaces_data(self.RULES, "", "", [{"name": "DP-2"}], [], [], set())
        mons = {m["monitor"]: m for m in data["monitors"]}
        self.assertEqual(mons["DP-1"]["workspaces"], ["1"])
        self.assertFalse(mons["DP-1"]["connected"])
        self.assertEqual(data["unplaced"], ["7"])


if __name__ == "__main__":
    unittest.main()
