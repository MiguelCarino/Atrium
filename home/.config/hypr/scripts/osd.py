#!/usr/bin/env python3
"""On-screen indicator: a small pill with an icon, a bar and the percent,
bottom-centre on the focused screen, for a second after volume, microphone
or brightness changes.

    osd.py daemon                         the resident window (osd.service)
    osd.py show volume|mic|brightness [value] [screen] [--on <screen>]
                                          show it; without a value the daemon
                                          reads the real one (wpctl /
                                          screen-color's settings); --on puts
                                          it on that screen instead of the
                                          focused one
    osd.py vol up|down|mute               change the volume, then show it
    osd.py mic mute                       mute / unmute the microphone, then show it
    osd.py bright up|down [screen]        software brightness (screen-color.py)
                                          of one screen or all, then show it

The key binds call the change commands, so one press is one process: the
client half is stdlib only (no GTK) and hands the daemon one datagram on
$XDG_RUNTIME_DIR/osd.sock. With the daemon down it still changes the value,
it just shows nothing.

The pill is the popup panels' card (panel.css through panelui, so it is in
the theme), on a layer surface called waybar-osd -- lua/rules.lua's
waybar-glass rule frosts it like the panels. One window, reused: repeated
presses move the bar and push the hide back; it moves to whichever screen
has the focus at the press. Clicks go through it.
"""
import json
import os
import socket
import subprocess
import sys

RUNTIME = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
SOCK = os.path.join(RUNTIME, "osd.sock")
HERE = os.path.dirname(os.path.abspath(__file__))
SCREEN_COLOR = os.path.join(HERE, "screen-color.py")
SCREEN_STATE = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"),
                            "hypr", "screen-color.json")
VOL_STEP, BRIGHT_STEP = 5, 5
HIDE_MS = 1200
MARGIN_BOTTOM = 140
ICONS = {"volume": "", "volume-muted": "", "mic": "", "mic-muted": "",
         "brightness": ""}


# -- client (stdlib only) -----------------------------------------------------------
def send(msg):
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as s:
            s.sendto(json.dumps(msg).encode(), SOCK)
    except OSError:
        pass                    # daemon down: the change still happened


def vol_limit():
    """How far the volume keys may go: wpctl's -l, 1.0 (100 %), or 1.5 with
    over-amplification on in Settings > Sound (sound-settings.py boost, which
    keeps it in $XDG_STATE_HOME/hypr/sound.json). Read here rather than by
    running sound-settings.py, so a key press stays one small process."""
    try:
        with open(os.path.join(os.path.dirname(SCREEN_STATE), "sound.json")) as handle:
            return "1.5" if json.load(handle).get("boost") else "1.0"
    except (OSError, ValueError, AttributeError):
        return "1.0"


def quiet(*argv):
    subprocess.run(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def client(args):
    cmd = args[0]
    if cmd == "show" and len(args) >= 2:
        msg = {"kind": args[1]}
        rest = args[2:]
        if "--on" in rest:
            i = rest.index("--on")
            msg["on"] = rest[i + 1] if i + 1 < len(rest) else None
            del rest[i:i + 2]
        if rest and rest[0].lstrip("-").isdigit():
            msg["value"] = int(rest.pop(0))
        if rest:
            msg["screen"] = rest[0]
        send(msg)
    elif cmd == "vol" and len(args) == 2 and args[1] in ("up", "down", "mute"):
        sink = "@DEFAULT_AUDIO_SINK@"
        if args[1] == "up":
            quiet("wpctl", "set-mute", sink, "0")
            quiet("wpctl", "set-volume", "-l", vol_limit(), sink, f"{VOL_STEP}%+")
        elif args[1] == "down":
            quiet("wpctl", "set-volume", "-l", vol_limit(), sink, f"{VOL_STEP}%-")
        else:
            quiet("wpctl", "set-mute", sink, "toggle")
        send({"kind": "volume"})
    elif cmd == "mic" and args[1:] == ["mute"]:
        quiet("wpctl", "set-mute", "@DEFAULT_AUDIO_SOURCE@", "toggle")
        send({"kind": "mic"})
    elif cmd == "bright" and len(args) in (2, 3) and args[1] in ("up", "down"):
        screen = args[2] if len(args) == 3 else "all"
        step = f"+{BRIGHT_STEP}" if args[1] == "up" else f"-{BRIGHT_STEP}"
        quiet(sys.executable, SCREEN_COLOR, "set", screen, "brightness", step)
        send({"kind": "brightness", **({} if screen == "all" else {"screen": screen})})
    else:
        sys.exit(__doc__)


# -- daemon --------------------------------------------------------------------------
def read_volume(target):
    """(percent, muted) or (None, False)."""
    import re
    try:
        out = subprocess.run(["wpctl", "get-volume", target], capture_output=True, text=True, timeout=2).stdout
    except (OSError, subprocess.SubprocessError):
        return None, False
    m = re.search(r"Volume: ([\d.]+)( \[MUTED\])?", out)
    return (round(float(m[1]) * 100), bool(m[2])) if m else (None, False)


def read_brightness(screen):
    """screen-color.py's brightness for one screen (or "all"), from its file
    -- the same merge as its settings_for(), without starting python again."""
    try:
        with open(SCREEN_STATE) as handle:
            screens = json.load(handle).get("screens", {})
    except (OSError, ValueError):
        screens = {}
    value = 100
    for key in ("*", screen):
        if key and "brightness" in screens.get(key, {}):
            value = screens[key]["brightness"]
    return value


def screen_origin(name=None):
    """Where the pill goes: screen `name`, else the focused one."""
    try:
        out = subprocess.run(["hyprctl", "monitors", "-j"], capture_output=True, text=True, timeout=2).stdout
        mons = json.loads(out)
        for m in mons:
            if (m["name"] == name) if name else m.get("focused"):
                return m["x"], m["y"]
        for m in mons:
            if m.get("focused"):
                return m["x"], m["y"]
    except (OSError, subprocess.SubprocessError, ValueError):
        pass
    return None


def daemon():
    import gi
    gi.require_version("Gtk", "3.0")
    gi.require_version("Gdk", "3.0")
    gi.require_version("GtkLayerShell", "0.1")
    from gi.repository import Gdk, GLib, Gtk, GtkLayerShell
    import cairo
    sys.path.insert(0, os.path.expanduser("~/.config/waybar/scripts"))
    import panelui

    css_files = [panelui.CSS_FILE] + [os.path.expanduser(f"~/.config/waybar/generated/{f}")
                                      for f in ("theme-panel.css", "accent.css")]

    def css_stamp():
        return tuple(os.path.getmtime(f) if os.path.exists(f) else 0 for f in css_files)

    class Osd(Gtk.Window):
        def __init__(self):
            super().__init__()
            self.set_name("panel-window")
            self.set_app_paintable(True)
            visual = self.get_screen().get_rgba_visual()
            if visual:
                self.set_visual(visual)
            GtkLayerShell.init_for_window(self)
            GtkLayerShell.set_namespace(self, "waybar-osd")
            GtkLayerShell.set_layer(self, GtkLayerShell.Layer.OVERLAY)
            GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.BOTTOM, True)
            GtkLayerShell.set_margin(self, GtkLayerShell.Edge.BOTTOM, MARGIN_BOTTOM)
            GtkLayerShell.set_exclusive_zone(self, -1)
            GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.NONE)
            card = Gtk.Grid()
            card.set_name("panel")
            card.set_column_spacing(12)
            self.add(card)
            self.icon = Gtk.Label()
            self.icon.get_style_context().add_class("ctl-icon")
            self.icon.set_valign(Gtk.Align.CENTER)
            card.attach(self.icon, 0, 0, 1, 2)
            self.title = Gtk.Label(xalign=0)
            self.title.get_style_context().add_class("ctl-title")
            card.attach(self.title, 1, 0, 1, 1)
            self.scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
            self.scale.get_style_context().add_class("ctl-slider")
            self.scale.set_draw_value(False)
            self.scale.set_can_focus(False)
            self.scale.set_size_request(220, -1)
            card.attach(self.scale, 1, 1, 1, 1)
            self.value = Gtk.Label(xalign=1)
            self.value.get_style_context().add_class("ctl-value")
            self.value.set_width_chars(6)
            card.attach(self.value, 2, 1, 1, 1)
            # Clicks go through to whatever is underneath.
            self.connect("realize", lambda w: w.input_shape_combine_region(cairo.Region()))
            card.show_all()
            self.hide_id = None
            self.origin = None
            self.stamp = css_stamp()

        def present_on(self, msg):
            kind = msg.get("kind")
            screen = msg.get("screen")
            muted = False
            if kind in ("volume", "mic"):
                value, muted = read_volume("@DEFAULT_AUDIO_SINK@" if kind == "volume" else "@DEFAULT_AUDIO_SOURCE@")
                value = msg.get("value", value)
                if value is None:
                    return
                title = "Volume" if kind == "volume" else "Microphone"
                icon = ICONS[f"{kind}-muted" if muted else kind]
            elif kind == "brightness":
                value = msg.get("value", read_brightness(screen))
                title = f"{screen} brightness" if screen else "Brightness"
                icon = ICONS["brightness"]
            else:
                return
            if css_stamp() != self.stamp:      # the theme changed since the last press
                self.stamp = css_stamp()
                panelui.load_css()
            self.icon.set_text(icon)
            self.title.set_text(title + ("  (muted)" if muted else ""))
            self.scale.set_value(max(0, min(100, value)))
            self.scale.set_sensitive(not muted)
            self.value.set_text("muted" if muted else f"{value}%")
            # One screen's brightness shows on that screen; the rest on the
            # focused one ("on" picks one by hand).
            origin = screen_origin(msg.get("on") or (screen if kind == "brightness" else None))
            if origin != self.origin:
                # A layer surface changes screen only while unmapped.
                display = Gdk.Display.get_default()
                for i in range(display.get_n_monitors()):
                    mon = display.get_monitor(i)
                    geo = mon.get_geometry()
                    if (geo.x, geo.y) == origin:
                        self.hide()
                        GtkLayerShell.set_monitor(self, mon)
                        self.origin = origin
                        break
            self.show()
            if self.hide_id:
                GLib.source_remove(self.hide_id)
            self.hide_id = GLib.timeout_add(HIDE_MS, self.done)

        def done(self):
            self.hide_id = None
            self.hide()
            return False

    panelui.load_css()
    osd = Osd()
    try:
        os.unlink(SOCK)
    except OSError:
        pass
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    sock.bind(SOCK)

    def on_msg(_fd, _cond):
        data = sock.recv(4096)
        latest = data
        try:                        # a fast spin: only the newest matters
            while True:
                latest = sock.recv(4096, socket.MSG_DONTWAIT)
        except BlockingIOError:
            pass
        try:
            osd.present_on(json.loads(latest))
        except (ValueError, AttributeError):
            pass
        return True

    GLib.io_add_watch(sock.fileno(), GLib.IO_IN, on_msg)
    Gtk.main()


if __name__ == "__main__":
    args = sys.argv[1:]
    if args == ["daemon"]:
        daemon()
    elif args:
        client(args)
    else:
        sys.exit(__doc__)
