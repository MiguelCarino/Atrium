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
                         ["group/pills-1", "group/pills-2", "group/pills-3", "custom/settings", "custom/awake",
                          "tray"])
        # A line per side of the bar, in its order; the window title and
        # the toolbox pill never (CARD_NEVER).
        self.assertEqual(card["group/pills-1"], {"orientation": "horizontal", "modules": ["ext/workspaces"]})
        self.assertEqual(card["group/pills-2"]["modules"], ["custom/day", "custom/clock", "custom/weather"])
        self.assertEqual(card["group/pills-3"]["modules"], ["custom/cpu", "custom/power"])
        self.assertEqual(card["custom/weather"], bs.parse(BAR)["custom/weather"])
        self.assertIn("// wttr.in turns away the impatient", new)          # copied, comments and all
        self.assertNotIn("custom/updates", card)                           # not on the bar: not copied

    def test_skips_what_the_taskbar_shows_and_what_is_hidden(self):
        bar = bs.set_shown(BAR, "ext/workspaces", False)
        new = bs.toolbox_variant(NAMED_TOOLBOX, bar, skip={"custom/day", "custom/clock", "custom/weather",
                                                           "custom/power", "custom/cpu"})
        card = bs.parse(new)
        self.assertEqual(card["group/card"]["modules"], ["custom/settings", "custom/awake", "tray"])
        self.assertEqual(new, NAMED_TOOLBOX)                              # nothing left to add

    def test_no_name_line_is_refused(self):
        with self.assertRaisesRegex(ValueError, "name"):
            bs.toolbox_variant(TOOLBOX, BAR, skip=set())

    def test_toolbox_config_path(self):
        with mock.patch.object(bs, "bar_wanted", lambda: True), \
                mock.patch.object(bs, "taken_by_taskbar", lambda: []), \
                mock.patch.object(bs, "GRID_TOOLBOX", os.path.join(helpers.SCRATCH, "tb-grid0")):
            self.assertEqual(bs.toolbox_config_path(), bs.GRID_TOOLBOX)
        with mock.patch.object(bs, "bar_wanted", lambda: False), \
                mock.patch.object(bs, "taken_by_taskbar", lambda: []), \
                mock.patch.object(bs, "read", lambda p: NAMED_TOOLBOX if p == bs.TOOLBOX else BAR), \
                mock.patch.object(bs, "NOBAR_TOOLBOX", os.path.join(helpers.SCRATCH, "config-toolbox-nobar")):
            path = bs.toolbox_config_path()
            self.assertEqual(path, bs.NOBAR_TOOLBOX)
            with open(path) as handle:
                self.assertIn("group/pills-1", handle.read())

    def test_toolbox_config_path_falls_back(self):
        with mock.patch.object(bs, "bar_wanted", lambda: False), \
                mock.patch.object(bs, "taken_by_taskbar", lambda: []), \
                mock.patch.object(bs, "read", lambda p: TOOLBOX if p == bs.TOOLBOX else BAR):   # no "name"
            self.assertEqual(bs.toolbox_config_path(), bs.TOOLBOX)


LANG_BAR = BAR.replace('"ext/workspaces",', '"ext/workspaces",\n        "hyprland/language",', 1)
MIC_TOOLBOX = NAMED_TOOLBOX.replace('"custom/awake",', '"custom/awake",\n            // hidden: "custom/keybinds#mic",', 1)
BATT_TOOLBOX = MIC_TOOLBOX.replace('// hidden: "custom/keybinds#mic",',
                                   '// hidden: "custom/keybinds#mic",\n            // hidden: "custom/keybinds#battery",', 1)
# The bar with the meters and the battery pill, on a laptop.
METER_BAR = LANG_BAR.replace('"custom/cpu",', '"custom/drives",\n        "custom/cpu",\n        "custom/gpu",\n'
                             '        "custom/disk",\n        "battery",', 1)


class DockCard(unittest.TestCase):
    """The card while the dock or taskbar runs: the keyboard layout always
    (dock.py CARD_PILLS), the Microphone row with the top bar off."""
    def test_only_limits_what_is_added(self):
        new = bs.toolbox_variant(NAMED_TOOLBOX, LANG_BAR, skip=set(), only={"hyprland/language"})
        card = bs.parse(new)
        self.assertEqual(card["group/card"]["modules"][0], "group/pills-1")
        self.assertEqual(card["group/pills-1"]["modules"], ["hyprland/language"])
        self.assertNotIn("group/pills-2", card)

    def test_mic_row_is_shown(self):
        self.assertNotIn("custom/keybinds#mic", bs.parse(MIC_TOOLBOX)["group/card"]["modules"])
        shown = bs.show_off_rows(MIC_TOOLBOX)
        self.assertIn("custom/keybinds#mic", bs.parse(shown)["group/card"]["modules"])
        self.assertEqual(bs.show_off_rows(NAMED_TOOLBOX), NAMED_TOOLBOX)      # no row: as it is

    def test_battery_row_is_shown_too(self):
        modules = bs.parse(bs.show_off_rows(BATT_TOOLBOX))["group/card"]["modules"]
        self.assertIn("custom/keybinds#mic", modules)
        self.assertIn("custom/keybinds#battery", modules)

    def test_bar_off_meters_first_and_no_battery_pill(self):
        with mock.patch.object(bs, "bar_wanted", lambda: False), \
                mock.patch.object(bs, "taken_by_taskbar", lambda: ["custom/power"]), \
                mock.patch.object(bs, "card_pills", lambda: ("hyprland/language",)), \
                mock.patch.object(bs, "read", lambda p: BATT_TOOLBOX if p == bs.TOOLBOX else METER_BAR), \
                mock.patch.object(bs, "NOBAR_TOOLBOX", os.path.join(helpers.SCRATCH, "tb-nobar")):
            with open(bs.toolbox_config_path()) as handle:
                card = bs.parse(handle.read())
        self.assertEqual(card["group/card"]["modules"][0], "group/pills-1")
        self.assertEqual(card["group/pills-1"]["modules"], ["custom/cpu", "custom/gpu", "custom/disk"])
        pills = [n for g, v in card.items() if g.startswith("group/pills-") for n in v["modules"]]
        self.assertNotIn("battery", pills)                                       # the Battery row has it
        self.assertEqual(pills.count("custom/cpu"), 1)
        self.assertIn("custom/drives", pills)
        rows = [n for g, v in card.items() if g.startswith("group/grid-") for n in v["modules"]]
        self.assertIn("custom/keybinds#battery", rows + card["group/card"]["modules"])

    def test_meters_line_follows_hide(self):
        hidden = METER_BAR.replace('"custom/gpu",', '// hidden: "custom/gpu",', 1)
        lines = bs.card_lines(hidden, skip=set(), first=bs.METERS)
        self.assertEqual(lines[0][1], ["custom/cpu", "custom/disk"])
        self.assertEqual(bs.card_lines(BAR, skip={"custom/cpu"}, first=bs.METERS)[0][1], ["ext/workspaces"])

    def paths(self, wanted, taken, card=("hyprland/language",)):
        out = {}
        with mock.patch.object(bs, "bar_wanted", lambda: wanted), \
                mock.patch.object(bs, "taken_by_taskbar", lambda: list(taken)), \
                mock.patch.object(bs, "card_pills", lambda: card), \
                mock.patch.object(bs, "read", lambda p: MIC_TOOLBOX if p == bs.TOOLBOX else LANG_BAR), \
                mock.patch.object(bs, "NOBAR_TOOLBOX", os.path.join(helpers.SCRATCH, "tb-nobar")), \
                mock.patch.object(bs, "DOCK_TOOLBOX", os.path.join(helpers.SCRATCH, "tb-dock")), \
                mock.patch.object(bs, "GRID_TOOLBOX", os.path.join(helpers.SCRATCH, "tb-grid")):
            path = bs.toolbox_config_path()
            if path != bs.TOOLBOX:
                with open(path) as handle:
                    out = bs.parse(handle.read())
            return os.path.basename(path), out

    def test_toolbox_config_path_by_case(self):
        name, card = self.paths(True, [])                                       # no dock: the grid alone
        self.assertEqual(name, "tb-grid")
        self.assertNotIn("group/pills-1", card)
        name, card = self.paths(True, ["hyprland/language", "custom/power"])     # dock, bar on
        self.assertEqual(name, "tb-dock")
        self.assertEqual(card["group/pills-1"]["modules"], ["hyprland/language"])
        self.assertNotIn("custom/keybinds#mic", card["group/card"]["modules"])
        name, card = self.paths(False, ["hyprland/language", "custom/power"])    # bar off
        self.assertEqual(name, "tb-nobar")
        self.assertEqual(card["group/pills-1"]["modules"], ["custom/cpu"])      # the meters first
        self.assertEqual(card["group/pills-2"]["modules"], ["ext/workspaces", "hyprland/language"])
        self.assertIn("custom/keybinds#mic", card["group/card"]["modules"])
        self.assertNotIn("group/pills-4", card)                                 # the taskbar has the power pill


class Grid(unittest.TestCase):
    """grid_variant: the card's plain rows two to a line; groups and the tray
    a line of their own; hidden rows gone; an odd one out stays alone."""
    def test_pairs_in_order(self):
        text = NAMED_TOOLBOX.replace('"custom/awake",', '"custom/awake",\n            "custom/display",', 1)
        card = bs.parse(bs.grid_variant(text))
        self.assertEqual(card["group/card"]["modules"], ["group/grid-1", "custom/display", "tray"])
        self.assertEqual(card["group/grid-1"], {"orientation": "horizontal",
                                                "modules": ["custom/settings", "custom/awake"]})
        self.assertEqual(card["tray"], bs.parse(text)["tray"])

    def test_groups_cut_the_runs_and_hidden_rows_go(self):
        text = bs.toolbox_variant(MIC_TOOLBOX, LANG_BAR, skip=set(), only={"hyprland/language"})
        card = bs.parse(bs.grid_variant(text))
        self.assertEqual(card["group/card"]["modules"], ["group/pills-1", "group/grid-1", "tray"])
        self.assertEqual(card["group/grid-1"]["modules"], ["custom/settings", "custom/awake"])  # mic hidden
        shown = bs.parse(bs.grid_variant(bs.show_off_rows(MIC_TOOLBOX)))
        self.assertEqual(shown["group/card"]["modules"], ["group/grid-1", "custom/keybinds#mic", "tray"])

    def test_nothing_to_pair(self):
        one = NAMED_TOOLBOX.replace('            "custom/awake",\n', "", 1)
        self.assertEqual(bs.grid_variant(one), one)

    def test_plain_toolbox_is_a_grid_too(self):
        with mock.patch.object(bs, "bar_wanted", lambda: True), \
                mock.patch.object(bs, "taken_by_taskbar", lambda: []), \
                mock.patch.object(bs, "read", lambda p: NAMED_TOOLBOX if p == bs.TOOLBOX else BAR), \
                mock.patch.object(bs, "GRID_TOOLBOX", os.path.join(helpers.SCRATCH, "tb-grid")):
            path = bs.toolbox_config_path()
            self.assertEqual(path, bs.GRID_TOOLBOX)
            with open(path) as handle:
                self.assertIn("group/grid-1", bs.parse(handle.read())["group/card"]["modules"])


class MicRow(unittest.TestCase):
    """scripts/mic_row.py: the card's Microphone row."""
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, WAYBAR_SCRIPTS)
        cls.m = load(os.path.join(WAYBAR_SCRIPTS, "mic_row.py"), "mic_row")

    def test_level(self):
        self.assertEqual(self.m.level("Volume: 0.45\n"), (45, False))
        self.assertEqual(self.m.level("Volume: 1.00 [MUTED]"), (100, True))
        self.assertIsNone(self.m.level(""))

    def test_row(self):
        self.assertEqual(self.m.row((45, False), [])["class"], "on")
        self.assertIn("45%", self.m.row((45, False), [])["text"])
        busy = self.m.row((45, False), [{"app": "Firefox"}, {"app": "Firefox"}, {"app": "OBS"}])
        self.assertEqual(busy["class"], "listening")
        self.assertIn("in use: Firefox, OBS", busy["tooltip"])
        self.assertEqual(self.m.row((45, True), [{"app": "x"}])["class"], "muted")
        self.assertEqual(self.m.row(None, [])["class"], "none")
        # Font Awesome ligatures ("microphone", "phone") never see the word whole.
        text = self.m.row((45, False), [])["text"]
        self.assertNotIn("phone", text)
        self.assertIn("Microphone 45%", text.replace("\u200c", ""))

    def test_card_row_and_config(self):
        self.assertIn("custom/keybinds#mic", bs.MODULES)
        with open(bs.TOOLBOX) as handle:
            toolbox = handle.read()
        card = dict((it["name"], it["shown"]) for it in bs.lists_of(toolbox, True)["card"])
        self.assertIs(card.get("custom/keybinds#mic"), False)          # hidden as shipped
        self.assertIn("mic_row.py watch", bs.parse(toolbox)["custom/keybinds#mic"]["exec"])


class BatteryRow(unittest.TestCase):
    """scripts/battery_row.py: the card's Battery row, with the time left."""
    @classmethod
    def setUpClass(cls):
        cls.m = load(os.path.join(WAYBAR_SCRIPTS, "battery_row.py"), "battery_row")

    UPOWER = """\
  native-path:          BAT0
  power supply:         yes
  battery
    present:             yes
    state:               discharging
    energy-rate:         9.1 W
    percentage:          64%
    time to empty:       2.3 hours
"""

    def test_from_upower(self):
        self.assertEqual(self.m.from_upower(self.UPOWER), {"pct": 64, "state": "discharging", "hours": 2.3})
        charging = self.UPOWER.replace("discharging", "charging").replace("time to empty:       2.3 hours",
                                                                          "time to full:        40.0 minutes")
        got = self.m.from_upower(charging)
        self.assertEqual(got["state"], "charging")
        self.assertAlmostEqual(got["hours"], 40 / 60)
        self.assertIsNone(self.m.from_upower(self.UPOWER.replace("present:             yes",
                                                                 "present:             no")))
        self.assertIsNone(self.m.from_upower(""))

    def test_from_sysfs(self):
        import tempfile
        with tempfile.TemporaryDirectory() as root:
            self.assertIsNone(self.m.from_sysfs(root))
            bat = os.path.join(root, "BAT0")
            os.makedirs(bat)
            for key, value in (("capacity", "50"), ("status", "Discharging"), ("energy_now", "25000000"),
                               ("energy_full", "50000000"), ("power_now", "10000000")):
                with open(os.path.join(bat, key), "w") as fh:
                    fh.write(value + "\n")
            self.assertEqual(self.m.from_sysfs(root), {"pct": 50, "state": "discharging", "hours": 2.5})

    def test_row(self):
        plain = lambda r: r["text"].replace("\u200c", "")
        down = self.m.row({"pct": 64, "state": "discharging", "hours": 2.25})
        self.assertIn("Battery 64% · 2h 15m left", plain(down))
        self.assertEqual(down["class"], "on")
        self.assertNotIn("Battery", down["text"])                    # no Font Awesome ligature
        self.assertEqual(self.m.row({"pct": 20, "state": "discharging", "hours": 0.5})["class"], "warning")
        self.assertEqual(self.m.row({"pct": 8, "state": "discharging", "hours": None})["class"], "critical")
        up = self.m.row({"pct": 70, "state": "charging", "hours": 40 / 60})
        self.assertIn("full in 40m", up["text"])
        self.assertEqual(up["class"], "charging")
        full = self.m.row({"pct": 100, "state": "fully-charged", "hours": None})
        self.assertTrue(plain(full).endswith("Battery 100%"))                     # the charge alone
        self.assertIn("full", full["tooltip"])
        self.assertEqual(self.m.row(None)["text"], "")                # no battery: waybar hides the row

    def test_card_row_and_config(self):
        self.assertIn("custom/keybinds#battery", bs.MODULES)
        with open(bs.TOOLBOX) as handle:
            toolbox = handle.read()
        card = dict((it["name"], it["shown"]) for it in bs.lists_of(toolbox, True)["card"])
        self.assertIs(card.get("custom/keybinds#battery"), False)      # hidden as shipped
        block = bs.parse(toolbox)["custom/keybinds#battery"]
        self.assertIn("battery_row.py", block["exec"])
        self.assertIn("settings.py power", block["on-click"])


TASKBAR_VIEW = {"enabled": True, "layout": "taskbar", "top_bar": True,
                "taken": ["custom/day", "custom/clock", "custom/power", "hyprland/language"],
                "card": ["hyprland/language"],
                "keys": {"custom/day": "clock", "custom/clock": "clock", "custom/weather": "weather"},
                "settings": {"clock": True, "weather": False}}


class Destinations(unittest.TestCase):
    """Phase 3: where each bar pill is (where_of), the card's lines from the
    bar's own list (card_lines), and the Bar page's chooser (destinations,
    destination_commands)."""
    @classmethod
    def setUpClass(cls):
        try:
            import gi
            gi.require_version("Gtk", "3.0")
            sys.path.insert(0, os.path.dirname(helpers.SCRIPTS + "/"))
            from settings_pages import bar
        except Exception as exc:                    # noqa: BLE001 - no GTK
            raise unittest.SkipTest(f"settings_pages.bar not importable: {exc}")
        cls.page = bar

    def item(self, name, shown=True, view=TASKBAR_VIEW, title=None):
        return {"name": name, "title": title or name, "shown": shown, "where": bs.where_of(name, shown, view),
                "dock_key": view["keys"].get(name), "card_never": name in bs.CARD_NEVER}

    def test_where_of(self):
        off = dict(TASKBAR_VIEW, top_bar=False)
        self.assertEqual(bs.where_of("custom/day", True, TASKBAR_VIEW), "taskbar")
        self.assertEqual(bs.where_of("hyprland/language", True, TASKBAR_VIEW), "toolbox")
        self.assertEqual(bs.where_of("custom/cpu", True, TASKBAR_VIEW), "bar")
        self.assertEqual(bs.where_of("custom/cpu", False, TASKBAR_VIEW), "hidden")
        self.assertEqual(bs.where_of("custom/cpu", True, off), "toolbox")
        self.assertEqual(bs.where_of("hyprland/window", True, off), "hidden")       # CARD_NEVER
        self.assertEqual(bs.where_of("custom/cpu", True, dict(TASKBAR_VIEW, enabled=False, taken=[])), "bar")
        self.assertEqual(bs.where_of("custom/mic", True, dict(off, layout="dock", taken=["custom/mic"])), "dock")

    def test_card_lines_cut_long_sides(self):
        many = BAR.replace('"custom/cpu",', "".join(f'"custom/p{i}",\n        ' for i in range(9)) + '"custom/cpu",')
        lines = bs.card_lines(many, skip={"custom/power"})
        self.assertEqual([len(n) for _g, n in lines], [1, 3, bs.PILLS_PER_LINE, 3])
        self.assertEqual([g for g, _n in lines], ["group/pills-1", "group/pills-2", "group/pills-3", "group/pills-4"])
        self.assertEqual(lines[3][1], ["custom/p7", "custom/p8", "custom/cpu"])     # the toolbox pill never

    def test_destinations(self):
        d = self.page.destinations
        self.assertIsNone(d(self.item("custom/cpu"), dict(TASKBAR_VIEW, enabled=False)))   # the switch
        self.assertEqual(d(self.item("custom/cpu"), TASKBAR_VIEW), ["bar", "hidden"])
        self.assertEqual(d(self.item("custom/day"), TASKBAR_VIEW), ["bar", "taskbar", "hidden"])
        self.assertEqual(d(self.item("hyprland/language"), TASKBAR_VIEW), ["toolbox", "hidden"])
        self.assertEqual(d(self.item("custom/power"), TASKBAR_VIEW), ["taskbar"])          # always the start menu's
        off = dict(TASKBAR_VIEW, top_bar=False)
        self.assertEqual(d(self.item("custom/cpu", view=off), off), ["toolbox", "hidden"])
        self.assertEqual(d(self.item("hyprland/window", view=off), off), ["hidden"])
        dock = dict(off, layout="dock", taken=["custom/mic"], keys={"custom/mic": "privacy"},
                    settings={"privacy": True})
        self.assertEqual(d(self.item("custom/mic", view=dock), dock), ["toolbox", "dock", "hidden"])

    def test_commands(self):
        c = self.page.destination_commands
        self.assertEqual(c(self.item("custom/day"), "bar", TASKBAR_VIEW), [("dock", "set", "clock", "off")])
        self.assertEqual(c(self.item("custom/day"), "hidden", TASKBAR_VIEW),
                         [("dock", "set", "clock", "off"), ("bar", "hide", "custom/day")])
        self.assertEqual(c(self.item("custom/weather", shown=False), "taskbar", TASKBAR_VIEW),
                         [("dock", "set", "weather", "on"), ("bar", "show", "custom/weather")])
        self.assertEqual(c(self.item("custom/cpu", shown=False), "bar", TASKBAR_VIEW),
                         [("bar", "show", "custom/cpu")])
        self.assertEqual(c(self.item("custom/cpu"), "hidden", TASKBAR_VIEW), [("bar", "hide", "custom/cpu")])

    def test_together(self):
        lists = {"modules-center": [self.item("custom/day", title="Date"), self.item("custom/clock", title="Time"),
                                    self.item("custom/weather", title="Weather")]}
        self.assertEqual(self.page.together(lists["modules-center"][0], lists), ["Time"])
        self.assertEqual(self.page.together(self.item("custom/cpu"), lists), [])


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
