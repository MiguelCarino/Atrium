"""The main modifier and the pointer settings: input-settings.py's main_mod /
hide_after / edge_reach keys (checked, reloaded rather than eval'd for
main_mod), mod_clashes() over a hyprctl binds -j reply, and lua/shared.lua's
mainMod read from the input state under luajit. Hyprland is never asked:
apply() and reload() are stubbed."""
import json
import os
import shutil
import subprocess
import unittest
from unittest import mock

import helpers

ins = helpers.import_script("input-settings.py")
HYPR = os.path.dirname(helpers.SCRIPTS)


def bind(mods, key, desc="", submap=""):
    bits = {"SUPER": 64, "CTRL": 4, "ALT": 8, "SHIFT": 1}
    mask = sum(bits[m] for m in mods.split("+") if m)
    return {"modmask": mask, "key": key, "submap": submap, "description": desc}


class Keys(unittest.TestCase):
    def test_main_mod_choices(self):
        self.assertEqual(ins.check("main_mod", "super"), "SUPER")
        self.assertEqual(ins.check("main_mod", "ALT"), "ALT")
        with self.assertRaises(ValueError):
            ins.check("main_mod", "CTRL")

    def test_pointer_ranges(self):
        self.assertEqual(ins.check("hide_after", "3"), "3")
        self.assertEqual(ins.check("hide_after", "0"), "0")
        with self.assertRaises(ValueError):
            ins.check("hide_after", "61")
        self.assertEqual(ins.check("edge_reach", "600"), "600")
        with self.assertRaises(ValueError):
            ins.check("edge_reach", "2001")

    def test_defaults_keep_alt_and_hide_after_three_seconds(self):
        defs = ins.defaults()
        self.assertEqual(defs["main_mod"], "ALT")
        self.assertEqual(defs["hide_after"], "3")
        self.assertEqual(defs["hide_on_typing"], "on")

    def test_main_mod_reloads_and_the_rest_evals(self):
        calls = []
        with mock.patch.object(ins, "apply", lambda: calls.append("apply")), \
                mock.patch.object(ins, "reload", lambda: calls.append("reload")):
            ins.save("main_mod", "SUPER")
            ins.save("hide_after", "5")
            ins.save("main_mod", None)
            ins.save("hide_after", None)
        self.assertEqual(calls, ["reload", "apply", "reload", "apply"])
        self.assertEqual(ins.read_state(), {})


class SwitchWarning(unittest.TestCase):
    def test_alt_switch_names_the_main_modifier_only_when_it_is_alt(self):
        self.assertIn("main modifier", ins.switch_warning("grp:alt_shift_toggle"))
        w = ins.switch_warning("grp:alt_shift_toggle", "SUPER")
        self.assertNotIn("main modifier", w)
        self.assertIn("ALT", w)


class Clashes(unittest.TestCase):
    BINDS = [bind("ALT", "Q", "Apps: Terminal"), bind("SUPER", "Q", "Tools: Something"),
             bind("ALT", "W", "Apps: Files"),
             bind("ALT+SHIFT", "1", "Workspaces: Send"), bind("SUPER+SHIFT", "1", "Other"),
             bind("SUPER+ALT", "L", "Session: Lock"),           # has SUPER: never a clash
             bind("ALT", "R", "resize", submap="resize"), bind("SUPER", "R", "Windows: Resize mode")]

    def test_with_alt_lists_what_super_would_double(self):
        self.assertEqual(ins.mod_clashes(self.BINDS, "ALT"), ["SUPER+Q", "SUPER+SHIFT+1"])

    def test_with_super_lists_what_is_doubled(self):
        now = [bind("SUPER", "Q", "Apps: Terminal"), bind("SUPER", "Q", "Tools: Something"),
               bind("SUPER", "W", "Apps: Files")]
        self.assertEqual(ins.mod_clashes(now, "SUPER"), ["SUPER+Q"])

    def test_nothing(self):
        self.assertEqual(ins.mod_clashes([], "ALT"), [])


@unittest.skipUnless(shutil.which("luajit"), "luajit is not installed")
class SharedLua(unittest.TestCase):
    CONF = os.path.join(os.environ["XDG_STATE_HOME"], "hypr", "input.conf")

    def tearDown(self):
        try:
            os.remove(self.CONF)
        except FileNotFoundError:
            pass

    def main_mod(self, content):
        if content is not None:
            os.makedirs(os.path.dirname(self.CONF), exist_ok=True)
            with open(self.CONF, "w") as handle:
                handle.write(content)
        lua = f'local S = dofile({json.dumps(os.path.join(HYPR, "lua", "shared.lua"))}) print(S.mainMod)'
        out = subprocess.run(["luajit", "-e", lua], capture_output=True, text=True, timeout=10)
        self.assertEqual(out.returncode, 0, out.stderr)
        return out.stdout.strip()

    def test_alt_without_a_file(self):
        self.assertEqual(self.main_mod(None), "ALT")

    def test_super_from_the_file(self):
        self.assertEqual(self.main_mod("# x\nmain_mod=super\n"), "SUPER")

    def test_anything_else_is_alt(self):
        self.assertEqual(self.main_mod("main_mod=HYPER\n"), "ALT")


if __name__ == "__main__":
    unittest.main()
