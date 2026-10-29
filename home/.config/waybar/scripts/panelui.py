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
from gi.repository import Gdk, GLib, GObject, Gtk, GtkLayerShell  # noqa: E402

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


WHEEL_TAKERS = (Gtk.ComboBox, Gtk.Scale, Gtk.SpinButton)


def wheel_to_page(widget, event):
    """The mouse wheel over a drop-down, slider or number box inside a page
    that scrolls: scroll the page, not the control. GTK would otherwise
    change its value -- and every control here applies at once, so turning
    the wheel down a page picked another resolution. In a panel that does not
    scroll (the audio panel's volume), the wheel still moves the control."""
    page = widget.get_ancestor(Gtk.ScrolledWindow)
    if page is None:
        return False
    if event.direction == Gdk.ScrollDirection.SMOOTH:
        dy = event.delta_y
    else:
        dy = {Gdk.ScrollDirection.UP: -1, Gdk.ScrollDirection.DOWN: 1}.get(event.direction, 0)
    adj = page.get_vadjustment()
    step = adj.get_page_size() ** (2 / 3)        # GTK's own wheel step
    adj.set_value(max(adj.get_lower(), min(adj.get_upper() - adj.get_page_size(),
                                           adj.get_value() + dy * step)))
    return True


def _guard_one(widget):
    if not getattr(widget, "_wheel_guarded", False):
        widget._wheel_guarded = True
        widget.connect("scroll-event", wheel_to_page)


def guard_wheel(_widget=None):
    """wheel_to_page for every such control this program ever shows: hooked
    on their "map", so the rows a page rebuilds later are covered too. Once
    per program; the argument is only for callers that pass their window."""
    global _WHEEL_HOOKED
    if _WHEEL_HOOKED:
        return
    _WHEEL_HOOKED = True
    for kind in WHEEL_TAKERS:
        GObject.add_emission_hook(kind, "map", lambda w, *_: (_guard_one(w), True)[1])


_WHEEL_HOOKED = False


# -- small shared widgets ---------------------------------------------------
def label(text, cls=None, xalign=0.0):
    """A Gtk.Label with one style class and its x alignment: the line every
    panel used to write out (or keep a local copy of) for each caption."""
    widget = Gtk.Label(label=text)
    if cls:
        widget.get_style_context().add_class(cls)
    widget.set_xalign(xalign)
    return widget


ARM_SECONDS = 3
SURE = "Sure?"


class Arming:
    """The two-click rule, without GTK: press(now) says "armed" for the first
    press and "fire" for a second one within ARM_SECONDS of it; a press after
    that arms again. armed(now) says whether it is still waiting. Pure, so
    the tests can drive it with their own clock.

    by_key: the press came from the keyboard (Enter / Space). A key that
    armed it and is still held down repeats by itself (after the repeat
    delay, as little as 100 ms), and that repeat must not count as the
    second press -- so until release() says the key came up, a keyboard
    press only answers "held"."""

    def __init__(self, seconds=ARM_SECONDS):
        self.seconds = seconds
        self.since = None
        self.held = False

    def armed(self, now):
        return self.since is not None and now - self.since < self.seconds

    def press(self, now, by_key=False):
        if self.armed(now):
            if by_key and self.held:
                return "held"
            self.since, self.held = None, False
            return "fire"
        self.since, self.held = now, by_key
        return "armed"

    def release(self):
        """The key that armed it came up: the next press is a real one."""
        self.held = False

    def disarm(self):
        self.since, self.held = None, False


class Armed(Gtk.Button):
    """A button for something that cannot be undone (cancel every print job,
    forget a device, reboot): the first click arms it -- it says "Sure?" and
    takes the .armed class -- and only a second click within ARM_SECONDS
    runs on_fire(). Left alone it goes back to its caption by itself. The
    same rule as the power and process cards, in one place for the rest."""

    def __init__(self, caption, on_fire, cls="ctl-link", sure=SURE, seconds=ARM_SECONDS):
        super().__init__(label=caption)
        self.caption, self.sure, self.on_fire = caption, sure, on_fire
        self.arming = Arming(seconds)
        self._timer = 0
        if cls:
            self.get_style_context().add_class(cls)
        self.connect("clicked", self._on_clicked)
        self.connect("destroy", lambda *_: self._stop_timer())

    def _stop_timer(self):
        if self._timer:
            GLib.source_remove(self._timer)
            self._timer = 0

    def _on_clicked(self, _button):
        now = GLib.get_monotonic_time() / 1e6
        event = Gtk.get_current_event()
        by_key = event is not None and event.type == Gdk.EventType.KEY_PRESS
        outcome = self.arming.press(now, by_key)
        if outcome == "held":           # Enter held down: its repeat, not a second press
            return
        self._stop_timer()
        if outcome == "fire":
            self._show(False)
            self.on_fire()
            return
        self._show(True)
        self._timer = GLib.timeout_add(int(self.arming.seconds * 1000), self._expire)
        if by_key:
            self._watch_release()

    def _watch_release(self):
        """Armed from the keyboard: hear the key come up. On the window, not
        the button -- a release is delivered wherever the focus is by then."""
        top = self.get_toplevel()
        if not isinstance(top, Gtk.Window):
            self.arming.release()
            return
        handler = []

        def released(*_args):
            self.arming.release()
            top.disconnect(handler[0])
            return False
        handler.append(top.connect("key-release-event", released))

    def _expire(self):
        self._timer = 0
        self.arming.disarm()
        self._show(False)
        return False

    def disarm(self):
        self._stop_timer()
        self.arming.disarm()
        self._show(False)

    def _show(self, armed):
        self.set_label(self.sure if armed else self.caption)
        (self.get_style_context().add_class if armed
         else self.get_style_context().remove_class)("armed")


# -- the keyboard -----------------------------------------------------------
# Widgets a key press can act on, in the order a panel is read: the first of
# them gets the focus when the card opens, Tab / Up / Down walk them, Enter
# or Space presses the focused one (GTK's own activate). Labels, graphs and
# boxes are skipped.
ACTIONABLE = (Gtk.Button, Gtk.Switch, Gtk.Entry, Gtk.Scale, Gtk.ComboBox)
# Widgets that use Up / Down themselves (a slider steps, a list moves its
# row, a text box moves its caret): the arrows stay theirs there.
ARROW_TAKERS = (Gtk.Scale, Gtk.SpinButton, Gtk.ComboBox, Gtk.TextView,
                Gtk.TreeView, Gtk.ListBox, Gtk.FlowBox, Gtk.Entry)
# Text fields a panel may have focused on purpose (a search box): opening
# the card leaves the focus there rather than moving it to a button.
TEXT_INPUTS = (Gtk.Entry, Gtk.TextView)


def first_match(root, children, wanted):
    """The first node, depth first in reading order, for which wanted(node)
    is true, or None. children(node) lists a node's children ([] for a
    leaf). Pure: the panel hands in GTK's tree, the tests a dict."""
    stack = [root]
    while stack:
        node = stack.pop()
        if wanted(node):
            return node
        stack.extend(reversed(children(node) or []))
    return None


def arrow_move(keyname, focus_takes_arrows):
    """What an arrow key does in a panel: "next" or "prev" through the
    actionable widgets for Down / Up (the same walk as Tab and Shift+Tab --
    a card is a column, so up and down is the natural way through it), or
    None to leave the key alone: any other key, and Up / Down while the
    focused widget uses them itself. Left / Right stay GTK's (directional
    focus, or the slider's own step)."""
    if focus_takes_arrows:
        return None
    return {"Down": "next", "KP_Down": "next", "Up": "prev", "KP_Up": "prev"}.get(keyname)


def gtk_children(widget):
    """A widget's children for first_match: the visible ones of a container
    (forall, so a button's own label counts as inside it), else none."""
    if not isinstance(widget, Gtk.Container):
        return []
    found = []
    widget.forall(found.append)
    return [w for w in found if w.get_visible() and w.get_child_visible()]


def actionable(widget):
    """Can a key press act on this widget right now?"""
    return (isinstance(widget, ACTIONABLE) and widget.get_visible()
            and widget.is_sensitive() and widget.get_can_focus()
            and widget.get_mapped())


def _keyboard_one(widget):
    """Every button reachable by the keyboard. Several panels switch focus
    off on their tiles and chips so a CLICK would not leave a focus ring on
    them; focus-on-click off keeps that, and Tab still reaches them."""
    if getattr(widget, "_kb_ready", False):
        return
    widget._kb_ready = True
    if not widget.get_can_focus():
        widget.set_can_focus(True)
        widget.set_focus_on_click(False)


def keyboard_reach():
    """_keyboard_one for every button this program ever maps (rows rebuilt
    later included), hooked once like guard_wheel."""
    global _KB_HOOKED
    if _KB_HOOKED:
        return
    _KB_HOOKED = True
    GObject.add_emission_hook(Gtk.Button, "map", lambda w, *_: (_keyboard_one(w), True)[1])


_KB_HOOKED = False


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
        keyboard_reach()
        self.build()
        guard_wheel(self.card)
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

    def step_aside(self):
        """Before something that asks for a password (pkexec): the prompt is an
        ordinary window, so it opens beneath this layer -- the keyboard stays
        the card's and a click on the prompt lands on a click catcher. Give
        both up until step_back()."""
        for catcher in self.catchers:
            catcher.hide()
        GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.NONE)

    def step_back(self):
        """After the prompt: the catchers again, then the card mapped once more
        so it stacks above them (the last mapped is on top of a layer)."""
        for catcher in self.catchers:
            catcher.show_all()
        GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.ON_DEMAND)
        self.hide()
        self.show()

    # None: focus the first actionable widget when the card opens, unless
    # the subclass has a keyboard model of its own (it overrides on_key, as
    # the git card's row keys do) -- then it decides. True / False force it.
    focus_first = None

    def on_key(self, _widget, event):
        if event.keyval == Gdk.KEY_Escape:
            self.quit()
            return True
        if event.state & (Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.MOD1_MASK):
            return False
        move = arrow_move(Gdk.keyval_name(event.keyval) or "",
                          isinstance(self.get_focus(), ARROW_TAKERS))
        if move:
            self.set_focus_visible(True)
            self.child_focus(Gtk.DirectionType.TAB_FORWARD if move == "next"
                             else Gtk.DirectionType.TAB_BACKWARD)
            return True
        return False

    def wants_focus_first(self):
        if self.focus_first is not None:
            return self.focus_first
        return type(self).on_key is Panel.on_key

    def focus_first_actionable(self):
        """On open: the focus on the first thing a key can act on, shown with
        its ring, so Enter does what the eye lands on. A text box the panel
        focused itself keeps it."""
        if not self.wants_focus_first():
            return False
        if isinstance(self.get_focus(), TEXT_INPUTS):
            return False
        target = first_match(self.card, gtk_children, actionable)
        if target is not None:
            target.grab_focus()
            self.set_focus_visible(True)
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
        # Idle: after on_ready's first fill, so rows it adds count too.
        GLib.idle_add(self.focus_first_actionable)
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
