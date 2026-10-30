"""Settings page: the dynamic island -- a pill at the top of the screen that
opens when something happens (island.py; its docstring has the rest). A tab
of Bar & toolbox.

    ISLAND     on / off (island.service), its design (notch, floating
               island, theme), black, the theme's colour or glass for the
               notch and the floating island, an outline on any design,
               whether the bar's centre
               capsules take the same look, which screen it is on,
               whether the pill stays in the bar while something goes on
    SHOWS      what it shows: music playing, timers ending, a screen
               recording, Railguard stepping in, and every notification
               ("Show notifications in the island", on: mako's popups give
               way to the island; off: mako pops them up as before, and
               the island can still show a short line for the desktop's
               own)
    Details    the state file, the service, the journal

Nothing is kept here: every control runs `island.py set KEY on|off` or
`island.py set monitor|style|notch_color VALUE` (`set enabled` also enables
and starts, or stops and disables, island.service), and the page redraws from
`island.py status --json`.
"""
import os

from .common import *  # noqa: F401,F403  (the shared helpers and paths)
from gi.repository import Gtk  # noqa: E402  (after common: it picks GTK 3)

PAGE = {"id": "island", "title": "Island", "icon": "\uf111", "group": "Look", "order": 75,
        "parent": "bar", "tab": "Island",
        "keywords": ["dynamic island", "now playing", "media", "mpris", "pill", "timers countdown",
                     "screen recording", "railguard", "isla dinamica", "notch", "island design", "island style",
                     "notch colour", "notch color", "island colour", "glass", "outline", "island border",
                     "notifications in the island"]}

ISLAND = os.path.join(HYPR, "island.py")  # noqa: F405  (HYPR: common)
SOURCES = [("media", "\uf001", "Music and video",
            "what is playing, with play / pause and next"),
           ("timers", "\uf2f2", "Timers",
            "the last minute of a countdown, and Snooze / Stop when one rings"),
           ("record", "\uf03d", "Screen recording",
            "a red dot and the time while it records"),
           ("railguard", "\uf132", "Railguard",
            "when it steps in, with the mascot"),
           ("notifications", "\uf0f3", "Show notifications in the island",
            "every app's, instead of a popup: hover for the rest and the buttons; "
            "Do Not Disturb still holds them back, the bell keeps the history"),
           ("notify", "\uf075", "Desktop notifications, a short line",
            "only with the one above off: mako shows them, the island a line too")]
STYLES = [("notch", "Notch"), ("island", "Floating island"), ("theme", "Theme")]
COLORS = [("black", "Black"), ("theme", "Theme colour"), ("glass", "Glass")]
SOLID = ("notch", "island")            # the designs a colour applies to
FIXED_SCREENS = [("", "Main screen"), ("focused", "Focused screen")]


# -- words (pure; tests/test_settings_island.py) --------------------------------------------------
def screen_choices(st):
    """Chips: the main screen, the focused one, every screen Hyprland knows,
    and the chosen one when it is none of those (unplugged), so the lit chip
    is always the truth."""
    items = list(FIXED_SCREENS) + [(m, m) for m in (st.get("monitors") or [])]
    current = (st.get("settings") or {}).get("monitor") or ""
    if current not in [k for k, _ in items]:
        items.append((current, f"{current}  (not connected)"))
    return items


def now_text(st):
    """The line under the master switch."""
    conf = st.get("settings") or {}
    if not conf.get("enabled"):
        return "Off"
    if st.get("service") != "active":
        return "On but not running: systemctl --user status island"
    monitor = conf.get("monitor") or ""
    if monitor == "focused":
        return "On, following the focused screen"
    return f"On, on {monitor}" if monitor else "On, on the main screen"


def popups_text(st):
    """Where notifications show right now (the Details line)."""
    conf = st.get("settings") or {}
    where = st.get("popups") or ""
    if where == "island":
        return "Notifications: in the island (mako's popups are off)"
    if conf.get("enabled") and conf.get("notifications") and st.get("service") == "active":
        return "Notifications: mako's popups -- the island has not taken them (journalctl --user -u island)"
    return "Notifications: mako's popups"


def call(*cmd, timeout=30):
    import subprocess
    try:
        done = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as err:
        return False, str(err)
    return done.returncode == 0, (done.stdout if done.returncode == 0 else done.stderr or done.stdout).strip()


def put(switch, on):
    switch.set_active(on)
    switch.set_state(on)


def wrapped(text, cls="ctl-sub"):
    lab = dp.label(text, cls)  # noqa: F405
    lab.set_line_wrap(True)
    lab.set_max_width_chars(80)
    lab.set_xalign(0)
    return lab


class Page:
    def __init__(self):
        self.updating = False
        self.data = None
        self.switches = {}
        self.widget = page_box()  # noqa: F405
        w = self.widget
        self.problem = wrapped("")
        self.problem.set_no_show_all(True)
        w.pack_start(self.problem, False, False, 0)

        # -- island -------------------------------------------------------------------------------
        w.pack_start(heading("ISLAND"), False, False, 0)  # noqa: F405
        grid, self.now = self.switch_row("enabled", "\uf111", "Dynamic island",
                                         "A pill at the top that opens when something happens.")
        w.pack_start(grid, False, False, 0)
        self.not_running, _sub = row("\uf071", "Not running", "It is on, but the service has stopped.",  # noqa: F405
                                     link("Start it", lambda: self.change(ISLAND, "set", "on")))  # noqa: F405
        self.not_running.set_no_show_all(True)
        w.pack_start(self.not_running, False, False, 0)
        w.pack_start(dp.label("Design", "ctl-sub"), False, False, 0)  # noqa: F405
        self.style = Chips(lambda k: self.change(ISLAND, "set", "style", k))  # noqa: F405
        w.pack_start(self.style.widget, False, False, 0)
        # Notch and floating island only: the theme's card has its own fill.
        self.color_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.color_box.pack_start(dp.label("Colour", "ctl-sub"), False, False, 0)  # noqa: F405
        self.color = Chips(lambda k: self.change(ISLAND, "set", "notch_color", k))  # noqa: F405
        self.color_box.pack_start(self.color.widget, False, False, 0)
        self.color_box.pack_start(dp.label("Theme colour: the theme's accent, deep enough for "  # noqa: F405
                                           "the white text. Glass: dark and see-through", "ctl-sub"),
                                  False, False, 0)
        w.pack_start(self.color_box, False, False, 0)
        grid, _sub = self.switch_row("outline", "\uf096", "Outline",
                                     "a thin edge in the theme's colour, on any design")
        w.pack_start(grid, False, False, 0)
        grid, _sub = self.switch_row("match_bar", "\uf2d0", "Bar centre matches",
                                     "the clock and its neighbours take the island's look, "
                                     "so it opens out of them")
        w.pack_start(grid, False, False, 0)
        w.pack_start(dp.label("Screen", "ctl-sub"), False, False, 0)  # noqa: F405
        self.screen = Chips(lambda k: self.change(ISLAND, "set", "monitor", k or "auto"))  # noqa: F405
        w.pack_start(self.screen.widget, False, False, 0)
        grid, _sub = self.switch_row("ongoing", "\uf068", "Stay in the bar",
                                     "while music plays or a recording runs (covers the clock)")
        w.pack_start(grid, False, False, 0)

        # -- shows --------------------------------------------------------------------------------
        w.pack_start(sep(), False, False, 0)  # noqa: F405
        w.pack_start(heading("SHOWS"), False, False, 0)  # noqa: F405
        for key, icon, title, sub in SOURCES:
            grid, _sub = self.switch_row(key, icon, title, sub)
            w.pack_start(grid, False, False, 0)
        w.pack_start(wrapped("It hides in full screen and while a game runs."), False, False, 0)

        self.more = details(label="Details")  # noqa: F405
        self.more_words = wrapped("")
        self.more_words.set_selectable(True)
        self.more.box.pack_start(self.more_words, False, False, 0)
        w.pack_start(self.more, False, False, 0)

    # -- building ---------------------------------------------------------------------------------
    def switch_row(self, key, icon, title, sub):
        sw = Gtk.Switch()
        sw.connect("state-set", lambda _s, on, k=key: self.flip(k, on))
        self.switches[key] = sw
        return row(icon, title, sub, sw)  # noqa: F405

    # -- changing things --------------------------------------------------------------------------
    def flip(self, key, on):
        if self.updating:
            return True
        return self.change(ISLAND, "set", key, "on" if on else "off")

    def change(self, *cmd, timeout=30):
        if self.updating:
            return True
        background(lambda: call(*cmd, timeout=timeout), self.changed)  # noqa: F405
        return True

    def changed(self, result):
        ok, why = result
        self.problem.set_text("" if ok else f"Not done: {why}")
        self.problem.set_visible(not ok)
        self.refresh()

    # -- drawing ------------------------------------------------------------------------------------
    def refresh(self):
        background(lambda: run_json(ISLAND, "status", "--json", timeout=30), self.show)  # noqa: F405

    def show(self, st):
        if not st:
            self.problem.set_text("Could not read the island's status")
            self.problem.set_tooltip_text(f"Try it in a terminal: {ISLAND} status")
            self.problem.set_visible(True)
            self.widget.show_all()
            return
        self.data = st
        conf = st["settings"]
        self.updating = True
        try:
            for key, sw in self.switches.items():
                put(sw, bool(conf.get(key)))
            # the short line is for when the island does not take them all
            self.switches["notify"].set_sensitive(not conf.get("notifications"))
            self.screen.set(screen_choices(st), conf.get("monitor") or "")
            self.style.set(STYLES, conf.get("style") or "notch")
            self.color.set(COLORS, conf.get("notch_color") or "black")
        finally:
            self.updating = False
        self.color_box.set_sensitive((conf.get("style") or "notch") in SOLID)
        self.now.set_text(now_text(st))
        stopped = bool(conf.get("enabled")) and st.get("service") != "active"
        self.not_running.set_visible(stopped)
        if stopped:
            self.not_running.show_all()
        self.more_words.set_text(
            popups_text(st) + "\n"
            "Settings: ~/.local/state/hypr/island.json\n"
            "systemctl --user status island.service\n"
            "journalctl --user -u island -f\n"
            "Right-click the island to come back here.")
        self.widget.show_all()
