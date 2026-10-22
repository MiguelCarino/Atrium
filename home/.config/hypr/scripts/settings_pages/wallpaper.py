"""Settings page: the wallpaper (wallpaper-slideshow.py) and the lock screen
(lock-screen.py, which edits hyprlock.conf).

Wallpaper: every screen has a folder of its own, ~/Pictures/Wallpapers/<screen>/,
and the slideshow daemon shows a picture from it -- only the ones whose names
start with the theme's wallpaper_prefix (the "set"; the Theme page switches
it). Per screen the page shows what is on it now, "Next", a grid of the
folder's pictures to pick one from (thumbnails, drawn only when the grid is
opened) and "Other file..." for a picture from anywhere. Then the slideshow's
own options: change by itself or not, how often, shuffled or in name order
-- `wallpaper-slideshow.py interval / auto / shuffle`, kept in its options
file, which the daemon re-reads by itself. The moving and living wallpaper
belong to the theme, so they are only shown here, with a link to Theme.

Lock screen: what is behind the password field (a blurred screenshot, the
wallpaper, a plain colour), how much blur and how dark, the clock 24 h or
12 h, the date, the user name, the keyboard layout, a message line, and on
which screen the field and clock go. Every control is one `lock-screen.py`
command; hyprlock reads its file at every lock, so the next lock shows it.
"Lock now to preview" is the real lock (hyprlock has no preview), so it takes
two clicks.

Nothing is kept on the page: after every change it redraws from
`wallpaper-slideshow.py settings` and `lock-screen.py status`. A picked
picture goes through the daemon, which applies it within its 5 s poll, so
the page looks again a few seconds later.
"""
import hashlib
import os
import re
import subprocess
import threading
import urllib.parse

# common first: it pins Gtk/Gdk to 3.0 before anything imports them.
from .common import *  # noqa: F401,F403  (the shared helpers and paths)

import gi  # noqa: E402

gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gdk, GdkPixbuf, GLib, Gtk  # noqa: E402,F401

PAGE = {"id": "wallpaper", "title": "Wallpaper & lock screen", "icon": "\uf03e", "group": "Look", "order": 15,
        "keywords": ["wallpaper", "fondo", "fondo de pantalla", "background", "picture", "slideshow",
                     "shuffle", "next wallpaper", "interval", "lock screen", "pantalla de bloqueo",
                     "hyprlock", "lock", "clock", "12 hour", "24 hour", "date", "user name",
                     "keyboard layout", "message", "blur"]}

SLIDESHOW = os.path.join(HYPR, "wallpaper-slideshow.py")
LOCK = os.path.join(HYPR, "lock-screen.py")
MOTION = os.path.join(HYPR, "wallpaper-motion.py")
SETTINGS = os.path.join(HYPR, "settings.py")
APPLY_WAIT_S = 6                # the daemon's poll (5 s) and a little
THUMB_W, THUMB_H = 168, 96      # the grid's pictures fit in this
CURRENT_W, CURRENT_H = 120, 68  # the "now showing" one
ARM_S = 4                       # the preview button's second click window
INTERVALS = [60, 300, 600, 900, 1800, 3600, 10800]
BACKGROUNDS = [("screenshot", "Blurred screenshot"), ("wallpaper", "Wallpaper"), ("color", "Colour")]
BLUR = [("0", "None"), ("1", "Light"), ("2", "Medium"), ("3", "Strong"), ("4", "Strongest")]
DIM = [0.35, 0.5, 0.7, 1.0]
HOME = os.path.expanduser("~")


def short(path):
    return path.replace(HOME, "~", 1) if path.startswith(HOME) else path


def every(seconds):
    """600 -> "10 min", 3600 -> "1 h", 5400 -> "1½ h"."""
    seconds = int(seconds)
    if seconds < 3600:
        return f"{seconds // 60} min" if seconds % 60 == 0 else f"{seconds} s"
    if seconds % 3600 == 0:
        return f"{seconds // 3600} h"
    if seconds % 3600 == 1800:
        return f"{seconds // 3600}½ h"
    return f"{seconds // 60} min"


def interval_choices(current):
    values = sorted(set(INTERVALS) | {int(current)})
    return [(str(s), every(s)) for s in values]


def dim_caption(value):
    return "As is" if value >= 1 else f"{round(value * 100)} %"


def screen_sub(name, info, matched):
    """The line under a screen's title: what it shows, how many pictures,
    whether the slideshow counts time on it."""
    if not info["exists"]:
        return f"no folder yet: make {short(info['folder'])}/ and put pictures in it"
    bits = [os.path.basename(info["current"]) if info["current"] else "nothing shown by the slideshow yet"]
    bits.append(f"{info['in_set']} of {info['pictures']} pictures in the set")
    if not info["connected"]:
        bits.append("not connected")
    elif info["covered"] is True:
        bits.append("covered by windows: its time stands still" + (" (another screen's may run)" if matched else ""))
    elif info["covered"] is False:
        bits.append("visible: counting")
    return "  ·  ".join(bits)


def rgb_text(rgba):
    """Gdk.RGBA -> what lock-screen.py takes."""
    return f"rgb({round(rgba.red * 255)}, {round(rgba.green * 255)}, {round(rgba.blue * 255)})"


def parse_colour(text):
    """'rgb(10, 12, 20)' / 'rgba(0, 0, 0, 1.0)' / 'rgb(0a0c14)' -> (r, g, b) 0..1, None if unknown."""
    m = re.match(r"rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)", text or "")
    if m:
        return tuple(min(float(v), 255) / 255 for v in m.groups())
    m = re.match(r"rgba?\(\s*([0-9a-fA-F]{6})", text or "")
    if m:
        h = m.group(1)
        return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    return None


def attempt(*cmd, timeout=20):
    """"" when the command worked, else its last stderr line (both scripts
    exit with a readable one). From background() only."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        return f"{os.path.basename(cmd[0])}: {exc}"
    if r.returncode == 0:
        return ""
    return (r.stderr.strip().splitlines() or [f"{os.path.basename(cmd[0])} failed ({r.returncode})"])[-1]


# -- thumbnails --------------------------------------------------------------------
_thumbs = {}
_thumbs_lock = threading.Lock()


def cached_thumbnail(path):
    """The freedesktop thumbnail the file manager already made, if any
    (~/.cache/thumbnails/{large,normal}/<md5 of the file URI>.png) and not
    older than the picture."""
    uri = "file://" + urllib.parse.quote(os.path.realpath(path))
    name = hashlib.md5(uri.encode()).hexdigest() + ".png"
    base = os.environ.get("XDG_CACHE_HOME") or os.path.join(HOME, ".cache")
    try:
        mtime = os.stat(path).st_mtime
    except OSError:
        return None
    for size in ("large", "normal"):
        thumb = os.path.join(base, "thumbnails", size, name)
        try:
            if os.stat(thumb).st_mtime >= mtime:
                return thumb
        except OSError:
            continue
    return None


def thumbnail(path, width, height):
    """A Pixbuf of the picture fitting width x height, kept for the session.
    Decoding a 3440x1440 PNG takes ~0.1 s, so this runs in background()."""
    try:
        key = (path, os.stat(path).st_mtime, width, height)
    except OSError:
        return None
    with _thumbs_lock:
        if key in _thumbs:
            return _thumbs[key]
    pix = None
    for source in (cached_thumbnail(path), path):
        if not source:
            continue
        try:
            pix = GdkPixbuf.Pixbuf.new_from_file_at_scale(source, width, height, True)
            break
        except GLib.Error:
            continue
    with _thumbs_lock:
        _thumbs[key] = pix
    return pix


def picture(pix, width, height):
    """A Gtk.Image of the pixbuf, or a grey placeholder of the same size."""
    if pix is not None:
        return Gtk.Image.new_from_pixbuf(pix)
    image = Gtk.Image.new_from_icon_name("image-missing", Gtk.IconSize.DIALOG)
    image.set_size_request(width, height)
    return image


# -- the page ------------------------------------------------------------------------
class Page:
    def __init__(self):
        self.widget = page_box()
        w = self.widget
        self.data = None
        self.updating = False
        self.screens_built = None       # the screen names the rows were built for
        self.screen_rows = {}           # name -> (image box, sub label, grid box, expander)
        self.armed = None

        self.error = dp.label("", "ctl-sub")
        self.error.set_line_wrap(True)
        self.error.set_no_show_all(True)
        w.pack_start(self.error, False, False, 0)

        # -- wallpaper -------------------------------------------------------------
        w.pack_start(heading("WALLPAPER"), False, False, 0)
        self.intro = dp.label("", "ctl-sub")
        self.intro.set_line_wrap(True)
        self.intro.set_max_width_chars(90)
        w.pack_start(self.intro, False, False, 0)
        self.set_row, self.set_sub = row("\uf5fd", "Which set", "", link("Open Theme", lambda: spawn(SETTINGS, "theme")))
        w.pack_start(self.set_row, False, False, 0)
        self.screens = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        w.pack_start(self.screens, False, False, 0)
        w.pack_start(sep(), False, False, 0)

        w.pack_start(heading("SLIDESHOW"), False, False, 0)
        self.auto = self.switch()
        self.auto.connect("state-set", lambda _s, on: self.toggle(SLIDESHOW, "auto", on))
        grid, self.auto_sub = row("\uf021", "Change the picture by itself", "", self.auto)
        w.pack_start(grid, False, False, 0)
        self.interval = self.make_chips(lambda k: self.do(SLIDESHOW, "interval", k))
        w.pack_start(self.interval.widget, False, False, 0)
        self.shuffle = self.switch()
        self.shuffle.connect("state-set", lambda _s, on: self.toggle(SLIDESHOW, "shuffle", on))
        grid, self.shuffle_sub = row("\uf074", "Shuffle", "", self.shuffle)
        w.pack_start(grid, False, False, 0)
        self.daemon_row, self.daemon_sub = row("\uf013", "The slideshow", "")
        w.pack_start(self.daemon_row, False, False, 0)
        w.pack_start(sep(), False, False, 0)

        w.pack_start(heading("MOVING WALLPAPER"), False, False, 0)
        self.motion_row, self.motion_sub = row("\uf008", "Moving wallpaper", "",
                                               link("Open Theme", lambda: spawn(SETTINGS, "theme")))
        w.pack_start(self.motion_row, False, False, 0)
        self.react_row, self.react_sub = row("\uf21e", "Living wallpaper", "",
                                             link("Open Theme", lambda: spawn(SETTINGS, "theme")))
        w.pack_start(self.react_row, False, False, 0)
        w.pack_start(sep(), False, False, 0)

        # -- lock screen -----------------------------------------------------------
        w.pack_start(heading("LOCK SCREEN"), False, False, 0)
        grid, self.bg_sub = row("\uf03e", "Background", "")
        w.pack_start(grid, False, False, 0)
        self.background = self.make_chips(self.pick_background)
        w.pack_start(self.background.widget, False, False, 0)
        self.colour = Gtk.ColorButton()
        self.colour.set_use_alpha(False)
        self.colour.connect("color-set", lambda b: self.do(LOCK, "background", "color", rgb_text(b.get_rgba())))
        self.colour_row, _ = row("\uf53f", "Colour", "behind the clock and the field", self.colour)
        self.colour_row.set_no_show_all(True)
        w.pack_start(self.colour_row, False, False, 0)
        self.blur_row, self.blur_sub = row("\uf043", "Blur", "")
        w.pack_start(self.blur_row, False, False, 0)
        self.blur = self.make_chips(lambda k: self.do(LOCK, "blur", k))
        w.pack_start(self.blur.widget, False, False, 0)
        grid, self.dim_sub = row("\uf185", "Brightness of the background", "")
        w.pack_start(grid, False, False, 0)
        self.dim = self.make_chips(lambda k: self.do(LOCK, "dim", k))
        w.pack_start(self.dim.widget, False, False, 0)

        grid, self.clock_sub = row("\uf017", "Clock", "")
        w.pack_start(grid, False, False, 0)
        self.clock = self.make_chips(lambda k: self.do(LOCK, "clock", k))
        w.pack_start(self.clock.widget, False, False, 0)
        self.shown = {}
        for key, icon, title, sub in (
                ("date", "\uf133", "Date", "the day and date under the clock"),
                ("user", "\uf007", "User name", "your login name over the password field"),
                ("layout", "\uf11c", "Keyboard layout", "under the field: a password that \"stopped working\" is "
                 "usually the wrong layout (SUPER+Space switches it while locked)")):
            sw = self.switch()
            sw.connect("state-set", lambda _s, on, k=key: self.toggle(LOCK, k, on))
            grid, _ = row(icon, title, sub, sw)
            w.pack_start(grid, False, False, 0)
            self.shown[key] = sw

        grid, self.message_sub = row("\uf075", "Message", "")
        w.pack_start(grid, False, False, 0)
        self.message = Gtk.Entry()
        self.message.set_placeholder_text("e.g. If found, call …")
        self.message.set_max_length(120)
        self.message.set_hexpand(True)
        self.message.connect("activate", lambda _e: self.save_message())
        box = Gtk.Box(spacing=6)
        box.set_margin_start(36)
        box.pack_start(self.message, True, True, 0)
        box.pack_start(link("Save", self.save_message), False, False, 0)
        box.pack_start(link("Remove", lambda: (self.message.set_text(""), self.save_message())), False, False, 0)
        w.pack_start(box, False, False, 0)

        grid, self.screen_sub = row("\uf108", "Password field and clock on", "")
        w.pack_start(grid, False, False, 0)
        self.screen = self.make_chips(lambda k: self.do(LOCK, "screen", *([k] if k else [])))
        w.pack_start(self.screen.widget, False, False, 0)

        self.preview = link("Lock now to preview", self.press_preview)
        self.preview.set_tooltip_text("hyprlock has no preview mode: this is the real lock, and your password "
                                      "brings you back")
        w.pack_start(links_row(self.preview,
                               link("Open hyprlock.conf", lambda: spawn("xdg-open", os.path.expanduser(
                                   "~/.config/hypr/hyprlock.conf"))),
                               link("Check again", self.refresh)), False, False, 0)
        note = dp.label("Changes show at the next lock: hyprlock reads hyprlock.conf every time it starts. "
                        "lock-screen.py only edits the lines it owns; the previous file is kept as "
                        "~/.local/state/hypr/hyprlock.conf.prev.", "ctl-sub")
        note.set_line_wrap(True)
        note.set_max_width_chars(90)
        w.pack_start(note, False, False, 0)

    # -- building blocks -------------------------------------------------------------
    @staticmethod
    def switch():
        sw = Gtk.Switch()
        sw.set_valign(Gtk.Align.CENTER)
        return sw

    @staticmethod
    def make_chips(on_pick):
        """Chips on one line where they fit (power.py's reasoning: a FlowBox
        packed at the start shrinks to one chip a line unless told)."""
        chips = Chips(on_pick)
        chips.widget.set_max_children_per_line(8)
        chips.widget.set_halign(Gtk.Align.START)
        chips.widget.set_margin_start(36)
        plain_set = chips.set

        def set_items(items, active):
            plain_set(items, active)
            chips.widget.set_min_children_per_line(max(1, min(len(items), 8)))
        chips.set = set_items
        return chips

    # -- actions ---------------------------------------------------------------------
    def do(self, *cmd, later=False):
        """Every control: the command in the background, then redraw from
        what the scripts report (again after the daemon's poll for a
        picture change), its complaint on top if it failed."""
        if self.updating:
            return

        def done(error):
            self.error.set_text(f"!  {error}" if error else "")
            self.error.set_visible(bool(error))
            self.refresh()
            if later and not error:
                GLib.timeout_add_seconds(APPLY_WAIT_S, lambda: (self.refresh(), False)[1])
        background(lambda: attempt(*cmd), done)

    def toggle(self, script, key, on):
        if not self.updating:
            self.do(script, key, "on" if on else "off")
        return True         # the switch moves when the redraw says so

    def pick_background(self, mode):
        if mode == "color":
            self.do(LOCK, "background", "color", rgb_text(self.colour.get_rgba()))
        else:
            self.do(LOCK, "background", mode)

    def save_message(self):
        self.do(LOCK, "message", self.message.get_text())

    def press_preview(self):
        """Two clicks: the first arms it for ARM_S seconds."""
        if self.armed is None:
            self.preview.set_label("Click again: locks for real")
            self.armed = GLib.timeout_add_seconds(ARM_S, self.disarm)
            return
        self.disarm()
        spawn(LOCK, "preview")

    def disarm(self):
        if self.armed is not None:
            GLib.source_remove(self.armed)
            self.armed = None
        self.preview.set_label("Lock now to preview")
        return False

    def choose_file(self, name, folder):
        dialog = Gtk.FileChooserNative.new(f"A picture for {name}", self.widget.get_toplevel(),
                                           Gtk.FileChooserAction.OPEN, "Show", "Cancel")
        filt = Gtk.FileFilter()
        filt.set_name("Pictures")
        filt.add_mime_type("image/*")
        dialog.add_filter(filt)
        if os.path.isdir(folder):
            dialog.set_current_folder(folder)
        if dialog.run() == Gtk.ResponseType.ACCEPT:
            self.do(SLIDESHOW, "show", name, dialog.get_filename(), later=True)
        dialog.destroy()

    # -- drawing ---------------------------------------------------------------------
    def refresh(self):
        if self.data is None:
            self.intro.set_text("looking…")
        background(lambda: (run_json(SLIDESHOW, "settings", timeout=10),
                            run_json(LOCK, "status", timeout=10),
                            run_json(SLIDESHOW, "motion", timeout=10),
                            run_json(MOTION, "react", "status", timeout=10),
                            run_json("hyprctl", "monitors", "-j", timeout=5)), self.show)

    def show(self, data):
        wall, lock, motion, react, monitors = data
        self.data = data
        self.updating = True
        try:
            if wall:
                self.show_wallpaper(wall, motion or {}, react or {})
            else:
                self.intro.set_text("wallpaper-slideshow.py did not answer (run `wallpaper-slideshow.py "
                                    "settings` in a terminal to see why)")
            if lock:
                self.show_lock(lock, monitors or [])
            else:
                self.bg_sub.set_text("lock-screen.py did not answer (run `lock-screen.py status` in a terminal)")
            self.widget.show_all()
            self.colour_row.set_visible(bool(lock) and lock["background"] == "color")
        finally:
            self.updating = False

    def show_wallpaper(self, wall, motion, react):
        self.intro.set_text(f"Each screen has a folder of its own, {short(wall['folder'])}/<screen>/: drop pictures "
                            "in (PNG, JPEG, WebP, JPEG XL) and they join at the next change. hyprpaper fills the "
                            "screen with each and crops the overflow, so pictures the screen's shape look best.")
        pre = wall["prefix"]
        self.set_sub.set_text((f"only pictures whose names start with \"{pre}\" -- the theme's wallpaper set "
                               "(wallpaper_prefix); switch the theme to switch the set. The rest stay in the "
                               "folders, out of the rotation, and can still be picked below"
                               if pre else "every picture in the folders (this theme has no set of its own)")
                              + ("  ·  all screens change together, to pictures of the same name"
                                 if wall["matched"] else ""))
        names = list(wall["outputs"])
        if names != self.screens_built:
            self.build_screens(wall)
        for name, info in wall["outputs"].items():
            image_box, sub, _grid, _exp, _folder = self.screen_rows[name]
            sub.set_text(screen_sub(name, info, wall["matched"]))
            current = info["current"]
            clear(image_box)
            if current:
                background(lambda p=current: thumbnail(p, CURRENT_W, CURRENT_H),
                           lambda pix, box=image_box: self.put_image(box, pix, CURRENT_W, CURRENT_H))
            else:
                self.put_image(image_box, None, CURRENT_W, CURRENT_H)

        self.auto.set_state(wall["auto"])
        self.auto.set_active(wall["auto"])
        self.auto_sub.set_text(f"a new picture every {every(wall['interval'])} of the wallpaper being SEEN: time "
                               "under tiled or fullscreen windows does not count" if wall["auto"] else
                               "off: the picture stays until you press Next or pick one (a theme switch still "
                               "changes the set)")
        self.interval.set(interval_choices(wall["interval"]), str(int(wall["interval"])))
        self.interval.widget.set_sensitive(wall["auto"])
        self.shuffle.set_state(wall["shuffle"])
        self.shuffle.set_active(wall["shuffle"])
        self.shuffle_sub.set_text("random order, every picture once before any repeats" if wall["shuffle"] else
                                  "in name order, round and round")
        pid = wall.get("daemon")
        self.daemon_sub.set_text((f"running (pid {pid})" if pid else
                                  "NOT running: nothing changes by itself and Next does nothing until the next "
                                  "login (or start it: ~/.config/hypr/scripts/wallpaper-slideshow.py &)")
                                 + f"  ·  options in {short(wall['options_file'])}")

        video = motion.get("video")
        if video:
            self.motion_sub.set_text(f"{video}, playing in a loop over the still: "
                                     f"{'on' if motion.get('on') else 'off'}  ·  switched on the Theme page")
            self.react_sub.set_text(("on" if react.get("on") else "off") + ": its speed follows the CPU, its "
                                    "colour the time of day and the weather  ·  switched on the Theme page")
        else:
            self.motion_sub.set_text("this theme has none (a theme names one with wallpaper_video=)  ·  the "
                                     "switch is on the Theme page")
            # The switch is kept even without a video, so it is ready for a
            # theme that has one; say so rather than a bare "on".
            self.react_sub.set_text("goes with the moving wallpaper, so it does nothing in this theme (its "
                                    "switch stays " + ("on" if react.get("on") else "off") + " for one that has a "
                                    "video)  ·  switched on the Theme page")

    def build_screens(self, wall):
        clear(self.screens)
        self.screen_rows = {}
        for name, info in wall["outputs"].items():
            outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            line = Gtk.Box(spacing=12)
            line.get_style_context().add_class("ctl-row")
            image_box = Gtk.Box()
            image_box.set_size_request(CURRENT_W, CURRENT_H)
            line.pack_start(image_box, False, False, 0)
            text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            text.set_valign(Gtk.Align.CENTER)
            text.pack_start(dp.label(name, "ctl-title"), False, False, 0)
            sub = dp.label("", "ctl-sub")
            sub.set_line_wrap(True)
            sub.set_max_width_chars(60)
            text.pack_start(sub, False, False, 0)
            line.pack_start(text, True, True, 0)
            outer.pack_start(line, False, False, 0)
            folder = info["folder"]
            buttons = links_row(
                link("Next", lambda n=name: self.do(SLIDESHOW, "next", n, later=True)),
                link("Other file…", lambda n=name, f=folder: self.choose_file(n, f)),
                link("Open folder", lambda f=folder: spawn("xdg-open", f)))
            outer.pack_start(buttons, False, False, 0)
            expander = Gtk.Expander(label="Pick a picture from the folder")
            expander.get_style_context().add_class("ctl-sub")
            expander.set_margin_start(CURRENT_W + 12)
            grid = Gtk.FlowBox()
            grid.set_selection_mode(Gtk.SelectionMode.NONE)
            grid.set_max_children_per_line(6)
            grid.set_min_children_per_line(2)
            grid.set_column_spacing(6)
            grid.set_row_spacing(6)
            expander.add(grid)
            expander.connect("notify::expanded", lambda e, _p, n=name: e.get_expanded() and self.fill_grid(n))
            outer.pack_start(expander, False, False, 0)
            self.screens.pack_start(outer, False, False, 0)
            self.screen_rows[name] = (image_box, sub, grid, expander, folder)
        self.screens_built = list(wall["outputs"])

    @staticmethod
    def put_image(box, pix, width, height):
        clear(box)
        box.pack_start(picture(pix, width, height), False, False, 0)
        box.show_all()

    def fill_grid(self, name):
        """The folder's pictures as buttons, thumbnails loaded in the
        background (once per session each)."""
        _image, _sub, grid, _exp, _folder = self.screen_rows[name]
        clear(grid)
        grid.add(dp.label("loading the pictures…", "ctl-sub"))
        grid.show_all()

        def work():
            listing = run_json(SLIDESHOW, "list", name, timeout=10) or []
            return [(p, thumbnail(p["path"], THUMB_W, THUMB_H)) for p in listing]
        background(work, lambda items: self.show_grid(name, items))

    def show_grid(self, name, items):
        _image, _sub, grid, _exp, folder = self.screen_rows[name]
        clear(grid)
        current = ((self.data or [None])[0] or {}).get("outputs", {}).get(name, {}).get("current", "")
        if not items:
            grid.add(dp.label(f"No pictures in {short(folder)}/ yet.", "ctl-sub"))
        for info, pix in items:
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            box.pack_start(picture(pix, THUMB_W, THUMB_H), False, False, 0)
            caption = Gtk.Label(label=info["name"])
            caption.set_ellipsize(3)            # Pango.EllipsizeMode.END
            caption.set_max_width_chars(20)
            caption.get_style_context().add_class("ctl-sub")
            box.pack_start(caption, False, False, 0)
            button = Gtk.Button()
            button.add(box)
            button.get_style_context().add_class("dev-pick")
            if info["path"] == current:
                button.get_style_context().add_class("active")
            button.set_tooltip_text(info["name"] + ("" if info["in_set"] else
                                                    "\nnot in the theme's set: it stays until the next change"))
            if not info["in_set"]:
                button.set_opacity(0.6)
            button.connect("clicked", lambda _b, p=info["path"]: self.do(SLIDESHOW, "show", name, p, later=True))
            grid.add(button)
        grid.show_all()

    def show_lock(self, lock, monitors):
        mode = lock["background"]
        items = list(BACKGROUNDS) + ([("picture", "Your own picture")] if mode == "picture" else [])
        self.background.set(items, mode)
        self.bg_sub.set_text({
            "screenshot": "what was on each screen at the moment it locked, blurred and darkened so nothing "
                          "is readable over your shoulder",
            "wallpaper": "the picture each screen had (the slideshow keeps links to them in "
                         "~/.cache/wallpaper-slideshow/lock/)",
            "color": "one plain colour on every screen",
            "picture": f"a fixed picture set by hand in hyprlock.conf: {short(lock['path'])}",
        }.get(mode, mode))
        rgb = parse_colour(lock["color"])
        if rgb:
            self.colour.set_rgba(Gdk.RGBA(*rgb, 1.0))
        self.blur.set(BLUR, str(lock["blur"]))
        self.blur.widget.set_sensitive(mode != "color")
        self.blur_sub.set_text("not used with a plain colour" if mode == "color" else
                               "how far the background is smeared (blur passes)")
        self.dim.set([(f"{v:g}", dim_caption(v)) for v in sorted(set(DIM) | {lock["dim"]})], f"{lock['dim']:g}")
        self.dim_sub.set_text("lower keeps the white text readable over a bright picture")

        self.clock.set([("24h", "24-hour  (21:30)"), ("12h", "12-hour  (9:30 PM)")], lock["clock"])
        self.clock_sub.set_text("the big clock over the field" if lock["clock"] != "off" else
                                "hyprlock.conf has no clock label ($TIME) to change")
        self.clock.widget.set_sensitive(lock["clock"] != "off")
        for key, sw in self.shown.items():
            sw.set_state(lock[key])
            sw.set_active(lock[key])
        if not self.message.has_focus():
            self.message.set_text(lock["message"])
        self.message_sub.set_text(f"shown under the field: \"{lock['message']}\"" if lock["message"] else
                                  "a line of your own under the field (Enter or Save; empty = none)")

        connected = [m["name"] for m in monitors if not m.get("disabled")]
        screen = lock["screen"]
        names = sorted(set(connected) | ({screen} if screen else set()))
        self.screen.set([(n, n) for n in names] + [("", "Every screen")], screen)
        if screen and connected and screen not in connected:
            self.screen_sub.set_text(f"!  {screen} is not connected now: the field and clock would not show on "
                                     "any screen (typing the password still works). Pick a connected one or "
                                     "Every screen.")
        elif screen:
            self.screen_sub.set_text(f"on {screen} only; the other screens show just the background")
        else:
            self.screen_sub.set_text("on every screen")
