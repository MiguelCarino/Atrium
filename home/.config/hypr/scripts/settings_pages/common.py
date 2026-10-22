"""Shared building blocks for the Settings pages (settings_pages/*.py).

A page is a module in this folder with

    PAGE = {"id": "fonts", "title": "Fonts", "icon": "\\uf031", "group": "Look", "order": 30,
            "keywords": ["font", "text size", "hinting", "cursor"]}
    class Page:
        def __init__(self): self.widget = <a Gtk widget, usually page_box()>
        def refresh(self): ...    # called each time the page is shown

settings.py finds every module here with a PAGE and lists it in the sidebar
under its group (groups in GROUPS order, pages by "order").

"keywords" is optional: the words people may search for that the title does
not say -- what is on the page ("tap to click", "hdr", "time zone"), other
names for it ("wifi", "dnd"), a Spanish word where one is likely ("sonido").
The sidebar's search box and the launcher ("Settings: <page>") match a page
by its title and these (settings_pages/_catalog.py: every typed word must
start a word of either). Keep PAGE literal -- plain strings, numbers and a
list -- because the launcher reads it from the source without importing the
page (a PAGE built from variables still works in the window, but the launcher
cannot see it).

refresh() must not block: anything slow goes through background(). Every control runs a
command or writes a setting and then redraws from what the system reports --
pages hold no settings of their own.

The look comes from the panels' stylesheet (waybar/panel.css and the
desktop theme), so use its classes: kb-heading, ctl-row / ctl-title /
ctl-sub / ctl-icon / ctl-value, ctl-link, dev-pick (+ .active), ctl-slider,
ctl-sep -- the helpers below do.
"""
import json
import os
import subprocess
import sys
import threading
import time

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import GLib, Gtk  # noqa: E402

HYPR = os.path.expanduser("~/.config/hypr/scripts")
WAYBAR = os.path.expanduser("~/.config/waybar/scripts")
sys.path.insert(0, WAYBAR)
import display_panel as dp  # noqa: E402  (Chips, Slider, label)

from settings_pages._catalog import GROUPS  # noqa: E402,F401  (the sidebar's group order)
EMERGENCY = os.path.join(HYPR, "emergency-alerts.py")
DOCTOR = os.path.join(HYPR, "doctor.py")
SNAPSHOTS = os.path.join(HYPR, "snapshots.py")
GUARD = os.path.join(HYPR, "hypr-guard.py")
AUTOMOUNT = os.path.join(HYPR, "automount.py")
PHONE = os.path.join(HYPR, "phone.py")
GAMES = os.path.join(HYPR, "game-profiles.py")
PANEL = os.path.join(WAYBAR, "panel.py")
SETUP_ROOT = os.path.join(HYPR, "setup-root.sh")
Chips, Slider, label = dp.Chips, dp.Slider, dp.label


def run(*cmd, timeout=15):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def run_json(*cmd, timeout=15):
    try:
        return json.loads(run(*cmd, timeout=timeout) or "null")
    except ValueError:
        return None


def background(work, done):
    """work() in a thread, done(result) back on the GTK thread."""
    def go():
        result = work()
        GLib.idle_add(lambda: (done(result), False)[1])
    threading.Thread(target=go, daemon=True).start()


def spawn(*cmd):
    subprocess.Popen(cmd, start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# -- building blocks (the panels' classes, so the theme styles them) ---------------
def heading(text):
    return dp.label(text, "kb-heading")


def sep():
    s = Gtk.Separator()
    s.get_style_context().add_class("ctl-sep")
    return s


def link(text, on_click):
    b = Gtk.Button(label=text)
    b.get_style_context().add_class("ctl-link")
    b.connect("clicked", lambda _b: on_click())
    return b


def row(icon, title, sub="", widget=None):
    """The panels' ctl-row: icon, title over a sub line, a widget at the end.
    Returns (grid, sub label)."""
    grid = Gtk.Grid()
    grid.get_style_context().add_class("ctl-row")
    grid.set_column_spacing(12)
    ic = dp.label(icon, "ctl-icon", 0.5)
    ic.set_valign(Gtk.Align.CENTER)
    grid.attach(ic, 0, 0, 1, 2)
    grid.attach(dp.label(title, "ctl-title"), 1, 0, 1, 1)
    sub_label = dp.label(sub, "ctl-sub")
    sub_label.set_hexpand(True)
    sub_label.set_line_wrap(True)
    sub_label.set_max_width_chars(70)
    grid.attach(sub_label, 1, 1, 1, 1)
    if widget is not None:
        widget.set_valign(Gtk.Align.CENTER)
        grid.attach(widget, 2, 0, 1, 2)
    return grid, sub_label


def links_row(*buttons):
    box = Gtk.Box(spacing=6)
    box.set_halign(Gtk.Align.END)
    for b in buttons:
        box.pack_start(b, False, False, 0)
    return box


def page_box():
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    box.set_margin_start(6)
    box.set_margin_end(6)
    return box


def clear(box):
    for child in box.get_children():
        box.remove(child)


def ago(seconds):
    if seconds is None:
        return "never"
    if seconds < 90:
        return f"{seconds} s ago"
    if seconds < 5400:
        return f"{seconds // 60} min ago"
    return f"{seconds // 3600} h ago"
