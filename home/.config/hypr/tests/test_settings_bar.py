"""bar-settings.py (Settings > Bar & toolbox): editing waybar's JSONC lists
and values in place, the guard against an edit that changes more than it
meant to, and the page's small text helpers; plus the toolbox's Keep awake
row (toolbox_awake.py) and the audio panel's volume limit. Pure functions
on strings only: no config is written, waybar is never restarted."""
import importlib.util
import json
import os
import sys
import unittest
from unittest import mock

import helpers

bs = helpers.import_script("bar-settings.py")

WAYBAR_SCRIPTS = os.path.expanduser("~/.config/waybar/scripts")


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BAR = """\
// The bar. A comment with "quotes" and a URL: https://example.org/x
[{
    "output": "DP-1",   // the big screen
    "modules-left": [
        "ext/workspaces",
        "hyprland/window"
    ],
    "modules-center": [
        // the date and time capsule
        "custom/day",
        "custom/clock", // keep next to the day
        "custom/weather"
    ],
    "modules-right": [
        "custom/cpu",
        "custom/toolbox",
        "custom/power"
    ],
    "custom/weather": {
        "exec": "wttr.py --url \\"https://wttr.in/?format=j1\\"",
        "interval": 1800,   // wttr.in turns away the impatient
        "nested": { "a": 1 }
    },
    "custom/updates": {
        "interval": 3600
    }
}]
"""

TOOLBOX = """\
{
    "output": "DP-1",
    "modules-left": ["group/card"],
    "group/card": {
        "orientation": "vertical",
        "modules": [
            "custom/settings",
            "custom/awake",
            "tray"
        ]
    },
    "tray": { "spacing": 8 }
}
"""


def names(text, key, toolbox=False):
    return [(it["name"], it["shown"]) for it in bs.lists_of(text, toolbox)[key]]


class Parsing(unittest.TestCase):
    def test_comments_go_strings_stay(self):
        bar = bs.parse(BAR)
        self.assertEqual(bar["output"], "DP-1")
        self.assertIn("https://wttr.in/", bar["custom/weather"]["exec"])

    def test_bad_json_says_the_line(self):
        with self.assertRaisesRegex(ValueError, "line"):
            bs.parse('{\n "a": 1,,\n}')

    def test_lists(self):
        self.assertEqual(names(BAR, "modules-center"),
                         [("custom/day", True), ("custom/clock", True), ("custom/weather", True)])
        self.assertEqual([n for n, _ in names(TOOLBOX, "card", True)],
                         ["custom/settings", "custom/awake", "tray"])

    def test_one_line_list_is_refused(self):
        with self.assertRaisesRegex(ValueError, "one line"):
            bs.find_list(TOOLBOX.split("\n"), "modules-left")


class Editing(unittest.TestCase):
    def roundtrip(self, text, edit, toolbox=False):
        new = edit(text)
        bs.expect_change(text, new, bs.shown_after(text, new, toolbox))   # raises if it overreached
        return new

    def test_hide_last_fixes_commas_and_keeps_comments(self):
        new = self.roundtrip(BAR, lambda t: bs.set_shown(t, "custom/weather", False))
        self.assertIn('// hidden by Settings: "custom/weather"', new)
        self.assertIn('"custom/clock" // keep next to the day', new)      # its comma went, its comment stayed
        self.assertIn("// the date and time capsule", new)
        self.assertEqual(bs.parse(new)["modules-center"], ["custom/day", "custom/clock"])
        self.assertIn("// The bar. A comment", new)

    def test_hidden_entry_keeps_its_comment(self):
        new = bs.set_shown(BAR, "custom/clock", False)
        self.assertIn('// hidden by Settings: "custom/clock" // keep next to the day', new)
        self.assertEqual(bs.parse(new)["modules-center"], ["custom/day", "custom/weather"])

    def test_show_puts_it_back_in_place(self):
        hidden = bs.set_shown(BAR, "custom/clock", False)
        self.assertEqual(bs.parse(hidden)["modules-center"], ["custom/day", "custom/weather"])
        back = self.roundtrip(hidden, lambda t: bs.set_shown(t, "custom/clock", True))
        self.assertEqual(bs.parse(back)["modules-center"], ["custom/day", "custom/clock", "custom/weather"])
        self.assertEqual(back, BAR)

    def test_move_within_its_side(self):
        new = self.roundtrip(BAR, lambda t: bs.move(t, "custom/power", "up"))
        self.assertEqual(bs.parse(new)["modules-right"], ["custom/cpu", "custom/power", "custom/toolbox"])
        first = bs.move(BAR, "custom/power", "first")
        self.assertEqual(bs.parse(first)["modules-right"][0], "custom/power")
        # Already first: nothing changes.
        self.assertEqual(bs.move(BAR, "ext/workspaces", "up"), BAR)

    def test_comment_travels_with_its_entry(self):
        new = bs.move(BAR, "custom/day", "down")
        lines = new.split("\n")
        i = lines.index("        // the date and time capsule")
        self.assertIn('"custom/day"', lines[i + 1])

    def test_toolbox_rows(self):
        new = self.roundtrip(TOOLBOX, lambda t: bs.set_shown(t, "tray", False, toolbox=True), toolbox=True)
        self.assertEqual(bs.parse(new)["group/card"]["modules"], ["custom/settings", "custom/awake"])
        moved = bs.move(TOOLBOX, "tray", "first", toolbox=True)
        self.assertEqual(bs.parse(moved)["group/card"]["modules"][0], "tray")

    def test_unknown_module(self):
        with self.assertRaises(ValueError):
            bs.set_shown(BAR, "custom/nothing", False)
        with self.assertRaises(ValueError):
            bs.move(BAR, "custom/cpu", "sideways")

    def test_interval_changes_one_number(self):
        new = bs.set_interval(BAR, "custom/weather", 3600)
        self.assertIn('"interval": 3600,   // wttr.in turns away the impatient', new)
        self.assertEqual(bs.parse(new)["custom/updates"]["interval"], 3600)
        self.assertEqual(bs.interval_of(bs.parse(new), "custom/weather"), 3600)
        self.assertEqual(new.count("\n"), BAR.count("\n"))
        with self.assertRaises(ValueError):
            bs.set_interval(BAR, "custom/cpu", 10)

    def test_output(self):
        new = bs.set_output(BAR, "DP-2")
        self.assertIn('"output": "DP-2",   // the big screen', new)
        bs.expect_change(BAR, new, lambda bar: bar.__setitem__("output", "DP-2"))

    def test_guard_catches_an_overreach(self):
        sneaky = bs.set_output(BAR, "DP-2").replace('"interval": 3600', '"interval": 60')
        with self.assertRaisesRegex(ValueError, "more than intended"):
            bs.expect_change(BAR, sneaky, lambda bar: bar.__setitem__("output", "DP-2"))


class TaskbarVariant(unittest.TestCase):
    """config-path's copy of the bar for the taskbar (dock.py TOP BAR)."""
    def test_pills_hidden_in_place_the_rest_kept(self):
        new = bs.taskbar_variant(BAR, ["custom/day", "custom/clock", "custom/power", "pulseaudio"])
        self.assertEqual(names(new, "modules-center"),
                         [("custom/day", False), ("custom/clock", False), ("custom/weather", True)])
        self.assertEqual(bs.parse(new)["modules-right"], ["custom/cpu", "custom/toolbox"])
        self.assertEqual(bs.parse(new)["custom/weather"], bs.parse(BAR)["custom/weather"])
        self.assertIn("// keep next to the day", new)            # the comments stay

    def test_nothing_taken_is_the_same_bar(self):
        self.assertEqual(bs.parse(bs.taskbar_variant(BAR, [])), bs.parse(BAR))

    def test_config_path_falls_back_to_the_bar(self):
        real_taken, real_read = bs.taken_by_taskbar, bs.read
        try:
            bs.taken_by_taskbar = lambda: []
            self.assertEqual(bs.config_path(), bs.BAR)
            bs.taken_by_taskbar = lambda: ["custom/power"]

            def broken(_path):
                raise OSError("gone")
            bs.read = broken
            self.assertEqual(bs.config_path(), bs.BAR)
        finally:
            bs.taken_by_taskbar, bs.read = real_taken, real_read


NAMED_TOOLBOX = TOOLBOX.replace('{\n    "output"', '{\n    "name": "waybar-toolbox",\n    "output"', 1)


class ToolboxVariant(unittest.TestCase):
    """toolbox-config-path's copy of the card with the top bar off
    (dock.py TOP BAR OFF): the bar's pills as rows on top."""
    def test_rows_on_top_with_the_bars_blocks(self):
        new = bs.toolbox_variant(NAMED_TOOLBOX, BAR, skip=set())
        card = bs.parse(new)
        self.assertEqual(card["group/card"]["modules"],
                         ["group/status-now", "group/status-more", "custom/settings", "custom/awake", "tray"])
        self.assertEqual(card["group/status-now"], {"orientation": "horizontal",
                                                    "modules": ["custom/day", "custom/clock"]})
        # In STATUS_ROWS' order, only what the bar shows; the cpu and the
        # window title are not taken in, the toolbox pill never.
        self.assertEqual(card["group/status-more"]["modules"],
                         ["ext/workspaces", "custom/weather", "custom/power"])
        self.assertEqual(card["custom/weather"], bs.parse(BAR)["custom/weather"])
        self.assertIn("// wttr.in turns away the impatient", new)          # copied, comments and all
        self.assertNotIn("custom/updates", card)                           # not on the bar: not copied

    def test_skips_what_the_taskbar_shows_and_what_is_hidden(self):
        bar = bs.set_shown(BAR, "ext/workspaces", False)
        new = bs.toolbox_variant(NAMED_TOOLBOX, bar, skip={"custom/day", "custom/clock", "custom/weather",
                                                           "custom/power"})
        card = bs.parse(new)
        self.assertEqual(card["group/card"]["modules"], ["custom/settings", "custom/awake", "tray"])
        self.assertEqual(new, NAMED_TOOLBOX)                              # nothing left to add

    def test_no_name_line_is_refused(self):
        with self.assertRaisesRegex(ValueError, "name"):
            bs.toolbox_variant(TOOLBOX, BAR, skip=set())

    def test_toolbox_config_path(self):
        with mock.patch.object(bs, "bar_wanted", lambda: True):
            self.assertEqual(bs.toolbox_config_path(), bs.TOOLBOX)
        with mock.patch.object(bs, "bar_wanted", lambda: False), \
                mock.patch.object(bs, "taken_by_taskbar", lambda: []), \
                mock.patch.object(bs, "read", lambda p: NAMED_TOOLBOX if p == bs.TOOLBOX else BAR), \
                mock.patch.object(bs, "NOBAR_TOOLBOX", os.path.join(helpers.SCRATCH, "config-toolbox-nobar")):
            path = bs.toolbox_config_path()
            self.assertEqual(path, bs.NOBAR_TOOLBOX)
            with open(path) as handle:
                self.assertIn("group/status-now", handle.read())

    def test_toolbox_config_path_falls_back(self):
        with mock.patch.object(bs, "bar_wanted", lambda: False), \
                mock.patch.object(bs, "taken_by_taskbar", lambda: []), \
                mock.patch.object(bs, "read", lambda p: TOOLBOX if p == bs.TOOLBOX else BAR):   # no "name"
            self.assertEqual(bs.toolbox_config_path(), bs.TOOLBOX)


class Wanted(unittest.TestCase):
    """bar-settings.py wanted (bar-wanted.sh, waybar.service's condition):
    off only with the dock's top_bar off AND dock.service active."""
    def wanted(self, settings, dock_state="active"):
        dock = helpers.import_script("dock.py", "dock")
        with mock.patch.object(dock, "read_settings", lambda: dict(dock.DEFAULTS, **settings)), \
                mock.patch.dict(sys.modules, {"dock": dock}), \
                mock.patch.object(bs, "run", lambda *cmd, **_kw: dock_state + "\n"):
            return bs.bar_wanted()

    def test_off_needs_all_three(self):
        self.assertFalse(self.wanted({"enabled": True, "top_bar": False}))
        self.assertTrue(self.wanted({"enabled": True, "top_bar": True}))
        self.assertTrue(self.wanted({"enabled": False, "top_bar": False}))
        for state in ("inactive", "failed", "activating", "deactivating", ""):
            self.assertTrue(self.wanted({"enabled": True, "top_bar": False}, state), state)

    def test_any_trouble_is_a_bar(self):
        def broken():
            raise RuntimeError("no dock")
        dock = helpers.import_script("dock.py", "dock")
        with mock.patch.object(dock, "read_settings", broken), mock.patch.dict(sys.modules, {"dock": dock}):
            self.assertTrue(bs.bar_wanted())

    def test_condition_script_skips_only_on_off(self):
        """bar-wanted.sh: exit 1 on the exact word, 0 on anything else."""
        import subprocess
        import tempfile
        script = os.path.join(WAYBAR_SCRIPTS, "bar-wanted.sh")
        with open(script) as handle:
            text = handle.read()
        for said, rc in (("off", 1), ("on", 0), ("", 0), ("Traceback", 0)):
            home = tempfile.mkdtemp(dir=helpers.SCRATCH)
            os.makedirs(os.path.join(home, ".config/hypr/scripts"))
            with open(os.path.join(home, ".config/hypr/scripts/bar-settings.py"), "w") as handle:
                handle.write(f"print({said!r})\n")
            done = subprocess.run(["bash", "-c", text], env=dict(os.environ, HOME=home))
            self.assertEqual(done.returncode, rc, said)


class Status(unittest.TestCase):
    def test_pending(self):
        self.assertTrue(bs.pending(100.0, 100.0, {"bar": 101.0, "toolbox": 50.0}))
        self.assertFalse(bs.pending(100.0, 100.0, {"bar": 99.0, "toolbox": 99.5}))
        self.assertFalse(bs.pending(None, None, {"bar": 101.0}))      # not running: nothing to reload
        # The bar off: its file feeds the toolbox, which reloads for it.
        self.assertTrue(bs.pending(None, 100.0, {"bar": 101.0}, bar_off=True))
        self.assertFalse(bs.pending(None, 100.0, {"bar": 99.0}, bar_off=True))

    def test_describe(self):
        self.assertEqual(bs.describe("custom/toolbox")["keep"], bs.KEEP["custom/toolbox"])
        self.assertEqual(bs.describe("custom/unknown")["title"], "custom/unknown")


class Restarting(unittest.TestCase):
    """apply restarts only when a file is newer than the bar; restart (the
    page's Restart the bar link) always does. Both via bar-restart.sh."""

    def runs(self, func, started):
        calls = []

        def fake_run(cmd, **_kw):
            calls.append(cmd)
            return mock.Mock(returncode=0, stdout="", stderr="")
        with mock.patch.object(bs.subprocess, "run", fake_run), \
                mock.patch.object(bs, "started", lambda unit: started), \
                mock.patch.object(bs.os.path, "getmtime", lambda p: 100.0):
            func()
        return [c for c in calls if c == [bs.RESTART]]

    def test_apply_skips_when_up_to_date(self):
        self.assertEqual(self.runs(bs.apply, 200.0), [])

    def test_restart_always_restarts(self):
        self.assertEqual(self.runs(bs.restart, 200.0), [[bs.RESTART]])


class PageHelpers(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import gi
            gi.require_version("Gtk", "3.0")
            sys.path.insert(0, os.path.dirname(helpers.SCRIPTS + "/"))
            from settings_pages import bar
        except Exception as exc:                    # no GTK: skip the page's helpers
            raise unittest.SkipTest(f"settings_pages.bar not importable: {exc}")
        cls.bar = bar

    def test_every(self):
        self.assertEqual(self.bar.every(1800), "30 min")
        self.assertEqual(self.bar.every(3600), "1 h")
        self.assertEqual(self.bar.every(90), "90 s")

    def test_interval_choices_keep_a_hand_edit(self):
        keys = [k for k, _ in self.bar.interval_choices([900, 1800], 2400)]
        self.assertEqual(keys, ["900", "1800", "2400"])

    def test_screens(self):
        screens = [{"name": "DP-2", "description": "Acme Displays ACME ULTRAWIDE 0x0003A5B1"}]
        self.assertEqual(self.bar.screen_name(screens[0]), "DP-2 · ACME ULTRAWIDE")
        self.assertIn(("DP-1", "DP-1  (not connected)"), self.bar.screen_choices(screens, "DP-1"))
        self.assertIn("not connected", self.bar.screen_sub({"bar": {"output": "DP-1"}, "screens": screens}))

    def test_bar_sub(self):
        self.assertIn("NOT running", self.bar.bar_sub({"running": {}}))
        self.assertIn("not loaded", self.bar.bar_sub({"running": {"bar": 100.0}, "pending": True}, now=200.0))
        off = self.bar.bar_sub({"running": {}, "top_bar": "off"})
        self.assertIn("Dock & taskbar", off)
        self.assertNotIn("NOT running", off)                 # not a fault: switched off there


class ToolboxAwake(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.aw = load(os.path.join(WAYBAR_SCRIPTS, "toolbox_awake.py"), "toolbox_awake")

    def test_rows(self):
        self.assertEqual(self.aw.row(None)["class"], "error")
        self.assertEqual(self.aw.row({"on": False})["alt"], "deactivated")
        on = self.aw.row({"on": True, "until": None})
        self.assertEqual((on["alt"], on["class"], on["text"]), ("activated", "activated", "Keep awake"))
        self.assertIn(":", self.aw.row({"on": True, "until": 1_800_000_000})["text"])

    def test_toggle_asks_idle_settings(self):
        calls = []

        def fake_run(cmd, **_kw):
            calls.append(cmd)
            out = json.dumps({"on": False}) if cmd[1:] == ["awake", "status"] else ""
            return mock.Mock(stdout=out, returncode=0)
        with mock.patch.object(self.aw.subprocess, "run", fake_run), \
                mock.patch.object(sys, "argv", ["toolbox_awake.py", "toggle", "60"]):
            self.aw.main()
        self.assertEqual(calls[1], [self.aw.IDLE, "awake", "on", "60"])
        self.assertEqual(calls[2][:2], ["systemctl", "--user"])


class AudioLimit(unittest.TestCase):
    """audio_panel.volume_limit only: the module imports GTK and panelui."""
    @classmethod
    def setUpClass(cls):
        try:
            sys.path.insert(0, WAYBAR_SCRIPTS)
            cls.ap = load(os.path.join(WAYBAR_SCRIPTS, "audio_panel.py"), "audio_panel_t")
        except Exception as exc:
            raise unittest.SkipTest(f"audio_panel not importable: {exc}")

    def test_limit_follows_the_switch(self):
        path = os.path.join(helpers.SCRATCH, "sound.json")
        with mock.patch.object(self.ap, "SOUND_STATE", path):
            self.assertEqual(self.ap.volume_limit(), 1.0)            # no file: off
            with open(path, "w") as h:
                json.dump({"boost": True}, h)
            self.assertEqual(self.ap.volume_limit(), 1.5)
            with open(path, "w") as h:
                h.write("{broken")
            self.assertEqual(self.ap.volume_limit(), 1.0)


if __name__ == "__main__":
    unittest.main()
