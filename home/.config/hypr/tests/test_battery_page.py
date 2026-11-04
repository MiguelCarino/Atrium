"""Settings > Battery and what goes with it: battery-settings.py (the page's
backend: status, set), the page's words and drawing, the pages' "needs"
(_catalog.present(): the page, its search hits and the launcher's items only
with a battery), the launcher's battery commands, the toolbox's Battery row
(draw in W, the saver's leaf), and the cross-track pieces this track
finished: power_state.plugged(), the quick display panel's brightness on a
laptop, window-look's held_by_saver, install.sh's idle init and
hypridle.conf keep, sync.sh's exclude, theme-schedule's margin.

Hermetic: the battery is a fake power_supply tree (helpers.fake_power_supply)
pointed at by ATRIUM_POWER_SUPPLY for one test at a time -- without one,
helpers.py makes this a desktop. battery.json is a scratch file; no command
is run (battery-settings' saver_auto gets a recorder), no window is shown,
and nothing reaches Hyprland, tuned-ppd or the firmware."""
import importlib.util
import io
import json
import os
import re
import tempfile
import unittest
from unittest import mock

import helpers
import power_state as ps

from settings_pages import _catalog as C

BS = helpers.import_script("battery-settings.py", "battery_settings")
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(HERE))))
WAYBAR_SCRIPTS = os.path.join(os.path.dirname(os.path.dirname(helpers.SCRIPTS)), "waybar", "scripts")


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Tree(unittest.TestCase):
    """A scratch folder per test, battery.json in it."""
    def setUp(self):
        self.dir = tempfile.mkdtemp(dir=helpers.SCRATCH)
        for patch in (mock.patch.object(ps, "SETTINGS_FILE", os.path.join(self.dir, "battery.json")),
                      mock.patch.object(ps, "POWER_STATE", os.path.join(self.dir, "power-state.json")),
                      mock.patch.object(ps, "SAVER_STATE", os.path.join(self.dir, "battery-saver.json"))):
            patch.start()
            self.addCleanup(patch.stop)
        ps.reset_cache()
        self.addCleanup(ps.reset_cache)

    def laptop(self, **battery):
        root = helpers.fake_power_supply(os.path.join(self.dir, "ps"),
                                         battery=dict({"status": "Discharging", "capacity": 40}, **battery),
                                         ac=battery.get("status") not in (None, "Discharging"))
        patch = mock.patch.dict(os.environ, {"ATRIUM_POWER_SUPPLY": root})
        patch.start()
        self.addCleanup(patch.stop)
        return root

    def mouse_only(self):
        root = helpers.fake_power_supply(os.path.join(self.dir, "ps"), extra={
            "hidpp_battery_0": {"type": "Battery", "scope": "Device", "capacity": 50, "status": "Discharging"}})
        patch = mock.patch.dict(os.environ, {"ATRIUM_POWER_SUPPLY": root})
        patch.start()
        self.addCleanup(patch.stop)


# -- battery-settings.py -----------------------------------------------------------------
class Parse(unittest.TestCase):
    def test_warn_at(self):
        self.assertEqual(BS.parse("warn_at", "20,10,5"), [20, 10, 5])
        self.assertEqual(BS.parse("warn_at", "5 20 10 20"), [20, 10, 5])      # spaces, a repeat
        self.assertEqual(BS.parse("warn_at", "15%,5%"), [15, 5])
        self.assertEqual(BS.parse("warn_at", "none"), [])
        for bad in ("0", "100", "twenty", "20,x"):
            with self.assertRaises(ValueError):
                BS.parse("warn_at", bad)

    def test_saver_keys(self):
        self.assertEqual(BS.parse("saver_auto_at", "15"), 15)
        self.assertEqual(BS.parse("saver_auto_at", "0"), 0)
        self.assertIs(BS.parse("saver_on_unplug", "On"), True)
        self.assertIs(BS.parse("saver_on_unplug", "off"), False)
        for key, bad in (("saver_auto_at", "100"), ("saver_auto_at", "-1"), ("saver_on_unplug", "maybe"),
                         ("charge_limit", "80"), ("nope", "1")):
            with self.assertRaises(ValueError):
                BS.parse(key, bad)

    def test_choices_keep_a_hand_set_value(self):
        got = BS.choices(dict(ps.DEFAULTS, warn_at=[33, 5], saver_auto_at=25))
        self.assertIn(33, got["warn_at"])
        self.assertEqual(got["saver_auto_at"], [0, 10, 15, 20, 25, 30])
        self.assertEqual(got["warn_at"], sorted(got["warn_at"], reverse=True))


class SetValue(Tree):
    def recorder(self):
        calls = []

        def run(argv, timeout=None):
            calls.append(argv)
            return mock.Mock(returncode=0, stderr="", stdout="")
        return calls, run

    def test_saver_setting_runs_auto_on_a_laptop(self):
        self.laptop()
        calls, run = self.recorder()
        self.assertEqual(BS.set_value("saver_auto_at", "30", run=run), (0, None))
        self.assertEqual(ps.load_settings()["saver_auto_at"], 30)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1:], [BS.SAVER, "auto"])

    def test_warnings_need_no_auto(self):
        self.laptop()
        calls, run = self.recorder()
        self.assertEqual(BS.set_value("warn_at", "25,5", run=run), (0, None))
        self.assertEqual(ps.load_settings()["warn_at"], [25, 5])
        self.assertEqual(calls, [])

    def test_a_desktop_starts_nothing(self):
        calls, run = self.recorder()
        self.assertEqual(BS.set_value("saver_on_unplug", "on", run=run), (0, None))
        self.assertTrue(ps.load_settings()["saver_on_unplug"])
        self.assertEqual(calls, [])

    def test_a_bad_value_writes_nothing(self):
        calls, run = self.recorder()
        code, message = BS.set_value("saver_auto_at", "150", run=run)
        self.assertEqual(code, 2)
        self.assertIn("0-99", message)
        self.assertFalse(os.path.exists(ps.SETTINGS_FILE))
        self.assertEqual(calls, [])

    def test_a_failed_auto_still_saves(self):
        self.laptop()
        code, message = BS.set_value("saver_auto_at", "10",
                                     run=lambda argv, timeout=None: mock.Mock(returncode=1, stderr="boom\n"))
        self.assertEqual(code, 0)
        self.assertIn("boom", message)
        self.assertEqual(ps.load_settings()["saver_auto_at"], 10)

    def test_main_exit_codes(self):
        with mock.patch.object(BS, "status", lambda: {"ok": True}), \
                mock.patch("sys.stdout", new_callable=io.StringIO), \
                mock.patch("sys.stderr", new_callable=io.StringIO):
            self.assertEqual(BS.main(["set", "warn_at", "10"]), 0)
            self.assertEqual(BS.main(["set", "warn_at", "abc"]), 2)
            self.assertEqual(BS.main(["frobnicate"]), 2)
            self.assertEqual(BS.main(["status"]), 0)


class Status(Tree):
    def status(self):
        with mock.patch.object(BS, "charge_status", lambda: {"supported": True, "installed": False}), \
                mock.patch.object(BS, "early_warnings", lambda: None):
            return BS.status()

    def test_desktop(self):
        st = self.status()
        self.assertFalse(st["has_battery"])
        self.assertIsNone(st["battery"])
        self.assertIsNone(st["plugged"])
        self.assertEqual(st["settings"], ps.DEFAULTS)
        self.assertFalse(st["watcher"])

    def test_laptop_on_battery_with_warnings_given(self):
        self.laptop(capacity=9)
        with open(ps.POWER_STATE, "w") as handle:
            json.dump({"on_battery": True, "warned": [20, 10]}, handle)
        st = self.status()
        self.assertTrue(st["has_battery"] and st["on_battery"])
        self.assertIs(st["plugged"], False)
        self.assertEqual(st["battery"]["capacity"], 9)
        self.assertEqual(st["warned"], [20, 10])
        self.assertTrue(st["watcher"])
        self.assertIsNotNone(st["saver"])                   # the real battery-saver.py's status()
        self.assertEqual(st["saver"]["active"], False)
        self.assertEqual(st["charge"], {"supported": True, "installed": False})

    def test_plugged_in_clears_the_warned_list(self):
        self.laptop(status="Charging")
        with open(ps.POWER_STATE, "w") as handle:
            json.dump({"on_battery": False, "warned": [20]}, handle)
        self.assertEqual(self.status()["warned"], [])

    def test_a_status_writes_nothing(self):
        self.laptop()
        before = sorted(os.listdir(self.dir))
        self.status()
        self.assertEqual(sorted(os.listdir(self.dir)), before)


class EarlyWarnings(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(dir=helpers.SCRATCH)
        self.conf = os.path.join(self.dir, "emergency.conf")

    def test_no_conf_is_none_and_is_not_written(self):
        self.assertIsNone(BS.early_warnings(self.conf))
        self.assertFalse(os.path.exists(self.conf))

    def test_a_fast_source(self):
        with open(self.conf, "w") as handle:
            handle.write("country=MX\nsources=sasmex\nbattery_poll=off\n")
        got = BS.early_warnings(self.conf)
        self.assertFalse(got["battery_poll"])
        self.assertEqual(len(got["fast"]), 1)
        self.assertIn("SASMEX", got["fast"][0])
        with open(self.conf, "w") as handle:
            handle.write("country=MX\nsources=sasmex\nbattery_poll=on\n")
        self.assertTrue(BS.early_warnings(self.conf)["battery_poll"])

    def test_only_slow_sources_is_none(self):
        with open(self.conf, "w") as handle:
            handle.write("country=US\nsources=usgs\n")
        self.assertIsNone(BS.early_warnings(self.conf))


# -- the pages' "needs" and the launcher -------------------------------------------------
class Needs(Tree):
    def ids(self):
        return [p["id"] for p in C.read_pages()]

    def test_battery_page_only_with_a_battery(self):
        self.assertNotIn("battery", self.ids())                         # helpers.py: a desktop
        self.assertIn("battery", [p["id"] for p in C.read_pages(everything=True)])
        self.laptop()
        self.assertIn("battery", self.ids())

    def test_a_mouse_battery_is_not_a_laptop(self):
        self.mouse_only()
        self.assertNotIn("battery", self.ids())

    def test_present(self):
        self.assertTrue(C.present({"id": "x"}))
        self.assertTrue(C.present({"id": "x", "needs": "warp-drive"}))     # a typo never hides a page
        self.assertFalse(C.present({"id": "x", "needs": "battery"}))
        self.laptop()
        self.assertTrue(C.present({"id": "x", "needs": "battery"}))

    def test_search_words_find_the_page_on_a_laptop(self):
        self.laptop()
        pages = C.read_pages()
        for words in ("battery", "charge limit", "battery saver", "battery health", "cycle count",
                      "low battery", "stop charging", "batería"):
            self.assertEqual(C.resolve(pages, words), "battery", words)
        self.assertEqual(C.resolve(pages, "idle"), "power")

    def test_a_desktop_search_for_battery_is_as_before(self):
        self.assertEqual(C.resolve(C.read_pages(), "battery"), "power")

    def test_page_source(self):
        with open(os.path.join(helpers.SCRIPTS, "settings_pages", "battery.py")) as handle:
            page = C.page_of(handle.read())
        self.assertEqual((page["id"], page["needs"], page["group"]), ("battery", "battery", "System"))
        for word in ("battery saver", "charge limit", "health", "cycles", "watts", "low battery"):
            self.assertIn(word, page["keywords"])


class Launcher(Tree):
    @classmethod
    def setUpClass(cls):
        cls.L = helpers.import_script("launcher.py", "launcher")

    def names(self):
        with mock.patch.object(self.L, "claude_cli", lambda: None):
            return [i.name for i in self.L.command_items()]

    def test_battery_commands_only_on_a_laptop(self):
        self.assertFalse(set(self.L.BATTERY_ONLY) & set(self.names()))
        self.laptop()
        self.assertTrue(set(self.L.BATTERY_ONLY) <= set(self.names()))

    def test_every_battery_command_is_in_the_table(self):
        table = {c[0]: c[3] for c in self.L.COMMANDS}
        for name in self.L.BATTERY_ONLY:
            self.assertIn(name, table)
            self.assertIn("sh", table[name][:1])
        self.assertIn("battery-saver.py", " ".join(table["Battery saver: on"]))
        self.assertIn("charge-limit.py", " ".join(table["Charge limit: 80 %"]))

    def test_settings_item_on_a_laptop(self):
        self.laptop()
        items = self.L.settings_items("charge limit")
        self.assertEqual([i.name for i in items][:1], ["Settings: Battery"])
        self.assertEqual(self.L.SETTINGS_ICONS["battery"], "battery")

    def test_help_text_says_backlight(self):
        self.assertIn("laptop panel's own backlight", self.L.__doc__)


# -- the page ----------------------------------------------------------------------------
class Words(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from settings_pages import common  # noqa: F401  (Gtk 3 first, as settings.py does)
            from settings_pages import battery
        except Exception as exc:                         # noqa: BLE001
            raise unittest.SkipTest(f"settings_pages.battery not importable: {exc}")
        cls.B = battery

    BAT = {"name": "BATT", "capacity": 64, "status": "Discharging", "watts": 10.84, "health_pct": 57,
           "cycles": 255, "minutes_left": 165, "minutes_to_full": None}

    def test_hm(self):
        self.assertEqual(self.B.hm(165), "2 h 45 min")
        self.assertEqual(self.B.hm(17), "17 min")
        self.assertIsNone(self.B.hm(0))
        self.assertIsNone(self.B.hm(None))
        self.assertIsNone(self.B.hm(60 * 72))

    def test_summary(self):
        title, sub = self.B.summary(self.BAT, False)
        self.assertEqual(title, "64 %  ·  on battery")
        self.assertEqual(sub, "2 h 45 min left  ·  drawing 10.8 W")
        title, sub = self.B.summary(dict(self.BAT, status="Charging", minutes_to_full=40, watts=30.0), True)
        self.assertIn("charging", title)
        self.assertEqual(sub, "full in 40 min  ·  30.0 W going in")
        _, sub = self.B.summary(dict(self.BAT, capacity=80, status="Not charging"), True, limit=80)
        self.assertIn("held at the 80 % charge limit", sub)
        title, _ = self.B.summary(dict(self.BAT, capacity=100, status="Full"), True)
        self.assertIn("full", title)
        _, sub = self.B.summary(dict(self.BAT, minutes_left=None, watts=None), False)
        self.assertEqual(sub, "working out the time left")
        self.assertEqual(self.B.summary(None, None)[0], "No battery")

    def test_health(self):
        title, sub = self.B.health_text(self.BAT)
        self.assertEqual(title, "Health 57 %")
        self.assertIn("255 charge cycles", sub)
        self.assertIn("worn", sub)
        self.assertNotIn("worn", self.B.health_text(dict(self.BAT, health_pct=95))[1])
        self.assertIsNone(self.B.health_text(dict(self.BAT, health_pct=None, cycles=None)))

    def test_saver_text(self):
        settings = dict(ps.DEFAULTS)
        self.assertEqual(self.B.saver_text({"active": False, "declined": []}, settings),
                         "turns on by itself at 20 %")
        self.assertIn("off by you", self.B.saver_text({"active": False, "declined": ["auto"], "on_battery": True},
                                                      settings))
        on = self.B.saver_text({"active": True, "why": "auto", "since": 1700000000}, settings)
        self.assertIn("battery ran low", on)
        self.assertIn("off again when plugged in", on)
        self.assertNotIn("plugged in", self.B.saver_text({"active": True, "why": "manual", "since": 0}, settings))
        self.assertIn("only when you turn it on",
                      self.B.saver_text({"active": False}, dict(settings, saver_auto_at=0)))
        self.assertIn("not installed", self.B.saver_text(None, settings))

    def test_warnings(self):
        self.assertEqual(self.B.toggled([20, 10, 5], 10), [20, 5])
        self.assertEqual(self.B.toggled([20, 5], 30), [30, 20, 5])
        self.assertEqual(self.B.toggled([], 5), [5])
        self.assertIn("20 %, 10 %", self.B.warn_text([20, 10, 5], []))
        self.assertIn("given this time: 20 %", self.B.warn_text([20, 10, 5], [20]))
        self.assertIn("no warnings", self.B.warn_text([], []))

    def test_limit_text(self):
        sub, usable = self.B.limit_text({"supported": True, "installed": True, "limit": 100, "fixed": True,
                                         "choices": [60, 80, 100]})
        self.assertTrue(usable)
        self.assertIn("only 60 %, 80 %, 100 %", sub)
        self.assertIn("80 % spares it", sub)
        sub, usable = self.B.limit_text({"supported": True, "installed": False, "limit": 100, "choices": []})
        self.assertFalse(usable)
        self.assertIn("system part", sub)
        self.assertEqual(self.B.limit_text({"supported": False}), ("this battery cannot stop charging short of full",
                                                                   False))
        self.assertFalse(self.B.limit_text(None)[1])
        self.assertEqual(self.B.limit_caption(100), "100 % (full)")

    def test_early_text(self):
        early = {"battery_poll": False, "fast": ["SASMEX earthquake early warning (CIRES, official)"],
                 "battery_s": 15}
        self.assertIn("SASMEX earthquake early warning:", self.B.early_text(early))
        self.assertIn("lose up to 15 s", self.B.early_text(dict(early, battery_poll=True)))

    @helpers.needs_repo
    def test_install_hint_matches_charge_limit(self):
        self.assertEqual(self.B.INSTALL, "sudo ./system/charge-limit/install.sh")
        self.assertTrue(os.access(os.path.join(REPO, "system", "charge-limit", "install.sh"), os.X_OK))

    def test_backends_exist(self):
        for name in ("battery-settings.py", "battery-saver.py", "charge-limit.py"):
            self.assertTrue(os.access(os.path.join(helpers.SCRIPTS, name), os.X_OK), name)


class Drawing(Tree):
    """The page built and drawn from a status (no window shown)."""
    def page(self):
        try:
            from settings_pages import common  # noqa: F401
            from settings_pages import battery
        except Exception as exc:                         # noqa: BLE001
            self.skipTest(f"settings_pages.battery not importable: {exc}")
        self.B = battery
        patch = mock.patch.object(battery, "background", lambda work, done: None)
        patch.start()
        self.addCleanup(patch.stop)
        try:
            return battery.Page()
        except Exception as exc:                         # noqa: BLE001  (no display to build widgets on)
            self.skipTest(f"no GTK display: {exc}")

    def data(self, **over):
        settings = dict(ps.DEFAULTS)
        base = {"has_battery": True, "on_battery": True, "plugged": False, "battery": Words.BAT,
                "settings": settings, "choices": BS.choices(settings), "warned": [], "watcher": True,
                "saver": {"active": False, "why": "", "since": 0, "declined": [], "on_battery": True,
                          "gamemode": None},
                "charge": {"supported": True, "installed": True, "limit": 80, "saved": 80,
                           "choices": [60, 80, 100], "fixed": True},
                "early_warnings": None}
        base.update(over)
        return base

    def test_drawn(self):
        page = self.page()
        page.show(self.data())
        self.assertEqual(page.now_title.get_text(), "64 %  ·  on battery")
        self.assertIn("10.8 W", page.now_sub.get_text())
        self.assertEqual(page.health_title.get_text(), "Health 57 %")
        self.assertFalse(page.saver.get_active())
        lit = {k for k, b in page.warn.buttons.items() if b.get_style_context().has_class("active")}
        self.assertEqual(lit, {"20", "10", "5"})
        self.assertEqual(list(page.limit.buttons), ["60", "80", "100"])
        self.assertTrue(page.limit.buttons["80"].get_style_context().has_class("active"))
        self.assertTrue(page.limit.widget.get_sensitive())
        self.assertFalse(page.install.get_visible())
        self.assertFalse(page.early.get_visible())
        self.assertFalse(page.watch_note.get_visible())

    def test_not_installed_says_how(self):
        page = self.page()
        page.show(self.data(charge={"supported": True, "installed": False, "limit": 100, "saved": None,
                                    "choices": [60, 80, 100], "fixed": True}))
        self.assertTrue(page.install.get_visible())
        self.assertFalse(page.limit.widget.get_sensitive())

    def test_unsupported_hides_the_chips(self):
        page = self.page()
        page.show(self.data(charge={"supported": False, "installed": False}))
        self.assertFalse(page.limit.widget.get_visible())
        self.assertFalse(page.install.get_visible())

    def test_early_warnings_and_watcher(self):
        page = self.page()
        page.show(self.data(early_warnings={"battery_poll": True, "fast": ["SASMEX x"], "battery_s": 15},
                            watcher=False))
        self.assertTrue(page.early.get_visible())
        self.assertTrue(page.early_switch.get_active())
        self.assertTrue(page.watch_note.get_visible())

    def test_controls_run_the_backends(self):
        page = self.page()
        page.show(self.data(saver={"active": True, "why": "manual", "since": 0, "declined": []}))
        self.assertTrue(page.saver.get_active())
        ran = []
        with mock.patch.object(page, "do", lambda *cmd, **kw: ran.append(cmd)):
            page.pick_warning("10")
            page.auto.on_pick("30")
            page.switch_saver(False)
            page.limit.on_pick("60")
        self.assertEqual(ran[0], (self.B.BACKEND, "set", "warn_at", "20,5"))
        self.assertEqual(ran[1], (self.B.BACKEND, "set", "saver_auto_at", "30"))
        self.assertEqual(ran[2], (self.B.SAVER, "off"))
        self.assertEqual(ran[3], (self.B.CHARGE, "set", "60"))

    def test_redraw_is_quiet(self):
        """Drawing sets the switches; that must not run a command."""
        page = self.page()
        ran = []
        with mock.patch.object(page, "do", lambda *cmd, **kw: ran.append(cmd)):
            page.show(self.data(saver={"active": True, "why": "auto", "since": 0, "declined": []},
                                settings=dict(ps.DEFAULTS, saver_on_unplug=True)))
        self.assertEqual(ran, [])

    def test_live_tick_reads_sysfs(self):
        self.laptop(capacity=33)
        page = self.page()
        page.show(self.data())
        with mock.patch.object(page.widget, "get_mapped", lambda: True):
            self.assertTrue(page.tick())
        self.assertTrue(page.now_title.get_text().startswith("33 %"))
        self.assertFalse(page.tick())                               # not on screen: stops itself
        self.assertIsNone(page.ticking)


# -- the toolbox's Battery row -----------------------------------------------------------
class BatteryRow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = load(os.path.join(WAYBAR_SCRIPTS, "battery_row.py"), "battery_row_t")

    def plain(self, r):
        return r["text"].replace("‌", "")

    def test_watts_text(self):
        self.assertEqual(self.m.watts_text(6.18), "6.2 W")
        self.assertEqual(self.m.watts_text(10.84), "11 W")
        self.assertIsNone(self.m.watts_text(0))
        self.assertIsNone(self.m.watts_text(None))

    def test_draw_only_while_running_down(self):
        down = self.m.row({"pct": 64, "state": "discharging", "hours": 2.25, "watts": 9.1})
        self.assertIn("64% · 2h 15m left · 9.1 W", self.plain(down))
        self.assertIn("Drawing 9.1 W", down["tooltip"])
        up = self.m.row({"pct": 70, "state": "charging", "hours": 0.5, "watts": 30.0})
        self.assertNotIn("W", self.plain(up).split("·", 1)[1])
        self.assertIn("Charging at 30 W", up["tooltip"])
        self.assertIn("Battery settings", up["tooltip"])

    def test_saver_leaf_and_class(self):
        got = {"pct": 50, "state": "discharging", "hours": 3.0, "watts": 7.0}
        on = self.m.row(got, {"active": True, "why": "auto"})
        self.assertTrue(on["text"].startswith(self.m.LEAF))
        self.assertEqual(on["class"], ["on", "saver"])
        self.assertIn("battery ran low", on["tooltip"])
        off = self.m.row(got, None)
        self.assertFalse(off["text"].startswith(self.m.LEAF))
        self.assertEqual(off["class"], "on")

    def test_saver_file(self):
        folder = tempfile.mkdtemp(dir=helpers.SCRATCH)
        path = os.path.join(folder, "battery-saver.json")
        self.assertIsNone(self.m.saver(path))
        with open(path, "w") as handle:
            json.dump({"active": True, "why": "manual"}, handle)
        self.assertEqual(self.m.saver(path)["why"], "manual")
        with open(path, "w") as handle:
            json.dump({"active": False}, handle)
        self.assertIsNone(self.m.saver(path))

    def test_sysfs_charge_units(self):
        root = helpers.fake_power_supply(tempfile.mkdtemp(dir=helpers.SCRATCH),
                                         battery={"status": "Discharging", "capacity": 80})
        os.rename(os.path.join(root, "BATT"), os.path.join(root, "BAT1"))
        got = self.m.from_sysfs(root)
        self.assertAlmostEqual(got["watts"], 10.8)          # 0.9 A x 12 V

    def test_click_opens_the_battery_page(self):
        with open(os.path.join(os.path.dirname(WAYBAR_SCRIPTS), "config-toolbox")) as handle:
            text = handle.read()
        block = text[text.index('"custom/keybinds#battery": {'):]
        block = block[:block.index("\n    }")]
        self.assertIn("settings.py battery", block)


# -- the other tracks' asks --------------------------------------------------------------
class Plugged(unittest.TestCase):
    def test_rule(self):
        self.assertIs(ps.plugged_from(True, "Discharging"), True)       # the charger's word wins
        self.assertIs(ps.plugged_from(None, "Discharging"), False)
        for status in ("Charging", "Full", "Not charging"):
            self.assertIs(ps.plugged_from(None, status), True)
        self.assertIsNone(ps.plugged_from(None, "Unknown"))
        self.assertIsNone(ps.plugged_from(None, None))

    def test_on_a_tree(self):
        root = helpers.fake_power_supply(tempfile.mkdtemp(dir=helpers.SCRATCH),
                                         battery={"status": "Unknown"}, ac=False)
        self.assertIs(ps.plugged(root), False)
        self.assertIsNone(ps.plugged(tempfile.mkdtemp(dir=helpers.SCRATCH)))
        self.assertEqual([n for n, _ in ps.system_batteries(root)], ["BATT"])
        self.assertIs(ps._system_batteries, ps.system_batteries)    # the old name still works

    def test_saver_and_watcher_share_it(self):
        saver = helpers.import_script("battery-saver.py", "battery_saver_t")
        watch = helpers.import_script("power-watch.py", "power_watch_t")
        self.assertEqual(saver.PLUGGED_STATUSES, ps.PLUGGED_STATUSES)
        self.assertIs(watch.plugged({"ac_online": None, "battery": {"status": "Not charging"}}), True)
        with mock.patch.object(ps, "ac_online", lambda root=None: None), \
                mock.patch.object(ps, "battery", lambda root=None: {"status": "Full"}):
            self.assertIs(saver.plugged(), True)


class QuickBrightness(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import sys
        sys.path.insert(0, WAYBAR_SCRIPTS)
        try:
            cls.dp = load(os.path.join(WAYBAR_SCRIPTS, "display_panel.py"), "display_panel_t")
        except Exception as exc:                         # noqa: BLE001
            raise unittest.SkipTest(f"display_panel not importable: {exc}")

    def test_hardware_screen_wins(self):
        status = {"screens": [{"name": "HDMI-A-1", "brightness": 95},
                              {"name": "eDP-1", "brightness": 62, "hardware": True}],
                  "all": {"brightness": 95}}
        self.assertEqual(self.dp.all_brightness(status), 62)

    def test_desktop_is_as_before(self):
        self.assertEqual(self.dp.all_brightness({"screens": [{"name": "DP-1", "brightness": 80}],
                                                 "all": {"brightness": 70}}), 70)
        self.assertIsNone(self.dp.all_brightness({}))


class WindowLook(unittest.TestCase):
    def test_saver_holds_blur_and_shadows(self):
        wl = helpers.import_script("window-look.py", "window_look_t")
        rows = {r["key"]: r for r in wl.rows({}, {}, {}, gamemode=False, saver=True)}
        self.assertTrue(rows["blur"]["held_by_saver"] and rows["shadow"]["held_by_saver"])
        self.assertFalse(rows["gaps_in"]["held_by_saver"])
        rows = {r["key"]: r for r in wl.rows({}, {}, {})}
        self.assertFalse(rows["blur"]["held_by_saver"])

    def test_windows_page_leaves_them_out_of_not_in_effect(self):
        with open(os.path.join(helpers.SCRIPTS, "settings_pages", "windows.py")) as handle:
            text = handle.read()
        self.assertIn('held_by_saver', text)
        self.assertIn("Battery saver is on", text)


@helpers.needs_repo
class InstallAndSync(unittest.TestCase):
    def read(self, name):
        with open(os.path.join(REPO, name)) as handle:
            return handle.read()

    def test_idle_init_after_the_copy(self):
        text = self.read("install.sh")
        copy = text.index('run rsync -a "${keep[@]}" "$REPO/home/" "$HOME/"')
        init = text.index('run python3 "$HOME/.config/hypr/scripts/idle-settings.py" init')
        self.assertGreater(init, copy)
        keep = text.index('keep+=("--exclude=/.config/hypr/hypridle.conf")')
        self.assertLess(keep, copy)

    def test_sync_never_ships_the_maintainers_timings(self):
        self.assertRegex(self.read("sync.sh"), r"'--exclude=/hypridle\.conf'")

    def test_sync_keeps_the_shipped_timings(self):
        # --delete-excluded would take the shipped file out of the repo
        # without the protect rule (it did once: sync 2026-11-04).
        text = self.read("sync.sh")
        self.assertLess(text.index("'--filter=P /hypridle.conf'"), text.index("'--exclude=/hypridle.conf'"))
        self.assertTrue(os.path.isfile(os.path.join(REPO, "home", ".config", "hypr", "hypridle.conf")))


class AmbientMargin(unittest.TestCase):
    def test_theme_schedule_waits_three_battery_ticks(self):
        with open(os.path.join(helpers.SCRIPTS, "theme-schedule.py")) as handle:
            fresh = int(re.search(r"^AMBIENT_FRESH_S = (\d+)", handle.read(), re.M).group(1))
        with open(os.path.join(helpers.SCRIPTS, "ambient.py")) as handle:
            tick = int(re.search(r"^TICK_BATTERY_S = (\d+)", handle.read(), re.M).group(1))
        self.assertGreaterEqual(fresh, 3 * tick)


if __name__ == "__main__":
    unittest.main()
