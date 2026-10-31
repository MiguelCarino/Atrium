"""The dock and taskbar (scripts/dock.py): its settings (dock.json: defaults,
hand edits, what `set` accepts, the systemctl it runs, pin / unpin / move),
status --json's shape, and the pure logic the daemon is built on -- which
installed app a window is, the items in their order (pinned first, running
grouped, never-combine), what a click does, the commands it runs, autohide,
where the preview goes, the thumbnails' scale, the clock, the stylesheet's
imports, the tray's StatusNotifierItem / dbusmenu parsing, the effects'
pure part (magnification's falloff and spread, the easing and its timing,
the launch hop, the room round the card, reduce motion, the theme's
dock.magnify, every theme's dock.css, the harness file), and the toolbox
button: the record toolbox_fit.py places the card from, the pill poke and
the refit `set on|off` runs (a stand-in toolbox.sh under a scratch HOME).

Hermetic: dock.json is a scratch file (DOCK_SETTINGS), DOCK_DRY=1 keeps
systemctl out (the test that checks the systemctl line runs the CLI with a
stand-in systemctl first on PATH), and nothing here needs a display, gi,
Hyprland or the session bus."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime

import helpers

DOCK_PY = os.path.join(helpers.SCRIPTS, "dock.py")
SETTINGS = os.path.join(helpers.SCRATCH, "state", "hypr", "dock-test.json")
D = None


def setUpModule():
    global D
    os.environ["DOCK_DRY"] = "1"
    os.environ["DOCK_SETTINGS"] = SETTINGS
    D = helpers.import_script("dock.py")


def tearDownModule():
    os.environ.pop("DOCK_DRY", None)
    os.environ.pop("DOCK_SETTINGS", None)


def clean():
    if os.path.exists(SETTINGS):
        os.remove(SETTINGS)


def write_raw(text):
    os.makedirs(os.path.dirname(SETTINGS), exist_ok=True)
    with open(SETTINGS, "w") as handle:
        handle.write(text)


APPS = [
    {"id": "org.mozilla.firefox.desktop", "name": "Firefox", "wmclass": "firefox", "exec": "firefox", "hidden": False},
    {"id": "kitty.desktop", "name": "kitty", "wmclass": "", "exec": "kitty", "hidden": False},
    {"id": "org.gnome.Nautilus.desktop", "name": "Files", "wmclass": "", "exec": "nautilus", "hidden": False},
    # a hidden helper entry that also says "firefox": the visible one wins
    {"id": "firefox-helper.desktop", "name": "Firefox helper", "wmclass": "firefox", "exec": "", "hidden": True},
]


def client(addr, cls, title="", focus=5, monitor=0, ws=1, at=(0, 0), size=(800, 600), stable="1a"):
    return {"address": addr, "mapped": True, "hidden": False, "class": cls, "initialClass": cls, "title": title,
            "focusHistoryID": focus, "monitor": monitor, "workspace": {"id": ws, "name": str(ws)},
            "at": list(at), "size": list(size), "stableId": stable}


CLIENTS = [
    client("0xa1", "kitty", "shell", focus=2),
    client("0xb1", "firefox", "news", focus=0),
    client("0xa2", "kitty", "logs", focus=1, monitor=1),
    client("0xc1", "steam_app_123", "Game", focus=3),
]


def items(**kw):
    index = D.app_index(APPS)
    by_id = {a["id"]: a for a in APPS}
    order = D.update_order([], CLIENTS, index)
    pinned = kw.pop("pinned", ["org.mozilla.firefox.desktop", "org.gnome.Nautilus.desktop"])
    return D.build_items(pinned, CLIENTS, index, by_id, order, **kw)


# -- settings ----------------------------------------------------------------------------------
class Settings(unittest.TestCase):
    setUp = tearDown = staticmethod(clean)

    def test_paths_are_scratch(self):
        self.assertEqual(D.SETTINGS_FILE, SETTINGS)
        self.assertTrue(D.SETTINGS_FILE.startswith(helpers.SCRATCH))

    def test_defaults_off_and_unchosen_pins(self):
        cur = D.read_settings()
        self.assertFalse(cur["enabled"])
        self.assertEqual((cur["layout"], cur["position"], cur["autohide"], cur["monitors"]),
                         ("dock", "bottom", "never", "main"))
        self.assertIsNone(cur["pinned"])            # seeded by the daemon on its first start

    def test_hand_edits_are_cleaned(self):
        write_raw(json.dumps({"enabled": "yes", "layout": "TASKBAR", "position": "top", "icon_size": 500,
                              "pinned": ["kitty", "kitty.desktop", "bad id!", 3], "extra": 1}))
        cur = D.read_settings()
        self.assertIs(cur["enabled"], True)
        self.assertEqual(cur["layout"], "taskbar")
        self.assertEqual(cur["position"], "bottom")   # not a choice: the default
        self.assertEqual(cur["icon_size"], D.ICON_MAX)
        self.assertEqual(cur["pinned"], ["kitty.desktop"])
        write_raw("not json")
        self.assertEqual(D.read_settings(), D.DEFAULTS)
        # an icon size too big for an int (JSON 1e999 / Infinity): the default,
        # not an OverflowError that would stop status, set and the daemon
        for raw in ('{"icon_size": 1e999}', '{"icon_size": Infinity}', '{"icon_size": NaN}'):
            write_raw(raw)
            self.assertEqual(D.read_settings()["icon_size"], D.DEFAULTS["icon_size"], raw)
        write_raw('{"icon_size": 1e999}')
        D.set_key("layout", "taskbar")                # and `set` can still repair the file
        self.assertEqual(D.read_settings()["layout"], "taskbar")

    def test_set_keys(self):
        D.set_key("layout", "taskbar")
        D.set_key("combine", "off")
        D.set_key("icon_size", "20")
        D.set_key("pinned", "kitty, org.gnome.Nautilus")
        cur = D.read_settings()
        self.assertEqual(cur["layout"], "taskbar")
        self.assertIs(cur["combine"], False)
        self.assertEqual(cur["icon_size"], D.ICON_MIN)
        self.assertEqual(cur["pinned"], ["kitty.desktop", "org.gnome.Nautilus.desktop"])
        for key, value in (("layout", "sideways"), ("combine", "maybe"), ("icon_size", "big"),
                           ("pinned", "no/such"), ("nope", "1")):
            with self.assertRaises(SystemExit):
                D.set_key(key, value)

    def test_pin_unpin_move(self):
        D.change_pinned("pin", "kitty")
        D.change_pinned("pin", "org.mozilla.firefox")
        D.change_pinned("pin", "kitty")                       # once only
        self.assertEqual(D.read_settings()["pinned"], ["kitty.desktop", "org.mozilla.firefox.desktop"])
        D.change_pinned("move", "firefox", -1)                # a short name finds the pinned one
        self.assertEqual(D.read_settings()["pinned"], ["org.mozilla.firefox.desktop", "kitty.desktop"])
        D.change_pinned("unpin", "org.mozilla.firefox.desktop")
        self.assertEqual(D.read_settings()["pinned"], ["kitty.desktop"])
        with self.assertRaises(SystemExit):
            D.change_pinned("pin", "")

    def test_magnify_setting(self):
        self.assertEqual(D.read_settings()["magnify"], "theme")       # the theme decides by default
        D.set_key("magnify", "on")
        self.assertEqual(D.read_settings()["magnify"], "on")
        D.set_key("magnify", "OFF")
        self.assertEqual(D.read_settings()["magnify"], "off")
        with self.assertRaises(SystemExit):
            D.set_key("magnify", "huge")
        write_raw(json.dumps({"magnify": "sideways"}))
        self.assertEqual(D.read_settings()["magnify"], "theme")

    def test_status_shape(self):
        D.set_key("pinned", "kitty")
        st = D.status()
        for key in ("settings", "defaults", "service", "enabled_unit", "running", "monitors", "pinned_apps", "file"):
            self.assertIn(key, st)
        self.assertEqual(st["service"], "dry")
        self.assertEqual(st["pinned_apps"][0]["id"], "kitty.desktop")
        json.dumps(st)


class Cli(unittest.TestCase):
    def setUp(self):
        clean()
        self.bin = tempfile.mkdtemp(dir=helpers.SCRATCH)
        self.log = os.path.join(self.bin, "calls")
        with open(os.path.join(self.bin, "systemctl"), "w") as handle:
            handle.write(f'#!/bin/sh\necho "systemctl $*" >> {self.log}\n')
        os.chmod(os.path.join(self.bin, "systemctl"), 0o755)
        # HOME is self.bin in cli(): dock.py's TOOLBOX_SH is this stand-in.
        scripts = os.path.join(self.bin, ".config", "waybar", "scripts")
        os.makedirs(scripts)
        with open(os.path.join(scripts, "toolbox.sh"), "w") as handle:
            handle.write(f'#!/bin/sh\necho "toolbox.sh $*" >> {self.log}\n')
        os.chmod(os.path.join(scripts, "toolbox.sh"), 0o755)

    tearDown = staticmethod(clean)

    def cli(self, *args, dry=True):
        env = dict(os.environ, PATH=self.bin + os.pathsep + os.environ.get("PATH", ""),
                   DOCK_SETTINGS=SETTINGS, HOME=self.bin)
        if not dry:
            env.pop("DOCK_DRY", None)
        return subprocess.run([sys.executable, DOCK_PY, *args], capture_output=True, text=True, timeout=30, env=env)

    def calls(self):
        try:
            with open(self.log) as handle:
                return handle.read().splitlines()
        except OSError:
            return []

    def test_set_on_off_runs_systemctl(self):
        done = self.cli("set", "on", dry=False)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("systemctl --user enable --now dock.service", self.calls())
        self.assertIs(D.read_settings()["enabled"], True)
        self.assertNotIn("toolbox.sh refit", self.calls())     # the daemon refits once drawn
        done = self.cli("set", "enabled", "off", dry=False)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("systemctl --user disable --now dock.service", self.calls())
        # Off: the toolbox goes back under the top bar's pill, after the stop.
        calls = self.calls()
        self.assertIn("toolbox.sh refit", calls)
        self.assertGreater(calls.index("toolbox.sh refit"),
                           calls.index("systemctl --user disable --now dock.service"))

    def test_other_keys_and_dry_never_touch_systemd(self):
        self.assertEqual(self.cli("set", "layout", "taskbar", dry=False).returncode, 0)
        self.assertEqual(self.cli("set", "on").returncode, 0)
        self.assertEqual(self.cli("set", "off").returncode, 0)
        self.assertFalse([c for c in self.calls() if c.startswith("systemctl --user enable")])
        self.assertNotIn("toolbox.sh refit", self.calls())

    def test_switching_pokes_the_toolbox_pill(self):
        from unittest import mock
        with mock.patch.object(D, "poke_toolbox_pill") as poke:
            D.set_key("layout", "taskbar")
            self.assertFalse(poke.called)
            D.set_key("enabled", "on")
            D.set_key("enabled", "off")
        self.assertEqual(poke.call_count, 2)

    def test_usage(self):
        self.assertEqual(self.cli("frobnicate").returncode, 2)
        self.assertEqual(self.cli("move", "kitty", "sideways").returncode, 2)

    def test_daemon_switched_off_exits(self):
        done = self.cli("daemon")
        self.assertEqual(done.returncode, 0)
        self.assertIn("switched off", done.stdout)


# -- apps and items ----------------------------------------------------------------------------
class Items(unittest.TestCase):
    def test_window_to_app(self):
        index = D.app_index(APPS)
        self.assertEqual(D.window_app(client("0x1", "firefox"), index)["id"], "org.mozilla.firefox.desktop")
        self.assertEqual(D.window_app(client("0x1", "kitty"), index)["id"], "kitty.desktop")
        self.assertEqual(D.window_app(client("0x1", "org.gnome.Nautilus"), index)["id"],
                         "org.gnome.Nautilus.desktop")
        self.assertIsNone(D.window_app(client("0x1", "steam_app_123"), index))

    def test_pinned_first_then_running_grouped(self):
        got = items(active="0xb1")
        self.assertEqual([i["key"] for i in got],
                         ["org.mozilla.firefox.desktop", "org.gnome.Nautilus.desktop", "kitty.desktop",
                          "class:steam_app_123"])
        fx, files, kitty, game = got
        self.assertTrue(fx["pinned"] and fx["focused"])
        self.assertEqual(files["windows"], [])                      # pinned, not running
        self.assertEqual([w["address"] for w in kitty["windows"]], ["0xa1", "0xa2"])
        self.assertFalse(kitty["pinned"])
        self.assertEqual(game["name"], "steam_app_123")             # unknown: its class

    def test_uninstalled_pin_is_left_out(self):
        got = items(pinned=["gone.desktop", "kitty.desktop"])
        self.assertEqual(got[0]["key"], "kitty.desktop")
        self.assertNotIn("gone.desktop", [i["key"] for i in got])
        # its windows, were there any, are an unknown app's: still shown
        gone = D.build_items(["gone.desktop"], [client("0xd1", "gone")], D.app_index(APPS),
                             {a["id"]: a for a in APPS}, [])
        self.assertEqual([i["key"] for i in gone], ["class:gone"])
        self.assertFalse(gone[0]["pinned"])

    def test_monitor_filter(self):
        got = items(monitor_id=1)
        kitty = next(i for i in got if i["key"] == "kitty.desktop")
        self.assertEqual([w["address"] for w in kitty["windows"]], ["0xa2"])
        self.assertEqual(next(i for i in got if i["key"] == "org.mozilla.firefox.desktop")["windows"], [])

    def test_never_combine(self):
        got = items(combine=False, pinned=["kitty.desktop"])
        self.assertEqual([i["key"] for i in got[:2]], ["kitty.desktop#0xa1", "kitty.desktop#0xa2"])
        self.assertTrue(got[0]["pinned"])
        self.assertFalse(got[1]["pinned"])
        self.assertEqual(got[1]["title"], "logs")

    def test_urgent_and_launching(self):
        got = items(urgent={"0xa2"}, launching={"org.gnome.Nautilus.desktop"})
        self.assertTrue(next(i for i in got if i["key"] == "kitty.desktop")["urgent"])
        self.assertTrue(next(i for i in got if i["key"] == "org.gnome.Nautilus.desktop")["launching"])

    def test_order_is_stable(self):
        index = D.app_index(APPS)
        order = D.update_order(["class:steam_app_123", "gone"], CLIENTS, index)
        self.assertEqual(order[0], "class:steam_app_123")
        self.assertNotIn("gone", order)
        self.assertEqual(set(order), {"class:steam_app_123", "kitty.desktop", "org.mozilla.firefox.desktop"})

    def test_icon_names(self):
        self.assertEqual(D.icon_names("steam_app_123")[0], "steam_icon_123")
        self.assertEqual(D.icon_names("Org.Foo.Bar")[:3], ["Org.Foo.Bar", "org.foo.bar", "bar"])
        self.assertEqual(D.icon_names("")[-1], "application-x-executable")

    def test_live_clients(self):
        bad = [client("nope", "x"), dict(client("0x9", "x"), mapped=False), dict(client("0x8", "x"), hidden=True)]
        self.assertEqual(D.live_clients(bad + CLIENTS[:1]), CLIENTS[:1])


class Clicks(unittest.TestCase):
    def test_click_action(self):
        fx, files, kitty, _game = items()
        self.assertEqual(D.click_action(files, "0xb1"), ("launch", "org.gnome.Nautilus.desktop"))
        self.assertEqual(D.click_action(fx, "0xb1"), ("focus", "0xb1"))        # focused: stays
        self.assertEqual(D.click_action(kitty, "0xb1"), ("focus", "0xa2"))     # the most recent
        self.assertEqual(D.click_action(kitty, "0xa2"), ("focus", "0xa1"))     # then round them
        self.assertEqual(D.click_action(kitty, "0xa1"), ("focus", "0xa2"))
        self.assertIsNone(D.click_action({"windows": [], "app_id": None}, None))

    def test_commands(self):
        self.assertEqual(D.focus_argv("0xab")[:2], ["hyprctl", "dispatch"])
        self.assertIn("address:0xab", D.focus_argv("0xab")[2])
        self.assertIsNone(D.focus_argv("0xzz'; rm"))
        self.assertIsNone(D.close_argv("abc"))
        self.assertIn("hl.dsp.window.close({ window = 'address:0x1f' })", D.close_argv("0x1f")[2])
        with_uwsm = lambda name: "/usr/bin/uwsm" if name == "uwsm" else None  # noqa: E731
        self.assertEqual(D.launch_argv("kitty", which=with_uwsm), ["uwsm", "app", "--", "kitty.desktop"])
        self.assertEqual(D.launch_argv("kitty.desktop", "new-window", which=with_uwsm)[-1],
                         "kitty.desktop:new-window")
        self.assertEqual(D.launch_argv("kitty", which=lambda _n: None), ["gtk-launch", "kitty.desktop"])
        self.assertIsNone(D.launch_argv("kitty", "x;y", which=with_uwsm))
        self.assertIsNone(D.launch_argv("bad id", which=with_uwsm))
        self.assertEqual(D.new_window_action(["new-private-window", "new-window"]), "new-window")
        self.assertIsNone(D.new_window_action(["preferences"]))

    def test_events_only_the_wanted_ones(self):
        # socket2 without the relay sends everything: none of these costs a refresh
        quiet = D.read_events([b"windowtitle>>55d3", b"openlayer>>notifications", b"closelayer>>x",
                               b"activelayout>>kbd,English", b"activewindow>>kitty,shell", b"workspace>>2",
                               b"focusedmon>>DP-1,2", b"movewindow>>55d3,2", b"screencast>>1,0", b""])
        self.assertEqual(quiet, {"now": False, "titles": False, "place": False, "game": False, "ops": []})
        self.assertEqual(D.read_events([b"windowtitlev2>>55d3,a title"]),
                         {"now": False, "titles": True, "place": False, "game": False, "ops": []})
        got = D.read_events([b"activewindowv2>>55d3", b"urgent>>66e4", b"openwindow>>77,1,kitty,x"])
        self.assertTrue(got["now"] and got["game"])
        self.assertEqual(got["ops"], [("active", "0x55d3"), ("urgent", "0x66e4")])
        self.assertTrue(D.read_events([b"monitorremoved>>DP-3"])["place"])
        for name in (b"fullscreen>>1", b"workspacev2>>2,2", b"focusedmonv2>>DP-1,2", b"movewindowv2>>55,2,2",
                     b"changefloatingmode>>55,1", b"activespecial>>,DP-1"):
            self.assertTrue(D.read_events([name])["now"], name)

    def test_addresses_from_events(self):
        self.assertEqual(D.norm_address("55d3a1b0"), "0x55d3a1b0")
        self.assertEqual(D.norm_address("0x55"), "0x55")
        self.assertIsNone(D.norm_address(""))
        self.assertIsNone(D.norm_address("not,hex"))

    def test_pins(self):
        self.assertEqual(D.move_pin(["a", "b", "c"], "a", -1), ["a", "b", "c"])
        self.assertEqual(D.move_pin(["a", "b", "c"], "a", 1), ["b", "a", "c"])
        self.assertEqual(D.move_pin_to(["a", "b", "c"], "c", "a"), ["c", "a", "b"])
        self.assertEqual(D.move_pin_to(["a", "b"], "z", "a"), ["a", "b"])
        self.assertEqual(D.seed_pinned(["firefox.desktop", "", "firefox.desktop", "kitty.desktop"]),
                         ["firefox.desktop", "kitty.desktop"])
        self.assertIsNone(D.pinned_match(["org.a.x.desktop", "org.b.x.desktop"], "x"))   # ambiguous


# -- where things go ---------------------------------------------------------------------------
class Geometry(unittest.TestCase):
    MON = {"name": "DP-1", "x": 0, "y": 0, "width": 3440, "height": 1440, "scale": 1, "transform": 0,
           "activeWorkspace": {"id": 1}, "specialWorkspace": {"id": 0}}

    def test_logical_rect_scaled_and_rotated(self):
        self.assertEqual(D.logical_rect(self.MON), (0, 0, 3440, 1440))
        self.assertEqual(D.logical_rect(dict(self.MON, scale=0.8, width=2560, height=1080, y=-1350)),
                         (0, -1350, 3200, 1350))
        self.assertEqual(D.logical_rect(dict(self.MON, transform=1, width=1920, height=1080))[2:], (1080, 1920))

    def test_overlap(self):
        dock = (1500, 1360, 440, 72)
        ws = D.visible_workspaces(self.MON)
        self.assertEqual(ws, {1})
        self.assertTrue(D.overlapped(dock, [client("0x1", "a", at=(0, 38), size=(3440, 1400))], ws))
        self.assertFalse(D.overlapped(dock, [client("0x1", "a", at=(0, 38), size=(3440, 1300))], ws))
        self.assertFalse(D.overlapped(dock, [client("0x1", "a", ws=2, at=(0, 38), size=(3440, 1400))], ws))
        self.assertFalse(D.overlapped(None, CLIENTS, ws))
        self.assertEqual(D.visible_workspaces(dict(self.MON, specialWorkspace={"id": -98})), {1, -98})

    def test_should_hide(self):
        self.assertFalse(D.should_hide("never", False, False, True))
        self.assertTrue(D.should_hide("always", False, False, False))
        self.assertFalse(D.should_hide("always", True, False, False))       # hovered
        self.assertFalse(D.should_hide("always", False, True, False))       # a menu is open
        self.assertTrue(D.should_hide("overlap", False, False, True))
        self.assertFalse(D.should_hide("overlap", False, False, False))

    def test_toward_edge(self):
        rect = (100, 1008, 400, 64)                  # a bottom dock 8 px off a 1080 px screen
        grown = D.toward_edge(rect, "bottom", D.DOCK_MARGIN + D.EDGE_PX)
        self.assertFalse(D.inside((300, 1079), rect))
        self.assertTrue(D.inside((300, 1079), grown))  # resting on the hot edge: still on it
        self.assertFalse(D.inside((50, 1079), grown))  # beside it: not
        self.assertEqual(D.toward_edge((8, 100, 64, 400), "left", 11), (-3, 100, 75, 400))
        self.assertEqual(D.toward_edge((1840, 100, 64, 400), "right", 11), (1840, 100, 75, 400))
        self.assertIsNone(D.toward_edge(None, "bottom", 11))

    def test_layer_rect_and_inside(self):
        layers = {"DP-1": {"levels": {"2": [{"namespace": "waybar-main", "pid": 9, "x": 0, "y": 0, "w": 3440, "h": 38},
                                            {"namespace": "waybar-dock", "pid": 7, "x": 1500, "y": 1360, "w": 440,
                                             "h": 72}]}}}
        rect = D.layer_rect(layers, "DP-1", "waybar-dock", 7)
        self.assertEqual(rect, (1500, 1360, 440, 72))
        self.assertIsNone(D.layer_rect(layers, "DP-1", "waybar-dock", 8))     # another process's
        self.assertIsNone(D.layer_rect({}, "DP-2", "waybar-dock", 7))
        self.assertTrue(D.inside((1600, 1400), rect))
        self.assertFalse(D.inside((10, 10), rect))
        self.assertFalse(D.inside(None, rect))

    def test_preview_place(self):
        mon = (0, 0, 3440, 1440)
        anchors, margins = D.preview_place("bottom", (1600, 1370, 56, 56), mon, (300, 200))
        self.assertEqual(anchors, ("bottom", "left"))
        self.assertEqual(margins["left"], 1600 + 28 - 150)
        self.assertEqual(margins["bottom"], 1440 - 1370 + D.GAP)
        _a, margins = D.preview_place("bottom", (0, 1400, 40, 40), mon, (300, 200))
        self.assertEqual(margins["left"], D.SCREEN_EDGE)                       # never off the screen
        anchors, margins = D.preview_place("left", (8, 600, 56, 56), mon, (300, 200))
        self.assertEqual((anchors, margins["left"], margins["top"]), (("top", "left"), 8 + 56 + D.GAP, 528))
        anchors, margins = D.preview_place("right", (3376, 600, 56, 56), (3440, -200, 1080, 1920), (300, 200))
        self.assertEqual(anchors, ("top", "right"))
        self.assertEqual(margins["right"], 3440 + 1080 - 3376 + D.GAP)

    def test_thumb_scale(self):
        self.assertEqual(D.thumb_scale([2200, 1400]), 0.1)
        self.assertEqual(D.thumb_scale([100, 50]), 1.0)
        self.assertEqual(D.thumb_scale(None), 0.25)


class Effects(unittest.TestCase):
    """EFFECTS in dock.py's docstring: the pure part the frame clock runs."""

    def test_reduce_motion_and_magnify_switch(self):
        self.assertTrue(D.motion_ok(True))
        self.assertFalse(D.motion_ok(False))
        on = D.magnify_on
        self.assertTrue(on("theme", "yes", "dock"))
        self.assertFalse(on("theme", "", "dock"))
        self.assertFalse(on("theme", "no", "dock"))
        self.assertTrue(on("on", "", "dock"))                  # the setting beats the theme
        self.assertFalse(on("off", "yes", "dock"))
        self.assertFalse(on("on", "yes", "taskbar"))           # the dock only

    def test_falloff_is_a_half_cosine(self):
        self.assertEqual(D.falloff(0, 2.5), 1.0)
        self.assertAlmostEqual(D.falloff(1.25, 2.5), 0.5)
        self.assertEqual(D.falloff(2.5, 2.5), 0.0)
        self.assertEqual(D.falloff(-9, 2.5), 0.0)
        self.assertEqual(D.falloff(1, 0), 0.0)
        self.assertAlmostEqual(D.falloff(-1, 2.5), D.falloff(1, 2.5))
        values = [D.falloff(d / 10, 2.5) for d in range(0, 26)]
        self.assertEqual(values, sorted(values, reverse=True))   # never grows away from the pointer

    def test_magnify_scales(self):
        centers = [28, 84, 140, 196, 252]
        got = D.magnify_scales(centers, 140, 56, peak=1.6, radius=2.5)
        self.assertAlmostEqual(got[2], 1.6)                       # the icon under the pointer
        self.assertAlmostEqual(got[1], got[3])                    # neighbours alike
        self.assertTrue(1.0 < got[0] < got[1] < got[2])
        self.assertEqual(D.magnify_scales(centers, None, 56), [1.0] * 5)
        self.assertEqual(D.magnify_scales(centers, 140, 56, fixed={1})[1], 1.0)   # a line never grows
        far = D.magnify_scales(centers, 1000, 56)
        self.assertEqual(far, [1.0] * 5)

    def test_spread_keeps_the_point_under_the_pointer(self):
        starts, lengths = [0.0, 56.0, 112.0, 125.0, 181.0], [56.0, 56.0, 13.0, 56.0, 56.0]
        for pointer in (10.0, 84.0, 118.0, 150.0, 230.0):
            centers = [a + l / 2 for a, l in zip(starts, lengths)]
            scales = D.magnify_scales(centers, pointer, 56, fixed={2})
            new = D.spread(starts, lengths, scales, pointer)
            k = next(i for i in range(5) if pointer < starts[i] + lengths[i])
            f = (pointer - starts[k]) / lengths[k]
            self.assertAlmostEqual(new[k] + f * lengths[k] * scales[k], pointer, msg=pointer)
            for i in range(4):                                    # end to end, nothing overlaps
                self.assertAlmostEqual(new[i + 1], new[i] + lengths[i] * scales[i])
            before, after = D.spread_extents(starts, lengths, scales, new)
            self.assertGreaterEqual(before, 0)
            self.assertGreaterEqual(after, 0)
            self.assertLessEqual(max(before, after), D.spread_room(56) + 1e-6)

    def test_spread_at_rest_and_gaps(self):
        starts, lengths = [0.0, 60.0, 130.0], [50.0, 50.0, 50.0]
        self.assertEqual(D.spread(starts, lengths, [1.0, 1.0, 1.0], 75.0), starts)
        self.assertEqual(D.spread(starts, lengths, [1.0, 1.0, 1.0], None), starts)
        grown = D.spread(starts, lengths, [1.0, 2.0, 1.0], None)
        self.assertEqual(grown, [0.0, 60.0, 180.0])               # the gaps are kept
        self.assertEqual(D.spread([], [], [], 3.0), [])
        self.assertEqual(D.spread_extents([], [], [], []), (0.0, 0.0))

    def test_approach_is_frame_rate_independent(self):
        one = D.approach(1.0, 1.6, 1 / 60, 0.05)
        two = D.approach(D.approach(1.0, 1.6, 1 / 120, 0.05), 1.6, 1 / 120, 0.05)
        self.assertAlmostEqual(one, two)
        self.assertTrue(1.0 < one < 1.6)                          # part of the way, never past
        self.assertAlmostEqual(D.approach(1.0, 2.0, 0.05, 0.05), 1 + (1 - 2.718281828 ** -1), places=6)
        self.assertEqual(D.approach(1.0, 2.0, 0, 0.05), 1.0)
        self.assertEqual(D.approach(1.0, 2.0, 0.01, 0), 2.0)
        # it settles: after a few time constants it is there and stops
        v, going, t = 1.0, True, 0.0
        while going and t < 2:
            v, going = D.settle(D.approach(v, 1.12, 1 / 60, D.TAU_HOVER_S), 1.12)
            t += 1 / 60
        self.assertEqual(v, 1.12)
        self.assertLess(t, 0.6)
        self.assertEqual(D.settle(1.0, 1.0005), (1.0005, False))
        self.assertEqual(D.settle(1.0, 1.5), (1.0, True))

    def test_hop(self):
        self.assertEqual(D.hop(0), 0.0)
        self.assertAlmostEqual(D.hop(D.HOP_S / 2), 1.0)
        self.assertAlmostEqual(D.hop(D.HOP_S * 1.5), 1.0)         # again and again
        self.assertAlmostEqual(D.hop(D.HOP_S * 0.25), 0.75)
        self.assertEqual(D.hop(-1), 0.0)
        self.assertTrue(all(0 <= D.hop(t / 100) <= 1 for t in range(300)))

    def test_shelf_margins(self):
        task = D.shelf_margins("taskbar", "bottom", 48, True, True)
        self.assertEqual(task, {"top": D.TASKBAR_PAD, "bottom": 0, "left": 0, "right": 0})
        still = D.shelf_margins("dock", "bottom", 48, False, False)
        self.assertEqual(still, {"top": D.SHADOW_PAD, "bottom": D.DOCK_MARGIN,
                                 "left": D.SHADOW_PAD, "right": D.SHADOW_PAD})
        grow = D.shelf_margins("dock", "bottom", 48, False, True)
        mag = D.shelf_margins("dock", "bottom", 48, True, True)
        self.assertGreater(grow["top"], D.SHADOW_PAD - 1)
        self.assertGreater(mag["top"], grow["top"])               # a magnified icon rises higher
        self.assertGreaterEqual(mag["top"], (48 + 16) * (D.MAGNIFY_PEAK - 1) + 48 * D.HOP_FRAC)
        self.assertEqual(mag["left"], D.SHADOW_PAD + D.spread_room(64))
        self.assertEqual(grow["left"], D.SHADOW_PAD)              # growing in place needs no room along
        left = D.shelf_margins("dock", "left", 48, True, True)
        self.assertEqual((left["left"], left["right"]), (D.DOCK_MARGIN, mag["top"]))
        right = D.shelf_margins("dock", "right", 48, True, True)
        self.assertEqual((right["right"], right["left"]), (D.DOCK_MARGIN, mag["top"]))
        self.assertEqual(D.shelf_margins("dock", "bottom", 96, False, False)["top"], D.SHADOW_PAD)

    def test_icon_sizes(self):
        self.assertEqual(D.icon_sizes(48, 1.6), [48, 52, 56, 60, 64, 68, 72, 77])
        self.assertEqual(D.icon_sizes(48, 1.0), [48])
        self.assertEqual(D.icon_sizes(96, 1.12)[-1], 108)
        sizes = D.icon_sizes(48, 1.6)
        self.assertEqual(D.icon_pick(sizes, 48), 48)
        self.assertEqual(D.icon_pick(sizes, 43.2), 48)            # pressed: the size at rest
        self.assertEqual(D.icon_pick(sizes, 62), 64)              # a tie goes up: never blurred up
        self.assertEqual(D.icon_pick(sizes, 76.8), 77)
        self.assertEqual(D.icon_pick([], 50.4), 50)

    def test_harness_file(self):
        self.assertEqual(D.read_harness({}), {})
        path = os.path.join(helpers.SCRATCH, "harness-test.json")
        with open(path, "w") as handle:
            json.dump({"monitor": "X-1", "hold": 0.5}, handle)
        self.assertEqual(D.read_harness({D.HARNESS_ENV: path})["monitor"], "X-1")
        with open(path, "w") as handle:
            handle.write("[1, 2]")
        self.assertEqual(D.read_harness({D.HARNESS_ENV: path}), {})
        self.assertEqual(D.read_harness({D.HARNESS_ENV: path + ".gone"}), {})

    def test_every_theme_draws_its_dock(self):
        themes = os.path.expanduser("~/.config/themes")
        names = [n for n in os.listdir(themes)
                 if os.path.isfile(os.path.join(themes, n, "theme.conf"))]
        self.assertIn("orchard", names)
        for name in names:
            with self.subTest(name):
                path = os.path.join(themes, name, "dock.css")
                self.assertTrue(os.path.isfile(path), f"{name} has no dock.css")
                with open(path) as handle:
                    css = handle.read()
                for sel in ("#dock.dock-layout-dock", "#dock.dock-layout-taskbar", "button.dock-item"):
                    self.assertIn(sel, css, f"{name}: {sel}")

    def test_the_stylesheet_eases_and_the_code_draws(self):
        with open(D.CSS_FILE) as handle:
            css = handle.read()
        for needle in ("transition:", "@keyframes dock-urgent", ".dock-dot.lit", "button.dock-item:active",
                       ".bouncing", "@define-color dock-shadow"):
            self.assertIn(needle, css)
        with open(DOCK_PY) as handle:
            text = handle.read()
        # the clock runs only while something moves, and only on the frame clock
        self.assertIn("add_tick_callback(self.on_tick)", text)
        self.assertIn("gtk-enable-animations", text)
        self.assertNotIn("timeout_add(16", text)


class ToolboxButton(unittest.TestCase):
    def test_record_is_what_toolbox_fit_reads(self):
        rec = D.toolbox_record(4242, "DP-1", "taskbar", "bottom", (0, 0, 3440, 1440),
                               (0, 1400, 3440, 40), (3300.0, 3), (34, 34), 40)
        self.assertEqual(rec["button"], [3300, 1403, 34, 34])
        self.assertEqual((rec["pid"], rec["output"], rec["reserved"]), (4242, "DP-1", 40))
        sys.path.insert(0, os.path.expanduser("~/.config/waybar/scripts"))
        import toolbox_fit
        dock = toolbox_fit.live_dock(json.loads(json.dumps(rec)), lambda pid: pid == 4242)
        self.assertEqual(dock["button"], (3300, 1403, 34, 34))
        self.assertIsNone(toolbox_fit.live_dock(rec, lambda pid: False))
        self.assertEqual(D.toolbox_record(1, "DP-1", "dock", "left", (0, 0, 10, 10), (0, 0, 5, 5),
                                          (0, 0), (1, 1), None)["reserved"], 0)

    def test_paths_meet(self):
        sys.path.insert(0, os.path.expanduser("~/.config/waybar/scripts"))
        import toolbox_fit
        self.assertEqual(D.TOOLBOX_BUTTON, toolbox_fit.DOCK_BUTTON)
        self.assertTrue(D.TOOLBOX_SH.endswith("/waybar/scripts/toolbox.sh"))
        with open(D.TOOLBOX_SH) as handle:
            self.assertIn('DOCK_BUTTON=${XDG_RUNTIME_DIR:-/run/user/$UID}/dock-toolbox.json', handle.read())
        self.assertEqual(D.TOOLBOX_GLYPH, "\uf1de")

    def test_the_button_is_built_and_styled(self):
        with open(DOCK_PY) as handle:
            text = handle.read()
        self.assertIn('spawn(TOOLBOX_SH, "toggle")', text)
        self.assertIn('spawn(TOOLBOX_SH, "refit")', text)
        self.assertIn("engine.forget_toolbox()", text)
        with open(os.path.join(helpers.SCRIPTS, "dock.css")) as handle:
            css = handle.read()
        self.assertIn("button.dock-toolbox", css)
        self.assertIn(".dock-toolbox-glyph", css)


class LookAndClock(unittest.TestCase):
    def test_clock_never_has_seconds(self):
        moment = datetime(2026, 10, 29, 15, 4, 5)
        self.assertEqual(D.clock_text(moment, {"clock": "24", "seconds": "on", "date": "iso"}),
                         ("15:04", "2026-10-29"))
        self.assertEqual(D.clock_text(moment, {"clock": "12", "seconds": "on", "date": "short"})[0], "3:04 PM")

    def test_css_imports_made_absolute_and_missing_dropped(self):
        folder = tempfile.mkdtemp(dir=helpers.SCRATCH)
        os.makedirs(os.path.join(folder, "a", "b"))
        with open(os.path.join(folder, "there.css"), "w") as handle:
            handle.write("")
        base = os.path.join(folder, "a", "b", "dock.css")
        with open(base, "w") as handle:
            handle.write('@import url("../../there.css");\n#dock {}\n@import url("../../gone.css");\n')
        text = D.css_text(base)
        self.assertIn(f'@import url("file://{folder}/there.css");', text)
        self.assertNotIn('@import url("../../gone.css")', text)
        self.assertIn("#dock {}", text)
        self.assertEqual(D.css_text(os.path.join(folder, "none.css")), "")

    def test_real_stylesheet_imports_the_panels_and_the_theme(self):
        with open(D.CSS_FILE) as handle:
            text = handle.read()
        self.assertIn('@import url("../../waybar/panel.css");', text)
        self.assertTrue(text.rstrip().endswith('@import url("../../waybar/generated/theme-dock.css");'))


class TrayParsing(unittest.TestCase):
    def test_parse_item(self):
        self.assertEqual(D.parse_item(":1.42/StatusNotifierItem"), (":1.42", "/StatusNotifierItem"))
        self.assertEqual(D.parse_item(":1.7/org/ayatana/NotificationItem/steam"),
                         (":1.7", "/org/ayatana/NotificationItem/steam"))
        self.assertEqual(D.parse_item("org.kde.StatusNotifierItem-12-1"),
                         ("org.kde.StatusNotifierItem-12-1", "/StatusNotifierItem"))
        self.assertEqual(D.parse_item("/Item", sender=":1.5"), (":1.5", "/Item"))

    def test_pixmaps(self):
        small = (16, 16, bytes(16 * 16 * 4))
        big = (32, 32, bytes(32 * 32 * 4))
        broken = (64, 64, b"\0" * 10)
        self.assertEqual(D.best_pixmap([big, small, broken], 18)[0], 32)
        self.assertEqual(D.best_pixmap([small], 18)[0], 16)
        self.assertIsNone(D.best_pixmap([broken], 18))
        self.assertIsNone(D.best_pixmap(None, 18))
        self.assertEqual(D.argb_to_rgba(bytes([0xFF, 1, 2, 3, 0x80, 4, 5, 6])), bytes([1, 2, 3, 0xFF, 4, 5, 6, 0x80]))

    def test_tooltip(self):
        self.assertEqual(D.tooltip_text({"ToolTip": ("", [], "Steam", "<b>Online</b>")}), "Steam\nOnline")
        self.assertEqual(D.tooltip_text({"Title": "Remmina"}), "Remmina")
        self.assertEqual(D.tooltip_text({}), "")

    def test_menu_tree(self):
        layout = (0, {"children-display": "submenu"}, [
            (1, {"label": "_Show"}, []),
            (2, {"type": "separator"}, []),
            (3, {"label": "Mute", "toggle-type": "checkmark", "toggle-state": 1, "enabled": False}, []),
            (4, {"label": "More", "visible": True}, [(5, {"label": "Inner"}, [])]),
            (6, {"label": "Hidden", "visible": False}, []),
        ])
        tree = D.menu_tree(layout)
        kids = tree["children"]
        self.assertEqual([k["id"] for k in kids], [1, 2, 3, 4, 6])
        self.assertEqual(kids[0]["label"], "_Show")
        self.assertTrue(kids[1]["separator"])
        self.assertEqual((kids[2]["toggle"], kids[2]["state"], kids[2]["enabled"]), ("checkmark", True, False))
        self.assertEqual(kids[3]["children"][0]["label"], "Inner")
        self.assertFalse(kids[4]["visible"])
        self.assertIsNone(D.menu_tree("garbage"))


class TopBarTakeover(unittest.TestCase):
    """TOP BAR: the pills the taskbar stands in for, and the status
    buttons' and the classic menu's pure parts."""
    def cfg(self, **kw):
        return dict(D.DEFAULTS, **dict({"enabled": True, "layout": "taskbar"}, **kw))

    def test_only_the_taskbar_takes_pills(self):
        """The dock takes only the keyboard layout (to the toolbox card);
        off, nothing at all."""
        self.assertEqual(D.bar_takeover(dict(D.DEFAULTS)), [])
        self.assertEqual(D.bar_takeover(self.cfg(layout="dock")), ["hyprland/language"])
        self.assertEqual(D.bar_takeover(self.cfg(enabled=False)), [])

    def test_each_setting_takes_its_pills_and_power_always_goes(self):
        self.assertEqual(D.bar_takeover(self.cfg()),
                         ["custom/day", "custom/clock", "custom/menuclock", "custom/weather",
                          "custom/network", "pulseaudio", "ext/workspaces", "custom/notifications",
                          "battery", "custom/recording", "custom/mic", "custom/camera", "custom/location",
                          "custom/power", "hyprland/language"])
        self.assertEqual(D.bar_takeover(self.cfg(clock=False, weather=False, network=False, sound=False,
                                                 workspaces=False, notifications=False, battery=False,
                                                 privacy=False)),
                         ["custom/power", "hyprland/language"])
        self.assertNotIn("pulseaudio", D.bar_takeover(self.cfg(sound=False)))

    def test_start_menu_setting(self):
        self.assertEqual(D.DEFAULTS["start_menu"], "launcher")
        self.assertEqual(D.set_key("start_menu", "Classic")["start_menu"], "classic")
        with self.assertRaises(SystemExit):
            D.set_key("start_menu", "metro")

    def test_set_restarts_the_bar_only_when_the_takeover_changes(self):
        calls = []
        real_dry, real_restart = D.dry_env, D.restart_bar
        D.dry_env, D.restart_bar = (lambda: False), (lambda: calls.append(1))
        real_switch, real_refit, real_poke = D.switch_unit, D.toolbox_refit, D.poke_toolbox_pill
        D.switch_unit = D.toolbox_refit = D.poke_toolbox_pill = lambda *a: None
        try:
            D.write_settings(self.cfg())
            D.set_key("combine", "off")             # not a pill: no restart
            self.assertEqual(calls, [])
            D.set_key("sound", "off")               # pulseaudio comes back to the bar
            self.assertEqual(calls, [1])
            D.set_key("layout", "dock")             # every pill comes back
            self.assertEqual(calls, [1, 1])
        finally:
            D.dry_env, D.restart_bar = real_dry, real_restart
            D.switch_unit, D.toolbox_refit, D.poke_toolbox_pill = real_switch, real_refit, real_poke

    def test_the_dock_takes_the_privacy_pills_only_with_the_bar_off(self):
        lang = list(D.CARD_PILLS)
        self.assertEqual(D.bar_takeover(self.cfg(layout="dock", top_bar=False)), list(D.PRIVACY_PILLS) + lang)
        self.assertEqual(D.bar_takeover(self.cfg(layout="dock", top_bar=False, privacy=False)), lang)
        self.assertEqual(D.bar_takeover(self.cfg(layout="dock")), lang)

    def test_status_wanted(self):
        self.assertEqual(D.status_wanted(dict(D.DEFAULTS)), set())
        self.assertEqual(D.status_wanted(self.cfg()),
                         set(D.STATUS_KEYS) | set(D.PRIVACY_KEYS) | {"notifications", "battery"})
        self.assertEqual(D.status_wanted(self.cfg(privacy=False, battery=False, sound=False)),
                         {"network", "weather", "notifications"})
        self.assertEqual(D.status_wanted(self.cfg(layout="dock")), set())
        self.assertEqual(D.status_wanted(self.cfg(layout="dock", top_bar=False)), set(D.PRIVACY_KEYS))
        # every pill has its clicks, its setting, and a source
        for key in D.PILL_SETTING:
            self.assertIn(key, D.PILL_CLICKS)
            self.assertTrue(key in D.PILL_WATCH or key in ("notifications", "battery"), key)

    def test_pill_state(self):
        self.assertEqual(D.pill_state('{"text": "x", "tooltip": "t", "class": "active"}'), ("x", "t", "active"))
        self.assertEqual(D.pill_state('{"text": "x"}'), ("x", "", ""))
        self.assertEqual(D.pill_state('{"text": "x", "class": ["a", "b"]}'), ("x", "", ""))
        self.assertIsNone(D.pill_state("nope"))

    def test_battery_text(self):
        self.assertEqual(D.battery_text(None, ""), ("", "", ""))
        self.assertEqual(D.battery_text(100, "Full"), ("\uf240 100%", "Battery 100% · full", "full"))
        self.assertEqual(D.battery_text(64, "Discharging"), ("\uf241 64%", "Battery 64% · on battery", ""))
        self.assertEqual(D.battery_text(20, "Discharging")[2], "warning")
        self.assertEqual(D.battery_text(10, "Discharging")[2], "critical")
        self.assertEqual(D.battery_text(10, "Charging"),
                         (f"{D.CHARGING_GLYPH} \uf244 10%", "Battery 10% · charging", "charging"))
        self.assertEqual(D.battery_text(130, "Unknown")[0], "\uf240 100%")

    def test_read_battery(self):
        root = tempfile.mkdtemp(dir=helpers.SCRATCH)
        self.assertEqual(D.read_battery(root), (None, ""))
        os.makedirs(os.path.join(root, "AC"))
        os.makedirs(os.path.join(root, "BAT0"))
        with open(os.path.join(root, "BAT0", "capacity"), "w") as fh:
            fh.write("57\n")
        with open(os.path.join(root, "BAT0", "status"), "w") as fh:
            fh.write("Discharging\n")
        self.assertEqual(D.read_battery(root), (57, "Discharging"))
        self.assertEqual(D.read_battery(os.path.join(root, "nope")), (None, ""))

    def test_workspace_buttons(self):
        """Only the workspace in front: the focused screen's, or one
        screen's on its own bar; none for a special one or no screen."""
        mons = [{"name": "eDP-1", "focused": True, "activeWorkspace": {"id": 1, "name": "1"}},
                {"name": "DP-1", "focused": False, "activeWorkspace": {"id": 3, "name": "code"}}]
        self.assertEqual(D.workspace_buttons(mons), [(1, "1")])
        self.assertEqual(D.workspace_buttons(mons, "DP-1"), [(3, "code")])
        self.assertEqual(D.workspace_buttons(mons, "HDMI-A-1"), [])
        self.assertEqual(D.workspace_buttons(None), [])
        special = [{"name": "eDP-1", "focused": True, "activeWorkspace": {"id": -98, "name": "special:x"}}]
        self.assertEqual(D.workspace_buttons(special), [])
        self.assertEqual(D.OVERVIEW_ARGV[:2], ["hyprctl", "eval"])
        self.assertIn("hyprview.toggle", D.OVERVIEW_ARGV[2])

    def test_top_bar_off(self):
        """TOP BAR OFF: bar_hidden needs the dock on; switching it off while
        the dock is off is refused; a change restarts the bar, on either
        layout, and so does switching the dock off with the bar gone."""
        self.assertTrue(D.DEFAULTS["top_bar"])
        self.assertFalse(D.bar_hidden(dict(D.DEFAULTS)))
        self.assertTrue(D.bar_hidden(self.cfg(top_bar=False)))
        self.assertTrue(D.bar_hidden(self.cfg(top_bar=False, layout="dock")))
        self.assertFalse(D.bar_hidden(self.cfg(top_bar=False, enabled=False)))
        calls = []
        real_dry, real_restart = D.dry_env, D.restart_bar
        D.dry_env, D.restart_bar = (lambda: False), (lambda: calls.append(1))
        real_switch, real_refit, real_poke = D.switch_unit, D.toolbox_refit, D.poke_toolbox_pill
        D.switch_unit = D.toolbox_refit = D.poke_toolbox_pill = lambda *a: None
        try:
            D.write_settings(self.cfg(enabled=False))
            with self.assertRaises(SystemExit):
                D.set_key("top_bar", "off")
            self.assertTrue(D.read_settings()["top_bar"])     # nothing written
            D.write_settings(self.cfg(layout="dock"))
            D.set_key("top_bar", "off")
            self.assertEqual(calls, [1])
            D.set_key("enabled", "off")             # the bar is back
            self.assertEqual(calls, [1, 1])
            self.assertFalse(D.read_settings()["top_bar"])    # remembered for the next time
            D.set_key("enabled", "on")              # and gone again
            self.assertEqual(calls, [1, 1, 1])
            D.set_key("top_bar", "on")
            self.assertEqual(calls, [1, 1, 1, 1])
        finally:
            D.dry_env, D.restart_bar = real_dry, real_restart
            D.switch_unit, D.toolbox_refit, D.poke_toolbox_pill = real_switch, real_refit, real_poke

    def test_clock_in_a_ja_theme(self):
        moment = datetime(2026, 10, 30, 21, 5)         # a Friday
        t, d = D.clock_text(moment, None, "ja")
        self.assertEqual(d, "10月30日(金)")
        self.assertEqual(t, D.clock_text(moment)[0])   # the time as region.conf says
        self.assertNotIn("月", D.clock_text(moment, None, "en")[1])

    def test_volume_text(self):
        self.assertEqual(D.volume_text("Volume: 0.45\n"), ("\uf027 45%", "Volume 45%"))
        self.assertEqual(D.volume_text("Volume: 0.80"), ("\uf028 80%", "Volume 80%"))
        self.assertEqual(D.volume_text("Volume: 0.00"), ("\uf026 0%", "Volume 0%"))
        self.assertEqual(D.volume_text("Volume: 0.30 [MUTED]"), (D.MUTED_GLYPH, "Muted (30%)"))
        self.assertIsNone(D.volume_text(""))
        self.assertIsNone(D.volume_text("no such node"))

    def test_pill_text(self):
        self.assertEqual(D.pill_text('{"text": "<b>x</b>", "tooltip": "t", "class": "c"}'), ("<b>x</b>", "t"))
        self.assertEqual(D.pill_text('{"text": "x"}'), ("x", ""))
        for bad in ("", "nope", "[]", '{"text": 3}'):
            self.assertIsNone(D.pill_text(bad))

    def test_menu_programs(self):
        got = D.menu_programs([("Steam", "steam.desktop", "Network;Game;"),
                               ("Files", "files.desktop", "GTK;Utility;Core;"),
                               ("blender", "b.desktop", "Graphics;3DGraphics;"),
                               ("Krita", "k.desktop", "Graphics;"),
                               ("Odd", "odd.desktop", ""),
                               ("Files again", "files.desktop", "Utility;")])
        self.assertEqual([title for (title, _icon), _ in got],
                         ["Accessories", "Games", "Graphics", "Other"])
        self.assertEqual(dict((t, items) for (t, _i), items in got)["Graphics"],
                         [("blender", "b.desktop"), ("Krita", "k.desktop")])   # by name, any case
        self.assertEqual(dict((t, items) for (t, _i), items in got)["Accessories"],
                         [("Files", "files.desktop")])                         # each id once


class Wiring(unittest.TestCase):
    def test_unit_ships_off_and_like_the_island(self):
        unit = os.path.expanduser("~/.config/systemd/user/dock.service")
        with open(unit) as handle:
            text = handle.read()
        for line in ("PartOf=graphical-session.target", "Restart=on-failure", "WatchdogSec=20",
                     "MemoryHigh=150M", "dock.py daemon", 'ExecCondition=/usr/lib/systemd/systemd-xdg-autostart-condition "Hyprland" ""'):
            self.assertIn(line, text)
        # TOP BAR OFF: however the dock stops, the bar comes back.
        self.assertIn("ExecStopPost=-/usr/bin/systemctl --user --no-block start waybar.service", text)
        # Ships OFF even when this install has it on: the repo's sync.sh keeps
        # dock.service out of the units a new install enables.
        sync = os.path.expanduser("~/Github/Atrium/sync.sh")
        if os.path.exists(sync):
            with open(sync) as handle:
                self.assertRegex(handle.read(), r"grep -vE '\^\([^)]*\bdock\b[^)]*\)", "dock.service ships OFF")

    def test_the_toolbox_runs_without_the_bar(self):
        """With the top bar off the bar is skipped (its condition) and the
        toolbox -- the session's tray watcher -- must stay up on its own."""
        units = os.path.expanduser("~/.config/systemd/user")
        with open(os.path.join(units, "waybar-toolbox.service")) as handle:
            toolbox = handle.read()
        self.assertRegex(toolbox, r"(?m)^PartOf=graphical-session\.target$")
        self.assertRegex(toolbox, r"(?m)^WantedBy=graphical-session\.target$")
        self.assertIn("ExecStart=%h/.config/waybar/scripts/toolbox-main.sh", toolbox)
        with open(os.path.join(units, "waybar.service.d", "hyprland.conf")) as handle:
            bar = handle.read()
        self.assertIn("ExecCondition=%h/.config/waybar/scripts/bar-wanted.sh", bar)
        self.assertRegex(bar, r"(?m)^After=dock\.service$")
        self.assertIn("ExecStartPost=-%h/.config/waybar/scripts/toolbox-follow.sh", bar)

    def test_events_are_valid_hyprbus_names(self):
        import hyprbus
        hyprbus.hello(D.DOCK_EVENTS)          # raises on a bad name


if __name__ == "__main__":
    unittest.main()
