"""Settings page: the window switcher (SUPER+W, window-switcher.py) and the
keys that move between windows.

Four choices, each one `switcher_conf.py set KEY VALUE` (kept in
$XDG_STATE_HOME/hypr/switcher.conf, read by the switcher each time it
opens): which windows it lists (every one, this workspace's, this screen's),
in what order (most recent first, or by workspace), whether scratchpad
windows count, and how many rows show before the list scrolls. The page
redraws from `switcher_conf.py status --json`.

<main>+Tab / <main>+SHIFT+Tab (cycle the windows of this workspace), <main>+U
and SUPER+Tab (the previous workspace) are lua/binds.lua's; <main> is the main
modifier (Settings > Input, input-settings.py main_mod: ALT unless it says
SUPER). The Shortcuts page changes those keys.
"""
from gi.repository import GLib, Gtk  # noqa: F401

from .common import *  # noqa: F401,F403  (the shared helpers and paths)

import importlib.util  # noqa: E402
import os  # noqa: E402
import subprocess  # noqa: E402

PAGE = {"id": "switcher", "title": "Window switcher", "icon": "", "group": "Look", "order": 45,
        "parent": "windows", "tab": "Window switcher",
        "keywords": ["window switcher", "switch windows", "alt tab", "super w", "window list", "recent windows",
                     "scratchpad", "cambiar ventana"]}

CONF_CLI = os.path.join(HYPR, "switcher_conf.py")
INPUT = os.path.join(HYPR, "input-settings.py")
SETTINGS = os.path.join(HYPR, "settings.py")
CHOICES = [
    ("scope", "", "Lists", [("all", "Every window"), ("workspace", "This workspace"),
                                   ("monitor", "This screen")]),
    ("order", "", "Order", [("recent", "Most recent first"), ("workspace", "By workspace")]),
    ("special", "", "Scratchpad windows", [("on", "Included"), ("off", "Left out")]),
    ("lines", "", "Rows shown", [("10", "10"), ("15", "15"), ("20", "20"), ("25", "25")]),
]
SUBS = {
    ("scope", "all"): "every window on every workspace and screen",
    ("scope", "workspace"): "only the windows of the workspace you are on",
    ("scope", "monitor"): "only the windows on the screen you are on",
    ("order", "recent"): "the window you were just in is first: Enter on it goes back",
    ("order", "workspace"): "workspace 1 first, then 2, ...; the most recent first within each",
    ("special", "on"): "the scratchpads' windows too (special workspaces)",
    ("special", "off"): "only ordinary workspaces",
}


def attempt(*cmd, timeout=10):
    """"" when it worked, else its last stderr line. Called from background()."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        return f"{os.path.basename(cmd[0])}: {exc}"
    if r.returncode == 0:
        return ""
    return (r.stderr.strip().splitlines() or [f"{os.path.basename(cmd[0])} failed ({r.returncode})"])[-1]


def main_mod():
    """The effective main modifier (input-settings.py: the saved main_mod,
    else lua/input.lua's default), "ALT" when it cannot be read. Called from
    background()."""
    try:
        spec = importlib.util.spec_from_file_location("input_settings", INPUT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return str(module.effective().get("main_mod") or "ALT").upper()
    except Exception:                                              # noqa: BLE001
        return "ALT"


def keys_text(mod="ALT"):
    """The KEYS paragraph, with the main modifier the binds really use."""
    return (f"{mod}+Tab / {mod}+SHIFT+Tab: the next / previous window on this workspace.  "
            f"SUPER+Tab: the workspace you came from.  {mod}+U: the window asking for "
            "attention, else the last one.")


def choice_sub(key, value, default):
    """The line under a choice: what it means, and "the default" when it is."""
    text = SUBS.get((key, value)) or (f"{value} rows, then it scrolls" if key == "lines" else value)
    return text + ("  ·  the default" if value == default else "")


class Page:
    def __init__(self):
        self.widget = page_box()
        w = self.widget
        self.updating = False
        self.error = dp.label("", "ctl-sub")
        self.error.set_line_wrap(True)
        self.error.set_no_show_all(True)
        w.pack_start(self.error, False, False, 0)

        w.pack_start(heading("WINDOW SWITCHER"), False, False, 0)
        grid, self.state_sub = row("", "SUPER+W", "checking…",
                                   link("Try it", lambda: spawn(os.path.join(HYPR, "window-switcher.py"))))
        w.pack_start(grid, False, False, 0)
        self.chips, self.subs = {}, {}
        for key, icon, title, items in CHOICES:
            grid, self.subs[key] = row(icon, title, "")
            w.pack_start(grid, False, False, 0)
            chips = Chips(lambda k, key=key: self.set(key, k))
            chips.widget.set_max_children_per_line(4)
            chips.widget.set_min_children_per_line(len(items))
            chips.widget.set_halign(Gtk.Align.START)
            chips.widget.set_margin_start(36)
            chips.items = items
            self.chips[key] = chips
            w.pack_start(chips.widget, False, False, 0)
        w.pack_start(sep(), False, False, 0)

        w.pack_start(heading("KEYS"), False, False, 0)
        self.keys = keys = dp.label(keys_text(), "ctl-sub")
        keys.set_line_wrap(True)
        keys.set_xalign(0)
        w.pack_start(keys, False, False, 0)
        w.pack_start(links_row(link("Open Keyboard shortcuts", lambda: spawn(SETTINGS, "shortcuts"))),
                     False, False, 0)

    def set(self, key, value):
        if not self.updating:
            background(lambda: attempt(CONF_CLI, "set", key, value), self.done)

    def done(self, error):
        self.error.set_text(f"!  {error}" if error else "")
        self.error.set_visible(bool(error))
        self.refresh()

    def refresh(self):
        background(lambda: run_json(CONF_CLI, "status", "--json", timeout=10), self.draw)
        background(main_mod, lambda mod: self.keys.set_text(keys_text(mod)))

    def draw(self, data):
        if not data:
            self.state_sub.set_text("switcher_conf.py did not answer")
            return
        self.updating = True
        values, defaults = data["values"], data["defaults"]
        for key, chips in self.chips.items():
            chips.set(chips.items, values[key])
            self.subs[key].set_text(choice_sub(key, values[key], defaults[key]))
        self.state_sub.set_text("the windows below in a searchable list; Enter focuses one")
        self.widget.show_all()
        self.updating = False
