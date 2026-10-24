"""Settings page: the bar and the toolbox card (bar-settings.py).

    THE BAR          which screen it is on (the toolbox goes along), whether
                     the running bar has every change, Restart the bar
    LEFT / MIDDLE / RIGHT   every pill on that side of the bar, in order: a
                     switch to show or hide it, arrows to move it along its side
    TOOLBOX          the toolbox card's rows, the same way
    REFRESH          how often the updates, weather and git pills look again
    CLOCK AND DATE   a link to Date, time & region, where their format lives

Nothing is kept here: every control runs ~/.config/hypr/scripts/bar-settings.py,
which edits ~/.config/waybar/config or config-toolbox in place (a hidden pill
stays in its list as a comment, so showing it puts it back where it was),
and the page redraws from `bar-settings.py status`. waybar reads its config
only when it starts, so a change needs the bar restarted: the page does that
itself (`bar-settings.py apply`, i.e. waybar/scripts/bar-restart.sh) a moment
after the last click, so moving one pill five places costs one restart, not
five. If the window is closed before then, the THE BAR row says the bar has
changes it has not loaded, and Restart the bar (or ALT+G) brings them in.
"""
from gi.repository import GLib, Gtk  # noqa: F401

from .common import *  # noqa: F401,F403  (the shared helpers and paths)

import os  # noqa: E402
import subprocess  # noqa: E402
import time  # noqa: E402

PAGE = {"id": "bar", "title": "Bar & toolbox", "icon": "", "group": "Look", "order": 70,
        "keywords": ["waybar", "barra", "panel", "top bar", "status bar", "pills", "modules", "widgets",
                     "tray", "toolbox", "restart the bar", "bar screen", "hide pill", "move pill",
                     "refresh interval", "weather", "git", "updates pill", "clock"]}

BAR_SETTINGS = os.path.join(HYPR, "bar-settings.py")
SETTINGS = os.path.join(HYPR, "settings.py")
APPLY_AFTER_MS = 1500           # restart the bar this long after the last change

SIDE_TEXT = {
    "modules-left": ("LEFT OF THE BAR", "from the left edge inwards"),
    "modules-center": ("MIDDLE OF THE BAR", "two joined capsules: moving or hiding an end pill leaves a square edge"),
    "modules-right": ("RIGHT OF THE BAR", "from the middle out to the right edge"),
}


def every(seconds):
    """1800 -> "30 min", 3600 -> "1 h", 90 -> "90 s"."""
    if seconds is None:
        return "?"
    if seconds % 3600 == 0:
        return f"{seconds // 3600} h"
    if seconds % 60 == 0 and seconds >= 120:
        return f"{seconds // 60} min"
    return f"{seconds} s"


def interval_choices(choices, current):
    """(key, caption) chips: the usual choices, and the file's own value when
    it is none of them (a hand edit), in order."""
    values = sorted(set(choices) | ({current} if current else set()))
    return [(str(s), f"every {every(s)}") for s in values]


def screen_name(screen):
    """"DP-2 · ACME ULTRAWIDE" -- the make and model out of Hyprland's
    description, without the serial number at its end."""
    words = (screen.get("description") or "").split()
    if words and any(c.isdigit() for c in words[-1]) and len(words[-1]) > 6:
        words = words[:-1]
    model = " ".join(words[-2:]) if len(words) > 2 else " ".join(words)
    return f"{screen['name']} · {model}" if model else screen["name"]


def screen_choices(screens, current):
    """Chips for every screen Hyprland knows, plus the configured one when it
    is not among them (unplugged), so the lit chip is always the truth."""
    items = [(s["name"], screen_name(s) + ("  (off)" if s.get("disabled") else "")) for s in screens]
    if current and current not in [k for k, _ in items]:
        items.append((current, f"{current}  (not connected)"))
    return items


def screen_sub(data):
    """The line under "Screen": where the bar is, and why it might not show."""
    bar = data.get("bar") or {}
    current = bar.get("output")
    if not current:
        return "on every screen (no \"output\" in the config)"
    found = next((s for s in data.get("screens") or [] if s["name"] == current), None)
    text = f"on {current}, with the toolbox"
    if found is None:
        text += f"  ·  {current} is not connected: no bar now, pick another"
    elif found.get("disabled"):
        text += f"  ·  {current} is off in Screens: no bar now"
    return text


def bar_sub(data, now=None):
    """The line under "The bar": running or not, and whether it has
    loaded every change."""
    now = time.time() if now is None else now
    since = (data.get("running") or {}).get("bar")
    if not since:
        return "NOT running: Restart the bar starts it"
    text = "running"
    if data.get("pending"):
        text += "  ·  changes not loaded yet: Restart the bar (ALT+G)"
    else:
        text += "  ·  up to date"
    return text


def attempt(*cmd, timeout=30):
    """Run bar-settings.py; "" when it worked, else the last line it said on
    stderr (its own readable message), so the page can show why a click did
    nothing. Called from background() only."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        return f"{os.path.basename(cmd[0])}: {exc}"
    if r.returncode == 0:
        return ""
    return (r.stderr.strip().splitlines() or [f"{os.path.basename(cmd[0])} failed ({r.returncode})"])[-1]


class Page:
    def __init__(self):
        self.widget = page_box()
        w = self.widget
        self.data = None
        self.updating = False
        self.apply_timer = None
        self.error = dp.label("", "ctl-sub")
        self.error.set_line_wrap(True)
        self.error.set_no_show_all(True)
        w.pack_start(self.error, False, False, 0)

        w.pack_start(heading("THE BAR"), False, False, 0)
        grid, self.bar_sub = row("", "The bar", "checking…")
        w.pack_start(grid, False, False, 0)
        w.pack_start(links_row(link("Restart the bar", lambda: self.apply_now(force=True))), False, False, 0)
        grid, self.screen_sub = row("", "Screen", "")
        w.pack_start(grid, False, False, 0)
        self.screen = self.make_chips(lambda k: self.do("screen", k))
        w.pack_start(self.screen.widget, False, False, 0)
        self.problems = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        w.pack_start(self.problems, False, False, 0)
        how = dp.label("Changes restart the bar a moment after your last click. If it stopped, "
                       "journalctl --user -u waybar says why.", "ctl-sub")
        how.set_line_wrap(True)
        w.pack_start(details(how, links_row(
            link("Open config", lambda: spawn("xdg-open", os.path.expanduser("~/.config/waybar/config"))),
            link("Open toolbox config", lambda: spawn("xdg-open", os.path.expanduser(
                "~/.config/waybar/config-toolbox"))))), False, False, 0)
        w.pack_start(sep(), False, False, 0)

        # One box per list, filled by show(): the rows are rebuilt from the
        # file each time, since a move changes their order.
        self.lists = {}
        for key in (*SIDE_TEXT, "card"):
            title, sub = SIDE_TEXT.get(key, ("TOOLBOX", "the card the toolbox button opens, top to bottom"))
            w.pack_start(heading(title), False, False, 0)
            hint = dp.label(sub, "ctl-sub")
            hint.set_line_wrap(True)
            w.pack_start(hint, False, False, 0)
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            self.lists[key] = box
            w.pack_start(box, False, False, 0)
            w.pack_start(sep(), False, False, 0)

        w.pack_start(heading("REFRESH"), False, False, 0)
        self.intervals = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        w.pack_start(self.intervals, False, False, 0)
        self.interval_chips = {}
        w.pack_start(sep(), False, False, 0)

        w.pack_start(heading("CLOCK AND DATE"), False, False, 0)
        grid, _sub = row("", "Time and date format",
                         "set on Date, time & region",
                         link("Open Region", lambda: spawn(SETTINGS, "region")))
        w.pack_start(grid, False, False, 0)

    # -- building blocks -------------------------------------------------------------
    @staticmethod
    def make_chips(on_pick):
        """Chips on one line where they fit (see the Power page: a FlowBox
        packed at the start shrinks to one chip per line otherwise)."""
        chips = Chips(on_pick)
        chips.widget.set_max_children_per_line(6)
        chips.widget.set_halign(Gtk.Align.START)
        plain_set = chips.set

        def set_items(items, active):
            plain_set(items, active)
            chips.widget.set_min_children_per_line(max(1, min(len(items), 6)))
        chips.set = set_items
        return chips

    def module_row(self, item, index, count):
        """One pill: its icon, name and what it is, then ↑ ↓ and a switch."""
        controls = Gtk.Box(spacing=4)
        for glyph, where, ok in (("", "up", index > 0), ("", "down", index < count - 1)):
            b = Gtk.Button(label=glyph)
            b.get_style_context().add_class("dev-pick")
            b.set_can_focus(False)
            b.set_sensitive(ok)
            b.set_tooltip_text("Move it " + ("left / up" if where == "up" else "right / down"))
            b.connect("clicked", lambda _b, n=item["name"], wh=where: self.do("move", n, wh))
            controls.pack_start(b, False, False, 0)
        sw = Gtk.Switch()
        sw.set_active(item["shown"])
        sw.set_state(item["shown"])
        sw.set_sensitive(not item.get("keep") or not item["shown"])
        sw.connect("state-set", lambda _s, state, n=item["name"]: self.toggle(n, state))
        controls.pack_start(sw, False, False, 6)
        sub = item["what"] or item["name"]
        if item.get("keep"):
            sub += f"  ·  stays: {item['keep']}"
        elif not item["shown"]:
            sub = "hidden  ·  " + sub
        grid, _sub = row(item["icon"], item["title"], sub, controls)
        if not item["shown"]:
            grid.set_opacity(0.6)
        return grid

    # -- actions ---------------------------------------------------------------------
    def do(self, *args):
        """Every control: bar-settings.py in the background, then redraw from
        what it reports, with its complaint on top if it failed; and the bar
        restarted a moment after the last change."""
        if self.updating:
            return
        background(lambda: attempt(BAR_SETTINGS, *args), self.done)

    def done(self, error):
        self.error.set_text(f"!  {error}" if error else "")
        self.error.set_visible(bool(error))
        if not error:
            if self.apply_timer:
                GLib.source_remove(self.apply_timer)
            self.apply_timer = GLib.timeout_add(APPLY_AFTER_MS, self.apply_later)
        self.refresh()

    def apply_later(self):
        self.apply_timer = None
        self.apply_now()
        return False

    def apply_now(self, force=False):
        """bar-settings.py apply: restarts the bar only when a file is newer
        than it (bar-restart.sh -- never SIGUSR2); with force (the Restart the
        bar link) `restart`, which always does, since a click on "Restart"
        that does nothing would be a lie. Takes a couple of seconds: the bar
        goes away and comes back, open panels close."""
        if self.apply_timer:
            GLib.source_remove(self.apply_timer)
            self.apply_timer = None
        self.bar_sub.set_text("restarting the bar…")
        background(lambda: attempt(BAR_SETTINGS, "restart" if force else "apply", timeout=60), self.applied)

    def applied(self, error):
        self.error.set_text(f"!  {error}" if error else "")
        self.error.set_visible(bool(error))
        self.refresh()

    def toggle(self, name, state):
        if not self.updating:
            self.do("show" if state else "hide", name)
        return True

    # -- drawing ---------------------------------------------------------------------
    def refresh(self):
        if self.data is None:
            self.bar_sub.set_text("checking…")
        background(lambda: run_json(BAR_SETTINGS, "status", timeout=15), self.show)

    def show(self, data):
        if not data:
            self.bar_sub.set_text("Bar settings did not answer")
            return
        self.data = data
        self.updating = True
        self.bar_sub.set_text(bar_sub(data))
        bar = data.get("bar") or {}
        self.screen.set(screen_choices(data.get("screens") or [], bar.get("output")), bar.get("output"))
        self.screen_sub.set_text(screen_sub(data))
        clear(self.problems)
        for p in data.get("problems") or []:
            lab = dp.label(f"!  {p[0].upper()}{p[1:]}.", "ctl-sub")
            lab.set_line_wrap(True)
            self.problems.pack_start(lab, False, False, 0)

        lists = dict(bar.get("lists") or {})
        lists.update((data.get("toolbox") or {}).get("lists") or {})
        for key, box in self.lists.items():
            clear(box)
            items = lists.get(key)
            if items is None:
                box.pack_start(dp.label("not in the config", "ctl-sub"), False, False, 0)
                continue
            for i, item in enumerate(items):
                box.pack_start(self.module_row(item, i, len(items)), False, False, 0)

        clear(self.intervals)
        for iv in data.get("intervals") or []:
            grid, _sub = row(next((it["icon"] for side in lists.values() for it in side
                                   if it["name"] == iv["module"]), ""),
                             iv["title"], f"every {every(iv['seconds'])} (10 min at least)  ·  right-click to refresh"
                             if iv["module"] == "custom/weather" else
                             f"every {every(iv['seconds'])}  ·  right-click to refresh")
            self.intervals.pack_start(grid, False, False, 0)
            chips = self.make_chips(lambda k, m=iv["module"]: self.do("interval", m, k))
            chips.set(interval_choices(iv["choices"], iv["seconds"]), str(iv["seconds"]))
            self.intervals.pack_start(chips.widget, False, False, 0)
        self.widget.show_all()
        self.error.set_visible(bool(self.error.get_text()))
        self.updating = False
