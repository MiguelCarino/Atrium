#!/usr/bin/env python3
"""Shortcuts panel — what the keyboard pill in the bar (and SUPER+F1) opens.

Every Hyprland bind that carries a description, grouped into sections. The list
is read from `hyprctl binds -j` each time the panel opens, never from a copy:
the Hyprland config (hyprland.lua and its lua/*.lua modules) is the only place
a shortcut is defined, so this can't go stale.
A bind shows up here as soon as it has

    { description = "Section: what it does" }

and the part before the colon is the heading it lands under. Binds without a
description (the keys inside the resize submap) are left out on purpose.

Families collapse into one row: the four arrow binds that share a description
and modifiers become "← → ↑ ↓", ALT+1..6 becomes "1–6". That is what keeps a
config with ~100 binds down to a panel you can read at a glance.

Your own changes (Settings > Keyboard shortcuts, kept in
~/.local/state/hypr/userbinds.conf) show too: a shortcut you moved is on its
new keys -- that is what Hyprland reports -- marked "· moved"; your own
shortcuts are under "Custom" (or the group you named them into); the ones
you turned off are listed at the end under "Turned off", since Hyprland no
longer has them to report.

Click anywhere on the card to close it, or press the pill / SUPER+F1 again.
The panel takes no keyboard focus (see panelui.place), so Esc can't do it.

    keybinds_panel.py [x,y]   desktop position of the click that opened it
"""

import json
import os
import subprocess
import sys

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gtk  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import panelui  # noqa: E402


def read_changes():
    """The user's changes, from ~/.config/hypr/scripts/shortcuts.py (which
    owns the file's format): {"off": {KEYS: desc}, "moves": {KEYS: (new
    keys, desc)}, "adds": [...]}. Empty when it can't be read: the panel
    then shows what Hyprland has, as it always did."""
    try:
        import importlib.util
        path = os.path.expanduser("~/.config/hypr/scripts/shortcuts.py")
        spec = importlib.util.spec_from_file_location("shortcuts_backend", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.load(), module.canon
    except Exception:  # noqa: BLE001 -- never let the panel fail over this
        return {"off": {}, "moves": {}, "adds": []}, lambda k: k

COLUMNS = 3

# Reading order. Sections not listed here still appear, after these.
SECTION_ORDER = [
    "Navigation", "Windows", "Workspaces", "Monitors", "Scratchpads", "Groups",
    "Apps", "Tools", "Screenshots", "Recording", "Notifications", "Media", "Games", "Bar",
    "Session", "Help", "Custom",
]

# xkb modifier bits, as hyprctl reports them in "modmask". Listed in the order
# they are printed -- the conventional Super, Ctrl, Alt, Shift.
MODS = [(64, "Super"), (4, "Ctrl"), (8, "Alt"), (1, "Shift")]

KEY_NAMES = {
    "left": "←", "right": "→", "up": "↑", "down": "↓",
    "grave": "`", "Return": "Enter", "return": "Enter", "escape": "Esc",
    "bracketleft": "[", "bracketright": "]", "Tab": "Tab",
    "mouse:272": "Left drag", "mouse:273": "Right drag",
    "mouse_down": "Wheel ↓", "mouse_up": "Wheel ↑",
    "XF86AudioRaiseVolume": "Vol +", "XF86AudioLowerVolume": "Vol −",
    "XF86AudioMute": "Mute", "XF86AudioMicMute": "Mic mute",
    "XF86AudioPlay": "Play", "XF86AudioNext": "Next",
    "XF86AudioPrev": "Prev", "XF86AudioStop": "Stop",
}
ARROWS = ["left", "right", "up", "down"]


def read_binds():
    try:
        out = subprocess.run(["hyprctl", "binds", "-j"], capture_output=True,
                             text=True, timeout=2).stdout
        return json.loads(out)
    except (subprocess.SubprocessError, OSError, ValueError):
        return []


def mod_names(mask):
    return [name for bit, name in MODS if mask & bit]


def key_label(keys):
    """One label for a family of keys that share a description and modifiers."""
    if sorted(keys) == sorted(ARROWS):
        return "← → ↑ ↓"
    if len(keys) > 1 and all(k.isdigit() for k in keys):
        nums = sorted(int(k) for k in keys)
        if nums == list(range(nums[0], nums[-1] + 1)):
            return f"{nums[0]}–{nums[-1]}"
    return " ".join(KEY_NAMES.get(k, k.upper() if len(k) == 1 else k) for k in keys)


def bind_keys(bind):
    """"SUPER+SHIFT+Q" for a hyprctl bind, comparable with canon()'s."""
    mods = [name.upper() for bit, name in MODS if bind.get("modmask", 0) & bit]
    return "+".join(mods + [str(bind.get("key", "")).upper()])


def sections_from(binds, changes=None):
    """{section: [(mods, key_label, text)]}, rows in config order. changes:
    read_changes()'s (over, canon), to mark moved shortcuts and list the
    ones turned off."""
    over, canon = changes or ({"off": {}, "moves": {}, "adds": []}, lambda k: k)
    moved = {(desc, canon(new)) for new, desc in over["moves"].values()}
    rows = {}           # (section, text, modmask) -> [keys], insertion-ordered
    for bind in binds:
        desc = bind.get("description") or ""
        if not desc or bind.get("submap"):
            continue
        section, _, text = desc.partition(": ")
        if not text:
            section, text = "Other", desc
        if (desc, bind_keys(bind)) in moved:
            text += "  · moved"
        rows.setdefault((section, text, bind["modmask"]), []).append(bind["key"])
    for desc in sorted(over["off"].values()):
        rows.setdefault(("Turned off", desc or "?", 0), []).append("off")

    sections = {}
    for (section, text, mask), keys in rows.items():
        sections.setdefault(section, []).append((mod_names(mask), key_label(keys), text))

    ordered = [s for s in SECTION_ORDER if s in sections]
    ordered += [s for s in sections if s not in SECTION_ORDER and s != "Turned off"]
    ordered += ["Turned off"] if "Turned off" in sections else []
    return [(s, sections[s]) for s in ordered]


def balance(sections, columns):
    """Fill columns in reading order, starting a new column once the current
    one passes its share of the rows. Keeps sections whole and in order, which
    matters more for scanning than perfectly even heights."""
    total = sum(len(rows) + 2 for _, rows in sections)     # +2: heading + gap
    share = total / columns
    out = [[] for _ in range(columns)]
    col, filled = 0, 0
    for section in sections:
        weight = len(section[1]) + 2
        if filled and filled + weight / 2 > share * (col + 1) and col < columns - 1:
            col += 1
        out[col].append(section)
        filled += weight
    return [c for c in out if c]


class Keybinds(panelui.Panel):
    def build(self):
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        header.set_name("kb-header")
        title = Gtk.Label(label="Keyboard shortcuts")
        title.set_name("kb-title")
        title.set_xalign(0)
        header.pack_start(title, True, True, 0)
        hint = Gtk.Label(label="Super+F1 · change them in Settings (Super+I) · click to close")
        hint.set_name("kb-hint")
        header.pack_end(hint, False, False, 0)
        self.card.pack_start(header, False, False, 0)

        sections = sections_from(read_binds(), read_changes())
        if not sections:
            empty = Gtk.Label(label="Could not read binds from hyprctl.")
            empty.set_name("kb-hint")
            self.card.pack_start(empty, False, False, 0)
        else:
            columns = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=28)
            columns.set_name("kb-columns")
            for column in balance(sections, COLUMNS):
                box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
                for name, rows in column:
                    box.pack_start(self.section(name, rows), False, False, 0)
                columns.pack_start(box, False, False, 0)

            # No ScrolledWindow: under gtk-layer-shell it sizes the panel to the
            # scroller's *minimum* height (one row) and clips the rest -- tested.
            # The whole list is ~800px, which fits even a 1080px-tall screen.
            self.card.pack_start(columns, False, False, 0)

        self.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        self.connect("button-press-event", lambda *_: self.quit())

    def section(self, name, rows):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        box.get_style_context().add_class("kb-section")
        heading = Gtk.Label(label=name.upper())
        heading.get_style_context().add_class("kb-heading")
        heading.set_xalign(0)
        box.pack_start(heading, False, False, 0)

        grid = Gtk.Grid()
        grid.set_column_spacing(14)
        grid.set_row_spacing(3)
        for row, (mods, keys, text) in enumerate(rows):
            chips = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=3)
            chips.set_halign(Gtk.Align.END)
            for part in mods + [keys]:
                cap = Gtk.Label(label=part)
                cap.get_style_context().add_class("kb-cap")
                chips.pack_start(cap, False, False, 0)
            grid.attach(chips, 0, row, 1, 1)

            label = Gtk.Label(label=text)
            label.get_style_context().add_class("kb-desc")
            label.set_xalign(0)
            grid.attach(label, 1, row, 1, 1)
        box.pack_start(grid, False, False, 0)
        return box


def main():
    panelui.run(Keybinds)


if __name__ == "__main__":
    main()
