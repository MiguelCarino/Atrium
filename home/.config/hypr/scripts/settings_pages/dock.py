"""Settings page: the dock and the taskbar -- one engine, two layouts
(dock.py; its docstring has the rest). A tab of Bar & toolbox.

    DOCK & TASKBAR  None, Dock or Taskbar: off (dock.service stopped), a
                    floating dock, or a Windows-style taskbar along the
                    bottom; one screen or every screen, the window previews
                    on hover; the top bar on or off (off: only while one of
                    them is on -- dock.py, TOP BAR OFF); whether a theme's
                    layout is followed (dock.py, THEME LAYOUT)
    DOCK            its edge (bottom, left, right), when it hides (never,
                    when a window covers it, always), the icon size,
                    magnification (as the theme says, on, off)
    TASKBAR         one button per app or per window, the titles, the tray,
                    the clock, the weather, the network, the sound, the
                    workspaces, the notifications, the battery (each leaves
                    the top bar while it is here); what the start button
                    opens: the app launcher or a classic start menu
                    (the privacy indicators' switch is above: the dock shows
                    them too, with the top bar off)
    PINNED          the pinned apps in order: up, down, remove (pin more
                    from the dock itself: right-click a running app)
    Details         the state file, the service, the journal

Nothing is kept here: every control runs `dock.py set KEY VALUE` (None is
`set off`, which stops and disables dock.service; Dock and Taskbar set the
layout, then `set on` when it was off),
`dock.py move ID -1|+1` or `dock.py unpin ID`, and the page redraws from
`dock.py status --json`.
"""
import os

from .common import *  # noqa: F401,F403  (the shared helpers and paths)
from gi.repository import Gtk  # noqa: E402  (after common: it picks GTK 3)

PAGE = {"id": "dock", "title": "Dock & taskbar", "icon": "", "group": "Look", "order": 76,
        "parent": "bar", "tab": "Dock & taskbar",
        "keywords": ["dock", "taskbar", "task bar", "barra de tareas", "start button", "start menu",
                     "pinned apps", "pin app", "running apps", "autohide", "auto hide", "system tray",
                     "tray icons", "window previews", "thumbnails", "launcher bar", "magnification",
                     "magnify icons", "top bar", "hide top bar", "no top bar", "remove top bar",
                     "without the bar", "disable top bar", "top bar off", "turn off top bar",
                     "workspaces on the taskbar", "battery on the taskbar"]}

DOCK = os.path.join(HYPR, "dock.py")  # noqa: F405  (HYPR: common)
MODES = [("none", "None"), ("dock", "Dock"), ("taskbar", "Taskbar")]
POSITIONS = [("bottom", "Bottom"), ("left", "Left"), ("right", "Right")]
HIDES = [("never", "Never"), ("overlap", "When a window covers it"), ("always", "Always")]
SIZES = [32, 40, 48, 56, 64, 80]
MAGNIFIES = [("theme", "As the theme says"), ("on", "On"), ("off", "Off")]
SCREENS = [("main", "Main screen"), ("all", "Every screen")]
TASKBAR = [("combine", "", "One button per app",
            "off: a button for every window"),
           ("labels", "", "Window titles",
            "beside the icons"),
           ("tray", "", "System tray",
            "the apps' tray icons at the right (the toolbox keeps its own)"),
           ("clock", "", "Clock",
            "the time and the date, as Date, time & region writes them"),
           ("weather", "", "Weather",
            "the temperature; click: the forecast"),
           ("network", "", "Network",
            "the connection; click: the network panel"),
           ("sound", "", "Sound",
            "the volume; click: the audio panel, scroll: louder or quieter, right-click: mute"),
           ("workspaces", "\uf24d", "Workspaces",
            "the one in front, after the start button; click: every window (Super+D)"),
           ("notifications", "\uf0f3", "Notifications",
            "the bell, right of the clock; click: the notifications, right-click: Do Not Disturb"),
           ("battery", "\uf240", "Battery",
            "the charge, while there is a battery")]
START_MENUS = [("launcher", "App launcher"), ("classic", "Classic menu")]


# -- words (pure; tests/test_settings_dock.py) ----------------------------------------------------
def size_choices(current):
    """The icon-size chips, and the chosen size when it is none of them."""
    sizes = list(SIZES)
    if isinstance(current, int) and current not in sizes:
        sizes = sorted(sizes + [current])
    return [(str(n), f"{n} px") for n in sizes]


def mode_of(conf):
    """The lit chip: "none" while it is off, else the layout."""
    if not conf.get("enabled"):
        return "none"
    return "taskbar" if conf.get("layout") == "taskbar" else "dock"


def mode_commands(mode, conf):
    """What picking a chip runs, in order: None switches it off; Dock or
    Taskbar sets the layout first, then switches it on if it was off (so
    it starts once, already in the right layout). Nothing when the chip is
    the one already lit."""
    if mode == mode_of(conf):
        return []
    if mode == "none":
        return [("set", "off")]
    out = [] if conf.get("layout") == mode else [("set", "layout", mode)]
    return out + ([] if conf.get("enabled") else [("set", "on")])


def now_text(st):
    """The line under the None / Dock / Taskbar chips' title."""
    conf = st.get("settings") or {}
    if not conf.get("enabled"):
        return "Off"
    if st.get("service") != "active":
        return "On but not running: systemctl --user status dock"
    what = "a taskbar" if conf.get("layout") == "taskbar" else "a dock"
    where = "on every screen" if conf.get("monitors") == "all" else "on the main screen"
    return f"On: {what}, {where}" + ("; no top bar" if conf.get("top_bar") is False else "")


def pinned_rows(st):
    """[(id, caption, is_first, is_last)] for the pinned list."""
    apps = st.get("pinned_apps") or []
    out = []
    for i, app in enumerate(apps):
        name = app.get("name") or app.get("id")
        caption = name if app.get("installed", True) else f"{name}  (not installed)"
        out.append((app["id"], caption, i == 0, i == len(apps) - 1))
    return out


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

        # -- dock & taskbar -----------------------------------------------------------------------
        w.pack_start(heading("DOCK & TASKBAR"), False, False, 0)  # noqa: F405
        grid, self.now = row("", "Dock or taskbar",  # noqa: F405
                             "Your pinned and running apps along the edge of the screen.")
        w.pack_start(grid, False, False, 0)
        self.mode = Chips(self.pick_mode)  # noqa: F405
        w.pack_start(self.mode.widget, False, False, 0)
        self.not_running, _sub = row("", "Not running", "It is on, but the service has stopped.",  # noqa: F405
                                     link("Start it", lambda: self.change(DOCK, "set", "on")))  # noqa: F405
        self.not_running.set_no_show_all(True)
        w.pack_start(self.not_running, False, False, 0)
        w.pack_start(dp.label("Screen", "ctl-sub"), False, False, 0)  # noqa: F405
        self.screens = Chips(lambda k: self.change(DOCK, "set", "monitors", k))  # noqa: F405
        w.pack_start(self.screens.widget, False, False, 0)
        grid, _sub = self.switch_row("previews", "", "Window previews",
                                     "hover a running app for its windows, with pictures")
        w.pack_start(grid, False, False, 0)
        self.top_bar, _sub = self.switch_row("top_bar", "\uf2d0", "Top bar",
                                             "off: no bar at the top. The taskbar keeps what it shows; "
                                             "the rest is in the toolbox, with a Microphone row (mute, "
                                             "level). Back by itself if the dock or taskbar stops")
        w.pack_start(self.top_bar, False, False, 0)
        self.privacy, _sub = self.switch_row("privacy", "\uf3ed", "Privacy indicators",
                                             "what records the screen or uses the microphone, the camera "
                                             "or the location, only while something does: on the taskbar, "
                                             "or on the dock with the top bar off")
        w.pack_start(self.privacy, False, False, 0)
        grid, _sub = self.switch_row("follow_theme", "\uf53f", "Follow the theme",
                                     "a theme that says how it looks best sets the dock, the taskbar "
                                     "and the top bar: Windows 95 and Luna the taskbar without a top "
                                     "bar, Orchard the dock. Leaving it puts yours back")
        w.pack_start(grid, False, False, 0)

        # -- dock ---------------------------------------------------------------------------------
        w.pack_start(sep(), False, False, 0)  # noqa: F405
        self.dock_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.dock_box.pack_start(heading("DOCK"), False, False, 0)  # noqa: F405
        self.dock_box.pack_start(dp.label("Edge", "ctl-sub"), False, False, 0)  # noqa: F405
        self.position = Chips(lambda k: self.change(DOCK, "set", "position", k))  # noqa: F405
        self.dock_box.pack_start(self.position.widget, False, False, 0)
        self.dock_box.pack_start(dp.label("Hide", "ctl-sub"), False, False, 0)  # noqa: F405
        self.autohide = Chips(lambda k: self.change(DOCK, "set", "autohide", k))  # noqa: F405
        self.dock_box.pack_start(self.autohide.widget, False, False, 0)
        self.dock_box.pack_start(dp.label("Icon size", "ctl-sub"), False, False, 0)  # noqa: F405
        self.size = Chips(lambda k: self.change(DOCK, "set", "icon_size", k))  # noqa: F405
        self.dock_box.pack_start(self.size.widget, False, False, 0)
        self.dock_box.pack_start(dp.label("Magnification", "ctl-sub"), False, False, 0)  # noqa: F405
        self.magnify = Chips(lambda k: self.change(DOCK, "set", "magnify", k))  # noqa: F405
        self.dock_box.pack_start(self.magnify.widget, False, False, 0)
        self.dock_box.pack_start(wrapped("Hidden, it waits at the edge: touch the edge with the pointer "
                                         "to bring it back. Magnification grows the icons under the "
                                         "pointer (the Orchard themes turn it on); with Reduce motion "
                                         "nothing moves."), False, False, 0)
        w.pack_start(self.dock_box, False, False, 0)

        # -- taskbar ------------------------------------------------------------------------------
        self.task_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.task_box.pack_start(heading("TASKBAR"), False, False, 0)  # noqa: F405
        for key, icon, title, sub in TASKBAR:
            grid, _sub = self.switch_row(key, icon, title, sub)
            self.task_box.pack_start(grid, False, False, 0)
        self.task_box.pack_start(dp.label("Start button", "ctl-sub"), False, False, 0)  # noqa: F405
        self.start_menu = Chips(lambda k: self.change(DOCK, "set", "start_menu", k))  # noqa: F405
        self.task_box.pack_start(self.start_menu.widget, False, False, 0)
        self.task_box.pack_start(wrapped("The app launcher searches everything; the classic menu lists "
                                         "your apps by category. Both have the power menu (lock, sleep, "
                                         "restart, power off). What the taskbar shows leaves the top bar: "
                                         "the clock, weather, network, sound, workspaces, notifications, "
                                         "battery, the privacy indicators and the power button move down "
                                         "here, and the top bar restarts to match. With the dock or the "
                                         "taskbar, the keyboard layout is in the toolbox."), False, False, 0)
        w.pack_start(self.task_box, False, False, 0)

        # -- pinned -------------------------------------------------------------------------------
        w.pack_start(sep(), False, False, 0)  # noqa: F405
        w.pack_start(heading("PINNED"), False, False, 0)  # noqa: F405
        self.pinned = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        w.pack_start(self.pinned, False, False, 0)
        w.pack_start(wrapped("Right-click a running app in the dock to pin it; drag pinned apps to "
                             "reorder them there too."), False, False, 0)
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

    def pinned_row(self, app_id, caption, first, last):
        box = links_row(  # noqa: F405
            link("", lambda: self.change(DOCK, "move", app_id, "-1")),  # noqa: F405
            link("", lambda: self.change(DOCK, "move", app_id, "+1")),  # noqa: F405
            link("Remove", lambda: self.change(DOCK, "unpin", app_id)))  # noqa: F405
        up, down, _remove = box.get_children()
        up.set_sensitive(not first)
        down.set_sensitive(not last)
        up.set_tooltip_text("Move up (left in the dock)")
        down.set_tooltip_text("Move down (right in the dock)")
        grid, _sub = row("", caption, "", box)  # noqa: F405
        return grid

    # -- changing things --------------------------------------------------------------------------
    def flip(self, key, on):
        if self.updating:
            return True
        return self.change(DOCK, "set", key, "on" if on else "off")

    def pick_mode(self, mode):
        if self.updating or not self.data:
            return True
        cmds = mode_commands(mode, self.data.get("settings") or {})
        return self.change_all([(DOCK, *c) for c in cmds]) if cmds else True

    def change_all(self, cmds, timeout=30):
        """Several dock.py calls, one after the other, in one background job;
        the first that fails stops the rest."""
        if self.updating:
            return True

        def run():
            for cmd in cmds:
                ok, why = call(*cmd, timeout=timeout)
                if not ok:
                    return ok, why
            return True, ""
        background(run, self.changed)  # noqa: F405
        return True

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
        background(lambda: run_json(DOCK, "status", "--json", timeout=30), self.show)  # noqa: F405

    def show(self, st):
        if not st:
            self.problem.set_text("Could not read the dock's status")
            self.problem.set_tooltip_text(f"Try it in a terminal: {DOCK} status")
            self.problem.set_visible(True)
            self.widget.show_all()
            return
        self.data = st
        conf = st["settings"]
        self.updating = True
        try:
            for key, sw in self.switches.items():
                put(sw, bool(conf.get(key)))
            self.mode.set(MODES, mode_of(conf))
            self.screens.set(SCREENS, conf.get("monitors") or "main")
            self.position.set(POSITIONS, conf.get("position") or "bottom")
            self.autohide.set(HIDES, conf.get("autohide") or "never")
            self.size.set(size_choices(conf.get("icon_size")), str(conf.get("icon_size") or 48))
            self.magnify.set(MAGNIFIES, conf.get("magnify") or "theme")
            self.start_menu.set(START_MENUS, conf.get("start_menu") or "launcher")
        finally:
            self.updating = False
        mode = mode_of(conf)
        self.top_bar.set_sensitive(mode != "none")
        self.privacy.set_sensitive(mode == "taskbar" or (mode == "dock" and conf.get("top_bar") is False))
        self.dock_box.set_sensitive(mode == "dock")
        self.task_box.set_sensitive(mode == "taskbar")
        clear(self.pinned)  # noqa: F405
        rows = pinned_rows(st)
        for app_id, caption, first, last in rows:
            self.pinned.pack_start(self.pinned_row(app_id, caption, first, last), False, False, 0)
        if not rows:
            self.pinned.pack_start(wrapped("Nothing pinned yet." if conf.get("pinned") is not None else
                                           "Chosen on the first start: your browser, files and terminal."),
                                   False, False, 0)
        self.now.set_text(now_text(st))
        stopped = bool(conf.get("enabled")) and st.get("service") != "active"
        self.not_running.set_visible(stopped)
        if stopped:
            self.not_running.show_all()
        self.more_words.set_text(
            f"Settings: {st.get('file') or '~/.local/state/hypr/dock.json'}\n"
            "systemctl --user status dock.service\n"
            "journalctl --user -u dock -f\n"
            "The look: ~/.config/hypr/scripts/dock.css and the theme's dock.css.\n"
            "Right-click an app in the dock, then Dock settings, to come back here.")
        self.widget.show_all()
