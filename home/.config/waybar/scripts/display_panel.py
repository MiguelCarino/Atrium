#!/usr/bin/env python3
"""Display panel. The popup (the toolbox's Display row, SUPER+ALT+D, the
launcher's "> display") is QuickDisplay: HDR, brightness, night light and
filter, then "All display settings" -- Settings > Screens. The Settings window
lays out DisplayControls, everything below, as its Screens / Theme / Effects
pages.

    HDR          one switch per HDR-capable output, and the SDR white slider:
                 how bright ordinary (SDR) windows are inside HDR, in nits
    SCREENS      brightness, warmth and saturation -- for all screens or one
                 (the chips pick which), and under "Colour balance" a red /
                 green / blue gain to make different screens match, and
                 with one screen picked, its refresh rate (display.py rate)
                 (~/.config/hypr/scripts/screen-color.py; the night light's
                 warmth comes on top of a screen's own)
    ARRANGEMENT  first a map of the screens as they sit on the desktop (LayoutMap):
                 click one to pick it, drag it where it goes -- it snaps to
                 the nearest edge of another screen, lined up with its top,
                 bottom, left, right or middle when close, and never on top of
                 one -- and let go: display.py position X x Y --confirm. Then
                 per screen: on / off, primary, resolution, scale, rotation,
                 position (next to another screen, or exact), mirror, VRR,
                 colour depth, and "Back to defaults" -- display.py, with
                 --confirm ("Keep this?", undone by itself after 15 s)
    NIGHT LIGHT  on a schedule / always on / off, when it comes on and goes
                 off, how warm (nightlight.sh mode / start / end / temp)
    FILTER       off, or one GLSL screen shader (~/.config/hypr/shaders/)
    ANIMATIONS   snappy / smooth / fancy / calm / spring (lua/display.lua)
    THEME        the desktop theme (~/.config/themes/, ~/.config/hypr/scripts/
                 theme.py): one chip per theme folder, and the accent switch --
                 the bar, panels, launcher and window border take their accent
                 from the primary screen's wallpaper (scripts/theme-from-wallpaper.py).
                 The switch is greyed out while the current theme has
                 accent_follow=no: that theme's own accent always wins.
                 Then "Window glass": how see-through the terminals (COSMIC
                 Terminal, kitty) and COSMIC title bars are, for the current
                 theme -- `theme.py glass N`, kept per theme; under it the
                 worst case (the brightest wallpaper right behind): text and
                 dimmest-colour contrast. A new COSMIC window is needed for
                 its title bar; the terminal text area changes at once.
                 Then "Moving wallpaper": the theme's video wallpaper on or off
                 (`wallpaper-slideshow.py motion`), greyed out for a theme
                 that has none.
                 Then "Theme by time of day" (theme-schedule.py): on / off,
                 and which theme by day and which at night.

Every control is a front for ~/.config/hypr/scripts/display.py,
nightlight.sh or theme-from-wallpaper.py, the same commands the key binds and
the launcher run, so this panel holds no display logic of its own. It redraws
from `display.py status` (read in a thread, so the window never freezes) after
each action rather than trusting its own widgets.

    display_panel.py [x,y]   desktop position of the click that opened it
"""

import json
import os
import re
import subprocess
import sys
import threading

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import panelui  # noqa: E402
import themecolors  # noqa: E402

HYPR = os.path.expanduser("~/.config/hypr/scripts")
DISPLAY = os.path.join(HYPR, "display.py")
THEME = os.path.join(HYPR, "theme-from-wallpaper.py")
THEMES = os.path.join(HYPR, "theme.py")
SLIDESHOW = os.path.join(HYPR, "wallpaper-slideshow.py")
SCREEN_COLOR = os.path.join(HYPR, "screen-color.py")
DESKTOPCTL = os.path.join(HYPR, "desktopctl.py")
MOTION = os.path.join(HYPR, "wallpaper-motion.py")
MPV_STYLE = os.path.join(HYPR, "mpv-style.py")
SCHEDULE = os.path.join(HYPR, "theme-schedule.py")
NIGHTLIGHT = os.path.join(HYPR, "nightlight.sh")

SLIDE_DEBOUNCE_MS = 250     # one monitor re-apply per pause, not per pixel dragged
ICON_HDR = "\uf185"          # sun
ICON_GLASS = "\uf2d2"        # window-restore
ICON_MOTION = "\uf03d"       # video-camera
ICON_CLOCK = "\uf017"        # clock-o
ICON_FADE = "\uf042"         # adjust (half circle)
ICON_PULSE = "\uf21e"        # heartbeat
ICON_SOUND = "\uf028"        # volume-up
TABS = [("screens", "Screens"), ("theme", "Theme"), ("effects", "Effects")]
TAB_STATE = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"),
                         "hypr", "display-panel-tab")
SOUND = os.path.join(HYPR, "theme-sound.sh")
CUSTOM_DEBOUNCE_MS = 400
# (key, caption, step, unit) -- the ranges come from screen-color.py status
SCREEN_SLIDERS = [("brightness", "Brightness", 5, "%"), ("warmth", "Warmth", 100, "K"),
                  ("saturation", "Saturation", 5, "%")]
BALANCE_SLIDERS = [("red", "Red", 1, "%"), ("green", "Green", 1, "%"), ("blue", "Blue", 1, "%")]
GLASS_MAX = 80
# The arrangement's choices, as display.py takes them.
SIDES = [("right-of", "Right of"), ("left-of", "Left of"), ("above", "Above"), ("below", "Below")]
ROTATIONS = [("0", "Normal"), ("1", "90\u00b0"), ("2", "180\u00b0"), ("3", "270\u00b0"),
             ("4", "Flipped"), ("5", "Flipped 90\u00b0"), ("6", "Flipped 180\u00b0"),
             ("7", "Flipped 270\u00b0")]
VRR_CHOICES = [("0", "Off"), ("1", "On"), ("2", "Fullscreen only")]
# display.py's SCREEN_KEYS: "Back to defaults" empties every one.
SCREEN_KEYS = ("mode", "rate", "scale", "transform", "position", "mirror", "vrr", "bitdepth", "disabled")
LOW_CONTRAST = 3.0          # dimmest colour under this: say so


def read_tab():
    try:
        with open(TAB_STATE) as handle:
            return handle.read().strip()
    except OSError:
        return ""


def write_tab(key):
    try:
        os.makedirs(os.path.dirname(TAB_STATE), exist_ok=True)
        with open(TAB_STATE, "w") as handle:
            handle.write(key)
    except OSError:
        pass


def open_settings(page):
    """Settings on that page, detached (one instance: an open window comes
    forward and turns to it)."""
    try:
        subprocess.Popen([os.path.join(HYPR, "settings.py"), page], stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError:
        pass


def run(*cmd, quiet=True):
    env = dict(os.environ)
    if quiet:
        env["DISPLAY_QUIET"] = "1"      # the panel itself is the feedback
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=10,
                              env=env).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def status():
    """Everything the panel shows, from one process (desktopctl.py status):
    {display, screens, schedule, glass, fade, sounds, motion, react}."""
    try:
        return json.loads(run(DESKTOPCTL, "status"))
    except ValueError:
        return {}


def hz(rate):
    """"144.00" -> "144", "119.88" stays."""
    return f"{float(rate):.2f}".rstrip("0").rstrip(".")


label = panelui.label        # one caption helper for every panel


THEME_DOTS = {}     # theme name -> its colour dots (markup), read once


def theme_caption(theme):
    """A theme chip's caption: up to three dots in the theme's own border
    colours (hypr.active_border in its theme.conf), then its name -- so the
    list shows what each theme looks like, not only what it is called."""
    name = theme["name"]
    if name not in THEME_DOTS:
        colours = []
        try:
            with open(os.path.expanduser(f"~/.config/themes/{name}/theme.conf")) as handle:
                for line in handle:
                    if line.startswith("hypr.active_border="):
                        colours = re.findall(r"rgba?\(([0-9a-fA-F]{6})", line)[:3]
        except OSError:
            pass
        THEME_DOTS[name] = "".join(f"<span foreground='#{c}'>●</span>" for c in colours)
    dots = THEME_DOTS[name]
    text = GLib.markup_escape_text(theme["label"])
    return f"<span>{dots}  {text}</span>" if dots else theme["label"]


class Chips:
    """A wrapping row of dev-pick buttons, one lit: the filter list and the
    animation presets."""

    def __init__(self, on_pick, mark=True):
        self.on_pick = on_pick
        self.mark = mark            # a check mark on the chosen one (not on tabs)
        self.captions = {}
        self.widget = Gtk.FlowBox()
        self.widget.set_selection_mode(Gtk.SelectionMode.NONE)
        self.widget.set_max_children_per_line(4)
        self.widget.set_column_spacing(4)
        self.widget.set_row_spacing(4)
        self.widget.get_style_context().add_class("dev-list")
        self.buttons = {}

    def set(self, items, active):
        """items: [(key, caption)]. Rebuilt only when the list changes."""
        if list(self.buttons) != [key for key, _ in items]:
            for child in self.widget.get_children():
                self.widget.remove(child)
            self.buttons = {}
            for key, caption in items:
                # Every caption is Pango markup (the theme chips carry colour
                # dots); plain text is escaped into it.
                caption = str(caption)
                markup = caption if caption.startswith("<") else GLib.markup_escape_text(caption)
                self.captions[key] = markup
                button = Gtk.Button()
                button.add(Gtk.Label())
                button.get_style_context().add_class("dev-pick")
                # .chip: a choice among several, styled as a real button
                # (panel.css), unlike the audio panel's quiet device list.
                button.get_style_context().add_class("chip")
                button.set_can_focus(False)
                button.connect("clicked", lambda _b, k=key: self.on_pick(k))
                self.buttons[key] = button
                self.widget.add(button)
            self.widget.show_all()
        # Captions can change while the keys stay (Region's clock chips show
        # the time live): take the new ones without a rebuild.
        for key, caption in items:
            caption = str(caption)
            self.captions[key] = caption if caption.startswith("<") else GLib.markup_escape_text(caption)
        for key, button in self.buttons.items():
            style = button.get_style_context()
            (style.add_class if key == active else style.remove_class)("active")
            # The chosen one says so in words too, not only in colour: a
            # light and a dark fill can be hard to tell apart in some themes.
            tick = "\u2713 " if self.mark and key == active else ""
            button.get_child().set_markup(tick + self.captions[key])


class Slider:
    """Caption, value and a slider; tells on_commit(key, value) once the
    dragging pauses."""

    def __init__(self, key, caption, lo, hi, step, unit, on_commit):
        self.key, self.unit, self.on_commit = key, unit, on_commit
        self.updating = False
        self.pending = None
        self.widget = Gtk.Grid()
        self.widget.set_column_spacing(12)
        self.widget.attach(label(caption, "ctl-sub"), 0, 0, 1, 1)
        self.scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, lo, hi, step)
        self.scale.get_style_context().add_class("ctl-slider")
        self.scale.set_draw_value(False)
        self.scale.set_hexpand(True)
        self.scale.connect("value-changed", self.on_slide)
        self.widget.attach(self.scale, 0, 1, 1, 1)
        self.value = label("", "ctl-value", 1.0)
        self.value.set_width_chars(8)
        self.widget.attach(self.value, 1, 1, 1, 1)

    def show(self, value):
        if self.pending is None:
            self.updating = True
            self.scale.set_value(value)
            self.updating = False
        self.value.set_text(f"{int(self.scale.get_value())}{self.unit}")

    def on_slide(self, scale):
        self.value.set_text(f"{int(scale.get_value())}{self.unit}")
        if self.updating:
            return
        if self.pending:
            GLib.source_remove(self.pending)
        self.pending = GLib.timeout_add(SLIDE_DEBOUNCE_MS, self.commit)

    def commit(self):
        self.pending = None
        self.on_commit(self.key, int(self.scale.get_value()))
        return False


class ScreenColor:
    """The SCREENS section: which screen, then its sliders."""

    def __init__(self):
        self.target = "all"
        self.widget = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.chips = Chips(self.pick)
        self.widget.pack_start(self.chips.widget, False, False, 0)
        self.sub = label("", "ctl-sub")
        self.sub.set_line_wrap(True)
        self.sub.set_max_width_chars(44)
        self.widget.pack_start(self.sub, False, False, 0)
        self.sliders = []
        # Shown for one screen only: no_show_all keeps the panel's show_all
        # from showing it, show_rates() shows / hides it.
        self.rate_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.rate_box.set_no_show_all(True)
        self.rate_box.pack_start(label("Refresh rate", "ctl-sub"), False, False, 0)
        self.rates = Chips(self.set_rate)
        self.rate_box.pack_start(self.rates.widget, False, False, 0)
        self.widget.pack_start(self.rate_box, False, False, 0)
        self.box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.widget.pack_start(self.box, False, False, 0)
        self.balance = Gtk.Expander(label="Colour balance")
        self.balance.get_style_context().add_class("ctl-sub")
        self.balance_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.balance.add(self.balance_box)
        self.widget.pack_start(self.balance, False, False, 0)
        self.reset = Gtk.Button(label="Reset")
        self.reset.get_style_context().add_class("ctl-link")
        self.reset.set_halign(Gtk.Align.END)
        self.reset.connect("clicked", lambda _b: (run(SCREEN_COLOR, "reset", self.target), self.reload()))
        self.widget.pack_start(self.reset, False, False, 0)

    def reload(self):
        """Redraw; DisplayControls points this at its own (threaded) refresh."""
        self.refresh()

    def pick(self, key):
        self.target = key
        self.reload()

    def set(self, key, value):
        run(SCREEN_COLOR, "set", self.target, key, str(value))
        self.reload()

    def set_rate(self, rate):
        # Not quiet: the toast says what the screen really switched to. In a
        # thread: a mode change takes the screen (and hyprctl) a moment.
        background(lambda: run(DISPLAY, "rate", self.target, rate, "--confirm", quiet=False),
                   lambda _out: self.reload())

    def show_rates(self, outputs):
        """Per screen: its rate chips. All screens: the rates in the line."""
        one = self.target != "all" and outputs.get(self.target)
        if not one:
            self.rate_box.hide()
        else:
            self.rates.set([(r, f"{hz(r)} Hz") for r in one["rates"]], one["rate"])
            for child in self.rate_box.get_children():
                child.show_all()
            self.rate_box.show()
            return ""
        return "  ·  ".join(f"{n} {hz(o['rate'])} Hz" for n, o in outputs.items())

    def refresh(self, everything=None):
        """everything: a status() the panel already read; else read it now."""
        everything = everything or status()
        st = everything.get("screens") or {}
        if "screens" not in st:
            self.sub.set_text("screen-color.py did not answer")
            return
        if not self.sliders:
            for spec, box in ((SCREEN_SLIDERS, self.box), (BALANCE_SLIDERS, self.balance_box)):
                for key, caption, step, unit in spec:
                    lo, hi = st["ranges"][key]
                    slider = Slider(key, caption, lo, hi, step, unit, self.set)
                    self.sliders.append(slider)
                    box.pack_start(slider.widget, False, False, 0)
            self.widget.show_all()
        screens = {sc["name"]: sc for sc in st["screens"]}
        if self.target != "all" and self.target not in screens:
            self.target = "all"
        self.chips.set([("all", "All screens")] + [(n, n) for n in screens], self.target)
        values = st["all"] if self.target == "all" else screens[self.target]
        for slider in self.sliders:
            slider.show(values[slider.key])
        outputs = {o["name"]: o for o in everything.get("display", {}).get("outputs", [])}
        rate_line = self.show_rates(outputs)
        if self.target == "all":
            differ = [n for n, sc in screens.items()
                      if any(sc[k] != st["all"][k] for k, *_ in SCREEN_SLIDERS + BALANCE_SLIDERS)]
            sub = "every screen" + (f"  --  {', '.join(differ)} set on its own; this overrides it"
                                    if differ else "")
            if rate_line:
                sub += "\n" + rate_line
        else:
            sub = screens[self.target]["description"]
        if st.get("night"):
            sub += f"  --  night light adds {st['night']}K on top"
        if not st.get("running"):
            sub += "  --  screen-color.service is not running"
        self.sub.set_text(sub)
        self.reset.set_label("Reset all screens" if self.target == "all" else f"Reset {self.target}")


def background(work, done):
    """work() in a thread, done(result) back on the GTK thread: what keeps a
    redraw (or a mode change that takes a second) from freezing the window."""
    def go():
        result = work()
        GLib.idle_add(lambda: (done(result), False)[1])
    threading.Thread(target=go, daemon=True).start()


# Shared with every panel and the Settings window (panelui does the work).
wheel_to_page, guard_wheel = panelui.wheel_to_page, panelui.guard_wheel


def combo(on_changed):
    """A drop-down of (key, caption) items; on_changed(key) on a pick. As
    wide as its longest caption, not the row."""
    box = Gtk.ComboBoxText()
    box.set_can_focus(False)
    box.set_halign(Gtk.Align.START)
    box.keys = []
    box.connect("changed", lambda b: b.get_active() >= 0 and on_changed(b.keys[b.get_active()]))
    return box


def fill_combo(box, items, active):
    """Rebuild only when the list changed; select `active` (None: nothing).
    The caller holds its `updating` flag, so this fires no on_changed."""
    keys = [k for k, _ in items]
    if box.keys != keys:
        box.remove_all()
        for _, caption in items:
            box.append_text(caption)
        box.keys = keys
    box.set_active(keys.index(active) if active in keys else -1)


def picker_row(caption, widget):
    """A caption over a control, the Screens page's arrangement rows."""
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
    box.pack_start(label(caption, "ctl-sub"), False, False, 0)
    box.pack_start(widget, False, False, 0)
    return box


# -- the screens map ------------------------------------------------------------
SNAP_ALIGN = 0.12       # within this share of the smaller screen, line the edges up


def overlaps(a, b):
    """Do two (x, y, w, h) rectangles share any area (touching is fine)?"""
    return a[0] < b[0] + b[2] and b[0] < a[0] + a[2] and a[1] < b[1] + b[3] and b[1] < a[1] + a[3]


def snap(rect, others):
    """Where a screen dropped at rect (x, y, w, h) goes: against an edge of
    one of the others (so the pointer can cross between them), slid along
    that edge to where it was dropped but lined up with the other's start,
    end or middle when close, and never overlapping any screen. (x, y), or
    None when there is nowhere (no other screens)."""
    x, y, w, h = rect
    best = None
    for o in others:
        ox, oy, ow, oh = o
        sides = (("x", ox - w), ("x", ox + ow), ("y", oy - h), ("y", oy + oh))
        for axis, fixed in sides:
            if axis == "x":         # left / right of o: slide along y
                lo, hi, pos, size, ostart, olen = oy - h + 1, oy + oh - 1, y, h, oy, oh
            else:                   # above / below o: slide along x
                lo, hi, pos, size, ostart, olen = ox - w + 1, ox + ow - 1, x, w, ox, ow
            slide = min(max(pos, lo), hi)
            near = SNAP_ALIGN * min(size, olen)
            for target in (ostart, ostart + olen - size, ostart + (olen - size) // 2):
                if abs(slide - target) <= near:
                    slide = target
                    break
            cand = (fixed, slide) if axis == "x" else (slide, fixed)
            if any(overlaps((cand[0], cand[1], w, h), other) for other in others):
                continue
            dist = (cand[0] - x) ** 2 + (cand[1] - y) ** 2
            if best is None or dist < best[0]:
                best = (dist, (int(round(cand[0])), int(round(cand[1]))))
    return best[1] if best else None


class LayoutMap(Gtk.DrawingArea):
    """The screens drawn to scale where they sit on the desktop (logical
    pixels: scale and rotation counted). Click picks one for the controls
    below; a drag moves it and, let go, places it (snap()) through
    on_place(name, x, y). The primary screen has a bar along its bottom."""

    HEIGHT = 230
    PAD = 12

    def __init__(self, on_pick, on_place):
        super().__init__()
        self.on_pick, self.on_place = on_pick, on_place
        self.screens = []           # [{"name", "label", "rect": (x, y, w, h), "primary"}]
        self.target = None
        self.drag = None            # (name, pointer x, pointer y, original rect)
        self.moved = None           # the dragged screen's rect now, desktop pixels
        self.set_size_request(-1, self.HEIGHT)
        self.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK
                        | Gdk.EventMask.POINTER_MOTION_MASK)
        self.connect("draw", self.on_draw)
        self.connect("button-press-event", self.on_press)
        self.connect("motion-notify-event", self.on_motion)
        self.connect("button-release-event", self.on_release)
        self.set_tooltip_text("Drag a screen to where it sits on your desk; it snaps to the "
                              "nearest edge. A click picks it for the settings below.")

    def set(self, screens, target):
        if self.drag:
            return                  # a redraw from status never yanks a screen mid-drag
        self.screens, self.target = screens, target
        self.queue_draw()

    def frame(self):
        """(scale, offset x, offset y): desktop pixels to widget pixels."""
        rects = [s["rect"] for s in self.screens]
        if not rects:
            return 1, 0, 0
        x0 = min(r[0] for r in rects)
        y0 = min(r[1] for r in rects)
        x1 = max(r[0] + r[2] for r in rects)
        y1 = max(r[1] + r[3] for r in rects)
        width = max(1, self.get_allocated_width() - 2 * self.PAD)
        height = max(1, self.get_allocated_height() - 2 * self.PAD)
        k = min(width / max(1, x1 - x0), height / max(1, y1 - y0)) * 0.85  # room to drag past
        ox = self.PAD + (width - (x1 - x0) * k) / 2 - x0 * k
        oy = self.PAD + (height - (y1 - y0) * k) / 2 - y0 * k
        return k, ox, oy

    def rect_of(self, screen):
        if self.drag and self.moved and screen["name"] == self.drag[0]:
            return self.moved
        return screen["rect"]

    def at(self, px, py):
        k, ox, oy = self.frame()
        for screen in reversed(self.screens):
            x, y, w, h = screen["rect"]
            if ox + x * k <= px <= ox + (x + w) * k and oy + y * k <= py <= oy + (y + h) * k:
                return screen
        return None

    def on_press(self, _w, event):
        screen = self.at(event.x, event.y)
        if screen and event.button == 1:
            self.drag = (screen["name"], event.x, event.y, screen["rect"])
            self.moved = None
        return True

    def on_motion(self, _w, event):
        if not self.drag:
            return False
        name, px, py, (x, y, w, h) = self.drag
        k, _ox, _oy = self.frame()
        dx, dy = (event.x - px) / k, (event.y - py) / k
        if self.moved or abs(event.x - px) + abs(event.y - py) > 4:
            self.moved = (x + dx, y + dy, w, h)
            self.queue_draw()
        return True

    def on_release(self, _w, _event):
        if not self.drag:
            return False
        name, _px, _py, rect = self.drag
        moved, self.drag, self.moved = self.moved, None, None
        if not moved:
            self.on_pick(name)
        else:
            others = [s["rect"] for s in self.screens if s["name"] != name]
            spot = snap(moved, others)
            if spot and spot != (rect[0], rect[1]):
                self.on_place(name, *spot)
            self.target = name
        self.queue_draw()
        return True

    def on_draw(self, _w, cr):
        k, ox, oy = self.frame()
        fg = self.get_style_context().get_color(Gtk.StateFlags.NORMAL)
        accent = Gdk.RGBA()
        if not accent.parse(themecolors.hex("cyan", "#00e5ff")):
            accent.parse("#00e5ff")
        if self.drag and self.moved:       # where it would land
            others = [s["rect"] for s in self.screens if s["name"] != self.drag[0]]
            spot = snap(self.moved, others)
            if spot:
                w, h = self.moved[2], self.moved[3]
                cr.set_source_rgba(accent.red, accent.green, accent.blue, 0.5)
                cr.set_dash([4, 3])
                cr.set_line_width(1.5)
                cr.rectangle(ox + spot[0] * k, oy + spot[1] * k, w * k, h * k)
                cr.stroke()
                cr.set_dash([])
        for screen in self.screens:
            x, y, w, h = self.rect_of(screen)
            picked = screen["name"] == self.target
            rx, ry, rw, rh = ox + x * k + 1, oy + y * k + 1, w * k - 2, h * k - 2
            if picked:
                cr.set_source_rgba(accent.red, accent.green, accent.blue, 0.25)
            else:
                cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.08)
            cr.rectangle(rx, ry, rw, rh)
            cr.fill_preserve()
            if picked:
                cr.set_source_rgba(accent.red, accent.green, accent.blue, 0.95)
            else:
                cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.45)
            cr.set_line_width(2 if picked else 1)
            cr.stroke()
            if screen.get("primary"):       # the primary: a bar along its bottom edge
                cr.rectangle(rx + 3, ry + rh - 5, rw - 6, 3)
                cr.fill()
            cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.9)
            cr.select_font_face("sans")
            for i, (text, size) in enumerate(((screen["name"], 11), (screen["label"], 9))):
                while size > 7:             # a narrow (portrait) screen: smaller, not gone
                    cr.set_font_size(size)
                    ext = cr.text_extents(text)
                    if ext.width <= rw - 6:
                        break
                    size -= 1
                if ext.width > rw - 6:
                    continue
                cr.move_to(rx + (rw - ext.width) / 2 - ext.x_bearing, ry + rh / 2 - 2 + i * 13)
                cr.show_text(text)
        return False


FILLER = {"corporation", "corp", "corp.", "technologies", "technology", "electronics", "inc", "inc.",
          "co.", "ltd", "ltd."}


def short_name(description):
    """"Acer Technologies Acer P205H LGL0W0154332" -> "Acer P205H": the
    description is make, model, serial; the company words and the serial
    go, and the last two words left are the name on the bezel."""
    words = [w for w in description.split() if w.lower() not in FILLER]
    if len(words) > 2 and sum(c.isdigit() for c in words[-1]) >= 4:
        words = words[:-1]
    return " ".join(words[-2:])


# "Remember this layout": the keys that pin a screen where it is now.
LAYOUT_KEYS = ("mode", "rate", "scale", "transform", "position")


def live_layout(info):
    """{key: value} of one screen's live arrangement (a `display.py status`
    output), in display.conf's spelling -- what `display.py restore` takes."""
    return {"mode": info.get("resolution", ""),
            "rate": str(info.get("rate", "")),
            "scale": str(info.get("scale", "")),
            "transform": str(info.get("transform", 0)),
            "position": f"{info.get('x', 0)}x{info.get('y', 0)}"}


def remember_plan(outputs):
    """[(screen, ["key=value", ...])] that would write the live arrangement
    of every screen in use into display.conf -- only the screens where a
    stored key differs from what is live (one already pinned needs no
    write, and every write re-runs lua/monitors.lua). Screens switched off
    or mirroring another are left as they are: they have no place of their
    own to remember. A key with no live value is skipped, never blanked."""
    plan = []
    for info in outputs:
        if not info.get("enabled", True) or info.get("mirror_of"):
            continue
        chosen = info.get("chosen") or {}
        live = {k: v for k, v in live_layout(info).items() if v not in ("", "None")}
        if any(chosen.get(k, "") != v for k, v in live.items()):
            plan.append((info["name"], [f"{k}={v}" for k, v in live.items()]))
    return plan


def map_screens(outputs):
    """display.py status's outputs as LayoutMap's screens: the ones in use
    and not mirroring (a mirror has no place of its own)."""
    out = []
    for o in outputs:
        if not o.get("enabled", True) or o.get("mirror_of"):
            continue
        label = short_name(o.get("description") or "")
        out.append({"name": o["name"], "label": label, "primary": o.get("primary"),
                    "rect": (o.get("x", 0), o.get("y", 0), o.get("w", 0), o.get("h", 0))})
    return out


class Arrangement:
    """The ARRANGEMENT section: one screen at a time (the chips pick it), and
    for it everything display.py can set -- on / off, primary, resolution,
    scale, rotation, position, mirror, VRR, colour depth. Each control runs
    `display.py <what> <screen> <value> --confirm` (the "Keep this?" card,
    undone by itself after 15 s, since most of these can blank a screen), in
    the background, and then the whole page redraws from `display.py
    status`. The choices are kept in display.conf and laid over the host
    file by lua/monitors.lua, so they survive a reload and a re-login."""

    def __init__(self, on_change):
        self.on_change = on_change      # redraw the page (after an action)
        self.target = None
        self.updating = False
        self.info = {}
        self.widget = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.map = LayoutMap(self.pick, self.place)
        self.widget.pack_start(self.map, False, False, 0)
        self.chips = Chips(self.pick)
        self.widget.pack_start(self.chips.widget, False, False, 0)

        # Use this screen + primary, the two that are about the screen as a whole.
        head = Gtk.Grid()
        head.get_style_context().add_class("ctl-row")
        head.set_column_spacing(12)
        icon = label("", "ctl-icon", 0.5)      # desktop
        icon.set_valign(Gtk.Align.CENTER)
        head.attach(icon, 0, 0, 1, 2)
        self.title = label("", "ctl-title")
        head.attach(self.title, 1, 0, 1, 1)
        self.sub = label("", "ctl-sub")
        self.sub.set_hexpand(True)
        self.sub.set_line_wrap(True)
        self.sub.set_max_width_chars(40)
        head.attach(self.sub, 1, 1, 1, 1)
        self.use = Gtk.Switch()
        self.use.set_valign(Gtk.Align.CENTER)
        self.use.set_tooltip_text("Use this screen (off: switched off, its windows move away)")
        self.use.connect("state-set", self.on_use)
        head.attach(self.use, 2, 0, 1, 2)
        self.widget.pack_start(head, False, False, 0)
        self.primary = Gtk.Button(label="Make this the primary screen")
        self.primary.get_style_context().add_class("ctl-link")
        self.primary.set_halign(Gtk.Align.START)
        self.primary.set_no_show_all(True)          # show() decides
        self.primary.set_tooltip_text("Workspace 1 opens here")
        self.primary.connect("clicked", lambda _b: self.do("primary", confirm=False))
        self.widget.pack_start(self.primary, False, False, 0)

        # The rest only means something while the screen is on.
        self.details = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.widget.pack_start(self.details, False, False, 0)
        # Resolution and scale side by side, both drop-downs.
        self.resolution = combo(lambda key: self.do("resolution", key))
        self.scales = combo(lambda key: self.do("scale", key))
        mode = Gtk.Box(spacing=16)
        mode.pack_start(picker_row("Resolution", self.resolution), False, False, 0)
        mode.pack_start(picker_row("Scale", self.scales), False, False, 0)
        self.details.pack_start(mode, False, False, 0)
        self.rotation = Chips(lambda key: self.do("rotate", key))
        self.details.pack_start(picker_row("Rotation", self.rotation.widget), False, False, 0)

        # Position: next to another screen, or exactly (logical pixels).
        self.pos_sub = label("", "ctl-sub")
        place = Gtk.Box(spacing=6)
        self.side = combo(lambda _k: None)
        fill_combo(self.side, SIDES, SIDES[0][0])
        self.other = combo(lambda _k: None)
        go = Gtk.Button(label="Place")
        go.get_style_context().add_class("dev-pick")
        go.set_can_focus(False)
        go.connect("clicked", self.on_place)
        for widget in (self.side, self.other, go):
            place.pack_start(widget, False, False, 0)
        exact = Gtk.Box(spacing=6)
        self.pos_x = Gtk.SpinButton.new_with_range(-32768, 32768, 10)
        self.pos_y = Gtk.SpinButton.new_with_range(-32768, 32768, 10)
        for caption, spin in (("X", self.pos_x), ("Y", self.pos_y)):
            spin.set_width_chars(6)
            exact.pack_start(label(caption, "ctl-sub"), False, False, 0)
            exact.pack_start(spin, False, False, 0)
        set_exact = Gtk.Button(label="Set")
        set_exact.get_style_context().add_class("dev-pick")
        set_exact.set_can_focus(False)
        set_exact.connect("clicked", lambda _b: self.do(
            "position", f"{self.pos_x.get_value_as_int()}x{self.pos_y.get_value_as_int()}"))
        exact.pack_start(set_exact, False, False, 0)
        pos = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        pos.pack_start(self.pos_sub, False, False, 0)
        pos.pack_start(place, False, False, 0)
        pos.pack_start(exact, False, False, 0)
        self.details.pack_start(picker_row("Position", pos), False, False, 0)

        self.mirror = Chips(lambda key: self.do("mirror", key))
        self.details.pack_start(picker_row("Mirror", self.mirror.widget), False, False, 0)
        self.vrr = Chips(lambda key: self.do("vrr", key))
        self.details.pack_start(picker_row("Variable refresh rate (VRR)", self.vrr.widget), False, False, 0)
        self.depth = Chips(lambda key: self.do("bitdepth", key))
        self.details.pack_start(picker_row("Colour depth", self.depth.widget), False, False, 0)

        self.reset = Gtk.Button(label="Back to defaults")
        self.reset.get_style_context().add_class("ctl-link")
        self.reset.set_halign(Gtk.Align.END)
        self.reset.set_tooltip_text("Forget this screen's choices: the layout in lua/hosts/<host>.lua")
        self.reset.connect("clicked", lambda _b: self.do("restore", *[f"{k}=" for k in SCREEN_KEYS]))
        # Remember this layout: every screen's live mode, rate, scale,
        # rotation and position into display.conf (display.py restore, no
        # "Keep this?" -- nothing on screen changes), so an arrangement made
        # with hyprctl or another tool survives the next reload.
        self.remember = Gtk.Button(label="Remember this layout")
        self.remember.get_style_context().add_class("ctl-link")
        self.remember.set_tooltip_text("Keep every screen's current resolution, rate, scale, "
                                       "rotation and position after a reload or re-login")
        self.remember.connect("clicked", self.on_remember)
        ends = Gtk.Box(spacing=8)
        ends.pack_start(self.remember, False, False, 0)
        ends.pack_end(self.reset, False, False, 0)
        self.widget.pack_start(ends, False, False, 0)

    def pick(self, key):
        self.target = key
        self.show(self.everything)

    def do(self, what, *values, confirm=True):
        """display.py <what> <screen> <values> in the background; not quiet,
        so the toast says what the screen really switched to."""
        if self.updating or not self.target:
            return
        cmd = [DISPLAY, what, self.target, *values] + (["--confirm"] if confirm else [])
        # A mode change takes the screen a moment to come back: redraw after.
        background(lambda: run(*cmd, quiet=False),
                   lambda _out: GLib.timeout_add(400, lambda: (self.on_change(), False)[1]))

    def place(self, name, x, y):
        """A screen dragged on the map and let go: there, exactly."""
        self.target = name
        self.do("position", f"{x}x{y}")

    def on_use(self, _switch, state):
        if not self.updating:
            self.do("screen", "on" if state else "off")
        return True                     # redrawn from status, not here

    def on_remember(self, _button):
        outputs = (self.everything.get("display") or {}).get("outputs", [])
        plan = remember_plan(outputs)
        if not plan:
            self.remember.set_label("Already remembered")
            GLib.timeout_add(2500, lambda: (self.remember.set_label("Remember this layout"), False)[1])
            return
        self.remember.set_sensitive(False)

        def work():
            for name, pairs in plan:
                run(DISPLAY, "restore", name, *pairs)

        def done(_out):
            self.remember.set_sensitive(True)
            self.remember.set_label("Remembered")
            GLib.timeout_add(2500, lambda: (self.remember.set_label("Remember this layout"), False)[1])
            self.on_change()
        background(work, done)

    def on_place(self, _button):
        side = self.side.keys[self.side.get_active()] if self.side.get_active() >= 0 else ""
        other = self.other.keys[self.other.get_active()] if self.other.get_active() >= 0 else ""
        if side and other:
            self.do("position", side, other)

    everything = {}

    def show(self, everything):
        self.everything = everything
        st = everything.get("display") or {}
        outputs = {o["name"]: o for o in st.get("outputs", [])}
        if not outputs:
            self.title.set_text("No screens reported")
            return
        if self.target not in outputs:
            focused = [n for n, o in outputs.items() if o.get("focused")]
            self.target = focused[0] if focused else next(iter(outputs))
        info = outputs[self.target]
        self.map.set(map_screens(outputs.values()), self.target)
        self.updating = True
        self.chips.set([(n, n + ("  (off)" if not o.get("enabled", True) else ""))
                        for n, o in outputs.items()], self.target)
        on = info.get("enabled", True)
        self.title.set_text(info.get("description") or self.target)
        bits = []
        if not on:
            bits.append("switched off")
        else:
            bits.append(f"{info['resolution']} @ {hz(info['rate'])} Hz")
            if info.get("mirror_of"):
                bits.append(f"mirroring {info['mirror_of']}")
        primary = st.get("primary", "")
        if info.get("primary"):
            bits.append("primary screen")
        elif primary and not st.get("primary_live", True):
            bits.append(f"primary: {primary} (not connected)")
        self.sub.set_text("  ·  ".join(bits))
        self.use.set_state(on)
        # Never the last screen in use: display.py refuses, so grey it out.
        in_use = [o for o in outputs.values() if o.get("enabled", True) and not o.get("mirror_of")]
        self.use.set_sensitive(not (on and len(in_use) <= 1 and not info.get("mirror_of")))
        self.primary.set_visible(not info.get("primary"))
        self.details.set_sensitive(on)

        fill_combo(self.resolution, [(r, r) for r in info.get("resolutions", [])], info["resolution"])
        fill_combo(self.scales, [(s, f"{round(float(s) * 100)}%") for s in info.get("scales", [])], info["scale"])
        self.rotation.set(ROTATIONS, str(info.get("transform", 0)))
        self.pos_sub.set_text(f"now at {info.get('x', 0)}, {info.get('y', 0)}"
                              f"  ({info.get('w', 0)} x {info.get('h', 0)} on the desktop)")
        others = [(n, n) for n, o in outputs.items()
                  if n != self.target and o.get("enabled", True) and not o.get("mirror_of")]
        fill_combo(self.other, others, self.other.keys[self.other.get_active()]
                   if 0 <= self.other.get_active() < len(self.other.keys) else (others[0][0] if others else None))
        self.pos_x.set_value(info.get("x", 0))
        self.pos_y.set_value(info.get("y", 0))
        self.mirror.set([("off", "Off")] + [(n, n) for n in info.get("mirror_targets", [])],
                        info.get("mirror_of") or "off")
        chosen = info.get("chosen", {})
        self.vrr.set(VRR_CHOICES, chosen.get("vrr") or ("1" if info.get("vrr") else "0"))
        self.depth.set([("8", "8-bit"), ("10", "10-bit")], str(info.get("bitdepth", 8)))
        self.reset.set_sensitive(any(chosen.get(k) for k in SCREEN_KEYS))
        self.updating = False


class NightLight:
    """The NIGHT LIGHT section: auto (the schedule) / on / off, when the
    schedule starts and ends, and how warm. All of it is nightlight.sh's
    (mode / start / end / temp), kept in ~/.local/state/hypr/nightlight.conf,
    which the 5-minute timer in lua/nightlight.lua reads on every tick."""

    STEP_MIN = 15

    def __init__(self, on_change):
        self.on_change = on_change
        self.info = {}
        self.updating = False
        self.widget = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.modes = Chips(lambda key: self.do("mode", key))
        self.widget.pack_start(self.modes.widget, False, False, 0)
        self.sub = label("", "ctl-sub")
        self.sub.set_line_wrap(True)
        self.sub.set_max_width_chars(44)
        self.widget.pack_start(self.sub, False, False, 0)
        self.times = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.time_labels = {}
        for key, caption in (("start", "Comes on at"), ("end", "Goes off at")):
            row = Gtk.Box(spacing=8)
            row.pack_start(label(caption, "ctl-sub"), False, False, 0)
            later = Gtk.Button(label="›")
            earlier = Gtk.Button(label="‹")
            self.time_labels[key] = label("", "ctl-value")
            for button, step in ((later, self.STEP_MIN), (earlier, -self.STEP_MIN)):
                button.get_style_context().add_class("ctl-link")
                button.connect("clicked", lambda _b, k=key, d=step: self.shift(k, d))
            row.pack_end(later, False, False, 0)
            row.pack_end(self.time_labels[key], False, False, 0)
            row.pack_end(earlier, False, False, 0)
            self.times.pack_start(row, False, False, 0)
        self.widget.pack_start(self.times, False, False, 0)
        self.temp = Slider("temp", "Warmth (lower is warmer)", 1000, 6500, 100, "K",
                           lambda _k, value: self.do("temp", str(value)))
        self.widget.pack_start(self.temp.widget, False, False, 0)

    def do(self, *args):
        if self.updating:
            return
        background(lambda: run(NIGHTLIGHT, *args), lambda _out: self.on_change())

    def shift(self, key, minutes):
        h, m = (int(x) for x in self.info.get(key, "00:00").split(":"))
        total = (h * 60 + m + minutes) % (24 * 60)
        other = self.info.get("end" if key == "start" else "start", "")
        if f"{total // 60:02d}:{total % 60:02d}" == other:
            # nightlight.sh refuses equal times (no window, or all day): step
            # over the other end rather than have the click do nothing.
            total = (total + minutes) % (24 * 60)
        self.do(key, f"{total // 60:02d}:{total % 60:02d}")

    def show(self, info):
        if "mode" not in info:
            self.sub.set_text("nightlight.sh did not answer")
            return
        self.info = info
        self.updating = True
        self.modes.set([("auto", "On a schedule"), ("on", "Always on"), ("off", "Off")], info["mode"])
        now = f"on now, {info['now_temp']}K" if info["state"] == "on" else "off now"
        if info["why"] == "override":
            now += f" -- set by hand (SUPER+N) until {info['until']}"
        elif info["why"] == "schedule":
            now += f", until {info['until']}"
        self.sub.set_text(now)
        for key, widget in self.time_labels.items():
            widget.set_text(info[key])
        self.times.set_sensitive(info["mode"] == "auto")
        self.temp.show(info["temp"])
        self.temp.widget.set_sensitive(info["mode"] != "off")
        self.updating = False


class HdrRow:
    def __init__(self, output, on_toggle, on_white):
        self.output = output
        self.on_toggle, self.on_white = on_toggle, on_white
        self.updating = False
        self.pending = None

        self.widget = Gtk.Grid()
        self.widget.get_style_context().add_class("ctl-row")
        self.widget.set_column_spacing(12)

        icon = label(ICON_HDR, "ctl-icon", 0.5)
        icon.set_valign(Gtk.Align.CENTER)
        self.widget.attach(icon, 0, 0, 1, 2)

        self.title = label(f"{output}  HDR", "ctl-title")
        self.widget.attach(self.title, 1, 0, 1, 1)
        self.sub = label("", "ctl-sub")
        self.sub.set_hexpand(True)
        self.widget.attach(self.sub, 1, 1, 1, 1)

        self.switch = Gtk.Switch()
        self.switch.set_valign(Gtk.Align.CENTER)
        self.switch.connect("state-set", self.on_state_set)
        self.widget.attach(self.switch, 2, 0, 1, 2)

        white = label("SDR white", "ctl-sub")
        white.set_margin_top(6)
        self.widget.attach(white, 1, 2, 2, 1)
        self.scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 80, 480, 10)
        self.scale.get_style_context().add_class("ctl-slider")
        self.scale.set_draw_value(False)
        self.scale.set_size_request(240, -1)
        self.scale.connect("value-changed", self.on_slide)
        self.widget.attach(self.scale, 1, 3, 1, 1)
        self.value = label("", "ctl-value", 1.0)
        self.value.set_width_chars(8)
        self.widget.attach(self.value, 2, 3, 1, 1)

    def show(self, info):
        self.updating = True
        live = "HDR" if info["hdr_live"] else "SDR"
        if info["hdr_wanted"] and not info["hdr_live"]:
            live = "SDR -- HDR is off in the monitor's menu?"
        self.sub.set_text(live)
        self.switch.set_state(info["hdr_wanted"])
        if self.pending is None:
            self.scale.set_value(info["sdr_white"])
        self.value.set_text(f"{int(self.scale.get_value())} nits")
        self.scale.set_sensitive(info["hdr_live"])
        self.updating = False

    def on_state_set(self, _switch, state):
        if not self.updating:
            self.on_toggle(self.output, state)
        return True                         # redrawn from status, not here

    def on_slide(self, scale):
        self.value.set_text(f"{int(scale.get_value())} nits")
        if self.updating:
            return
        if self.pending:
            GLib.source_remove(self.pending)
        self.pending = GLib.timeout_add(SLIDE_DEBOUNCE_MS, self.commit)

    def commit(self):
        self.pending = None
        self.on_white(self.output, int(self.scale.get_value()))
        return False


class DisplayControls:
    """Everything this panel shows, as three pages (Screens, Theme, Effects).
    The panel puts them behind tabs in its card; the Settings window
    (hypr/scripts/settings.py) takes self.pages and lays them out itself, so
    both are the same widgets on the same code."""

    def __init__(self, card, tabs=True):
        self.card, self.with_tabs = card, tabs
        self.build()

    def build(self):
        pages = {key: Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0) for key, _ in TABS}
        self.pages = pages
        if self.with_tabs:
            # Three tabs, so the card stays short. The last one used opens
            # again next time (TAB_STATE).
            self.tabs = Chips(self.show_tab, mark=False)
            self.tabs.widget.set_max_children_per_line(3)
            self.tabs.widget.get_style_context().add_class("panel-tabs")
            self.card.pack_start(self.tabs.widget, False, False, 0)
            self.stack = Gtk.Stack()
            self.stack.set_vhomogeneous(False)
            self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
            self.stack.set_transition_duration(120)
            self.card.pack_start(self.stack, False, False, 0)
            for key, _ in TABS:
                self.stack.add_named(pages[key], key)
        screens_page, theme_page, effects_page = pages["screens"], pages["theme"], pages["effects"]

        # -- Screens --------------------------------------------------------
        screens_page.pack_start(label("DISPLAY", "kb-heading"), False, False, 0)
        self.hdr_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        screens_page.pack_start(self.hdr_box, False, False, 0)
        self.hdr_rows = {}
        self.no_hdr = label("No HDR screen connected right now (asleep or unplugged)", "ctl-sub")
        self.no_hdr.set_no_show_all(True)       # show() decides
        self.hdr_box.pack_start(self.no_hdr, False, False, 0)

        screens_page.pack_start(self.sep(), False, False, 0)
        screens_page.pack_start(label("SCREENS", "kb-heading"), False, False, 0)
        self.screens = ScreenColor()
        self.screens.reload = self.refresh
        screens_page.pack_start(self.screens.widget, False, False, 0)

        screens_page.pack_start(self.sep(), False, False, 0)
        screens_page.pack_start(label("ARRANGEMENT", "kb-heading"), False, False, 0)
        self.arrange = Arrangement(self.refresh)
        screens_page.pack_start(self.arrange.widget, False, False, 0)

        screens_page.pack_start(self.sep(), False, False, 0)
        screens_page.pack_start(label("NIGHT LIGHT", "kb-heading"), False, False, 0)
        self.night = NightLight(self.refresh)
        screens_page.pack_start(self.night.widget, False, False, 0)

        # -- Effects --------------------------------------------------------
        effects_page.pack_start(label("SCREEN FILTER", "kb-heading"), False, False, 0)
        self.filters = Chips(lambda key: self.act(DISPLAY, "filter", key or "off"))
        effects_page.pack_start(self.filters.widget, False, False, 0)

        effects_page.pack_start(self.sep(), False, False, 0)
        effects_page.pack_start(label("ANIMATIONS", "kb-heading"), False, False, 0)
        self.presets = Chips(lambda key: self.act(DISPLAY, "anim", key))
        effects_page.pack_start(self.presets.widget, False, False, 0)

        # -- Theme ----------------------------------------------------------
        theme_page.pack_start(label("THEME", "kb-heading"), False, False, 0)
        # theme.py set returns once the generated stylesheets are written (the
        # wallpaper change runs on in the slideshow); the chips are redrawn
        # from status afterwards, and set_theme reloads this panel's own CSS.
        self.themes = Chips(self.set_theme)
        theme_page.pack_start(self.themes.widget, False, False, 0)
        theme_page.pack_start(label("ACCENT COLOUR", "kb-heading"), False, False, 0)
        theme = Gtk.Grid()
        theme.get_style_context().add_class("ctl-row")
        theme.set_column_spacing(12)
        self.swatch = label("■", "ctl-icon", 0.5)
        self.swatch.set_valign(Gtk.Align.CENTER)
        theme.attach(self.swatch, 0, 0, 1, 2)
        theme.attach(label("Accent from wallpaper", "ctl-title"), 1, 0, 1, 1)
        self.theme_sub = label("", "ctl-sub")
        self.theme_sub.set_hexpand(True)
        theme.attach(self.theme_sub, 1, 1, 1, 1)
        self.accent_title = theme.get_child_at(1, 0)
        self.theme_switch = Gtk.Switch()
        self.theme_switch.set_valign(Gtk.Align.CENTER)
        self.theme_switch.connect("state-set", self.on_theme)
        theme.attach(self.theme_switch, 2, 0, 1, 2)
        theme_page.pack_start(theme, False, False, 0)

        # The row's own buttons sit under its text (indented past the icon),
        # not floating at the far right where they read as a separate thing.
        links = Gtk.Box(spacing=6)
        links.set_halign(Gtk.Align.START)
        links.set_margin_start(52)
        self.clear_custom = Gtk.Button(label="Use the theme's accent")
        self.clear_custom.get_style_context().add_class("ctl-link")
        self.clear_custom.connect("clicked", lambda _b: self.set_custom("off"))
        self.clear_custom.set_no_show_all(True)     # only with a colour of your own
        links.pack_start(self.clear_custom, False, False, 0)
        repick = Gtk.Button(label="Re-pick from wallpaper")
        repick.get_style_context().add_class("ctl-link")
        repick.connect("clicked", lambda _b: self.act(THEME, "apply"))
        self.repick = repick
        links.pack_start(repick, False, False, 0)
        theme_page.pack_start(links, False, False, 0)

        # Your own accent: a colour chooser inside the card (a dialog would
        # take the focus, and a click outside the card closes it).
        self.custom = Gtk.Expander(label="Your own accent colour")
        self.custom.get_style_context().add_class("ctl-sub")
        self.chooser = Gtk.ColorChooserWidget()
        self.chooser.set_use_alpha(False)
        self.chooser.connect("notify::rgba", self.on_chooser)
        self.chooser.connect("color-activated", lambda _w, _c: self.on_chooser(self.chooser, None))
        self.custom.add(self.chooser)
        theme_page.pack_start(self.custom, False, False, 0)
        self.custom_pending = None

        theme_page.pack_start(label("LOOK & MOTION", "kb-heading"), False, False, 0)
        glass = Gtk.Grid()
        glass.get_style_context().add_class("ctl-row")
        glass.set_column_spacing(12)
        icon = label(ICON_GLASS, "ctl-icon", 0.5)
        icon.set_valign(Gtk.Align.CENTER)
        glass.attach(icon, 0, 0, 1, 2)
        glass.attach(label("Window glass", "ctl-title"), 1, 0, 1, 1)
        self.glass_sub = label("", "ctl-sub")
        self.glass_sub.set_hexpand(True)
        self.glass_sub.set_line_wrap(True)
        self.glass_sub.set_max_width_chars(40)
        glass.attach(self.glass_sub, 1, 1, 2, 1)
        self.glass_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, GLASS_MAX, 1)
        self.glass_scale.get_style_context().add_class("ctl-slider")
        self.glass_scale.set_draw_value(False)
        self.glass_scale.set_size_request(240, -1)
        self.glass_scale.connect("value-changed", self.on_glass)
        glass.attach(self.glass_scale, 1, 2, 1, 1)
        self.glass_value = label("", "ctl-value", 1.0)
        self.glass_value.set_width_chars(8)
        glass.attach(self.glass_value, 2, 2, 1, 1)
        theme_page.pack_start(glass, False, False, 0)
        glass_links = Gtk.Box(spacing=6)
        glass_links.set_halign(Gtk.Align.START)
        glass_links.set_margin_start(52)
        self.glass_fix = Gtk.Button(label="Make readable")
        self.glass_fix.get_style_context().add_class("ctl-link")
        self.glass_fix.connect("clicked", lambda _b: self.show_glass(run(THEMES, "glass", "fix")))
        self.glass_fix.set_no_show_all(True)        # only while the text is hard to read
        glass_links.pack_start(self.glass_fix, False, False, 0)
        self.glass_default = Gtk.Button(label="Theme default")
        self.glass_default.get_style_context().add_class("ctl-link")
        self.glass_default.connect("clicked", lambda _b: self.show_glass(run(THEMES, "glass", "default")))
        glass_links.pack_start(self.glass_default, False, False, 0)
        theme_page.pack_start(glass_links, False, False, 0)
        self.glass_pending = None

        self.motion_switch, self.motion_title, self.motion_sub = self.switch_row(
            theme_page, ICON_MOTION, "Moving wallpaper", self.on_motion)
        self.react_switch, _, self.react_sub = self.switch_row(
            theme_page, ICON_PULSE, "Living wallpaper",
            lambda _s, state: self.toggle(MOTION, "react", state))
        self.fade_switch, _, self.fade_sub = self.switch_row(
            theme_page, ICON_FADE, "Fade between themes",
            lambda _s, state: self.toggle(THEMES, "fade", state))
        # Theme sounds are shown, not switched: they are notification chimes,
        # so their one switch is on Settings > Notifications (as on the Sound
        # page). The link opens Settings there, or brings it forward.
        sound_row = Gtk.Grid()
        sound_row.get_style_context().add_class("ctl-row")
        sound_row.set_column_spacing(12)
        sound_icon = label(ICON_SOUND, "ctl-icon", 0.5)
        sound_icon.set_valign(Gtk.Align.CENTER)
        sound_row.attach(sound_icon, 0, 0, 1, 2)
        sound_row.attach(label("Theme sounds", "ctl-title"), 1, 0, 1, 1)
        self.sound_sub = label("", "ctl-sub")
        self.sound_sub.set_hexpand(True)
        sound_row.attach(self.sound_sub, 1, 1, 1, 1)
        sound_link = Gtk.Button(label="Open Notifications")
        sound_link.get_style_context().add_class("ctl-link")
        sound_link.set_valign(Gtk.Align.CENTER)
        sound_link.connect("clicked", lambda _b: open_settings("notifications"))
        sound_row.attach(sound_link, 2, 0, 1, 2)
        theme_page.pack_start(sound_row, False, False, 0)

        # mpv's borders, over the theme's look (scripts/mpv-style.py): the
        # window frame takes at once, the controls on open mpv windows too.
        theme_page.pack_start(self.sep(), False, False, 0)
        theme_page.pack_start(label("VIDEO PLAYER", "kb-heading"), False, False, 0)
        theme_page.pack_start(label("Window frame", "ctl-sub"), False, False, 0)
        self.mpv_frames = Chips(lambda key: self.act(MPV_STYLE, "frame", key))
        theme_page.pack_start(self.mpv_frames.widget, False, False, 0)
        theme_page.pack_start(label("Controls", "ctl-sub"), False, False, 0)
        self.mpv_controls = Chips(lambda key: self.act(MPV_STYLE, "controls", key))
        theme_page.pack_start(self.mpv_controls.widget, False, False, 0)
        self.mpv_sub = label("", "ctl-sub")
        self.mpv_sub.set_line_wrap(True)
        self.mpv_sub.set_max_width_chars(48)
        theme_page.pack_start(self.mpv_sub, False, False, 0)

        theme_page.pack_start(self.sep(), False, False, 0)
        theme_page.pack_start(label("BY TIME OF DAY", "kb-heading"), False, False, 0)
        self.sched_switch, _, self.sched_sub = self.switch_row(
            theme_page, ICON_CLOCK, "Theme by time of day", self.on_schedule)
        self.sched_picks = {}
        self.sched_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        theme_page.pack_start(self.sched_box, False, False, 0)
        for part, caption in (("day", "By day"), ("evening", "In the evening"), ("night", "At night")):
            head = Gtk.Box(spacing=8)
            head.pack_start(label(caption, "ctl-sub"), False, False, 0)
            if part == "evening":
                # When the evening starts: half an hour a step.
                later = Gtk.Button(label="\u203a")
                self.evening_label = label("", "ctl-sub")
                earlier = Gtk.Button(label="\u2039")
                for button, step in ((later, 30), (earlier, -30)):
                    button.get_style_context().add_class("ctl-link")
                    button.connect("clicked", lambda _b, d=step: self.shift_evening(d))
                head.pack_end(later, False, False, 0)
                head.pack_end(self.evening_label, False, False, 0)
                head.pack_end(earlier, False, False, 0)
                self.evening_buttons = (earlier, self.evening_label, later)
            self.sched_box.pack_start(head, False, False, 0)
            self.sched_picks[part] = Chips(lambda key, p=part: self.set_pick(p, key))
            self.sched_box.pack_start(self.sched_picks[part].widget, False, False, 0)

        for page in pages.values():
            self.groupify(page)

        self.updating = False
        if self.with_tabs:
            self.tabs.set([(k, c) for k, c in TABS], "")
            GLib.idle_add(lambda: (self.show_tab(read_tab()), False)[1])
        self.refresh()

    def switch_row(self, page, icon_text, title_text, on_state):
        row = Gtk.Grid()
        row.get_style_context().add_class("ctl-row")
        row.set_column_spacing(12)
        icon = label(icon_text, "ctl-icon", 0.5)
        icon.set_valign(Gtk.Align.CENTER)
        row.attach(icon, 0, 0, 1, 2)
        title = label(title_text, "ctl-title")
        row.attach(title, 1, 0, 1, 1)
        sub = label("", "ctl-sub")
        sub.set_hexpand(True)
        row.attach(sub, 1, 1, 1, 1)
        switch = Gtk.Switch()
        switch.set_valign(Gtk.Align.CENTER)
        switch.connect("state-set", on_state)
        row.attach(switch, 2, 0, 1, 2)
        page.pack_start(row, False, False, 0)
        return switch, title, sub

    def show_tab(self, key):
        if key not in dict(TABS):
            key = TABS[0][0]
        self.stack.set_visible_child_name(key)
        self.tabs.set(TABS, key)
        write_tab(key)

    def toggle(self, script, sub, state):
        if not self.updating:
            run(*([script, sub] if sub else [script]), "on" if state else "off")
            self.refresh()
        return True

    @staticmethod
    def sep():
        sep = Gtk.Separator()
        sep.get_style_context().add_class("ctl-sep")
        return sep

    @staticmethod
    def groupify(page):
        """Turn a page's flat list -- heading, rows, separator, heading, rows
        -- into one card per section (.ctl-group in panel.css), so each
        section reads as a block instead of everything running together.
        Done once after build(), on the finished widgets, so the build code
        above keeps packing straight into the page."""
        children = page.get_children()
        group = None
        for child in children:
            expand = page.child_get_property(child, "expand")
            fill = page.child_get_property(child, "fill")
            page.remove(child)
            if child.get_style_context().has_class("ctl-sep"):
                continue        # the card edges separate the sections now
            if group is None or child.get_style_context().has_class("kb-heading"):
                group = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
                group.get_style_context().add_class("ctl-group")
                page.pack_start(group, False, False, 0)
            group.pack_start(child, expand, fill, 0)
        page.show_all()

    def refresh(self):
        """Read everything in a thread (desktopctl.py status and the night
        light's), then redraw: a page's refresh must never block the window."""
        self.generation = getattr(self, "generation", 0) + 1
        mine = self.generation

        def read():
            try:
                night = json.loads(run(NIGHTLIGHT, "status", "--json").strip().splitlines()[-1])
            except (ValueError, IndexError):
                night = {}
            try:
                mpv = json.loads(run(MPV_STYLE, "status", "--json"))
            except ValueError:
                mpv = {}
            return status(), night, mpv

        def done(result):
            if mine == self.generation:         # an older read finishing late is dropped
                self.show(*result)
        background(read, done)

    def show_mpv(self, mpv):
        if not mpv:
            return
        frames, controls = mpv.get("frames", {}), mpv.get("controls_presets", {})
        self.mpv_frames.set([(k, k.capitalize()) for k in frames], mpv.get("frame", "theme"))
        self.mpv_controls.set([(k, k.capitalize()) for k in controls], mpv.get("controls", "theme"))
        for chips, tips in ((self.mpv_frames, frames), (self.mpv_controls, controls)):
            for key, button in chips.buttons.items():
                button.set_tooltip_text(tips.get(key, ""))
        self.mpv_sub.set_text(f"Frame: {frames.get(mpv.get('frame'), '')}. "
                              f"Controls: {controls.get(mpv.get('controls'), '')}.")

    def show(self, everything, night, mpv=None):
        self.night.show(night)
        self.show_mpv(mpv)
        st = everything.get("display") or {}
        if not st or "error" in st:
            return
        self.updating = True
        here = set()
        for info in st.get("outputs", []):
            if not info["hdr_capable"]:
                continue
            here.add(info["name"])
            row = self.hdr_rows.get(info["name"])
            if row is None:
                row = HdrRow(info["name"], self.on_hdr, self.on_white)
                self.hdr_rows[info["name"]] = row
                self.hdr_box.pack_start(row.widget, False, False, 0)
            row.widget.show_all()
            row.show(info)
        # An HDR screen that is unplugged or asleep is not in the status:
        # hide its row (it comes back with it) and say why the section is empty.
        for name, row in self.hdr_rows.items():
            if name not in here:
                row.widget.hide()
        self.no_hdr.set_visible(not here)

        self.filters.set([("", "Off")] + [(f["name"], f["label"]) for f in st.get("filters", [])],
                         st.get("filter", ""))
        self.presets.set([(p, p.capitalize()) for p in st.get("presets", [])],
                         st.get("anim", "smooth"))

        self.themes.set([(t["name"], theme_caption(t)) for t in st.get("themes", [])],
                        st.get("theme", ""))

        accent = st.get("accent") or ""
        custom = st.get("accent_custom") or ""
        allowed = st.get("accent_follow", True) and not custom
        self.theme_switch.set_state(st.get("theme_auto", True) and allowed)
        # A theme with accent_follow=no keeps its own accent whatever the
        # switch says: grey the row out rather than offer a switch that does
        # nothing. The user's choice (theme_auto) is kept for the next theme.
        self.theme_switch.set_sensitive(allowed)
        self.repick.set_sensitive(allowed and st.get("theme_auto", True))
        self.accent_title.set_sensitive(allowed)
        # The swatch too: it still shows the fixed accent, but a theme can
        # dim it (label.ctl-icon:disabled) so the whole row reads as locked.
        self.swatch.set_sensitive(allowed)
        sub = accent if accent else "the theme's own"
        if custom:
            sub += "  --  your own colour"
        elif not allowed:
            sub += f"  --  fixed by {st.get('theme_label', 'this theme')}"
        self.clear_custom.set_visible(bool(custom))
        if accent and self.custom_pending is None:
            rgba = Gdk.RGBA()
            rgba.parse(accent)
            self.chooser.set_rgba(rgba)
        if st.get("crt_suggest") and st.get("filter") != "crt":
            sub += "  --  try the CRT filter"
        self.theme_sub.set_text(sub)
        self.swatch.set_markup(
            f"<span foreground='{accent}'>■</span>" if accent else "■")
        self.updating = False
        if self.glass_pending is None:
            self.show_glass(json.dumps(everything.get("glass", {})))
        self.show_motion(json.dumps(everything.get("motion", {})))
        self.updating = True
        self.fade_switch.set_state(everything.get("fade") != "off")
        self.fade_sub.set_text("a still of the screens fades into the new theme")
        self.sound_sub.set_text(("On" if everything.get("sounds") != "off" else "Off")
                                + "  ·  a chime with notifications and on a theme switch; quiet in Do Not Disturb")
        has_video = bool(everything.get("motion", {}).get("video"))
        self.react_switch.set_state(has_video and everything.get("react") != "off")
        self.react_switch.set_sensitive(has_video)
        self.react_sub.set_text("speed follows the CPU, colour the time and weather" if has_video
                                else "this theme has no moving wallpaper")
        self.updating = False
        self.screens.refresh(everything)
        self.arrange.show(everything)
        self.show_schedule([(t["name"], t["label"]) for t in st.get("themes", [])],
                           everything.get("schedule", {}))

    def show_schedule(self, themes, info):
        if "on" not in info:
            return
        self.updating = True
        self.sched_switch.set_state(info["on"])
        self.evening_at = info["evening_from"]
        self.evening_label.set_text(f"from {info['evening_from']}")
        self.updating = False
        evening = f", evening from {info['evening_from']}" if info["evening"] else ""
        self.sched_sub.set_text(f"day from {info['day_from']}{evening}, night from {info['night_from']}"
                                f"  --  now: {info['now']}")
        for part, chips in self.sched_picks.items():
            extra = [("random", "Random")] + ([("off", "Off")] if part == "evening" else [])
            chips.set(themes + extra, info[part] or ("off" if part == "evening" else ""))
        self.sched_box.set_sensitive(info["on"])
        for widget in self.evening_buttons:
            widget.set_sensitive(bool(info["evening"]))

    def on_schedule(self, _switch, state):
        if not self.updating:
            self.sched_box.set_sensitive(state)
            self.act(SCHEDULE, "on" if state else "off")
            panelui.load_css()      # turning it on can switch the theme
        return True

    def shift_evening(self, minutes):
        h, m = (int(x) for x in self.evening_at.split(":"))
        total = (h * 60 + m + minutes) % (24 * 60)
        run(SCHEDULE, "evening-from", f"{total // 60:02d}:{total % 60:02d}")
        self.refresh()

    def on_chooser(self, chooser, _pspec):
        if self.updating:
            return
        if self.custom_pending:
            GLib.source_remove(self.custom_pending)
        self.custom_pending = GLib.timeout_add(CUSTOM_DEBOUNCE_MS, self.commit_custom)

    def commit_custom(self):
        self.custom_pending = None
        c = self.chooser.get_rgba()
        self.set_custom("#{:02x}{:02x}{:02x}".format(*(round(x * 255) for x in (c.red, c.green, c.blue))))
        return False

    def set_custom(self, value):
        run(THEME, "custom", value)
        panelui.load_css()          # the panel's own accent too
        self.refresh()

    def set_pick(self, part, name):
        run(SCHEDULE, part, name)
        panelui.load_css()          # the pick for right now switches at once
        self.refresh()

    def show_motion(self, out):
        try:
            info = json.loads(out)
        except ValueError:
            return
        has = bool(info.get("video"))
        self.updating = True
        self.motion_switch.set_state(has and info.get("on", True))
        self.updating = False
        self.motion_switch.set_sensitive(has)
        self.motion_title.set_sensitive(has)
        self.motion_sub.set_text("stops in gamemode" if has
                                 else "this theme has none")

    def show_glass(self, out):
        try:
            info = json.loads(out)
        except ValueError:
            return
        self.updating = True
        self.glass_scale.set_value(info["glass"])
        self.updating = False
        self.glass_value.set_text(f"{info['glass']}%")
        sub = f"terminals, COSMIC title bars  --  worst case: text {info['text']}:1, colours {info['dimmest']}:1"
        if info["dimmest"] < LOW_CONTRAST:
            sub += "  (low)"
        self.glass_sub.set_text(sub)
        hard = info.get("readable", info["glass"]) < info["glass"]
        self.glass_fix.set_label(f"Make readable ({info.get('readable')}%)")
        self.glass_fix.set_visible(hard)
        self.glass_default.set_label(f"Theme default ({info['default']}%)")
        self.glass_default.set_sensitive(info["glass"] != info["default"])

    def on_motion(self, _switch, state):
        if not self.updating:
            self.show_motion(run(SLIDESHOW, "motion", "on" if state else "off"))
        return True

    def on_glass(self, scale):
        self.glass_value.set_text(f"{int(scale.get_value())}%")
        if self.updating:
            return
        if self.glass_pending:
            GLib.source_remove(self.glass_pending)
        self.glass_pending = GLib.timeout_add(SLIDE_DEBOUNCE_MS, self.commit_glass)

    def commit_glass(self):
        self.glass_pending = None
        self.show_glass(run(THEMES, "glass", str(int(self.glass_scale.get_value()))))
        return False

    def act(self, *cmd):
        run(*cmd)
        self.refresh()

    def set_theme(self, name):
        run(THEMES, "set", name)
        # The panel loaded panel.css (and with it generated/theme-panel.css and
        # accent.css) when it opened; without this it would keep the old
        # theme's look while everything around it switched.
        panelui.load_css()
        self.refresh()
        # A theme that follows the wallpaper has no accent yet at this point:
        # the slideshow is still fading in the new set, and the accent is
        # picked from it a few seconds later. Look again then, so the swatch
        # and "Accent from wallpaper" do not keep saying "the theme's own".
        # (refresh runs only on a live panel: closing it ends the process.)
        for ms in (3000, 8000):
            GLib.timeout_add(ms, lambda: (self.refresh(), False)[1])

    def on_hdr(self, output, state):
        # Not quiet: HDR can fail to take (the monitor's OSD), and that toast
        # says why where a switch alone could not.
        # In a thread (a mode change blocks hyprctl for a moment); the monitor
        # needs a moment more to come back, so the redraw waits a little.
        background(lambda: run(DISPLAY, "hdr", output, "on" if state else "off", "--confirm", quiet=False),
                   lambda _out: GLib.timeout_add(1200, lambda: (self.refresh(), False)[1]))

    def on_white(self, output, nits):
        run(DISPLAY, "sdr-white", output, str(nits))

    def on_theme(self, _switch, state):
        if not self.updating:
            self.act(THEME, "on" if state else "off")
        return True


class QuickDisplay:
    """The popup's card: only what is changed often -- HDR per screen, one
    brightness for all screens, night light, screen filter -- and, last, a
    link to the rest (Settings > Screens, the full DisplayControls)."""

    def __init__(self, card, on_close):
        self.on_close = on_close
        self.updating = False
        self.brightness = None
        group = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        group.get_style_context().add_class("ctl-group")
        card.pack_start(group, False, False, 0)
        group.pack_start(label("DISPLAY", "kb-heading"), False, False, 0)
        self.hdr_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        group.pack_start(self.hdr_box, False, False, 0)
        self.hdr = {}
        self.bright_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        group.pack_start(self.bright_box, False, False, 0)
        group.pack_start(label("Night light", "ctl-sub"), False, False, 0)
        self.night = Chips(lambda key: self.act(NIGHTLIGHT, "mode", key))
        group.pack_start(self.night.widget, False, False, 0)
        row = Gtk.Box(spacing=8)
        row.pack_start(label("Filter", "ctl-sub"), True, True, 0)
        self.filters = combo(lambda key: self.act(DISPLAY, "filter", key or "off"))
        row.pack_start(self.filters, False, False, 0)
        group.pack_start(row, False, False, 0)
        more = Gtk.Button(label="All display settings  \u203a")
        more.get_style_context().add_class("ctl-link")
        more.set_halign(Gtk.Align.END)
        more.connect("clicked", self.on_more)
        card.pack_start(more, False, False, 0)
        self.refresh()

    def on_more(self, _button):
        open_settings("screens")
        self.on_close()

    def act(self, *cmd):
        if not self.updating:
            background(lambda: run(*cmd), lambda _out: self.refresh())

    def refresh(self):
        def read():
            try:
                night = json.loads(run(NIGHTLIGHT, "status", "--json").strip().splitlines()[-1])
            except (ValueError, IndexError):
                night = {}
            return status(), night
        background(read, lambda result: self.show(*result))

    def hdr_row(self, name):
        row = Gtk.Box(spacing=8)
        row.pack_start(label(f"{ICON_HDR}  HDR  ·  {name}", "ctl-title"), True, True, 0)
        switch = Gtk.Switch()
        switch.set_valign(Gtk.Align.CENTER)
        switch.connect("state-set", self.on_hdr, name)
        row.pack_start(switch, False, False, 0)
        self.hdr_box.pack_start(row, False, False, 0)
        row.show_all()
        self.hdr[name] = (row, switch)
        return self.hdr[name]

    def on_hdr(self, _switch, state, name):
        if not self.updating:
            # Not quiet: HDR can fail to take, and the toast says why. The
            # monitor needs a moment to come back before the redraw.
            background(lambda: run(DISPLAY, "hdr", name, "on" if state else "off", "--confirm", quiet=False),
                       lambda _out: GLib.timeout_add(1200, lambda: (self.refresh(), False)[1]))
        return False

    def show(self, everything, night):
        self.updating = True
        st = everything.get("display") or {}
        here = set()
        for info in st.get("outputs", []):
            if info.get("hdr_capable"):
                here.add(info["name"])
                row, switch = self.hdr.get(info["name"]) or self.hdr_row(info["name"])
                switch.set_state(bool(info.get("hdr_wanted")))
                row.show()
        for name, (row, _switch) in self.hdr.items():
            row.set_visible(name in here)
        screens = everything.get("screens") or {}
        if self.brightness is None and screens.get("ranges"):
            lo, hi = screens["ranges"]["brightness"]
            self.brightness = Slider("brightness", "Brightness  ·  all screens", lo, hi, 5, "%",
                                     lambda key, value: self.act(SCREEN_COLOR, "set", "all", key, str(value)))
            self.bright_box.pack_start(self.brightness.widget, False, False, 0)
            self.bright_box.show_all()
        if self.brightness and screens.get("all"):
            self.brightness.show(screens["all"]["brightness"])
        if "mode" in night:
            self.night.set([("auto", "Schedule"), ("on", "On"), ("off", "Off")], night["mode"])
        if st:
            fill_combo(self.filters, [("", "Off")] + [(f["name"], f["label"]) for f in st.get("filters", [])],
                       st.get("filter", ""))
        self.updating = False


class Display(panelui.Panel):
    def build(self):
        self.controls = QuickDisplay(self.card, self.quit)


if __name__ == "__main__":
    panelui.run(Display)
