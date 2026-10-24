#!/usr/bin/env python3
"""Clipboard history for SUPER+V, laid out like the app launcher: the newest
entry (or the best match for what is typed) as a big hero card, the rest in
history order below it: text as one-line rows, images as thumbnail tiles.

    clipboard.py         open it, or close it if it is already open

Keys: type to filter (text entries by content, images by "png", "jpeg", size),
arrows to move (up/down to the row or tile above or below), Enter copies the highlighted entry back onto the clipboard,
Delete removes it from the history, Esc closes. A click copies; a click off the
card closes.

History is cliphist's (fed by the cliphist@text / cliphist@image watchers, see
lua/autostart.lua). Only the newest MAX_ITEMS matches are shown; image
thumbnails are decoded in the background, a few at a time, and cached for the
life of the window.

Looks: launcher.css next to this file (the clip-* classes); window plumbing
is shared with launcher.py.
"""

import os
import re
import signal
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
gi.require_version("GtkLayerShell", "0.1")
from gi.repository import Gdk, GdkPixbuf, GLib, Gtk, GtkLayerShell, Pango  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import launcher  # noqa: E402  (shared: CSS, monitor pick, single instance)

PID_FILE = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "clipboard-picker.pid")
COLUMNS = 4
MAX_ITEMS = 120
HERO_TEXT_CHARS = 600
TILE_THUMB = (200, 84)
HERO_THUMB = (700, 220)
BINARY = re.compile(r"^\[\[ binary data (.+?) (\w+) (\d+)x(\d+) \]\]$")


class Item:
    def __init__(self, line):
        self.line = line                        # what cliphist decode wants back
        self.id, _, self.preview = line.partition("\t")
        match = BINARY.match(self.preview)
        self.image = bool(match)
        if match:
            size, fmt, w, h = match.groups()
            self.caption = f"{fmt.upper()}  {w}×{h}  ·  {size}"
            self.search = f"{fmt} image {w}x{h}".lower()
        else:
            self.caption = ""
            self.search = self.preview.lower()

    def decode(self):
        try:
            return subprocess.run(["cliphist", "decode"], input=self.line.encode(),
                                  capture_output=True, timeout=3).stdout
        except (subprocess.SubprocessError, OSError):
            return b""


def history():
    try:
        out = subprocess.run(["cliphist", "list"], capture_output=True,
                             timeout=3).stdout.decode(errors="replace")
    except (subprocess.SubprocessError, OSError):
        return []
    return [Item(line) for line in out.splitlines() if "\t" in line]


def flat(text, limit):
    """One paragraph of readable text: whitespace runs collapsed, clipped."""
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit] + ("…" if len(text) > limit else "")


def thumbnail(data, box):
    loader = GdkPixbuf.PixbufLoader()

    def fit(_loader, width, height):
        scale = min(box[0] / width, box[1] / height, 1.0)
        loader.set_size(max(1, int(width * scale)), max(1, int(height * scale)))

    loader.connect("size-prepared", fit)
    try:
        loader.write(data)
        loader.close()
        return loader.get_pixbuf()
    except GLib.Error:
        return None


class Clipboard(Gtk.Window):
    def __init__(self):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.items = history()
        self.results = []
        self.selected = 0
        self.done = False
        self.thumbs = {}                        # (id, box) -> pixbuf | None
        self.pool = ThreadPoolExecutor(max_workers=4)

        self.set_name("launcher-window")
        self.set_app_paintable(True)
        visual = self.get_screen().get_rgba_visual()
        if visual:
            self.set_visual(visual)
        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_namespace(self, "launcher")
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.OVERLAY)
        GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.EXCLUSIVE)
        monitor = launcher.focused_monitor(self.get_display())
        if monitor:
            GtkLayerShell.set_monitor(self, monitor)

        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        card.set_name("card")
        self.add(card)

        self.entry = Gtk.Entry()
        self.entry.set_name("search")
        self.entry.set_placeholder_text("search clipboard")
        self.entry.set_icon_from_icon_name(Gtk.EntryIconPosition.PRIMARY,
                                           "edit-paste-symbolic")
        self.entry.connect("changed", lambda _e: self.refresh())
        self.entry.connect("activate", lambda _e: self.copy(self.selected))
        card.pack_start(self.entry, False, False, 0)

        # Hero: newest / best match, big.
        self.hero = launcher.styled(Gtk.EventBox(), "hero", "clip-hero")
        self.hero.set_name("hero")
        self.hero.connect("button-release-event", lambda *_: self.copy(0))
        row = Gtk.Box(spacing=22)
        row.set_margin_top(16)
        row.set_margin_bottom(16)
        row.set_margin_start(24)
        row.set_margin_end(22)
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.hero_image = Gtk.Image()
        self.hero_image.set_halign(Gtk.Align.START)
        self.hero_image.set_no_show_all(True)
        self.hero_text = launcher.styled(Gtk.Label(xalign=0, yalign=0), "clip-hero-text")
        self.hero_text.set_line_wrap(True)
        self.hero_text.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
        self.hero_text.set_lines(5)
        self.hero_text.set_ellipsize(Pango.EllipsizeMode.END)
        self.hero_text.set_max_width_chars(70)
        self.hero_text.set_no_show_all(True)
        self.hero_caption = launcher.styled(Gtk.Label(xalign=0), "hero-sub")
        body.pack_start(self.hero_image, False, False, 0)
        body.pack_start(self.hero_text, False, False, 0)
        body.pack_start(self.hero_caption, False, False, 0)
        row.pack_start(body, True, True, 0)
        hint = launcher.styled(Gtk.Label(label="ENTER copy  ·  DEL forget"), "hero-hint")
        hint.set_valign(Gtk.Align.START)
        row.pack_end(hint, False, False, 0)
        self.hero.add(row)
        card.pack_start(self.hero, False, False, 0)

        self.empty = launcher.styled(Gtk.Label(label="nothing in the clipboard history"), "empty")
        self.empty.set_no_show_all(True)
        card.pack_start(self.empty, False, False, 0)

        # Text rows and runs of image tiles, stacked in history order.
        self.list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.list.set_name("tiles")
        self.list.set_valign(Gtk.Align.START)
        self.scroll = Gtk.ScrolledWindow()
        self.scroll.set_name("tiles-scroll")
        self.scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.scroll.set_can_focus(False)
        self.scroll.add(self.list)
        card.pack_start(self.scroll, True, True, 0)

        self.connect("key-press-event", self.on_key)
        self.connect("destroy", Gtk.main_quit)
        self.refresh()
        self.show_all()
        self.entry.grab_focus()

        try:
            import panelui
            display = self.get_display()
            self.catchers = [panelui.ClickCatcher(display.get_monitor(i), self.close)
                             for i in range(display.get_n_monitors())]
        except Exception as exc:
            print(f"clipboard: no click-outside: {exc}", file=sys.stderr)
            self.catchers = []

    # -- thumbnails (decoded off the GTK thread) -----------------------------
    def want_thumb(self, item, box, image):
        key = (item.id, box)
        if key in self.thumbs:
            if self.thumbs[key]:
                image.set_from_pixbuf(self.thumbs[key])
            return
        image.set_from_icon_name("image-x-generic-symbolic", Gtk.IconSize.DIALOG)

        def work():
            pixbuf = thumbnail(item.decode(), box)
            GLib.idle_add(self.got_thumb, key, pixbuf, image)

        self.pool.submit(work)

    def got_thumb(self, key, pixbuf, image):
        self.thumbs[key] = pixbuf
        if pixbuf and image.get_parent() is not None:   # the tile may be gone
            image.set_from_pixbuf(pixbuf)
        return False

    # -- results ---------------------------------------------------------------
    def refresh(self):
        query = self.entry.get_text().strip().lower()
        matches = [i for i in self.items if query in i.search] if query else self.items
        self.results = matches[:MAX_ITEMS]
        self.selected = 0
        has = bool(self.results)
        self.hero.set_visible(has)
        self.empty.set_visible(not has)
        if has:
            self.show_hero(self.results[0])
        for child in self.list.get_children():
            child.destroy()
        self.tiles, grid = [], None
        for n, item in enumerate(self.results[1:], 1):
            if not item.image:
                grid = None
                self.tiles.append(self.make_row(item, n))
                continue
            if grid is None:                    # a run of images: one grid
                grid = self.make_grid()
            self.tiles.append(self.make_tile(item, n, grid))
        self.list.show_all()
        self.paint_selection()

    def show_hero(self, item):
        if item.image:
            self.hero_text.hide()
            self.hero_image.show()
            self.want_thumb(item, HERO_THUMB, self.hero_image)
            self.hero_caption.set_text(item.caption)
        else:
            self.hero_image.hide()
            self.hero_text.show()
            text = item.decode().decode(errors="replace") or item.preview
            self.hero_text.set_text(flat(text, HERO_TEXT_CHARS))
            self.hero_caption.set_text(f"TEXT  ·  {len(text)} chars")

    def make_grid(self):
        grid = Gtk.FlowBox()
        grid.set_min_children_per_line(COLUMNS)
        grid.set_max_children_per_line(COLUMNS)
        grid.set_homogeneous(True)
        grid.set_selection_mode(Gtk.SelectionMode.NONE)
        grid.set_valign(Gtk.Align.START)
        grid.set_can_focus(False)
        self.list.pack_start(grid, False, False, 0)
        return grid

    def clickable(self, widget, index, *classes):
        tile = launcher.styled(Gtk.EventBox(), "tile", *classes)
        tile.add(widget)
        tile.connect("button-release-event", lambda *_: self.copy(index))
        tile.connect("enter-notify-event", lambda *_: self.hover(index))
        return tile

    def make_row(self, item, index):
        text = launcher.styled(Gtk.Label(label=flat(item.preview, 300), xalign=0), "clip-text")
        text.set_ellipsize(Pango.EllipsizeMode.END)
        text.set_single_line_mode(True)
        text.set_margin_start(14)
        text.set_margin_end(14)
        text.set_margin_top(8)
        text.set_margin_bottom(8)
        row = self.clickable(text, index, "clip-row")
        row.set_margin_start(4)
        row.set_margin_end(4)
        row.set_margin_top(3)
        row.set_margin_bottom(3)
        self.list.pack_start(row, False, False, 0)
        return row

    def make_tile(self, item, index, grid):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_margin_start(10)
        box.set_margin_end(10)
        image = Gtk.Image()
        image.set_vexpand(True)
        box.pack_start(image, True, True, 0)
        self.want_thumb(item, TILE_THUMB, image)
        caption = launcher.styled(Gtk.Label(label=item.caption), "clip-caption")
        box.pack_start(caption, False, False, 0)
        tile = self.clickable(box, index, "clip-tile")
        child = Gtk.FlowBoxChild()
        child.set_can_focus(False)
        child.add(tile)
        grid.add(child)
        return tile

    def where(self, index):
        """(x, y, width, height) of a row or tile inside the list."""
        tile = self.tiles[index - 1]
        alloc = tile.get_allocation()
        x, y = tile.translate_coordinates(self.list, 0, 0) or (alloc.x, alloc.y)
        return x, y, alloc.width, alloc.height

    def step(self, down):
        """The row or tile straight above or below the selected one: on the
        nearest line in that direction, the one closest across."""
        x, y, w, h = self.where(self.selected)
        middle = x + w / 2
        best = None
        for index in range(1, len(self.tiles) + 1):
            ox, oy, ow, oh = self.where(index)
            if (oy >= y + h) if down else (oy + oh <= y):
                score = (abs(oy - y), abs(ox + ow / 2 - middle))
                if best is None or score < best[0]:
                    best = (score, index)
        return best[1] if best else None

    def paint_selection(self):
        style = self.hero.get_style_context()
        (style.add_class if self.selected == 0 else style.remove_class)("selected")
        for index, tile in enumerate(self.tiles, start=1):
            style = tile.get_style_context()
            (style.add_class if index == self.selected else style.remove_class)("selected")
        if self.selected:
            _x, y, _w, height = self.where(self.selected)
            adj = self.scroll.get_vadjustment()
            if y < adj.get_value():
                adj.set_value(y)
            elif y + height > adj.get_value() + adj.get_page_size():
                adj.set_value(y + height - adj.get_page_size())

    def hover(self, index):
        self.selected = index
        self.paint_selection()

    # -- keys ------------------------------------------------------------------
    def on_key(self, _widget, event):
        key = event.keyval
        if key == Gdk.KEY_Escape:
            self.close()
            return True
        n = len(self.results)
        if not n:
            return False
        if key == Gdk.KEY_Delete and not self.entry.get_text():
            self.forget(self.selected)
            return True
        if key == Gdk.KEY_Delete and event.state & Gdk.ModifierType.SHIFT_MASK:
            self.forget(self.selected)  # with a query typed, Shift+Del forgets
            return True
        sel = self.selected
        if key in (Gdk.KEY_Down, Gdk.KEY_KP_Down):
            sel = 1 if sel == 0 else (self.step(True) or sel)
        elif key in (Gdk.KEY_Up, Gdk.KEY_KP_Up):
            sel = 0 if sel == 0 else (self.step(False) or 0)
        elif key in (Gdk.KEY_Right, Gdk.KEY_Tab) and sel > 0:
            sel += 1
        elif key in (Gdk.KEY_Left, Gdk.KEY_ISO_Left_Tab) and sel > 0:
            sel -= 1
        elif key == Gdk.KEY_Tab:
            sel = 1
        else:
            return False
        self.selected = max(0, min(sel, n - 1))
        self.paint_selection()
        return True

    # -- actions ---------------------------------------------------------------
    def copy(self, index):
        if self.done or index >= len(self.results):
            return
        self.done = True                # a double click must not copy twice
        # wl-copy forks to serve the selection, so it outlives this window.
        proc = subprocess.Popen(["sh", "-c", "cliphist decode | wl-copy"],
                                stdin=subprocess.PIPE, start_new_session=True,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        proc.communicate(self.results[index].line.encode(), timeout=5)
        self.close()

    def forget(self, index):
        item = self.results[index]
        subprocess.run(["cliphist", "delete"], input=item.line.encode(),
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3)
        self.items = [i for i in self.items if i.id != item.id]
        keep = self.selected
        self.refresh()
        self.selected = max(0, min(keep, len(self.results) - 1))
        self.paint_selection()

    def close(self):
        self.pool.shutdown(wait=False, cancel_futures=True)
        Gtk.main_quit()


def main():
    launcher.PID_FILE = PID_FILE        # its own instance, not the launcher's
    if launcher.close_running(marker=b"clipboard.py"):
        return
    with open(PID_FILE, "w") as handle:
        handle.write(str(os.getpid()))
    launcher.on_sigterm(Gtk.main_quit)
    launcher.load_css()
    Clipboard()
    try:
        Gtk.main()
    finally:
        try:
            os.remove(PID_FILE)
        except OSError:
            pass


if __name__ == "__main__":
    main()
