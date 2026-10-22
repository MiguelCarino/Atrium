"""scripts/mpv-style.py and lua/mpvframe.lua: mpv's frame and controls presets."""

import os
import shutil
import subprocess
import tempfile
import unittest

import helpers

style = helpers.import_script("mpv-style.py", "mpv_style")
LUA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lua")


class Presets(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir)
        style.STATE = os.path.join(self.dir, "mpv-style.conf")
        style.THEME_CONF = os.path.join(self.dir, "theme.conf")
        style.CONTROLS_CONF = os.path.join(self.dir, "controls.conf")
        style.SOCKETS = os.path.join(self.dir, "sockets")       # no mpv running here

    def test_state_round_trip_and_defaults(self):
        self.assertEqual(style.read_state(), {"frame": "theme", "controls": "theme"})
        style.write_state({"frame": "cinema", "controls": "pill"})
        self.assertEqual(style.read_state(), {"frame": "cinema", "controls": "pill"})

    def test_controls_file_only_holds_the_preset(self):
        style.set_controls("pill")
        with open(style.CONTROLS_CONF) as handle:
            lines = [l for l in handle if l.startswith("script-opts-append")]
        self.assertIn("script-opts-append=uosc-border_radius=24\n", lines)
        self.assertEqual(len(lines), len(style.CONTROLS["pill"][1]))
        style.set_controls("theme")
        with open(style.CONTROLS_CONF) as handle:
            self.assertFalse([l for l in handle if l.startswith("script-opts-append")])

    def test_live_values_undo_to_theme_then_uosc_default(self):
        with open(style.THEME_CONF, "w") as handle:
            handle.write("script-opts-append=uosc-border_radius=12\n")
        values = style.live_values("theme")
        self.assertEqual(values["border_radius"], "12")             # the theme's
        self.assertEqual(values["timeline_border"], "1")            # uosc's default
        self.assertEqual(style.live_values("flat")["border_radius"], "0")

    def test_unknown_names_refused(self):
        with self.assertRaises(SystemExit):
            style.set_frame("nope")
        with self.assertRaises(SystemExit):
            style.set_controls("nope")

    def test_lua_knows_every_frame(self):
        if not shutil.which("luajit"):
            self.skipTest("luajit not installed")
        script = (f"package.path = '{os.path.dirname(LUA)}/?.lua;' .. package.path\n"
                  "hl = { window_rule = function() return { set_enabled = function() end } end,\n"
                  "       get_config = function() return true end }\n"
                  "local M = require('lua.mpvframe')\n"
                  "for k in pairs(M.presets('#8c2457')) do io.write(k, ' ') end\n")
        out = subprocess.run(["luajit", "-e", script], capture_output=True, text=True,
                             env=dict(os.environ, XDG_STATE_HOME=self.dir))
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(set(out.stdout.split()), set(style.FRAMES) - {"theme"})


if __name__ == "__main__":
    unittest.main()
