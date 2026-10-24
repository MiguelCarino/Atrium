"""Settings page: smart window layout (smartlayout.py) -- where each app
usually goes, learned from where you put it, and whether new windows are
put there.

    MODE         Off / Learn only / Learn and place, how many times before a
                 placement is used, and whether a placed window takes you to
                 its workspace
    LEARNED      one row per app: its usual place with how sure (times, %,
                 times you undid it), Lock / Unlock, Forget, and Edit -- the
                 places seen for it as chips; picking one locks it
    PAIRINGS     apps you keep side by side, with "arrange as usual" (the key)
                 and Forget

Nothing is kept here: every control runs smartlayout.py (set, lock, unlock,
forget, forget-pair), which writes $XDG_STATE_HOME/hypr/smartlayout.json,
and the page redraws from `smartlayout.py status --json`. The service
(smartlayout.service) reads the change on its next look.
"""
from .common import *  # noqa: F401,F403  (the shared helpers and paths; Gtk 3)

from gi.repository import GLib, Gtk  # noqa: E402,F401

import os  # noqa: E402

PAGE = {"id": "layout", "title": "Window layout", "icon": "", "group": "Look", "order": 16, "parent": "windows", "tab": "Layout",
        "keywords": ["smart layout", "window placement", "remember where windows go", "auto place",
                     "learn", "arrange", "side by side", "pairs", "workspace per app", "app workspace",
                     "colocar ventanas", "diseño de ventanas"]}

SMARTLAYOUT = os.path.join(HYPR, "smartlayout.py")
MODES = [("off", "Off"), ("learn", "Learn only"), ("on", "Learn and place")]
MODE_TEXT = {
    "off": "Off  ·  what was learned is kept",
    "learn": "Learning where you put apps; nothing is moved yet",
    "on": "New windows go to their usual place ({n}+ times, {conf} %)",
}
EVIDENCE = [("2", "2"), ("3", "3"), ("5", "5"), ("8", "8"), ("12", "12")]
ICON_GRID, ICON_LOCK, ICON_PAIR, ICON_EYE = "", "", "", ""


# -- pure helpers (tests/test_settings_layout.py) ------------------------------------------
def app_sub(app, evidence):
    """"workspace 5 (DP-1) · left side  ·  7 times, 88 %  ·  undone once  ·  used when it opens"."""
    best = app["places"][0]
    parts = [best["words"], f"{best['count']} time{'s' * (best['count'] != 1)}, "
                            f"{round(best['confidence'] * 100)} %"]
    if best.get("against"):
        parts.append("undone " + ("once" if best["against"] == 1 else f"{best['against']} times"))
    if app.get("locked"):
        locked = next((p for p in app["places"] if p["key"] == app["locked"]), None)
        parts = [f"locked: {locked['words'] if locked else app['locked']}"]
    elif app.get("applies"):
        parts.append("used when it opens")
    else:
        need = max(0, evidence - best["count"])
        parts.append(f"{need} more to go" if need else "not sure enough yet")
    return "  ·  ".join(parts)


def pair_sub(pair):
    sides = pair.get("sides") or {}
    where = ", ".join(f"{cls} {side}" for cls, side in sides.items())
    times = f"{pair['count']} time{'s' * (pair['count'] != 1)}"
    return f"{where}  ·  {times}" + ("" if pair.get("ready") else "  ·  not used yet")


class Page:
    def __init__(self):
        self.widget = page_box()
        w = self.widget
        self.updating = False
        self.armed = None
        self.editing = None         # the app whose places are shown as chips
        self.evidence_n = 3

        w.pack_start(heading("MODE"), False, False, 0)
        grid, self.mode_sub = row(ICON_GRID, "Put windows where you usually put them", "")
        w.pack_start(grid, False, False, 0)
        self.mode = Chips(lambda key: self.run("set", "mode", key))
        w.pack_start(self.mode.widget, False, False, 0)
        grid, _ = row(ICON_EYE, "Times before a place is used",
                      "Windows that stayed there 30 s or more")
        w.pack_start(grid, False, False, 0)
        self.evidence = Chips(lambda key: self.run("set", "evidence", key))
        w.pack_start(self.evidence.widget, False, False, 0)
        self.follow = Gtk.Switch()
        self.follow.connect("state-set", lambda _s, state: self.toggle_follow(state))
        grid, _ = row("", "Go along with a window it moves",
                      "Switch to the workspace an app was placed on",
                      self.follow)
        w.pack_start(grid, False, False, 0)
        w.pack_start(sep(), False, False, 0)

        w.pack_start(heading("LEARNED"), False, False, 0)
        self.rows = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        w.pack_start(self.rows, False, False, 0)
        w.pack_start(sep(), False, False, 0)

        w.pack_start(heading("SIDE BY SIDE"), False, False, 0)
        note = dp.label("Apps you keep together. SUPER+CTRL+R arranges them as usual.", "ctl-sub")
        note.set_line_wrap(True)
        note.set_max_width_chars(90)
        w.pack_start(note, False, False, 0)
        self.pairs = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        w.pack_start(self.pairs, False, False, 0)
        w.pack_start(sep(), False, False, 0)
        privacy = dp.label("Only app names (window classes) and places are kept, never titles, on this computer. "
                           "Dialogs, scratchpads, games, KeePassXC, private browser windows and the apps made "
                           "private in Settings > Privacy are never learned.", "ctl-sub")
        privacy.set_line_wrap(True)
        privacy.set_max_width_chars(90)
        how = dp.label("SUPER+CTRL+R brings an app's partner over if it is open and puts the two on their usual "
                       "sides; nothing is ever started for you. A placed window you move right away counts "
                       "against its place.", "ctl-sub")
        how.set_line_wrap(True)
        how.set_max_width_chars(90)
        w.pack_start(details(privacy, how, label="Privacy and details"), False, False, 0)
        self.forget_all = Gtk.Box(spacing=6)
        self.forget_all.set_halign(Gtk.Align.END)
        w.pack_start(self.forget_all, False, False, 0)
        self.msg = dp.label("", "ctl-sub")
        w.pack_start(self.msg, False, False, 0)

    # -- doing ----------------------------------------------------------------------------
    def run(self, *args):
        if self.updating:
            return
        background(lambda: run(SMARTLAYOUT, *args), lambda _r: self.refresh())

    def toggle_follow(self, state):
        if not self.updating:
            self.run("set", "follow", "on" if state else "off")
        return False

    def forget(self, cls, button):
        if self.armed != cls:
            self.armed = cls
            button.set_label("Forget?")
            GLib.timeout_add(3000, lambda: (self.disarm(cls, button, "Forget"), False)[1])
            return
        self.armed = None
        self.run("forget", cls)

    def disarm(self, key, button, text):
        if self.armed == key:
            self.armed = None
            button.set_label(text)

    def edit(self, cls):
        self.editing = None if self.editing == cls else cls
        self.refresh()

    def refresh(self):
        background(lambda: run_json(SMARTLAYOUT, "status", "--json") or {}, self.draw)

    # -- drawing --------------------------------------------------------------------------
    def draw(self, data):
        if not data:
            self.msg.set_text("Smart layout did not answer")
            return
        self.updating = True
        s = data["settings"]
        self.evidence_n = s["evidence"]
        self.mode.set(MODES, s["mode"])
        self.mode_sub.set_text(MODE_TEXT[s["mode"]].format(stay=data.get("min_stay_s", 30), n=s["evidence"],
                                                           conf=round(data.get("min_conf", 0.6) * 100)))
        items = EVIDENCE if str(s["evidence"]) in dict(EVIDENCE) else EVIDENCE + [(str(s["evidence"]),
                                                                                   str(s["evidence"]))]
        self.evidence.set(items, str(s["evidence"]))
        self.follow.set_active(s.get("follow") == "on")
        clear(self.rows)
        for app in data.get("apps") or []:
            self.rows.pack_start(self.app_row(app, s["evidence"]), False, False, 0)
        if not data.get("apps"):
            self.rows.pack_start(dp.label("Nothing learned yet  ·  use your apps as usual", "ctl-sub"), False, False, 0)
        clear(self.pairs)
        for pair in data.get("pairs") or []:
            grid, _ = row(ICON_PAIR, f"{pair['a']} + {pair['b']}", pair_sub(pair),
                          links_row(link("Forget", lambda p=pair: self.run("forget-pair", p["a"], p["b"]))))
            self.pairs.pack_start(grid, False, False, 0)
        if not data.get("pairs"):
            self.pairs.pack_start(dp.label("No pairings yet.", "ctl-sub"), False, False, 0)
        clear(self.forget_all)
        if data.get("apps") or data.get("pairs"):
            b = Gtk.Button(label="Forget everything")
            b.get_style_context().add_class("ctl-link")
            b.connect("clicked", lambda btn: self.forget("all", btn))
            self.forget_all.pack_start(b, False, False, 0)
        self.msg.set_text("")
        self.widget.show_all()
        self.updating = False

    def app_row(self, app, evidence):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        cls = app["class"]
        forget = Gtk.Button(label="Forget")
        forget.get_style_context().add_class("ctl-link")
        forget.connect("clicked", lambda b: self.forget(cls, b))
        lock = link("Unlock" if app.get("locked") else "Lock",
                    lambda: self.run("unlock" if app.get("locked") else "lock", cls))
        grid, _ = row(ICON_LOCK if app.get("locked") else ICON_GRID, cls, app_sub(app, evidence),
                      links_row(lock, link("Done" if self.editing == cls else "Edit", lambda: self.edit(cls)),
                                forget))
        box.pack_start(grid, False, False, 0)
        if self.editing == cls:
            chips = Chips(lambda key: (setattr(self, "editing", None), self.run("lock", cls, key)))
            chips.set([(p["key"], f"{p['words']} ({p['count']})") for p in app["places"]],
                      app.get("locked") or "")
            box.pack_start(dp.label("Pick the place to keep it on (that locks it):", "ctl-sub"), False, False, 0)
            box.pack_start(chips.widget, False, False, 0)
        return box
