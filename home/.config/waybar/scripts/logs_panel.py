#!/usr/bin/env python3
"""Logs panel -- today's problems from the desktop, in one place.

What counts as the desktop: every unit ~/.config/systemd/user's
*.target.wants/ pulls in (the same list doctor.py checks), Hyprland itself
(wayland-wm@hyprland...), and what was started from it (app-*.scope: binds,
the launcher's commands) -- including scripts that log through
~/.config/hypr/scripts/desklog.py.

    Errors      priority err and worse, plus lines that read like one
                (Traceback, "error", "failed", "exception") -- a Python
                service's traceback goes to the journal at info level
    Warnings    the above and warnings
    All today   everything the desktop logged today (the newest MAX_LINES)

The unit chips under them narrow it to one unit; "All" is every one. Newest
first. Clicking a line copies "time unit: message".

    logs_panel.py [x,y]   desktop position of the click that opened it
"""
import json
import os
import re
import subprocess
import sys
import time

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Pango  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import panelui  # noqa: E402

sys.path.insert(0, os.path.expanduser("~/.config/hypr/scripts"))
import doctor  # noqa: E402  (wanted_units: the desktop's units)

WIDTH = 520
MAX_LINES = 400
LEVELS = [("errors", "Errors"), ("warnings", "Warnings"), ("all", "All today")]
ERRORISH = re.compile(r"traceback|exception|\berror\b|failed|fatal|segfault|core dumped", re.I)
WARNISH = re.compile(r"\bwarn(ing)?\b|deprecat", re.I)


def label(text, cls, xalign=0.0):
    widget = Gtk.Label(label=text)
    widget.get_style_context().add_class(cls)
    widget.set_xalign(xalign)
    return widget


def desktop_units():
    units = set(doctor.wanted_units())
    for u in list(units):
        if u.endswith(".timer"):
            units.add(u[:-6] + ".service")
    return units


def who(entry, units):
    """The group a journal entry belongs to, or None when not the desktop's."""
    unit = entry.get("_SYSTEMD_USER_UNIT") or ""
    ident = entry.get("SYSLOG_IDENTIFIER") or ""
    if unit in units:
        return unit.removesuffix(".service")
    if unit.startswith("wayland-wm@"):
        return "Hyprland" if ident.lower() in ("hyprland", "") else ident
    if unit.startswith("app-") or (not unit and ident):
        return ident or unit
    return None


def classify(entry):
    """"error", "warning" or "info" -- by priority, or by what the line says."""
    prio = int(entry.get("PRIORITY", 6))
    msg = entry.get("MESSAGE")
    msg = msg if isinstance(msg, str) else ""
    if prio <= 3 or ERRORISH.search(msg):
        return "error"
    if prio == 4 or WARNISH.search(msg):
        return "warning"
    return "info"


def entries():
    """[(epoch, group, level, message)], newest first."""
    try:
        out = subprocess.run(["journalctl", "--user", "--since", "today", "-o", "json", "-r",
                              "-n", "20000", "--no-pager"],
                             capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    units, rows = desktop_units(), []
    for line in out.splitlines():
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        group = who(entry, units)
        msg = entry.get("MESSAGE")
        if group is None or not isinstance(msg, str) or not msg.strip():
            continue
        rows.append((int(entry.get("__REALTIME_TIMESTAMP", 0)) / 1e6, group, classify(entry), msg.strip()))
    return rows


class Chips:
    def __init__(self, on_pick):
        self.on_pick = on_pick
        self.widget = Gtk.FlowBox()
        self.widget.set_selection_mode(Gtk.SelectionMode.NONE)
        self.widget.set_max_children_per_line(4)
        self.widget.set_column_spacing(4)
        self.widget.set_row_spacing(4)
        self.buttons = {}

    def set(self, items, active):
        if list(self.buttons) != [k for k, _ in items]:
            for child in self.widget.get_children():
                self.widget.remove(child)
            self.buttons = {}
            for key, caption in items:
                button = Gtk.Button(label=caption)
                button.get_style_context().add_class("dev-pick")
                button.set_can_focus(False)
                button.connect("clicked", lambda _b, k=key: self.on_pick(k))
                self.buttons[key] = button
                self.widget.add(button)
            self.widget.show_all()
        for key, button in self.buttons.items():
            style = button.get_style_context()
            (style.add_class if key == active else style.remove_class)("active")


class Logs(panelui.Panel):
    def build(self):
        self.level, self.unit = "errors", ""
        self.rows = entries()
        self.card.pack_start(label("LOGS TODAY", "kb-heading"), False, False, 0)
        self.levels = Chips(self.pick_level)
        self.levels.widget.set_max_children_per_line(3)
        self.card.pack_start(self.levels.widget, False, False, 0)
        self.units = Chips(self.pick_unit)
        self.card.pack_start(self.units.widget, False, False, 0)
        self.summary = label("", "ctl-sub")
        self.card.pack_start(self.summary, False, False, 0)
        self.card.set_size_request(WIDTH + 30, panelui.CARD_HEIGHT + 120)
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)
        self.body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        scroll.add(self.body)
        self.card.pack_start(scroll, True, True, 0)
        reload_button = Gtk.Button(label="Reload")
        reload_button.get_style_context().add_class("ctl-link")
        reload_button.set_halign(Gtk.Align.END)
        reload_button.connect("clicked", lambda _b: self.reload())
        self.card.pack_start(reload_button, False, False, 0)
        self.show_rows()

    def reload(self):
        self.rows = entries()
        self.show_rows()

    def pick_level(self, key):
        self.level = key
        self.show_rows()

    def pick_unit(self, key):
        self.unit = key
        self.show_rows()

    def wanted(self, row):
        _, group, level, _ = row
        if self.unit and group != self.unit:
            return False
        return (self.level == "all" or level == "error"
                or (self.level == "warnings" and level == "warning"))

    def show_rows(self):
        self.levels.set(LEVELS, self.level)
        by_level = [r for r in self.rows if self.level == "all" or r[2] == "error"
                    or (self.level == "warnings" and r[2] == "warning")]
        counts = {}
        for r in by_level:
            counts[r[1]] = counts.get(r[1], 0) + 1
        groups = sorted(counts, key=lambda g: -counts[g])
        if self.unit and self.unit not in counts:
            self.unit = ""
        self.units.set([("", f"All ({len(by_level)})")] + [(g, f"{g} ({counts[g]})") for g in groups[:11]],
                       self.unit)
        for child in self.body.get_children():
            self.body.remove(child)
        shown = [r for r in self.rows if self.wanted(r)][:MAX_LINES]
        self.summary.set_text(f"{len(shown)} line{'s' if len(shown) != 1 else ''}"
                              + ("" if shown else "  --  nothing to worry about today"))
        for row in shown:
            self.body.pack_start(self.line(row), False, False, 0)
        self.body.show_all()

    def line(self, row):
        when, group, level, msg = row
        stamp = time.strftime("%H:%M:%S", time.localtime(when))
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        top = Gtk.Box(spacing=8)
        top.pack_start(label(f"{stamp}  {group}", "sn-label"), True, True, 0)
        if level != "info":
            top.pack_end(label(level, "sn-label", 1.0), False, False, 0)
        box.pack_start(top, False, False, 0)
        text = label(msg, "sn-value" if level == "error" else "ctl-sub")
        text.set_line_wrap(True)
        text.set_lines(3)
        text.set_ellipsize(Pango.EllipsizeMode.END)
        text.set_max_width_chars(64)
        box.pack_start(text, False, False, 0)
        button = Gtk.Button()
        button.add(box)
        button.set_size_request(WIDTH, -1)
        button.get_style_context().add_class("dk-fs")
        button.set_tooltip_text("Click: copy this line")
        button.connect("clicked", lambda _b: self.copy(f"{stamp} {group}: {msg}"))
        return button

    def copy(self, text):
        try:
            subprocess.run(["wl-copy"], input=text, text=True, timeout=3)
        except (OSError, subprocess.SubprocessError):
            pass
        self.quit()


if __name__ == "__main__":
    panelui.run(Logs)
