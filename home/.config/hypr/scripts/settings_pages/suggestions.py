"""Settings page: Live suggestions (suggest.py) -- the quiet strip that
offers the next step for what you are doing.

    LIVE SUGGESTIONS   the switch (suggest.service), what it is doing now,
                       Pause for an hour / Resume, Show a sample; the
                       quiet rules (folded)
    KINDS              each kind on / off, with what you did with it so far
                       (used of shown) and when a dismissed kind comes
                       back; Forget what it learned; how it learns (folded)
    WHERE AND HOW OFTEN  the corner, at most one every N minutes, how long a
                       card stays
    TIMING             what counts as away (resume), how old changes are
                       before a commit is suggested, how early a meeting is

Everything goes through `suggest.py get --json` / `set ...` / `snooze` /
`sample` / `forget`; the page keeps nothing of its own.
"""
import datetime
import os
import subprocess

from gi.repository import GLib, Gtk  # noqa: F401

from .common import *  # noqa: F401,F403  (the shared helpers and paths)

PAGE = {"id": "suggestions", "title": "Live suggestions", "icon": "\uf0eb", "group": "Apps", "order": 38, "parent": "ai", "tab": "Suggestions",
        "keywords": ["suggestions", "next step", "hints", "commit message", "git commit", "pick up where you left off",
                     "welcome back", "strip", "sugerencias", "proactive", "meeting soon", "focus round",
                     "smart clipboard strip", "dismiss", "snooze suggestions"]}

SUGGEST = os.path.join(HYPR, "suggest.py")
SETTINGS = os.path.join(HYPR, "settings.py")
ICONS = {"commit": "\uf386", "resume": "\uf2ea", "clipboard": "\uf328", "context": "\uf542", "meeting": "\uf073",
         "focus": "\uf140"}
POSITION_TEXT = {"top-left": "Top left", "top-center": "Top", "top-right": "Top right",
                 "bottom-left": "Bottom left", "bottom-center": "Bottom", "bottom-right": "Bottom right"}
QUIET = ("Never during a fullscreen window, a game (gamemode), Do Not Disturb, screen sharing or a locked "
         "screen, and never more than one at a time. Everything stays on this computer: nothing is sent "
         "anywhere, and the local model only runs when you click \"Draft a commit message\". Private windows "
         "(the Privacy page's list, password managers, private browsing) are never looked into.")
WHAT = {"commit": "Changes sat a while: draft the message (never commits)",
        "resume": "After a lock or sleep: back to the window you had",
        "clipboard": "Copy actions here instead of their own card",
        "context": "Entering a project context: start a focus round",
        "meeting": "An event starts soon: Do Not Disturb or the calendar",
        "focus": "Lots of switching: start a focus block (needs Focus noticing)"}     # short lines over suggest.py's own
LEARNS = ("It learns from the x: a kind you send away rests for half an hour, then longer each time in a row "
          "(up to a day); using one brings it back to normal. When two wait at once, the kind you use more "
          "goes first. A build failing in the terminal is not offered: COSMIC Terminal has no way to tell.")


def note(text):
    """A wrapped sub-styled paragraph, for the details folds."""
    label = dp.label(text, "ctl-sub")
    label.set_line_wrap(True)
    label.set_xalign(0)
    return label


def kind_sub(k, now=None):
    """The line under a kind: what it does, and what you did with it."""
    now = now or datetime.datetime.now().timestamp()
    parts = [WHAT.get(k["kind"], k["what"])]
    if k["shown"]:
        parts.append(f"used {k['acted']} of {k['shown']}")
    if k.get("resting_until", 0) > now:
        parts.append("resting until " + datetime.datetime.fromtimestamp(k["resting_until"]).strftime("%H:%M"))
    return "  ·  ".join(parts)


def live_text(data, now=None):
    if not data.get("on"):
        sub = "Off"
    else:
        live = data.get("live") or {}
        now = now or datetime.datetime.now().timestamp()
        if live.get("snooze_until", 0) > now:
            sub = "paused until " + datetime.datetime.fromtimestamp(live["snooze_until"]).strftime("%H:%M")
        elif live.get("showing"):
            sub = "On: a card is up now"
        elif live.get("quiet"):
            sub = f"On, quiet now ({live['quiet']})"
        else:
            sub = "On"
    if data.get("on") != data.get("enabled"):
        sub += "  ·  " + ("not started at login" if data.get("on") else "starts again at the next login")
    return sub


class Page:
    def __init__(self):
        self.widget = page_box()
        w = self.widget
        self.updating = False
        self.kind_switches = {}
        self.snoozed = False

        w.pack_start(heading("LIVE SUGGESTIONS"), False, False, 0)
        self.main_switch = self.switch(lambda on: self.act("set", "on" if on else "off"))
        grid, self.main_sub = row("\uf0eb", "Suggest the next step",
                                  "A small strip offers what to do next", self.main_switch)
        w.pack_start(grid, False, False, 0)
        self.snooze_link = link("Pause for an hour", self.toggle_snooze)
        w.pack_start(links_row(self.snooze_link, link("Show a sample", lambda: self.act("sample", "commit"))),
                     False, False, 0)
        grid, _ = row("\uf1f6", "Quiet by design", "Never in fullscreen, games or Do Not Disturb; all local")
        w.pack_start(grid, False, False, 0)
        w.pack_start(details(note(QUIET)), False, False, 0)
        w.pack_start(sep(), False, False, 0)

        w.pack_start(heading("KINDS"), False, False, 0)
        self.kinds_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        w.pack_start(self.kinds_box, False, False, 0)
        w.pack_start(links_row(link("Forget what it learned", lambda: self.act("forget")),
                               link("Open Smart clipboard", lambda: spawn(SETTINGS, "smartclip"))),
                     False, False, 0)
        w.pack_start(details(note(LEARNS), label="How it learns"), False, False, 0)
        w.pack_start(sep(), False, False, 0)

        w.pack_start(heading("WHERE AND HOW OFTEN"), False, False, 0)
        w.pack_start(dp.label("Corner", "ctl-sub"), False, False, 0)
        self.position = Chips(lambda key: self.set("position", key))
        self.position.widget.set_max_children_per_line(3)      # the top row over the bottom one
        self.position.widget.set_min_children_per_line(3)
        w.pack_start(self.position.widget, False, False, 0)
        self.gap = Slider("gap_min", "At most one every", 1, 120, 1, " min", self.set)
        w.pack_start(self.gap.widget, False, False, 0)
        self.show_s = Slider("show_s", "A card stays", 5, 60, 1, " s", self.set)
        w.pack_start(self.show_s.widget, False, False, 0)
        w.pack_start(sep(), False, False, 0)

        w.pack_start(heading("TIMING"), False, False, 0)
        self.away = Slider("away_min", "Welcome back: away at least", 3, 240, 1, " min",
                           self.set)
        w.pack_start(self.away.widget, False, False, 0)
        self.commit_after = Slider("commit_after_min", "Commit message: changes older than", 0, 240, 5,
                                   " min", self.set)
        w.pack_start(self.commit_after.widget, False, False, 0)
        self.lead = Slider("meeting_lead_min", "Meetings: before start", 2, 60, 1, " min", self.set)
        w.pack_start(self.lead.widget, False, False, 0)
        self.msg = dp.label("", "ctl-sub")
        self.msg.set_line_wrap(True)
        w.pack_start(self.msg, False, False, 0)

    def switch(self, on_change):
        sw = Gtk.Switch()
        sw.connect("state-set", lambda _s, state: self.switched(on_change, state))
        return sw

    def switched(self, on_change, state):
        if not self.updating:
            on_change(state)
        return True             # the switch moves when refresh() says the setting did

    def act(self, *args):
        def work():
            try:
                res = subprocess.run([SUGGEST, *args], capture_output=True, text=True, timeout=30)
                return "" if res.returncode == 0 else (res.stderr or res.stdout).strip()
            except (OSError, subprocess.SubprocessError) as exc:
                return str(exc)
        self.msg.set_text("")
        background(work, lambda err: (self.msg.set_text(err), self.refresh()))

    def set(self, key, value):
        if not self.updating:
            self.act("set", key, str(value))

    def toggle_snooze(self):
        self.act("snooze", "off" if self.snoozed else "60")

    def refresh(self):
        background(lambda: run_json(SUGGEST, "get", "--json"), self.show)

    def show(self, data):
        if not data:
            self.msg.set_text("suggest.py did not answer (run it in a terminal to see why)")
            return
        now = datetime.datetime.now().timestamp()
        values = data["values"]
        self.updating = True
        try:
            self.main_switch.set_active(data["on"])
            self.main_switch.set_state(data["on"])
            self.main_sub.set_text(live_text(data, now))
            live = data.get("live") or {}
            self.snoozed = live.get("snooze_until", 0) > now
            self.snooze_link.set_label("Resume now" if self.snoozed else "Pause for an hour")
            self.snooze_link.set_sensitive(bool(data["on"]))
            if not self.kind_switches:
                for k in data["kinds"]:
                    sw = self.switch(lambda on, key=k["kind"]: self.act("set", key, "on" if on else "off"))
                    grid, sub = row(ICONS.get(k["kind"], ""), k["label"], "", sw)
                    self.kind_switches[k["kind"]] = (sw, grid, sub)
                    self.kinds_box.pack_start(grid, False, False, 0)
            for k in data["kinds"]:
                sw, grid, sub = self.kind_switches[k["kind"]]
                sw.set_active(k["on"])
                sw.set_state(k["on"])
                sub.set_text(kind_sub(k, now))
                grid.set_sensitive(data["on"])
            self.position.set([(p, POSITION_TEXT.get(p, p)) for p in data["positions"]], values["position"])
            self.gap.show(int(values["gap_min"]))
            self.show_s.show(int(values["show_s"]))
            self.away.show(int(values["away_min"]))
            self.commit_after.show(int(values["commit_after_min"]))
            self.lead.show(int(values["meeting_lead_min"]))
        finally:
            self.updating = False
        self.widget.show_all()
