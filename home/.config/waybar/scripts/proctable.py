"""The process table the CPU, GPU and network panels share.

    name                 value  value   [End]

One row per app (each panel decides how processes are grouped into apps),
right-aligned value columns, and an End button that takes two clicks: the
first arms it (it turns red and says "Sure?") for ARM_SECONDS, the second
sends SIGTERM to every process of that app -- a polite quit that lets it
save, never SIGKILL. Apps that are the session itself (PROTECTED) get no
button at all: ending them takes the desktop down.

Not a panel on its own: imported by sensors_panel.py and network_panel.py.
"""

import os
import signal
import time

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk  # noqa: E402

import themecolors  # noqa: E402  (the "Sure?" colour; scripts/ is on sys.path via the panel)

ARM_SECONDS = 4
PROTECTED = {"Hyprland", "Xwayland", "waybar", "waybar-toolbox", "pipewire",
             "wireplumber", "pipewire-pulse", "systemd", "systemd-journald",
             "systemd-resolved", "NetworkManager", "dbus-broker", "hyprpaper", "mako",
             "hypridle", "hyprpolkitagent", "xdg-desktop-portal",
             "xdg-desktop-portal-hyprland", "gnome-keyring-daemon", "wayland-wm"}


def label(text, cls, xalign=0.0):
    widget = Gtk.Label(label=text)
    widget.get_style_context().add_class(cls)
    widget.set_xalign(xalign)
    return widget


class ProcTable:
    """rows: [{"name", "values": [str, ...], "pids": [int, ...]}]"""

    def __init__(self, headers, on_ended=None, killable=True):
        self.headers = headers          # value column titles, e.g. ["GPU", "VRAM"]
        self.on_ended = on_ended
        self.killable = killable
        self.armed = {}
        self.rows = []
        self.widget = Gtk.Grid(column_spacing=12, row_spacing=2)

    def set(self, rows):
        self.rows = rows
        self.draw()

    def draw(self):
        for child in self.widget.get_children():
            self.widget.remove(child)
        now = time.monotonic()
        self.armed = {k: t for k, t in self.armed.items() if now - t < ARM_SECONDS}
        if not self.rows:
            self.widget.attach(label("nothing right now", "ctl-sub"), 0, 0, 2, 1)
            self.widget.show_all()
            return
        for col, head in enumerate(self.headers, start=1):
            self.widget.attach(label(head, "sn-label", 1.0), col, 0, 1, 1)
        for r, row in enumerate(self.rows, start=1):
            name = label(row["name"], "sn-value")
            name.set_hexpand(True)
            name.set_ellipsize(3)               # Pango.EllipsizeMode.END
            # A minimum too: an ellipsizing label in a grid asks for no width
            # at all, and in a narrow column every name became "...".
            name.set_width_chars(16)
            name.set_max_width_chars(26)
            self.widget.attach(name, 0, r, 1, 1)
            for col, value in enumerate(row["values"], start=1):
                self.widget.attach(label(value, "sn-label", 1.0), col, r, 1, 1)
            if not self.killable or row["name"] in PROTECTED or not row.get("pids"):
                continue
            if any(row["name"].startswith(p) for p in ("wayland-wm",)):
                continue
            armed = row["name"] in self.armed
            button = Gtk.Button(label="End")
            button.get_style_context().add_class("dev-pick")
            if armed:
                button.get_style_context().add_class("active")
                button.get_child().set_markup(f"<span foreground='{themecolors.hex('danger', '#ff2a6d')}'>Sure?</span>")
            button.connect("clicked", lambda _b, rw=row: self.end(rw))
            self.widget.attach(button, len(self.headers) + 1, r, 1, 1)
        self.widget.show_all()

    def end(self, row):
        name = row["name"]
        if name not in self.armed:
            self.armed = {name: time.monotonic()}
            self.draw()
            GLib.timeout_add(ARM_SECONDS * 1000, lambda: (self.draw(), False)[1])
            return
        self.armed = {}
        for pid in row["pids"]:
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass
        if self.on_ended:
            GLib.timeout_add(800, lambda: (self.on_ended(), False)[1])
