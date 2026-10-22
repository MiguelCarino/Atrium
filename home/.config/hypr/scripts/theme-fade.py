#!/usr/bin/env python3
"""Cross-fade for a theme switch: a still of every screen is laid over it
(layer-shell, overlay layer), the theme changes underneath -- the bar
reloading, the wallpapers, the borders -- and then the still fades away.

theme.py set runs this and talks to it over stdin / stdout:

    theme-fade.py      prints "ready" once every screen is covered, then
                       waits; a line (or EOF) on stdin = the switch is done:
                       hold HOLD_MS for the bar to finish restyling, fade
                       over FADE_MS, exit

It gives up by itself after SAFETY_S, so a switch that hangs can never
leave the screens frozen behind a picture. Prints "skip" instead of "ready"
when it cannot cover the screens (grim failed, no screens), and theme.py
then just switches.

The layer surface is "theme-fade"; lua/rules.lua gives it no_anim so it
covers at once instead of popping in.
"""
import json
import os
import subprocess
import sys
import tempfile

import cairo
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
gi.require_version("GtkLayerShell", "0.1")
from gi.repository import Gdk, GdkPixbuf, GLib, Gtk, GtkLayerShell  # noqa: E402

HOLD_MS = 700
FADE_MS = 550
SAFETY_S = 20


def outputs():
    out = subprocess.run(["hyprctl", "monitors", "-j"], capture_output=True, text=True, timeout=3).stdout
    return json.loads(out or "[]")


def capture(mons, folder):
    """{name: pixbuf} -- grim per screen, all at once."""
    procs = {m["name"]: subprocess.Popen(["grim", "-o", m["name"], "-t", "ppm",
                                          os.path.join(folder, m["name"] + ".ppm")],
                                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
             for m in mons}
    shots = {}
    for name, proc in procs.items():
        if proc.wait(timeout=5) == 0:
            shots[name] = GdkPixbuf.Pixbuf.new_from_file(os.path.join(folder, name + ".ppm"))
    return shots


class Cover(Gtk.Window):
    def __init__(self, monitor, pixbuf, fader):
        super().__init__()
        self.pixbuf, self.fader = pixbuf, fader
        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_namespace(self, "theme-fade")
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.OVERLAY)
        GtkLayerShell.set_monitor(self, monitor)
        for edge in (GtkLayerShell.Edge.TOP, GtkLayerShell.Edge.BOTTOM,
                     GtkLayerShell.Edge.LEFT, GtkLayerShell.Edge.RIGHT):
            GtkLayerShell.set_anchor(self, edge, True)
        GtkLayerShell.set_exclusive_zone(self, -1)
        GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.NONE)
        visual = self.get_screen().get_rgba_visual()
        if visual:
            self.set_visual(visual)
        self.set_app_paintable(True)
        area = Gtk.DrawingArea()
        area.connect("draw", self.on_draw)
        self.area = area
        self.add(area)
        self.drawn = False
        # Clicks go through to whatever is underneath (an empty input region).
        self.connect("realize", lambda w: w.input_shape_combine_region(cairo.Region()))

    def on_draw(self, widget, cr):
        w, h = widget.get_allocated_width(), widget.get_allocated_height()
        cr.set_operator(0)          # CLEAR
        cr.paint()
        cr.set_operator(2)          # OVER
        cr.scale(w / self.pixbuf.get_width(), h / self.pixbuf.get_height())
        Gdk.cairo_set_source_pixbuf(cr, self.pixbuf, 0, 0)
        cr.paint_with_alpha(self.fader.alpha)
        if not self.drawn:
            self.drawn = True
            self.fader.drawn()
        return True


class Fader:
    def __init__(self):
        self.alpha = 1.0
        self.covers = []
        self.waiting = 0
        self.started = None

    def run(self):
        mons = outputs()
        with tempfile.TemporaryDirectory(dir=os.environ.get("XDG_RUNTIME_DIR")) as folder:
            shots = capture(mons, folder)
        display = Gdk.Display.get_default()
        for i in range(display.get_n_monitors()):
            gdk_mon = display.get_monitor(i)
            geo = gdk_mon.get_geometry()
            match = next((m for m in mons if m["name"] in shots
                          and (m["x"], m["y"]) == (geo.x, geo.y)), None)
            if match:
                self.covers.append(Cover(gdk_mon, shots[match["name"]], self))
        if not self.covers:
            print("skip", flush=True)
            return
        self.waiting = len(self.covers)
        for cover in self.covers:
            cover.show_all()
        GLib.timeout_add_seconds(SAFETY_S, self.go)
        GLib.io_add_watch(sys.stdin, GLib.IO_IN | GLib.IO_HUP, self.on_stdin)
        Gtk.main()

    def drawn(self):
        self.waiting -= 1
        if self.waiting == 0:
            # One more frame so the compositor has really shown them.
            GLib.timeout_add(50, lambda: (print("ready", flush=True), False)[1])

    def on_stdin(self, source, _cond):
        source.readline()
        GLib.timeout_add(HOLD_MS, self.go)
        return False

    def go(self):
        if self.started is None:
            self.started = GLib.get_monotonic_time()
            GLib.timeout_add(16, self.step)
        return False

    def step(self):
        done = (GLib.get_monotonic_time() - self.started) / 1000 / FADE_MS
        self.alpha = max(0.0, 1 - done) ** 2         # ease out: quick start, soft end
        for cover in self.covers:
            cover.area.queue_draw()
        if done >= 1:
            Gtk.main_quit()
            return False
        return True


if __name__ == "__main__":
    Fader().run()
