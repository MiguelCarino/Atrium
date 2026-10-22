"""scripts/pip.py (the live picture-in-picture mirror) and lua/pip.lua: the
settings file, the mirror's size and corner, slurp's window boxes, the
capture and viewer command lines, the PPM reader -- and the Lua rules'
opacity switching under a stub hl.

Hermetic: pip.conf is helpers.py's scratch XDG_STATE_HOME, nothing is
captured or shown, no hyprctl is run."""
import os
import shutil
import subprocess
import tempfile
import unittest

import helpers

pip = helpers.import_script("pip.py")
LUA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lua")

DP1 = {"name": "DP-1", "x": 0, "y": 0, "width": 3440, "height": 1440, "scale": 1, "transform": 0,
       "activeWorkspace": {"id": 1}, "specialWorkspace": {"id": 0}}
PORTRAIT = {"name": "HDMI-A-1", "x": 3440, "y": 0, "width": 1920, "height": 1080, "scale": 1, "transform": 1,
            "activeWorkspace": {"id": 6}, "specialWorkspace": {"id": 0}}
SCALED = {"name": "DP-2", "x": 0, "y": -1350, "width": 2560, "height": 1080, "scale": 0.8, "transform": 0,
          "activeWorkspace": {"id": 4}, "specialWorkspace": {"id": 0}}


class Settings(unittest.TestCase):
    def setUp(self):
        if os.path.exists(pip.CONF):
            os.remove(pip.CONF)

    tearDown = setUp

    def test_defaults_and_round_trip(self):
        self.assertEqual(pip.read_settings(), pip.DEFAULTS)
        pip.write_setting("opacity", "80")
        pip.write_setting("corner", "Top-Left")
        self.assertEqual((pip.read_settings()["opacity"], pip.read_settings()["corner"]), ("80", "top-left"))
        pip.write_setting("opacity", "100")                   # the default again: dropped from the file
        with open(pip.CONF) as handle:
            self.assertEqual(handle.read(), "corner=top-left\n")

    def test_refuses_bad_values(self):
        for key, value in (("opacity", "10"), ("opacity", "x"), ("width", "5000"), ("corner", "middle"),
                           ("passthrough", "maybe"), ("nope", "1")):
            with self.assertRaises(ValueError, msg=(key, value)):
                pip.write_setting(key, value)


class Geometry(unittest.TestCase):
    def test_fit_keeps_the_shape_on_the_long_side(self):
        self.assertEqual(pip.fit(1920, 1080, 480), (480, 270))
        self.assertEqual(pip.fit(1080, 1920, 480), (270, 480))
        self.assertEqual(pip.fit(500, 500, 480), (480, 480))
        self.assertEqual(pip.fit(0, 0, 480), (480, 480))       # never a zero-sized window

    def test_corners(self):
        self.assertEqual(pip.place(DP1, (480, 270), "bottom-right"), (3440 - 480 - 24, 1440 - 270 - 24))
        self.assertEqual(pip.place(DP1, (480, 270), "top-left"), (24, 24 + pip.BAR_H))

    def test_rotated_and_scaled_screens(self):
        self.assertEqual(pip.logical(PORTRAIT), (3440, 0, 1080, 1920))
        self.assertEqual(pip.logical(SCALED), (0, -1350, 3200, 1350))
        x, y = pip.place(PORTRAIT, (270, 480), "bottom-right")
        self.assertEqual((x, y), (3440 + 1080 - 270 - 24, 1920 - 480 - 24))

    def test_window_boxes_only_what_can_be_clicked(self):
        clients = [
            {"class": "firefox", "workspace": {"id": 1}, "at": [5, 41], "size": [800, 600], "stableId": "a1"},
            {"class": "kitty", "workspace": {"id": 2}, "at": [5, 41], "size": [800, 600], "stableId": "b2"},
            {"class": "mpv", "workspace": {"id": 2}, "at": [9, 9], "size": [320, 180], "stableId": "c3",
             "pinned": True},
            {"class": pip.APP_ID, "workspace": {"id": 1}, "at": [0, 0], "size": [480, 270], "stableId": "d4"},
            {"class": "chat", "workspace": {"id": 6}, "at": [3445, 41], "size": [1070, 900], "stableId": "e5"},
        ]
        boxes = pip.window_boxes(clients, [DP1, PORTRAIT])
        self.assertEqual(boxes, ["5,41 800x600 a1", "9,9 320x180 c3", "3445,41 1070x900 e5"])

    def test_parse_slurp(self):
        self.assertEqual(pip.parse_slurp("100,200 640x360\n"), (100, 200, 640, 360))
        self.assertIsNone(pip.parse_slurp("selection cancelled\n"))
        self.assertIsNone(pip.parse_slurp("1,1 1x1"))


class Commands(unittest.TestCase):
    def test_gsr_region_is_even_sized(self):
        argv = pip.gsr_argv((10, 20, 641, 361), "30")
        self.assertEqual(argv[argv.index("-w") + 1], "640x360+10+20")
        self.assertEqual(argv[argv.index("-o") + 1], "/dev/stdout")
        self.assertIn("mpegts", argv)

    def test_mpv_is_the_pip_window(self):
        argv = pip.mpv_argv("PiP · x", (480, 270))
        self.assertIn("--no-config", argv)
        self.assertIn(f"--wayland-app-id={pip.APP_ID}", argv)
        self.assertIn("--geometry=480x270", argv)
        self.assertEqual(argv[-1], "-")
        ppm = pip.mpv_argv("t", (480, 270), "ppm_pipe")
        self.assertIn("--demuxer-lavf-format=ppm_pipe", ppm)
        self.assertIn("--demuxer-lavf-probe-info=auto", ppm)  # low-latency's nostreams breaks ppm_pipe

    def test_grim_argv(self):
        self.assertEqual(pip.grim_argv({"mode": "window", "id": "18000006"}),
                         ["grim", "-T", "18000006", "-t", "ppm", "-"])
        self.assertEqual(pip.grim_argv({"mode": "region", "region": (1, 2, 30, 40)})[1:3], ["-g", "1,2 30x40"])

    def test_parse_ppm(self):
        data = b"P6\n# a comment\n2 1\n255\n" + bytes([255, 0, 0, 0, 0, 255])
        self.assertEqual(pip.parse_ppm(data), (2, 1, bytes([255, 0, 0, 0, 0, 255])))
        with self.assertRaises(ValueError):
            pip.parse_ppm(b"P5\n2 1\n255\n\x00\x00")

    def test_nothing_running(self):
        self.assertIsNone(pip.running())
        self.assertFalse(pip.close())


class Lua(unittest.TestCase):
    def test_opacity_rule_switches_without_stacking(self):
        if not shutil.which("luajit"):
            self.skipTest("luajit not installed")
        state = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, state)
        os.makedirs(os.path.join(state, "hypr"))
        conf = os.path.join(state, "hypr", "pip.conf")
        script = (f"package.path = '{os.path.dirname(LUA)}/?.lua;' .. package.path\n"
                  "made, on = {}, {}\n"
                  "hl = { window_rule = function(r) made[#made + 1] = r.name\n"
                  "         return { set_enabled = function(_, v) on[r.name] = v end } end,\n"
                  "       get_config = function() return true end }\n"
                  "local M = require('lua.pip')\n"
                  f"local f = io.open('{conf}', 'w') f:write('opacity=80\\n') f:close()\n"
                  "M.apply()\n"
                  f"f = io.open('{conf}', 'w') f:write('opacity=100\\n') f:close()\n"
                  "M.apply()\n"
                  f"f = io.open('{conf}', 'w') f:write('opacity=80\\n') f:close()\n"
                  "M.apply()\n"
                  "io.write(table.concat(made, ' '), ' | ', tostring(on['pip-mirror-opacity-80']))\n")
        out = subprocess.run(["luajit", "-e", script], capture_output=True, text=True,
                             env={**os.environ, "XDG_STATE_HOME": state})
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(out.stdout, "pip-mirror pip-mirror-opacity-80 | true")


class Page(unittest.TestCase):
    def test_page_dict(self):
        try:
            import gi
            gi.require_version("Gtk", "3.0")
            gi.require_version("Gdk", "3.0")
            from settings_pages import pip as page
        except Exception as exc:                                 # no display / GTK
            self.skipTest(f"settings_pages.pip not importable: {exc}")
        self.assertEqual(page.PAGE["id"], "pip")
        self.assertIn("mirror", page.PAGE["keywords"])


if __name__ == "__main__":
    unittest.main()
