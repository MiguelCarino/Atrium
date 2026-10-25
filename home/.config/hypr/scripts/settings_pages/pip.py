"""Settings page: the live picture-in-picture mirror (pip.py).

pip.py's settings (pip.conf) through `pip.py get --json` / `set KEY VALUE`,
and buttons that start a mirror the same way the keys do. The opacity is
applied by lua/pip.lua's rules, which `pip.py set opacity` re-evaluates;
everything else takes effect at the next mirror. The width and corner also
place mpv's own picture-in-picture button (mpv-pip.py moves the real player
window there), so the mirror and the parked player land in the same spot.
The page keeps nothing.
"""
import os

from gi.repository import GLib, Gtk  # noqa: F401

from .common import *  # noqa: F401,F403  (the shared helpers and paths)

PAGE = {"id": "pip", "title": "Picture-in-picture", "icon": "", "group": "Look", "order": 55, "parent": "windows", "tab": "Picture-in-picture",
        "keywords": ["pip", "mirror", "always on top", "floating video", "overlay", "opacity", "transparency",
                     "click through", "region", "watch a window", "imagen en imagen"]}

PIP = os.path.join(HYPR, "pip.py")
# Font Awesome 6 Solid, as escapes (see audio_panel.py on why).
ICON_WINDOW, ICON_HAND = "", ""
IDLE = "SUPER+CTRL+P: focused window  ·  SUPER+ALT+P: a region"
CORNERS = [("bottom-right", "Bottom right"), ("bottom-left", "Bottom left"),
           ("top-right", "Top right"), ("top-left", "Top left")]


class Page:
    def __init__(self):
        self.widget = page_box()
        w = self.widget
        self.updating = False
        w.pack_start(heading("MIRROR"), False, False, 0)
        grid, self.status = row(ICON_WINDOW, "Live copy of a window or region", IDLE)
        w.pack_start(grid, False, False, 0)
        w.pack_start(links_row(link("Mirror a window", lambda: self.start("window", "--pick")),
                               link("Mirror a region", lambda: self.start("region")),
                               link("Close", lambda: self.start("close"))), False, False, 0)
        w.pack_start(sep(), False, False, 0)
        w.pack_start(heading("LOOK"), False, False, 0)
        self.width = Slider("width", "Size", 240, 1600, 20, " px", self.set)
        w.pack_start(self.width.widget, False, False, 0)
        self.opacity = Slider("opacity", "Opacity", 30, 100, 5, " %", self.set)
        w.pack_start(self.opacity.widget, False, False, 0)
        w.pack_start(dp.label("Corner", "ctl-sub"), False, False, 0)
        self.corner = Chips(lambda key: self.set("corner", key))
        w.pack_start(self.corner.widget, False, False, 0)
        self.passthrough = Gtk.Switch()
        self.passthrough.connect("state-set", lambda _s, state: self.switch(state))
        grid, _ = row(ICON_HAND, "Clicks go through it",
                      "Watch-only: fixed in its corner, on every workspace", self.passthrough)
        w.pack_start(grid, False, False, 0)
        w.pack_start(sep(), False, False, 0)
        w.pack_start(heading("SMOOTHNESS"), False, False, 0)
        self.fps = Slider("fps", "Region frame rate", 5, 60, 5, " fps", self.set)
        w.pack_start(self.fps.widget, False, False, 0)
        self.window_fps = Slider("window_fps", "Window frame rate (higher costs CPU)", 2, 30, 1, " fps", self.set)
        w.pack_start(self.window_fps.widget, False, False, 0)
        note = dp.label("A window on another workspace can be mirrored too, but many apps stop drawing while "
                        "hidden, so its copy may stand still until it is shown. Region frames are recorded "
                        "on the graphics card; window frames are full copies of the window. Size and Corner "
                        "also set where mpv's picture-in-picture button parks the player itself.", "ctl-sub")
        note.set_line_wrap(True)
        note.set_xalign(0)
        w.pack_start(details(note), False, False, 0)

    def refresh(self):
        background(lambda: (run_json(PIP, "get", "--json") or {}, run_json(PIP, "status", "--json")), self.show)

    def show(self, data):
        values, live = data
        if not values:
            return
        self.updating = True
        self.width.show(int(values["width"]))
        self.opacity.show(int(values["opacity"]))
        self.fps.show(int(values["fps"]))
        self.window_fps.show(int(values["window_fps"]))
        self.corner.set(CORNERS, values["corner"])
        self.passthrough.set_state(values["passthrough"] == "on")
        self.status.set_text(f"Mirroring the {live['mode']}: {live['title'][:50]}" if live else IDLE)
        self.widget.show_all()
        self.updating = False

    def set(self, key, value):
        if not self.updating:
            background(lambda: run(PIP, "set", key, str(value)), lambda _r: self.refresh())

    def switch(self, state):
        self.set("passthrough", "on" if state else "off")
        return False

    def start(self, *args):
        spawn(PIP, *args)
        GLib.timeout_add(1500, lambda: (self.refresh(), False)[1])
