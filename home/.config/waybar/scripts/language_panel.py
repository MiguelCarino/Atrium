#!/usr/bin/env python3
"""Language panel -- what the language pill opens.

    Keyboard layout   the xkb groups in input.kb_layout (us, latam), the same
                      switch as SUPER+Space
    Input method      fcitx5's items (~/.config/fcitx5/profile): direct typing
                      or Mozc; Super+Space reaches it after the last layout

The two are independent and stack (see ~/.config/hypr/lua/autostart.lua): the
layout decides which letters the keys produce, the input method then reads
them. A pick applies at once and closes the panel, like any menu.

    language_panel.py [x,y]   desktop position of the click that opened it
"""

import configparser
import json
import os
import subprocess
import sys

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import panelui  # noqa: E402

XKB_RULES = "/usr/share/X11/xkb/rules/evdev.lst"
FCITX_PROFILE = os.path.expanduser("~/.config/fcitx5/profile")
# fcitx5 item names are ids; these read better. Anything else shows its id.
IM_NAMES = {
    "keyboard-us": "Direct (no input method)",
    "mozc": "Japanese (Mozc)",
}


def run(*cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=2).stdout
    except (subprocess.SubprocessError, OSError):
        return ""


def layout_names():
    """xkb code -> "English (US)", from the same list every layout picker uses."""
    names = {}
    try:
        with open(XKB_RULES) as handle:
            section = None
            for line in handle:
                if line.startswith("!"):
                    section = line[1:].strip()
                elif section == "layout" and line.strip():
                    code, _, desc = line.strip().partition(" ")
                    names.setdefault(code, desc.strip())
    except OSError:
        pass
    return names


def layouts():
    """[(index, code, name)] in kb_layout order, and the active index."""
    try:
        option = json.loads(run("hyprctl", "getoption", "input:kb_layout", "-j"))
        codes = [c.strip() for c in option["str"].split(",") if c.strip()]
    except (ValueError, KeyError):
        codes = []
    active = 0
    try:
        for kb in json.loads(run("hyprctl", "devices", "-j"))["keyboards"]:
            if kb.get("main"):
                active = kb.get("active_layout_index", 0)
    except (ValueError, KeyError):
        pass
    names = layout_names()
    return [(i, c, names.get(c, c)) for i, c in enumerate(codes)], active


def input_methods():
    """[(fcitx5 item name, label)] from the profile, and the current one."""
    profile = configparser.ConfigParser(interpolation=None)
    profile.read(FCITX_PROFILE)
    items = []
    for section in profile.sections():
        if section.startswith("Groups/0/Items/") and profile.has_option(section, "Name"):
            name = profile.get(section, "Name")
            items.append((name, IM_NAMES.get(name, name)))
    return items, run("fcitx5-remote", "-n").strip()


class Language(panelui.Panel):
    def build(self):
        layout_list, active = layouts()
        # The switch key is a setting now (Settings > Keyboard, mouse &
        # touchpad); ask its script rather than assume SUPER+Space.
        switch = run(os.path.expanduser("~/.config/hypr/scripts/input-settings.py"), "switch-label").strip()
        self.section("Keyboard layout", switch or "Super+Space",
                     [(code.upper(), name, i == active,
                       lambda i=i: run("hyprctl", "switchxkblayout", "all", str(i)))
                      for i, code, name in layout_list])

        ims, current = input_methods()
        if len(ims) > 1:
            sep = Gtk.Box()
            sep.get_style_context().add_class("ctl-sep")
            self.card.pack_start(sep, False, False, 6)
            self.section("Input method", "Super+Space",
                         [("", label, name == current,
                           lambda name=name: run("fcitx5-remote", "-s", name))
                          for name, label in ims])

    def section(self, title, hint, choices):
        header = Gtk.Box(spacing=8)
        label = Gtk.Label(label=title)
        label.get_style_context().add_class("ctl-title")
        label.set_xalign(0)
        header.pack_start(label, True, True, 0)
        keys = Gtk.Label(label=hint)
        keys.get_style_context().add_class("ctl-sub")
        header.pack_end(keys, False, False, 0)
        self.card.pack_start(header, False, False, 0)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        box.get_style_context().add_class("dev-list")
        box.set_size_request(280, -1)
        for kind, name, active, apply in choices:
            box.pack_start(self.choice(kind, name, active, apply), False, False, 0)
        self.card.pack_start(box, False, False, 0)

    def choice(self, kind, name, active, apply):
        """A dev-pick row, the same radio look as the audio panel's devices."""
        button = Gtk.Button()
        button.set_relief(Gtk.ReliefStyle.NONE)
        style = button.get_style_context()
        style.add_class("dev-pick")
        if active:
            style.add_class("active")
        row = Gtk.Box(spacing=8)
        dot = Gtk.Box()
        dot.get_style_context().add_class("dev-dot")
        dot.set_valign(Gtk.Align.CENTER)
        row.pack_start(dot, False, False, 0)
        text = Gtk.Label(label=name)
        text.get_style_context().add_class("dev-name")
        text.set_xalign(0)
        row.pack_start(text, True, True, 0)
        if kind:
            code = Gtk.Label(label=kind)
            code.get_style_context().add_class("dev-kind")
            row.pack_end(code, False, False, 0)
        button.add(row)
        button.connect("clicked", lambda _b: (apply(), self.quit()))
        return button


if __name__ == "__main__":
    panelui.run(Language)
