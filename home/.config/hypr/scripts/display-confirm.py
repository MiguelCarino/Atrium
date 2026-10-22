#!/usr/bin/env python3
""""Keep this display setting?" -- with a countdown that undoes it.

    display-confirm.py "<what changed>" <revert command ...>

display.py runs this (detached) after a refresh-rate or HDR change asked for
with --confirm. A card on EVERY screen -- the one that changed may be the
one that went black -- asks Keep / Undo; after TIMEOUT_S with no answer it
undoes the change by itself. Enter = Keep, Escape = Undo; a second change
while one card is up replaces it (the newest change wins, the older one is
kept as it is).
"""
import os
import signal
import subprocess
import sys

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GtkLayerShell", "0.1")
from gi.repository import Gdk, GLib, Gtk, GtkLayerShell  # noqa: E402

sys.path.insert(0, os.path.expanduser("~/.config/waybar/scripts"))
import panelui  # noqa: E402  (the panels' theme stylesheet)

TIMEOUT_S = 15
PIDFILE = os.path.join(os.environ.get("XDG_RUNTIME_DIR") or "/tmp", "display-confirm.pid")


class Card(Gtk.Window):
    def __init__(self, monitor, what, owner):
        super().__init__()
        self.set_name("panel-window")
        self.set_app_paintable(True)
        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_namespace(self, "waybar-panel")
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.OVERLAY)
        GtkLayerShell.set_monitor(self, monitor)
        GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.ON_DEMAND)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_name("panel")
        self.add(box)
        title = Gtk.Label(label="KEEP THIS DISPLAY SETTING?")
        title.get_style_context().add_class("kb-heading")
        box.pack_start(title, False, False, 0)
        body = Gtk.Label(label=what)
        body.get_style_context().add_class("ctl-title")
        box.pack_start(body, False, False, 0)
        self.count = Gtk.Label()
        self.count.get_style_context().add_class("ctl-sub")
        box.pack_start(self.count, False, False, 0)
        row = Gtk.Box(spacing=8)
        row.set_halign(Gtk.Align.CENTER)
        for caption, keep in (("Keep", True), ("Undo", False)):
            button = Gtk.Button(label=caption)
            button.get_style_context().add_class("dev-pick")
            if keep:
                button.get_style_context().add_class("active")
            button.connect("clicked", lambda _b, k=keep: owner.finish(k))
            row.pack_start(button, False, False, 0)
        box.pack_start(row, False, False, 0)
        self.connect("key-press-event", lambda _w, e: owner.key(e))


class Confirm:
    def __init__(self, what, revert):
        self.revert = revert
        self.left = TIMEOUT_S
        panelui.load_css()
        display = Gdk.Display.get_default()
        self.cards = [Card(display.get_monitor(i), what, self) for i in range(display.get_n_monitors())]
        for card in self.cards:
            card.show_all()
        self.tick()
        GLib.timeout_add_seconds(1, self.tick)

    def tick(self):
        if self.left <= 0:
            self.finish(False)
            return False
        for card in self.cards:
            card.count.set_text(f"Undone by itself in {self.left} s")
        self.left -= 1
        return True

    def key(self, event):
        if event.keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            self.finish(True)
        elif event.keyval == Gdk.KEY_Escape:
            self.finish(False)
        return True

    def finish(self, keep):
        if not keep:
            subprocess.Popen(self.revert, start_new_session=True,
                             env=dict(os.environ, DISPLAY_QUIET="1"))
        Gtk.main_quit()


def main(argv):
    if len(argv) < 2:
        sys.exit(__doc__)
    # The newest change wins: an older card (for a setting already replaced)
    # just goes away, keeping what it was asking about.
    try:
        with open(PIDFILE) as handle:
            os.kill(int(handle.read()), signal.SIGTERM)
    except (OSError, ValueError):
        pass
    with open(PIDFILE, "w") as handle:
        handle.write(str(os.getpid()))
    signal.signal(signal.SIGTERM, lambda *_: Gtk.main_quit())
    Confirm(argv[0], argv[1:])
    Gtk.main()
    try:
        with open(PIDFILE) as handle:
            if handle.read().strip() == str(os.getpid()):
                os.remove(PIDFILE)
    except OSError:
        pass


if __name__ == "__main__":
    main(sys.argv[1:])
