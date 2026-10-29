"""Settings page: accessibility (accessibility.py).

One place for everything that makes the desktop easier to see, hear and use,
in four groups:

  SEEING        the screen magnifier (Hyprland's cursor zoom), high contrast
                in apps, reduce transparency, a larger pointer -- and, from
                the pages that own them, the text size (Fonts, text &
                pointer) and the colour filters (Effects), with a link there
  HEARING       the Orca screen reader, and visual alerts: the screens flash
                for a notification instead of the theme's sound
  MOTION        reduce motion: the "calm" animations, no moving wallpaper,
                no wallpaper reactions, no animations inside apps
  TYPING        sticky / slow / bounce keys, which Hyprland does not have --
                said so here, with what there is instead; the on-screen
                keyboard (osk.py: wvkbd or squeekboard, whichever is
                installed -- neither: what to install), shown / hidden from
                here, and squeekboard's "come up for text fields"

The page keeps nothing: each control runs accessibility.py (which hands the
parts that belong to other scripts -- display.py, theme.py, window-look.py,
font-settings.py, theme-sound.sh -- to their own CLIs) and redraws from
`accessibility.py status`, which reads every one of them back. Reduce motion
and reduce transparency show as ON only while every part of them really is
at its still / opaque value, so switching the theme's glass back by hand
turns the switch off here too.
"""
from gi.repository import GLib, Gtk  # noqa: F401

from .common import *  # noqa: F401,F403  (the shared helpers and paths)

import os  # noqa: E402
import subprocess  # noqa: E402

PAGE = {"id": "accessibility", "title": "Accessibility", "icon": "", "group": "Look", "order": 60, "parent": "fonts", "tab": "Accessibility",
        # Words the search bar matches this page by.
        "keywords": ["accessibility", "a11y", "magnifier", "zoom", "screen reader", "orca", "high contrast",
                     "contrast", "reduce motion", "animations", "reduce transparency", "transparency", "blur",
                     "visual alert", "flash", "bell", "sticky keys", "slow keys", "bounce keys",
                     "larger pointer", "big cursor", "vision", "hearing", "on-screen keyboard",
                     "virtual keyboard", "osk", "touch keyboard", "wvkbd", "squeekboard"]}

A11Y = os.path.join(HYPR, "accessibility.py")
OSK = os.path.join(HYPR, "osk.py")
SETTINGS = os.path.join(HYPR, "settings.py")
ZOOMS = [(1.0, "Off"), (1.5, "1.5×"), (2.0, "2×"), (3.0, "3×"), (4.0, "4×")]
POINTERS = [(24, "Default"), (32, "32 px"), (48, "48 px"), (64, "64 px"), (96, "96 px")]
CONTRAST_SUB = "stronger borders and plainer colours in GTK4 apps"


def attempt(*cmd, timeout=40):
    """accessibility.py ARGS: "" when it worked, else its own last word on
    stderr (it exits with a readable message). Called from background()."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        return f"{os.path.basename(cmd[0])}: {exc}"
    if r.returncode == 0:
        return ""
    return (r.stderr.strip().splitlines() or [f"{os.path.basename(cmd[0])} failed ({r.returncode})"])[-1]


def zoom_text(factor):
    """1.0 -> "off", 2.0 -> "2×", 1.25 -> "1.25×"."""
    return "off" if factor <= 1.0 else f"{factor:g}×"


def motion_sub(m):
    """What reduce motion does, and the animation preset when it is not calm."""
    if m.get("on"):
        return "on: fades only, still wallpaper, no app animations"
    text = "calmer animations, a still wallpaper, no app animations"
    if m.get("anim") and m.get("anim") != "calm":
        text += f"  ·  now \"{m['anim']}\""
    return text


def transparency_sub(t):
    if t.get("on"):
        return "on: solid windows, no blur"
    bits = []
    if t.get("glass") not in (0, None):
        bits.append(f"window glass {t['glass']}%")
    if t.get("blur") == "yes":
        bits.append("blur on")
    try:
        if float(t.get("inactive_opacity") or 1) < 1:
            bits.append(f"unfocused windows at {float(t['inactive_opacity']):.0%}")
    except ValueError:
        pass
    return "solid windows, no frosted glass" + (f"  ·  now: {', '.join(bits)}" if bits else "")


def osk_sub(st):
    """The on-screen keyboard row's line, from `osk.py status --json`."""
    if not st:
        return "osk.py did not answer"
    if not st.get("keyboard"):
        return "not installed: wvkbd (small, for this desktop) or squeekboard (GNOME's)"
    name = {"wvkbd": "wvkbd", "squeekboard": "squeekboard"}[st["keyboard"]]
    state = "showing" if st.get("shown") else "hidden"
    key = st.get("key") or ""
    return f"{state}  ·  {name}" + (f"  ·  {key} shows or hides it" if key else "")


def osk_auto_sub(st):
    """The "come up for text fields" row's line."""
    if not st or not st.get("keyboard"):
        return "needs an on-screen keyboard"
    if not st.get("auto_supported"):
        return "only squeekboard can follow text fields; wvkbd is shown by hand"
    return ("on: it comes up when you tap into a text field" if st["settings"].get("auto") == "on"
            else "off: shown by hand only")


def alerts_sub(a):
    if not a.get("wired"):
        flash = "flash not connected yet"
    else:
        flash = "screens flash for each notification"
    if a.get("on"):
        return f"on: sounds off  ·  {flash}"
    return f"flash instead of sound  ·  sounds {a.get('sounds', 'on')} now"


class Page:
    def __init__(self):
        self.widget = page_box()
        w = self.widget
        self.data = None
        self.updating = False
        self.error = dp.label("", "ctl-sub")
        self.error.set_line_wrap(True)
        self.error.set_no_show_all(True)
        w.pack_start(self.error, False, False, 0)

        # -- SEEING ------------------------------------------------------------------
        w.pack_start(heading("SEEING"), False, False, 0)
        grid, self.zoom_sub = row("", "Magnifier", "zooms around the pointer")
        w.pack_start(grid, False, False, 0)
        self.zoom_chips = self.make_chips(lambda k: self.do(A11Y, "zoom", k))
        w.pack_start(self.zoom_chips.widget, False, False, 0)
        self.zoom_slider = Slider("zoom", "Zoom", 100, 500, 25, "%",
                                  lambda _k, v: self.do(A11Y, "zoom", f"{v / 100:g}"))
        self.zoom_slider.widget.set_margin_start(36)
        w.pack_start(self.zoom_slider.widget, False, False, 0)
        self.zoom_more = dp.label("", "ctl-sub")
        self.zoom_more.set_line_wrap(True)
        self.zoom_more.set_max_width_chars(90)
        w.pack_start(details(self.zoom_more, label="Zoom keys"), False, False, 0)

        self.switches = {}
        self.switch_row(w, "contrast", "", "High contrast in apps", CONTRAST_SUB)
        self.switch_row(w, "transparency", "", "Reduce transparency", "")

        grid, self.pointer_sub = row("", "Larger pointer", "")
        w.pack_start(grid, False, False, 0)
        self.pointer = self.make_chips(lambda k: self.do(A11Y, "pointer", k))
        w.pack_start(self.pointer.widget, False, False, 0)

        grid, self.text_sub = row("", "Text size", "")
        w.pack_start(grid, False, False, 0)
        grid, self.filter_sub = row("", "Colour filters", "")
        w.pack_start(grid, False, False, 0)
        w.pack_start(links_row(link("Open Fonts", lambda: self.open_page("fonts")),
                               link("Open Effects", lambda: self.open_page("effects")),
                               link("Open Theme", lambda: self.open_page("theme"))), False, False, 0)
        w.pack_start(sep(), False, False, 0)

        # -- HEARING -----------------------------------------------------------------
        w.pack_start(heading("HEARING"), False, False, 0)
        self.switch_row(w, "reader", "", "Screen reader (Orca)", "")
        self.switch_row(w, "alerts", "", "Visual alerts", "")
        self.hearing_links = links_row(link("Orca preferences", lambda: spawn("orca", "--setup")),
                                    link("Test the flash", lambda: spawn(A11Y, "flash")))
        w.pack_start(self.hearing_links, False, False, 0)
        w.pack_start(sep(), False, False, 0)

        # -- MOTION ------------------------------------------------------------------
        w.pack_start(heading("MOTION"), False, False, 0)
        self.switch_row(w, "motion", "", "Reduce motion", "")
        w.pack_start(links_row(link("Open Effects", lambda: self.open_page("effects"))), False, False, 0)
        w.pack_start(sep(), False, False, 0)

        # -- TYPING ------------------------------------------------------------------
        w.pack_start(heading("TYPING"), False, False, 0)
        grid, self.keys_sub = row("", "Sticky keys, slow keys, bounce keys", "")
        w.pack_start(grid, False, False, 0)
        w.pack_start(links_row(link("Open Input", lambda: self.open_page("input"))),
                     False, False, 0)
        self.keys_more = dp.label("", "ctl-sub")
        self.keys_more.set_line_wrap(True)
        self.keys_more.set_max_width_chars(90)
        w.pack_start(details(self.keys_more, label="Why"), False, False, 0)

        # The on-screen keyboard: osk.py, not accessibility.py (status and
        # actions of its own).
        self.osk = None
        self.osk_switch = Gtk.Switch()
        self.osk_switch.connect("state-set", lambda _s, on: self.osk_do("show" if on else "hide"))
        grid, self.osk_sub = row("\uf11c", "On-screen keyboard", "checking…", self.osk_switch)
        w.pack_start(grid, False, False, 0)
        self.osk_auto = Gtk.Switch()
        self.osk_auto.connect("state-set", lambda _s, on: self.osk_do("set", "auto", "on" if on else "off"))
        grid, self.osk_auto_sub = row("\uf246", "Come up for text fields", "", self.osk_auto)
        w.pack_start(grid, False, False, 0)

    # -- building blocks -------------------------------------------------------------
    @staticmethod
    def make_chips(on_pick):
        """Chips on one line where they fit (see power.py: a FlowBox packed at
        the start otherwise shrinks to one chip per line)."""
        chips = Chips(on_pick)
        chips.widget.set_max_children_per_line(7)
        chips.widget.set_halign(Gtk.Align.START)
        chips.widget.set_margin_start(36)
        plain_set = chips.set

        def set_items(items, active):
            plain_set(items, active)
            chips.widget.set_min_children_per_line(max(1, min(len(items), 7)))
        chips.set = set_items
        return chips

    def switch_row(self, box, key, icon, title, sub):
        sw = Gtk.Switch()
        sw.connect("state-set", lambda _s, state, k=key: self.toggle(k, state))
        grid, sub_label = row(icon, title, sub, sw)
        self.switches[key] = (sw, sub_label)
        box.pack_start(grid, False, False, 0)

    def open_page(self, page_id):
        """Another page of this window: settings.py is one instance, so
        running it with a page name only switches the open window."""
        spawn(SETTINGS, page_id)

    # -- actions ---------------------------------------------------------------------
    def do(self, *cmd):
        if self.updating:
            return
        background(lambda: attempt(*cmd), self.done)

    def done(self, error):
        self.error.set_text(f"!  {error}" if error else "")
        self.error.set_visible(bool(error))
        self.refresh()

    def toggle(self, key, state):
        if not self.updating:
            sw, sub = self.switches[key]
            sub.set_text("changing…")
            self.do(A11Y, key, "on" if state else "off")
        return True

    def osk_do(self, *args):
        if not self.updating:
            self.osk_sub.set_text("changing…")
            background(lambda: attempt(OSK, *args, timeout=15), self.osk_done)
        return True

    def osk_done(self, error):
        if error:
            self.error.set_text(f"!  {error}")
            self.error.set_visible(True)
        self.refresh_osk()

    def refresh_osk(self):
        background(lambda: run_json(OSK, "status", "--json", timeout=10), self.show_osk)

    def show_osk(self, st):
        was, self.updating = self.updating, True
        self.osk = st
        has = bool(st and st.get("keyboard"))
        self.osk_switch.set_sensitive(has)
        self.osk_switch.set_state(bool(st and st.get("shown")))
        self.osk_switch.set_active(bool(st and st.get("shown")))
        self.osk_sub.set_text(osk_sub(st))
        auto = bool(st and st.get("settings", {}).get("auto") == "on")
        self.osk_auto.set_sensitive(bool(st and st.get("auto_supported")))
        self.osk_auto.set_state(auto)
        self.osk_auto.set_active(auto)
        self.osk_auto_sub.set_text(osk_auto_sub(st))
        self.updating = was

    # -- drawing ---------------------------------------------------------------------
    def refresh(self):
        if self.data is None:
            self.zoom_sub.set_text("checking…")
        background(lambda: run_json(A11Y, "status", timeout=20), self.show)
        self.refresh_osk()

    def set_switch(self, key, on, sub):
        sw, sub_label = self.switches[key]
        sw.set_state(bool(on))
        sw.set_active(bool(on))
        sub_label.set_text(sub)

    def show(self, data):
        if not data:
            self.zoom_sub.set_text("Accessibility settings did not answer")
            return
        self.data = data
        self.updating = True

        z = data["zoom"]
        factor = z["factor"]
        items = [(f"{f:g}", c) for f, c in ZOOMS]
        if factor not in [f for f, _ in ZOOMS]:
            items = sorted(items + [(f"{factor:g}", f"{factor:g}×")], key=lambda i: float(i[0]))
        self.zoom_chips.set(items, f"{factor:g}")
        self.zoom_slider.show(min(500, factor * 100))
        # The keys that run `accessibility.py zoom`, as Hyprland has them bound.
        keys = ", ".join(f"{k['keys']} {k['what']}" for k in z.get("keys", []))
        sub = f"{zoom_text(factor)}  ·  zooms around the pointer"
        more = ""
        if z.get("live") is not None and abs(z["live"] - factor) > 0.005:
            sub += f"  ·  {z['live']:g}× now"
            more = f"Hyprland has {z['live']:g}× now (gamemode or a hand-set option); a reload puts yours back. "
        more += keys if keys else "Up to 10× from the search bar: accessibility.py zoom in / out"
        self.zoom_sub.set_text(sub)
        self.zoom_more.set_text(more)

        self.set_switch("contrast", data.get("contrast"), CONTRAST_SUB)
        self.set_switch("transparency", data["transparency"].get("on"), transparency_sub(data["transparency"]))

        p = data["pointer"]
        size = p.get("size") or 24
        items = [(str(s), c) for s, c in POINTERS]
        if size not in [s for s, _ in POINTERS]:
            items = sorted(items + [(str(size), f"{size} px")], key=lambda i: int(i[0]))
        self.pointer.set(items, str(size))
        self.pointer_sub.set_text(f"{size} px, {p.get('theme') or 'the theme’s'} pointer")

        scale = data.get("text_scale") or 1.0
        self.text_sub.set_text(f"{scale:.0%} of normal  ·  set on Fonts")
        f = data["filter"]
        self.filter_sub.set_text((f"on: {f['label']}" if f.get("name") else "none on") +
                                 "  ·  grayscale, reading, colour-blind  ·  set on Effects")

        r = data["reader"]
        if not r.get("installed"):
            sub = "Orca is not installed: sudo dnf install orca"
        elif r.get("enabled"):
            sub = ("on" + ("" if r.get("running") else ", but NOT running: switch it off and on")
                   + "  ·  Insert+S stops speech, Insert+Q quits")
        else:
            sub = "reads out the focused window, menus and text"
        self.set_switch("reader", r.get("enabled"), sub)
        self.switches["reader"][0].set_sensitive(bool(r.get("installed")))
        self.set_switch("alerts", data["alerts"].get("on"), alerts_sub(data["alerts"]))

        self.set_switch("motion", data["motion"].get("on"), motion_sub(data["motion"]))

        self.keys_sub.set_text("not in Hyprland  ·  see Input for key repeat")
        self.keys_more.set_text(data["keys"]["note"] + "  So there is no switch for them here. What there is: a "
                               "longer key-repeat delay (or repeat off) for keys that stick, on Keyboard, mouse "
                               "& touchpad; and every desktop shortcut also runs from the search bar, without "
                               "holding keys together.")
        self.widget.show_all()
        self.hearing_links.get_children()[0].set_visible(bool(r.get("running")))
        self.updating = False
