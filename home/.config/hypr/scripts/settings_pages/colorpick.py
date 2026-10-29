"""Settings page: the colour picker's history (colorpick.sh, SUPER+P).

colorpick.sh keeps the colours it picked, newest first, no repeats, in a
plain text file -- ${XDG_DATA_HOME:-~/.local/share}/colorpick/history, one
"#rrggbb" a line (30 at most) -- which the launcher's "#" mode reads too.
This page shows them as swatches with their rgb() and hsl() forms; Copy runs
`colorpick.sh copy` (the clipboard, the toast, and back to the top of the
list), ✕ takes one colour out of the file, and Clear all (two clicks) is
`colorpick.sh clear`. Pick a colour starts the picker itself (hyprpicker;
the page says when it is not installed).
"""
from gi.repository import GLib, Gtk  # noqa: F401

from .common import *  # noqa: F401,F403  (the shared helpers and paths)

import colorsys  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import shutil  # noqa: E402

PAGE = {"id": "colorpick", "title": "Colour picker", "icon": "", "group": "Apps", "order": 31,
        "parent": "capture", "tab": "Colour picker",
        "keywords": ["colour picker", "color picker", "eyedropper", "hyprpicker", "hex", "rgb", "hsl",
                     "colour history", "color history", "swatch"]}

COLORPICK = os.path.join(HYPR, "colorpick.sh")
HISTORY = os.path.join(os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share"),
                       "colorpick", "history")      # = colorpick.sh HISTORY
HEX = re.compile(r"^#[0-9a-f]{6}$")


# -- pure helpers (tests/test_settings_desk.py) ----------------------------------------
def read_history(text):
    """The file's colours in order, lower case, valid ones only, no repeats."""
    out = []
    for line in (text or "").splitlines():
        c = line.strip().lower()
        if HEX.match(c) and c not in out:
            out.append(c)
    return out


def forms(hexcolour):
    """'#ff8000' -> 'rgb(255, 128, 0)  ·  hsl(30, 100%, 50%)' (colorpick.sh's
    describe(), the same rounding)."""
    r, g, b = (int(hexcolour[i:i + 2], 16) for i in (1, 3, 5))
    h, l, s = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
    return f"rgb({r}, {g}, {b})  ·  hsl({h * 360:.0f}, {s * 100:.0f}%, {l * 100:.0f}%)"


def without(colours, hexcolour):
    """The history text with one colour taken out (newest first kept)."""
    kept = [c for c in colours if c != hexcolour.lower()]
    return "".join(c + "\n" for c in kept)


def swatch_markup(hexcolour):
    """A block of the colour itself, as Pango markup (no CSS needed)."""
    return f"<span background='{hexcolour}' foreground='{hexcolour}'>████</span>"


class Page:
    def __init__(self):
        self.widget = page_box()
        w = self.widget
        w.pack_start(heading("COLOUR PICKER"), False, False, 0)
        self.picker_row, self.picker_sub = row("", "Pick a colour from the screen",
                                               "SUPER+P: the hex goes to the clipboard and into this list",
                                               link("Pick", lambda: spawn(COLORPICK)))
        w.pack_start(self.picker_row, False, False, 0)
        w.pack_start(sep(), False, False, 0)
        w.pack_start(heading("HISTORY"), False, False, 0)
        self.rows = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        w.pack_start(self.rows, False, False, 0)
        self.clear_link = link("Clear all", self.clear_all)
        w.pack_start(links_row(self.clear_link), False, False, 0)
        more = dp.label(f"The list is {HISTORY.replace(os.path.expanduser('~'), '~')}, newest first, 30 at "
                        "most; the launcher's \"#\" mode offers the same colours.", "ctl-sub")
        more.set_line_wrap(True)
        more.set_xalign(0)
        w.pack_start(details(more), False, False, 0)
        self.armed = False

    # -- actions ---------------------------------------------------------------------
    def copy(self, hexcolour):
        background(lambda: run(COLORPICK, "copy", hexcolour, timeout=10), lambda _o: self.refresh())

    def remove(self, hexcolour):
        try:
            with open(HISTORY) as handle:
                colours = read_history(handle.read())
            tmp = f"{HISTORY}.{os.getpid()}.tmp"
            with open(tmp, "w") as handle:
                handle.write(without(colours, hexcolour))
            os.replace(tmp, HISTORY)
        except OSError:
            pass
        self.refresh()

    def clear_all(self):
        if not self.armed:
            self.armed = True
            self.clear_link.set_label("Clear all? Click again")
            GLib.timeout_add_seconds(4, self.disarm)
            return
        self.disarm()
        background(lambda: run(COLORPICK, "clear", timeout=10), lambda _o: self.refresh())

    def disarm(self):
        self.armed = False
        self.clear_link.set_label("Clear all")
        return False

    # -- drawing ---------------------------------------------------------------------
    def refresh(self):
        def work():
            try:
                with open(HISTORY) as handle:
                    return read_history(handle.read())
            except OSError:
                return []
        background(work, self.draw)

    def draw(self, colours):
        if not shutil.which("hyprpicker"):
            self.picker_sub.set_text("hyprpicker is not installed: the picker needs it (the history "
                                     "below still works)")
        clear(self.rows)
        for c in colours:
            grid = Gtk.Grid()
            grid.get_style_context().add_class("ctl-row")
            grid.set_column_spacing(12)
            sw = Gtk.Label()
            sw.set_markup(swatch_markup(c))
            sw.set_valign(Gtk.Align.CENTER)
            grid.attach(sw, 0, 0, 1, 2)
            title = dp.label(c, "ctl-title")
            title.set_selectable(True)
            grid.attach(title, 1, 0, 1, 1)
            sub = dp.label(forms(c), "ctl-sub")
            sub.set_selectable(True)
            sub.set_hexpand(True)
            grid.attach(sub, 1, 1, 1, 1)
            buttons = links_row(link("Copy", lambda h=c: self.copy(h)), link("✕", lambda h=c: self.remove(h)))
            buttons.set_valign(Gtk.Align.CENTER)
            grid.attach(buttons, 2, 0, 1, 2)
            self.rows.pack_start(grid, False, False, 0)
        if not colours:
            self.rows.pack_start(dp.label("No colours picked yet.", "ctl-sub"), False, False, 0)
        self.clear_link.set_sensitive(bool(colours))
        self.widget.show_all()
