"""Settings > Screens: the arrangement maths in display.py, the per-screen
overlay in lua/monitors.lua (under luajit, with a stand-in hl), the night
light's lasting settings (nightlight.sh mode / start / end / temp) and
theme-schedule.py reading its day / night times from them.

Nothing here reaches the screens: display.py is only asked pure questions,
nightlight.sh runs with NL_DRY (records what it would apply) on a scratch
state and conf, and the Lua sees a made-up display state."""
import calendar
import json
import os
import shutil
import subprocess
import tempfile
import unittest

import helpers

display = helpers.import_script("display.py")
capture = helpers.import_script("monitors-capture.py")
sched = helpers.import_script("theme-schedule.py")
BOUNDARIES = sched.boundaries        # the real one: test_schedule.py stubs it per test
NIGHTLIGHT = os.path.join(helpers.SCRIPTS, "nightlight.sh")
MONITORS_LUA = os.path.join(os.path.dirname(helpers.SCRIPTS), "lua", "monitors.lua")


def fake_monitor(**over):
    mon = {"name": "HDMI-A-1", "width": 1920, "height": 1080, "refreshRate": 60.0, "scale": 1.0,
           "transform": 0, "x": 0, "y": 0, "mirrorOf": "none", "disabled": False, "vrr": False,
           "currentFormat": "XRGB8888",
           "availableModes": ["1920x1080@60.00Hz", "1920x1080@50.00Hz", "1920x1080@59.94Hz",
                              "1280x720@60.00Hz", "1280x720@50.00Hz", "720x576@50.00Hz"]}
    mon.update(over)
    return mon


class Arrangement(unittest.TestCase):
    def test_resolutions_biggest_first(self):
        self.assertEqual(display.resolutions(fake_monitor()), ["1920x1080", "1280x720", "720x576"])

    def test_nearest_rate_keeps_the_rate(self):
        mon = fake_monitor()
        self.assertEqual(display.nearest_rate(mon, "1280x720", 59.94), "60.00")
        self.assertEqual(display.nearest_rate(mon, "720x576", 60), "50.00")
        self.assertEqual(display.nearest_rate(mon, "640x480", 60), "")

    def test_scales_give_whole_pixels(self):
        scales = display.scales_for(1920, 1080)
        self.assertIn("1.25", scales)
        self.assertIn("1.5", scales)
        self.assertNotIn("1.75", scales)            # 1080 / 1.75 is not whole
        self.assertIn("1.1", display.scales_for(1920, 1080, current=1.1))   # the current one stays

    def test_logical_size_turns_on_its_side(self):
        self.assertEqual(display.logical_size(1920, 1080, 1, 0), (1920, 1080))
        self.assertEqual(display.logical_size(1920, 1080, 1, 1), (1080, 1920))
        self.assertEqual(display.logical_size(2560, 1080, 0.8, 0), (3200, 1350))

    def test_place_next_to_another(self):
        other = {"x": 0, "y": 0, "w": 3440, "h": 1440}
        self.assertEqual(display.place("right-of", (1080, 1920), other), "3440x0")
        self.assertEqual(display.place("left-of", (1080, 1920), other), "-1080x0")
        self.assertEqual(display.place("above", (3200, 1350), other), "0x-1350")
        self.assertEqual(display.place("below", (3200, 1350), other), "0x1440")

    def test_transform_names(self):
        self.assertEqual(display.transform_of("90"), 1)
        self.assertEqual(display.transform_of("flipped-270"), 7)
        self.assertEqual(display.transform_of("3"), 3)
        self.assertIsNone(display.transform_of("sideways"))
        self.assertIsNone(display.transform_of("8"))

    def test_parse_position(self):
        self.assertEqual(display.parse_position("-1280x-200"), (-1280, -200))
        self.assertIsNone(display.parse_position("left"))

    def test_layout_info(self):
        mon = fake_monitor(transform=1, x=3440, currentFormat="XBGR2101010")
        other = fake_monitor(name="DP-2", x=0, y=-1350, mirrorOf="none")
        mirror = fake_monitor(name="DP-3", mirrorOf="DP-2")
        live = {"HDMI-A-1": mon, "DP-2": other, "DP-3": mirror}
        info = display.layout_info("HDMI-A-1", mon, {"primary": "HDMI-A-1", "vrr.HDMI-A-1": "2"}, live)
        self.assertEqual((info["w"], info["h"]), (1080, 1920))
        self.assertEqual(info["rotation"], "90")
        self.assertEqual(info["bitdepth"], 10)
        self.assertTrue(info["primary"])
        self.assertEqual(info["mirror_targets"], ["DP-2"])     # not a mirror itself
        self.assertEqual(info["chosen"]["vrr"], "2")
        self.assertEqual(info["chosen"]["scale"], "")

    def test_primary_default(self):
        # No primary= stored: the host file's first screen (the tests' fixture,
        # tests/fixtures/host-three-screens.lua, via screens.py).
        self.assertEqual(display.primary({}), display.default_primary())
        self.assertEqual(display.default_primary(), "DP-1")
        self.assertEqual(display.primary({"primary": "DP-2"}), "DP-2")


@unittest.skipUnless(shutil.which("luajit"), "luajit is not installed")
class MonitorsLua(unittest.TestCase):
    """lua/monitors.lua's overlay(): the display.conf keys over a host spec."""

    def overlay(self, spec, state):
        lua = f"""
            hl = {{ monitor = function() end }}
            package.preload["lua.shared"] = function()
                return {{ state = function() return {{}} end }}
            end
            package.path = ""               -- no lua.hosts.*: the generic fallback
            local M = dofile({json.dumps(MONITORS_LUA)})
            local function enc(v)
                if type(v) == "string" then return string.format("%q", v) end
                return tostring(v)
            end
            local out = M.overlay({spec}, {state})
            local keys = {{}}
            for k in pairs(out) do keys[#keys + 1] = k end
            table.sort(keys)
            for _, k in ipairs(keys) do print(k .. "=" .. tostring(out[k])) end
            print("primary=" .. tostring(M.primary({state})))
        """
        out = subprocess.run(["luajit", "-e", lua], capture_output=True, text=True, timeout=10)
        self.assertEqual(out.returncode, 0, out.stderr)
        return dict(line.split("=", 1) for line in out.stdout.splitlines())

    SPEC = '{ output = "HDMI-A-1", mode = "1920x1080@60", position = "3440x0", scale = 1, transform = 1 }'

    def test_no_keys_is_the_host_file(self):
        out = self.overlay(self.SPEC, "{}")
        self.assertEqual((out["mode"], out["scale"], out["transform"]), ("1920x1080@60", "1", "1"))
        # No host file and no hl.get_monitors (luajit): no screen is known.
        self.assertEqual(out["primary"], "nil")

    def test_keys_lay_over(self):
        out = self.overlay(self.SPEC, '{ ["scale.HDMI-A-1"] = "1.25", ["transform.HDMI-A-1"] = "0",'
                                      ' ["position.HDMI-A-1"] = "0x0", ["vrr.HDMI-A-1"] = "2",'
                                      ' ["bitdepth.HDMI-A-1"] = "8", ["mirror.HDMI-A-1"] = "DP-2",'
                                      ' primary = "HDMI-A-1" }')
        self.assertEqual(out["scale"], "1.25")
        self.assertEqual(out["transform"], "0")
        self.assertEqual(out["position"], "0x0")
        self.assertEqual((out["vrr"], out["bitdepth"], out["mirror"]), ("2", "8", "DP-2"))
        self.assertEqual(out["primary"], "HDMI-A-1")

    def test_new_resolution_drops_the_host_rate(self):
        out = self.overlay(self.SPEC, '{ ["mode.HDMI-A-1"] = "1280x720" }')
        self.assertEqual(out["mode"], "1280x720")
        out = self.overlay(self.SPEC, '{ ["mode.HDMI-A-1"] = "1280x720", ["rate.HDMI-A-1"] = "50.00" }')
        self.assertEqual(out["mode"], "1280x720@50.00")
        out = self.overlay(self.SPEC, '{ ["rate.HDMI-A-1"] = "50.00" }')
        self.assertEqual(out["mode"], "1920x1080@50.00")

    def test_disabled_sends_nothing_else(self):
        out = self.overlay(self.SPEC, '{ ["disabled.HDMI-A-1"] = "on", ["scale.HDMI-A-1"] = "2" }')
        self.assertEqual(out, {"disabled": "true", "output": "HDMI-A-1", "primary": "nil"})

    def test_other_screens_keys_are_ignored(self):
        out = self.overlay(self.SPEC, '{ ["scale.DP-2"] = "2" }')
        self.assertEqual(out["scale"], "1")

    def order(self, host, monitors, state="{}"):
        """primary() and order() with a host file (Lua text, or None) and a
        stand-in hl.get_monitors (a Lua list, or None for none at all)."""
        host_dir = tempfile.mkdtemp(dir=helpers.SCRATCH)
        if host is not None:
            os.makedirs(os.path.join(host_dir, "lua", "hosts"))
            with open(os.path.join(host_dir, "lua", "hosts", "testhost.lua"), "w") as handle:
                handle.write(host)
        get = f"get_monitors = function() return {monitors} end," if monitors else ""
        lua = f"""
            hl = {{ monitor = function() end, {get} }}
            package.preload["lua.shared"] = function()
                return {{ state = function() return {state} end }}
            end
            package.path = {json.dumps(host_dir + "/?.lua")}
            io.open = (function(open) return function(path, ...)
                if path == "/etc/hostname" then return open({json.dumps(os.path.join(host_dir, "hostname"))}, ...) end
                return open(path, ...)
            end end)(io.open)
            local f = io.open("/etc/hostname", "w"); f:write("testhost"); f:close()
            local M = dofile({json.dumps(MONITORS_LUA)})
            print(tostring(M.primary()) .. " " .. table.concat(M.order(), ","))
        """
        out = subprocess.run(["luajit", "-e", lua], capture_output=True, text=True, timeout=10)
        self.assertEqual(out.returncode, 0, out.stderr)
        return out.stdout.strip()

    HOST = """local M = {}
        M.hdr_capable = { ["DP-1"] = true }
        M.screens = { "DP-1", "DP-2", "HDMI-A-1" }
        function M.apply(screen) end
        return M"""
    LIVE = ('{ { name = "HDMI-A-1", id = 0, x = 3440, y = 0 }, { name = "DP-2", id = 1, x = 0, y = -1350 },'
            ' { name = "DP-1", id = 2, x = 0, y = 0 } }')

    def test_host_file_order_and_primary(self):
        self.assertEqual(self.order(self.HOST, self.LIVE), "DP-1 DP-1,DP-2,HDMI-A-1")
        # A stored primary moves only the primary, not the order (4 and 6 stay).
        self.assertEqual(self.order(self.HOST, self.LIVE, '{ primary = "DP-2" }'), "DP-2 DP-1,DP-2,HDMI-A-1")

    def test_no_host_file_uses_the_live_screens(self):
        # The one at 0x0 first, then by id -- screens.py's live_order() too.
        self.assertEqual(self.order(None, self.LIVE), "DP-1 DP-1,HDMI-A-1,DP-2")
        self.assertEqual(self.order(None, None), "nil")


class CapturedHostFile(unittest.TestCase):
    """monitors-capture.py: a host file it writes must go through screen(),
    or the Screens page's choices would do nothing on that machine."""

    MONS = [{"name": "HDMI-A-1", "description": "portrait screen", "width": 1920, "height": 1080,
             "refreshRate": 50.0, "x": 3440, "y": 0, "scale": 1.0, "transform": 1,
             "colorManagementPreset": "srgb"}]

    def test_blocks_use_screen(self):
        text = capture.text(self.MONS)
        self.assertIn("function M.apply(screen)", text)
        self.assertIn("screen({", text)
        self.assertNotIn("hl.monitor({", text)
        self.assertIn('mode     = "1920x1080@50"', text)

    def test_overlay_reaches_it(self):
        path = os.path.join(tempfile.mkdtemp(dir=helpers.SCRATCH), "host.lua")
        with open(path, "w") as handle:
            handle.write(capture.text(self.MONS))
        lua = f"""
            package.preload["lua.shared"] = function() return {{ state = function() return {{}} end }} end
            hl = {{ monitor = function() end }}
            package.path = ""
            local M = dofile({json.dumps(MONITORS_LUA)})
            local host = dofile({json.dumps(path)})
            host.apply(function(spec)
                local out = M.overlay(spec, {{ ["scale.HDMI-A-1"] = "1.25" }})
                print(out.output .. " " .. out.mode .. " " .. tostring(out.scale))
            end)
        """
        out = subprocess.run(["luajit", "-e", lua], capture_output=True, text=True, timeout=10)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(out.stdout.strip(), "HDMI-A-1 1920x1080@50 1.25")


def epoch(h, m=0):
    return calendar.timegm((2026, 10, 20, h, m, 0))     # TZ=UTC below


class NightLightSettings(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(dir=helpers.SCRATCH)
        self.conf = os.path.join(self.dir, "nightlight.conf")

    def nl(self, *args, now=None):
        env = dict(os.environ, NL_STATE_DIR=os.path.join(self.dir, "state"), NL_CONF=self.conf,
                   NL_NOW=str(now or epoch(12)), NL_DRY="1", TZ="UTC")
        out = subprocess.run([NIGHTLIGHT, *args], capture_output=True, text=True, env=env, timeout=10)
        return out.returncode, out.stdout, out.stderr

    def status(self, now=None):
        return json.loads(self.nl("status", "--json", now=now)[1].strip().splitlines()[-1])

    def test_defaults_without_a_conf(self):
        rc, out, _ = self.nl("config")
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(out), {"mode": "auto", "start": "20:00", "end": "07:00", "temp": 4000})
        self.assertFalse(os.path.exists(self.conf))      # reading never writes

    def test_mode_on_and_off_hold_all_day(self):
        self.nl("mode", "on")
        info = self.status(now=epoch(12))
        self.assertEqual((info["state"], info["why"], info["mode"]), ("on", "always", "on"))
        self.nl("mode", "off")
        self.assertEqual(self.status(now=epoch(23))["state"], "off")
        self.nl("mode", "auto")
        self.assertEqual(self.status(now=epoch(23))["state"], "on")
        self.assertEqual(self.nl("mode", "sometimes")[0], 2)

    def test_times_persist_and_move_the_window(self):
        rc, _, err = self.nl("start", "11:30")
        self.assertEqual(rc, 0, err)
        self.nl("end", "6:15")
        info = self.status(now=epoch(12))
        self.assertEqual((info["start"], info["end"], info["state"]), ("11:30", "06:15", "on"))
        with open(self.conf) as handle:
            self.assertIn("start=11:30\n", handle.read())

    def test_bad_times(self):
        self.assertEqual(self.nl("start", "25:00")[0], 2)
        self.assertEqual(self.nl("start", "07:00")[0], 2)    # the same as the end
        self.assertFalse(os.path.exists(self.conf))

    def test_temp_also_moves_a_forced_on(self):
        self.nl("on", "5000", now=epoch(12))
        self.assertEqual(self.status()["now_temp"], 5000)
        rc, _, _ = self.nl("temp", "3300")
        self.assertEqual(rc, 0)
        info = self.status()
        self.assertEqual((info["temp"], info["now_temp"], info["why"]), (3300, 3300, "override"))
        self.assertEqual(self.nl("temp", "9000")[0], 2)

    def test_a_typo_in_the_conf_keeps_the_default(self):
        with open(self.conf, "w") as handle:
            handle.write("start=8pm\ntemp=12\nmode=auto\nend=06:00\n")
        cfg = json.loads(self.nl("config")[1])
        self.assertEqual((cfg["start"], cfg["temp"], cfg["end"]), ("20:00", 4000, "06:00"))

    def test_equal_times_in_the_conf_fall_back(self):
        with open(self.conf, "w") as handle:
            handle.write("start=08:00\nend=08:00\n")
        cfg = json.loads(self.nl("config")[1])
        self.assertEqual((cfg["start"], cfg["end"]), ("20:00", "07:00"))

    def test_mode_clears_an_override(self):
        self.nl("off", now=epoch(21))
        self.assertEqual(self.status(now=epoch(21))["why"], "override")
        self.nl("mode", "auto", now=epoch(21))
        self.assertEqual(self.status(now=epoch(21))["why"], "schedule")


class ThemeScheduleTimes(unittest.TestCase):
    def tearDown(self):
        try:
            os.remove(sched.NIGHTLIGHT_CONF)
        except OSError:
            pass

    def test_conf_is_scratch(self):
        self.assertTrue(sched.NIGHTLIGHT_CONF.startswith(helpers.SCRATCH))

    def test_defaults_from_the_script(self):
        self.assertEqual(BOUNDARIES(), ((20, 0), (7, 0)))

    def test_conf_wins(self):
        os.makedirs(os.path.dirname(sched.NIGHTLIGHT_CONF), exist_ok=True)
        with open(sched.NIGHTLIGHT_CONF, "w") as handle:
            handle.write("mode=auto\nstart=21:30\nend=bad\ntemp=4000\n")
        self.assertEqual(BOUNDARIES(), ((21, 30), (7, 0)))

    def test_equal_conf_times_are_ignored(self):
        os.makedirs(os.path.dirname(sched.NIGHTLIGHT_CONF), exist_ok=True)
        with open(sched.NIGHTLIGHT_CONF, "w") as handle:
            handle.write("start=07:00\n")             # the same as the default end
        self.assertEqual(BOUNDARIES(), ((20, 0), (7, 0)))


if __name__ == "__main__":
    unittest.main()
