"""scripts/screens.py: the scripts' answer to "which screens, how big, which
is the primary, which can do HDR" -- the host file's lines read by pattern,
the live screens from canned hyprctl replies, and the fallbacks for a machine
with neither (what a test or a TTY sees). Nothing here calls hyprctl: every
function is fed its monitors, or Hyprland is unreachable (helpers.py drops
HYPRLAND_INSTANCE_SIGNATURE) and the fallback is what is being tested."""
import os
import tempfile
import unittest
from unittest import mock

import helpers

screens = helpers.import_script("screens.py")

# What `hyprctl monitors -j` says on a three-screen desk: a primary ultrawide
# at 0x0, a 2560x1080 at scale 0.8 above it and a 1920x1080 rotated to
# portrait on its right. Hyprland lists them by id, the portrait one first.
MONS = [
    {"id": 0, "name": "HDMI-A-1", "description": "portrait", "width": 1920, "height": 1080,
     "scale": 1.0, "transform": 1, "x": 3440, "y": 0},
    {"id": 1, "name": "DP-2", "description": "above", "width": 2560, "height": 1080,
     "scale": 0.8, "transform": 0, "x": 0, "y": -1350},
    {"id": 2, "name": "DP-1", "description": "primary", "width": 3440, "height": 1440,
     "scale": 1.0, "transform": 0, "x": 0, "y": 0},
]
HOST = {"screens": ["DP-1", "DP-2", "HDMI-A-1"], "hdr_capable": ["DP-1"]}
NONE = {"screens": [], "hdr_capable": []}


class HostFile(unittest.TestCase):
    def test_parse(self):
        text = ('local M = {}\n'
                'M.hdr_capable = { ["DP-1"] = true, ["DP-3"] = true }\n'
                '-- M.screens = { "X" }      a comment does not count\n'
                'M.screens = { "DP-1", "DP-2", "HDMI-A-1" }\n')
        self.assertEqual(screens.parse_host(text),
                         {"screens": ["DP-1", "DP-2", "HDMI-A-1"], "hdr_capable": ["DP-1", "DP-3"]})

    def test_missing_lines_are_empty(self):
        self.assertEqual(screens.parse_host("local M = {}\nreturn M\n"), NONE)
        self.assertEqual(screens.parse_host(""), NONE)

    def test_the_tests_fixture(self):
        # helpers.py points HYPR_HOST_FILE at tests/fixtures/host-three-screens.lua.
        self.assertEqual(screens.host(), HOST)

    def test_real_host_file_matches_monitors_lua_name(self):
        # The file name rule is lua/monitors.lua's hostname(): up to the first
        # dot, anything but [A-Za-z0-9_] turned into _.
        with mock.patch("builtins.open", mock.mock_open(read_data="my-box.lan\n")):
            self.assertEqual(screens.hostname(), "my_box")

    def test_env_pointing_nowhere_is_no_host_file(self):
        with mock.patch.dict(os.environ, {screens.HOST_FILE_ENV: "/nonexistent/host.lua"}):
            self.assertEqual(screens.host(), NONE)


class Order(unittest.TestCase):
    def test_host_file_wins(self):
        self.assertEqual(screens.order(MONS, HOST), ["DP-1", "DP-2", "HDMI-A-1"])

    def test_live_order_puts_0x0_first_then_by_id(self):
        self.assertEqual(screens.order(MONS, NONE), ["DP-1", "HDMI-A-1", "DP-2"])

    def test_nothing_known(self):
        self.assertEqual(screens.order([], NONE), [])
        self.assertEqual(screens.default_primary([], NONE), "")


class Primary(unittest.TestCase):
    def test_stored_choice_wins(self):
        self.assertEqual(screens.primary({"primary": "HDMI-A-1"}, MONS, HOST), "HDMI-A-1")

    def test_host_files_first_screen(self):
        self.assertEqual(screens.primary({}, MONS, HOST), "DP-1")
        self.assertEqual(screens.primary({}, [], HOST), "DP-1")     # not even running

    def test_live_without_host_file(self):
        self.assertEqual(screens.primary({}, MONS, NONE), "DP-1")
        single = [dict(MONS[0], x=0, y=0)]
        self.assertEqual(screens.primary({}, single, NONE), "HDMI-A-1")

    def test_reads_display_conf(self):
        path = os.path.join(tempfile.mkdtemp(dir=helpers.SCRATCH), "display.conf")
        with open(path, "w") as handle:
            handle.write("anim=fancy\nprimary=DP-2\n")
        with mock.patch.object(screens, "STATE", path):
            self.assertEqual(screens.primary(None, MONS, HOST), "DP-2")


class Sizes(unittest.TestCase):
    def test_pixels_turn_with_the_screen(self):
        self.assertEqual(screens.sizes(mons=MONS, profile=HOST),
                         {"DP-1": (3440, 1440), "DP-2": (2560, 1080), "HDMI-A-1": (1080, 1920)})

    def test_logical_divides_by_the_scale(self):
        self.assertEqual(screens.sizes(logical=True, mons=MONS, profile=HOST),
                         {"DP-1": (3440, 1440), "DP-2": (3200, 1350), "HDMI-A-1": (1080, 1920)})

    def test_outputs_in_order_described(self):
        out = screens.outputs(MONS, HOST)
        self.assertEqual([o["name"] for o in out], ["DP-1", "DP-2", "HDMI-A-1"])
        self.assertTrue(out[2]["portrait"])
        self.assertEqual((out[2]["width"], out[2]["height"]), (1920, 1080))   # the mode as driven

    def test_a_screen_the_host_file_does_not_name_comes_last(self):
        extra = MONS + [{"id": 3, "name": "DP-3", "width": 1920, "height": 1080, "scale": 1,
                         "transform": 0, "x": 5000, "y": 0}]
        self.assertEqual([o["name"] for o in screens.outputs(extra, HOST)][-1], "DP-3")

    def test_disabled_screens_get_no_picture(self):
        mons = [dict(m, disabled=(m["name"] == "DP-2")) for m in MONS]
        self.assertNotIn("DP-2", screens.sizes(mons=mons, profile=HOST))

    def test_fallback_without_hyprland(self):
        # The primary still has a name (the host file), at FALLBACK_SIZE.
        self.assertEqual(screens.sizes(mons=[], profile=HOST, state={}), {"DP-1": (1920, 1080)})
        # Nothing names one: a folder called FALLBACK_NAME, so a renderer
        # always has one screen to draw for.
        self.assertEqual(screens.sizes(mons=[], profile=NONE, state={}),
                         {screens.FALLBACK_NAME: screens.FALLBACK_SIZE})

    def test_primary_size_with_hyprland_unreachable(self):
        # helpers.py: hyprctl cannot reach Hyprland, the fixture host file
        # names DP-1 first.
        self.assertEqual(screens.primary_size(), (1920, 1080))


class Hdr(unittest.TestCase):
    def test_from_the_host_file_only(self):
        self.assertEqual(screens.hdr_capable(HOST), ["DP-1"])
        self.assertEqual(screens.hdr_capable(NONE), [])


class Users(unittest.TestCase):
    """The scripts that used to name DP-1 / DP-2 / HDMI-A-1 now ask."""

    def test_display_hdr_auto(self):
        display = helpers.import_script("display.py")
        with mock.patch.object(display, "HDR_CAPABLE", ["DP-1"]), \
                mock.patch.object(display, "read_state", lambda: {}):
            self.assertEqual(display.hdr_screen("auto"), "DP-1")
            self.assertEqual(display.hdr_screen("DP-2"), "DP-2")
        with mock.patch.object(display, "HDR_CAPABLE", ["DP-3"]), \
                mock.patch.object(display, "read_state", lambda: {}):
            self.assertEqual(display.hdr_screen("auto"), "DP-3")    # the primary has none

    def test_window_look_reads_rules_lua_by_role(self):
        look = helpers.import_script("window-look.py", "window_look")
        with open(os.path.join(os.path.dirname(helpers.SCRIPTS), "lua", "rules.lua")) as handle:
            text = handle.read()
        three = {r["workspace"]: (r["monitor"], r["default"])
                 for r in look.parse_workspace_rules(text, "DP-1", ["DP-1", "DP-2", "HDMI-A-1"])}
        self.assertEqual(three, {"1": ("DP-1", True), "2": ("DP-1", False), "3": ("DP-1", False),
                                 "5": ("DP-1", False), "4": ("DP-2", True), "6": ("HDMI-A-1", True)})
        # One screen: 4 and 6 stay (persistent) on it, without default.
        one = {r["workspace"]: (r["monitor"], r["default"])
               for r in look.parse_workspace_rules(text, "eDP-1", ["eDP-1"])}
        self.assertEqual(one["4"], ("eDP-1", False))
        self.assertEqual(one["6"], ("eDP-1", False))

    def test_window_look_prefers_hyprlands_own_rules(self):
        look = helpers.import_script("window-look.py", "window_look")
        live = [{"workspaceString": "1", "monitor": "HDMI-A-1", "default": True, "persistent": True}]
        data = look.workspaces_data("", "", "", [{"name": "HDMI-A-1"}], [], [], set(), live_rules=live)
        self.assertEqual(data["monitors"][0]["monitor"], "HDMI-A-1")
        self.assertEqual(data["monitors"][0]["default"], "1")

    def test_workspace_tint_colours_follow_the_order(self):
        tint = helpers.import_script(os.path.join("..", "..", "waybar", "scripts", "workspace-tint.py"),
                                     "workspace_tint")
        self.assertEqual(tint.monitor_colors(), {"DP-1": "mon1", "DP-2": "mon2", "HDMI-A-1": "mon3"})


class Check(unittest.TestCase):
    """screens.py check: config files that name a screen this machine lacks."""

    def test_reports_missing_screens_only(self):
        folder = tempfile.mkdtemp(dir=helpers.SCRATCH)
        bar, lock, mako, mako_gen = (os.path.join(folder, n) for n in ("bar", "lock", "mako", "mako-gen"))
        with open(bar, "w") as handle:
            handle.write('{\n    "output": "DP-1",\n}\n')
        with open(lock, "w") as handle:
            handle.write("background {\n    monitor =\n    path = x\n}\nlabel {\n    monitor = DP-1\n}\n")
        with open(mako, "w") as handle:
            handle.write("output=DP-1\n")
        with open(mako_gen, "w") as handle:
            handle.write("output=eDP-1\n")        # the later include wins: fine
        named = [(bar, r'^\s*"output"\s*:\s*"([^"]+)"', "bar {p}"),
                 (lock, r"^[ \t]*monitor[ \t]*=[ \t]*(\S+)", "lock {p}"),
                 ((mako, mako_gen), r"^output=(\S+)", "mako {p}")]
        laptop = [{"name": "eDP-1", "x": 0, "y": 0}]
        with mock.patch.object(screens, "NAMED_IN", named), mock.patch.object(screens, "read_state", dict):
            found = screens.check(laptop)
            self.assertEqual(found, [(bar, "DP-1", "bar eDP-1"), (lock, "DP-1", "lock eDP-1")])
            # On the desk: DP-1 is here, the mako include's eDP-1 is not.
            self.assertEqual(screens.check(MONS), [(mako_gen, "eDP-1", "mako DP-1")])
            self.assertEqual(screens.check([]), [])             # no Hyprland: nothing to say


class WallpaperMakers(unittest.TestCase):
    """--all renders one picture per screen screens.sizes() names, at that
    size, into a scratch folder (render stubbed: no real image is drawn)."""

    def run_all(self, filename, want_logical=False):
        maker = helpers.import_script(filename)
        folder = tempfile.mkdtemp(dir=helpers.SCRATCH)
        drawn = []
        fake = {"DP-1": (3440, 1440), "eDP-1": (1080, 1920)}

        def sizes(logical=False, **_):
            drawn.append("logical" if logical else "pixels")
            return dict(fake)

        def render(w, h, *_):
            drawn.append((w, h))
            return mock.Mock()
        with mock.patch.object(maker.screens, "sizes", sizes), \
                mock.patch.object(maker, "WALLDIR", folder), \
                mock.patch.object(maker, "render", render), \
                mock.patch.object(maker, "write", lambda *a: None, create=True), \
                mock.patch("sys.argv", [filename, "--all"]), \
                mock.patch("builtins.print"), mock.patch("os.makedirs"):
            maker.main()
        self.assertIn("logical" if want_logical else "pixels", drawn)
        self.assertEqual({d for d in drawn if isinstance(d, tuple)}, set(fake.values()))

    def test_aero(self):
        self.run_all("make-aero-wallpaper.py")

    def test_matrix(self):
        self.run_all("make-matrix-wallpaper.py")

    def test_win95(self):
        self.run_all("make-win95-wallpaper.py")

    def test_moe_uses_the_logical_size(self):
        self.run_all("make-moe-wallpaper.py", want_logical=True)


if __name__ == "__main__":
    unittest.main()
