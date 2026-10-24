"""Settings page: workspace sessions (sessions.py) and the closed-window
stack (closed-windows.py).

The saved sessions, newest first, each with how many windows, when, and
which apps, and Restore / Delete (Delete asks by turning into "Delete?"
for a few seconds); the last session from before this login ("where was
I"), with Restore; a box to save the windows open now under a name; and
three switches: the automatic save every few minutes, the offer to restore
after login, and whether Steam and games count.

Nothing is kept here: every control runs sessions.py (save, restore,
delete, set KEY on|off), which writes $XDG_STATE_HOME/hypr/sessions/, and
the page redraws from `sessions.py status`. A restore starts apps, so it
is spawned, never waited for. The key (ALT+SHIFT+T reopens the last
closed window) is in lua/binds.lua.
"""
from gi.repository import GLib, Gtk  # noqa: F401

from .common import *  # noqa: F401,F403  (the shared helpers and paths)

import os  # noqa: E402
import time  # noqa: E402

PAGE = {"id": "sessions", "title": "Workspaces", "icon": "", "group": "Apps", "order": 15, "tab": "Sessions",
        "keywords": ["session", "sesion", "restore windows", "save windows", "where was i", "last session",
                     "pick up where you left off", "reopen", "closed window", "undo close", "layout",
                     "workspaces", "autosave", "after login", "reboot", "logout"]}

SESSIONS = os.path.join(HYPR, "sessions.py")
CLOSED = os.path.join(HYPR, "closed-windows.py")
SWITCHES = [("autosave", "\uf0c7", "Save the open windows every few minutes",
             "and at logout; what \"where was I\" brings back"),
            ("offer", "\uf0f3", "Offer to restore after login",
             "a notification with a Restore button; never automatic"),
            ("games", "\uf11b", "Include Steam and games",
             "in saved sessions and the closed-window list")]


# -- pure helpers (tests/test_sessions.py) ------------------------------------------------
def saved_text(epoch, now=None):
    """"today 14:05", "yesterday 23:10", "Mon 13 Oct 09:00"."""
    now = time.localtime(now if now is not None else time.time())
    then = time.localtime(epoch)
    days = (now.tm_yday - then.tm_yday) % 366 if now.tm_year - then.tm_year <= 1 else 999
    day = "today" if days == 0 else "yesterday" if days == 1 else time.strftime("%a %d %b", then)
    return f"{day} {time.strftime('%H:%M', then)}"


def session_sub(s, now=None):
    count = s.get("windows", 0)
    return f"{count} window{'s' * (count != 1)}  ·  {saved_text(s.get('saved', 0), now)}  ·  {s.get('apps', '')}"


class Page:
    def __init__(self):
        self.widget = page_box()
        w = self.widget
        w.pack_start(heading("SAVE"), False, False, 0)
        box = Gtk.Box(spacing=8)
        self.name = Gtk.Entry()
        self.name.set_placeholder_text("a name: work, study, evening...")
        self.name.set_hexpand(True)
        self.name.connect("activate", lambda _e: self.save())
        box.pack_start(self.name, True, True, 0)
        box.pack_start(link("Save the open windows", self.save), False, False, 0)
        w.pack_start(box, False, False, 0)
        self.save_sub = dp.label("Apps, workspaces and positions. Same name replaces.", "ctl-sub")
        self.save_sub.set_line_wrap(True)
        w.pack_start(self.save_sub, False, False, 0)
        w.pack_start(sep(), False, False, 0)
        w.pack_start(heading("SESSIONS"), False, False, 0)
        self.rows = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        w.pack_start(self.rows, False, False, 0)
        w.pack_start(sep(), False, False, 0)
        w.pack_start(heading("AUTOMATIC"), False, False, 0)
        self.switches = {}
        for key, icon, title, sub in SWITCHES:
            sw = Gtk.Switch()
            sw.connect("state-set", lambda _s, state, k=key: self.toggle(k, state))
            grid, _ = row(icon, title, sub, sw)
            self.switches[key] = sw
            w.pack_start(grid, False, False, 0)
        w.pack_start(sep(), False, False, 0)
        w.pack_start(heading("CLOSED WINDOWS"), False, False, 0)
        w.pack_start(dp.label("ALT+SHIFT+T reopens the last closed window (up to 20).", "ctl-sub"),
                     False, False, 0)
        w.pack_start(links_row(link("Reopen the last closed window", lambda: spawn(CLOSED, "reopen"))),
                     False, False, 0)
        self.updating = False
        self.armed = None       # the session whose Delete was clicked once

    def save(self):
        name = self.name.get_text().strip()
        if not name or name.startswith(("_", ".")) or "/" in name or len(name) > 40:
            self.save_sub.set_text("a name is 1-40 characters, no \"/\", not starting with _ or .")
            return
        self.save_sub.set_text("saving...")
        background(lambda: run(SESSIONS, "save", name, timeout=20),
                   lambda out: (self.save_sub.set_text(out.strip() or "could not save: is Hyprland running?"),
                                self.name.set_text(""), self.refresh()))

    def restore(self, name):
        spawn(SESSIONS, "restore", name)

    def delete(self, name, button):
        if self.armed != name:
            self.armed = name
            button.set_label("Delete?")
            GLib.timeout_add(3000, lambda: (self.disarm(name, button), False)[1])
            return
        self.armed = None
        run(SESSIONS, "delete", name)
        self.refresh()

    def disarm(self, name, button):
        if self.armed == name:
            self.armed = None
            button.set_label("Delete")

    def toggle(self, key, state):
        if not self.updating:
            run(SESSIONS, "set", key, "on" if state else "off")
        return False        # let the switch move

    def refresh(self):
        background(lambda: run_json(SESSIONS, "status") or {}, self.draw)

    def draw(self, data):
        self.updating = True
        for key, sw in self.switches.items():
            sw.set_active(bool((data.get("settings") or {}).get(key)))
        clear(self.rows)
        last = data.get("last")
        if last:
            grid, _ = row("", "Where was I", "before this login: " + session_sub(last),
                          links_row(link("Restore", lambda: spawn(SESSIONS, "where-was-i"))))
            self.rows.pack_start(grid, False, False, 0)
        for s in data.get("sessions") or []:
            delete = Gtk.Button(label="Delete")
            delete.get_style_context().add_class("ctl-link")
            delete.connect("clicked", lambda b, n=s["name"]: self.delete(n, b))
            grid, _ = row("", s["name"], session_sub(s),
                          links_row(link("Restore", lambda n=s["name"]: self.restore(n)), delete))
            self.rows.pack_start(grid, False, False, 0)
        if not last and not data.get("sessions"):
            self.rows.pack_start(dp.label("Nothing saved yet.", "ctl-sub"), False, False, 0)
        self.widget.show_all()
        self.updating = False
