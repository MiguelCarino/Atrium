#!/usr/bin/env python3
"""The window every popup panel is built on.

waybar cannot host these. A bar is a layer surface anchored by "position", and
the moment a width is set the compositor centres it — there is no way to park
one under the pill that opened it. gtk-layer-shell gives that placement, and
being an ordinary GTK app means the contents can be anything, not just a row of
labels.

Subclasses fill self.card and start their timers in on_ready(), which does not
run until the window is on screen: a GL context, a video sink or anything else
that needs a realized widget will fail if it is set up any earlier.
"""

import json
import os
import subprocess
import sys

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GtkLayerShell", "0.1")
from gi.repository import Gdk, GLib, Gtk, GtkLayerShell  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
CSS_FILE = os.path.join(os.path.dirname(HERE), "panel.css")

# Anchored to the top edge and centred under the cursor, so a panel comes up
# beneath the pill that was clicked rather than in the middle of the screen.
# The exclusive zone stays at 0 (not -1): claim no space of our own, but stay
# clear of the bar's.
MARGIN_TOP = 10
SCREEN_EDGE = 12            # never let a panel touch the side of the monitor


def fallback_output():
    """Where a panel opens when the pointer is on no screen GDK knows: the
    primary (hypr/scripts/screens.py: Settings > Screens' choice, else the
    host file's first screen). Imported here, not at the top: most panels
    never need it."""
    sys.path.insert(0, os.path.expanduser("~/.config/hypr/scripts"))
    import screens
    return screens.primary()


def output_origin(name):
    """Layout position of a connector, straight from the compositor."""
    try:
        out = subprocess.run(["hyprctl", "monitors", "-j"],
                             capture_output=True, text=True, timeout=2).stdout
        for monitor in json.loads(out):
            if monitor.get("name") == name:
                return monitor["x"], monitor["y"]
    except (subprocess.SubprocessError, OSError, ValueError, KeyError):
        pass
    return None


_provider = None


def load_css():
    """Load panel.css, or RE-load it: a second call refills the same provider
    rather than stacking another one on the screen. Panels are short-lived and
    normally load it once, but the display panel's THEME chips change the
    theme while the panel is open -- reloading lets the panel you clicked
    switch with the rest of the desktop instead of keeping the old look until
    it is reopened. (A failed reload keeps whatever was loaded before.)"""
    global _provider
    if not os.path.exists(CSS_FILE):
        return
    provider = _provider or Gtk.CssProvider()
    try:
        provider.load_from_path(CSS_FILE)
    except GLib.Error as exc:
        print(f"panelui: {CSS_FILE}: {exc}", file=sys.stderr)
        return
    if _provider is None:
        _provider = provider
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_USER)


def cursor_from_argv():
    """panel.py passes the pointer position of the click that opened us."""
    if len(sys.argv) > 1:
        try:
            x, y = sys.argv[1].split(",")
            return int(x), int(y)
        except ValueError:
            pass
    return None


class ClickCatcher(Gtk.Window):
    """An invisible sheet over one monitor, under the panel: a click that lands
    on it missed the card, so the panel closes. Exclusive zone 0 keeps it out
    of the bar's strip, so the other pills still take their clicks. Its
    namespace is outside waybar-* so the glass rule never frosts it."""

    def __init__(self, monitor, on_click):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.set_app_paintable(True)
        visual = self.get_screen().get_rgba_visual()
        if visual:
            self.set_visual(visual)
        self.connect("draw", self.on_draw)

        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_namespace(self, "panel-dismiss")
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.TOP)
        for edge in (GtkLayerShell.Edge.TOP, GtkLayerShell.Edge.BOTTOM,
                     GtkLayerShell.Edge.LEFT, GtkLayerShell.Edge.RIGHT):
            GtkLayerShell.set_anchor(self, edge, True)
        GtkLayerShell.set_exclusive_zone(self, 0)
        GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.NONE)
        GtkLayerShell.set_monitor(self, monitor)

        self.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        self.connect("button-press-event", lambda *_: on_click())
        self.show_all()

    @staticmethod
    def on_draw(_widget, cr):
        cr.set_source_rgba(0, 0, 0, 0)
        cr.set_operator(1)              # cairo.OPERATOR_SOURCE
        cr.paint()
        return True


class Panel(Gtk.Window):
    def __init__(self, cursor=None):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.cursor = cursor
        self.monitor = None
        self.placed_width = 0
        self.started = False

        self.set_name("panel-window")
        self.set_app_paintable(True)     # or the rounded corners sit on grey
        self.card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.card.set_name("panel")
        self.add(self.card)

        self.setup()
        self.build()
        self.place()
        # Shown before the card so they stack beneath it on the same layer.
        self.catchers = [ClickCatcher(m, self.quit) for m in self.all_monitors()]
        # The width is only known once GTK has laid the card out, and the margin
        # that centres it under the cursor depends on that width — so this has
        # to be connected before the first allocation, not after.
        self.connect("size-allocate", self.on_allocate)
        self.connect("map-event", self.on_mapped)
        self.connect("delete-event", Gtk.main_quit)
        self.show_all()

    # -- subclass hooks -----------------------------------------------------
    def setup(self):
        """Subclass state, before any widget exists."""

    def build(self):
        """Fill self.card."""

    def on_ready(self):
        """Called once, after the window is actually on screen."""

    def quit(self):
        Gtk.main_quit()

    def on_key(self, _widget, event):
        if event.keyval == Gdk.KEY_Escape:
            self.quit()
            return True
        return False

    # -- placement ----------------------------------------------------------
    def place(self):
        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_namespace(self, "waybar-panel")
        # TOP rather than OVERLAY: a fullscreen window should cover a panel the
        # same way it covers the bar that opened it.
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.TOP)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.TOP, True)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.LEFT, True)
        GtkLayerShell.set_margin(self, GtkLayerShell.Edge.TOP, MARGIN_TOP)
        GtkLayerShell.set_exclusive_zone(self, 0)
        # The keyboard is the card's while it is open, so Esc closes it. It
        # used to take none ("whatever is playing behind keeps it"), but every
        # card opens on a click or a bind -- none pops up by itself -- and a
        # click outside closes it anyway; focus goes back when it does.
        GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.ON_DEMAND)
        if not getattr(self, "_esc_connected", False):
            self._esc_connected = True
            self.connect("key-press-event", self.on_key)

        self.monitor = self.pick_monitor()
        if self.monitor:
            GtkLayerShell.set_monitor(self, self.monitor)

    def all_monitors(self):
        display = self.get_display()
        return [display.get_monitor(i) for i in range(display.get_n_monitors())]

    def pick_monitor(self):
        """The pointer is on the bar that was just clicked, so the monitor under
        it is the one to open on. Falling back to the primary needs a detour
        through hyprland: GDK only knows monitors by marketing name (the model),
        never by connector, but the layout coordinates do match."""
        display = self.get_display()
        monitors = [display.get_monitor(i) for i in range(display.get_n_monitors())]

        if self.cursor:
            for monitor in monitors:
                box = monitor.get_geometry()
                if (box.x <= self.cursor[0] < box.x + box.width and
                        box.y <= self.cursor[1] < box.y + box.height):
                    return monitor

        origin = output_origin(fallback_output())
        if origin:
            for monitor in monitors:
                box = monitor.get_geometry()
                if (box.x, box.y) == origin:
                    return monitor
        return display.get_primary_monitor() or (monitors[0] if monitors else None)

    def on_allocate(self, _widget, allocation):
        if allocation.width == self.placed_width:
            return                      # setting the margin re-allocates us
        self.placed_width = allocation.width
        GtkLayerShell.set_margin(self, GtkLayerShell.Edge.LEFT,
                                 self.left_margin(allocation.width))

    def left_margin(self, width):
        """Centred on the pill that opened the panel, clamped to the monitor.
        Wayland will not tell a client where the pointer is, so the position
        comes from the compositor by way of panel.py at the moment of the
        click, in desktop coordinates — hence the monitor offset."""
        geometry = self.monitor.get_geometry()
        rightmost = geometry.width - width - SCREEN_EDGE
        if not self.cursor:
            return max(SCREEN_EDGE, rightmost)
        wanted = (self.cursor[0] - geometry.x) - width // 2
        return max(SCREEN_EDGE, min(wanted, rightmost))

    def on_mapped(self, *_):
        if self.started:
            return False                # remapping, not the first time up
        self.started = True
        self.on_ready()
        return False


# The CPU, GPU and network cards are all at least this tall (the whole card,
# padding included), so moving between them does not make the card jump. It
# is the tallest natural height of the three (network, 411 px measured, with
# five one-line connection rows; CPU is 407), rounded up; the others stretch
# their graphs or tables to fill it.
CARD_HEIGHT = 412


def columns(card, spacing=0):
    """Split a card into two columns with a hairline between them, for the
    panels that pair graphs with a process list (CPU, GPU, network): graphs
    and readings on the left, the processes on the right. Returns the two
    vertical boxes to fill."""
    row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=spacing)
    left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
    right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
    sep = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
    sep.get_style_context().add_class("ctl-vsep")
    row.pack_start(left, False, False, 0)
    row.pack_start(sep, False, False, 0)
    row.pack_start(right, True, True, 0)
    card.pack_start(row, True, True, 0)       # fills a card given a fixed height
    return left, right


def run(panel_class):
    load_css()
    panel_class(cursor_from_argv())
    Gtk.main()
