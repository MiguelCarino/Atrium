"""Settings page: Focus (focus-guard.py) -- notice when you are scattered,
and the focus block that helps: quiet notifications, distractions dimmed or
made to wait, a summary at the end, the minutes counted.

    FOCUS GUARD     the switch (focus-guard.service), what it is doing now,
                    Start a focus block / Stop it, Show the card
    NOTICING        the privacy switch (privacy.conf focus_watch, off as
                    shipped), how sensitive, over how many minutes, how often
                    at most, when (always / work hours / free time), and the
                    live numbers it is looking at
    THE BLOCK       how long (timers.py's focus_min), how quiet (Do Not
                    Disturb / the project context's own filter / nothing),
                    the digest and the "what you did" summary at the end
    DISTRACTIONS    dim / delay / both, how dim, how long the wait; the apps
                    (window classes) and the sites (words in a browser's title)
    BREAKS          the pomodoro rhythm on / off, and its lengths (timers.py's)
    STATS           today and the last seven days

Everything goes through `focus-guard.py get --json` / `set ...` / `apps` /
`sites` / `start` / `stop` / `sample`; the page keeps nothing of its own.
"""
import datetime
import os
import subprocess

from gi.repository import GLib, Gtk  # noqa: F401

from .common import *  # noqa: F401,F403  (the shared helpers and paths)

PAGE = {"id": "focus", "title": "Focus", "icon": "", "group": "Apps", "order": 39,
        "keywords": ["focus guard", "focus block", "pomodoro", "concentration", "concentrarse", "enfoque",
                     "distractions", "distracting apps", "distracting sites", "scattered", "context switching",
                     "dim apps", "delay apps", "still want this", "breaks", "deep work", "focus minutes",
                     "focus stats"]}

GUARD = os.path.join(HYPR, "focus-guard.py")
SETTINGS = os.path.join(HYPR, "settings.py")
SENSITIVITY_TEXT = {"low": "Low (only a real scramble)", "medium": "Medium", "high": "High (sooner)"}
WHEN_TEXT = {"always": "Any time", "work": "Work hours only", "free": "Free time only"}
QUIET_TEXT = {"dnd": "Do Not Disturb", "project": "Project's own filter", "none": "Leave notifications"}
STYLE_TEXT = {"dim": "Dim them", "delay": "Make them wait", "both": "Both"}
QUIET_SUB = {"dnd": "Notifications go quietly to the history (urgent ones still show); the digest at the end "
                    "says what came.",
             "project": "Inside a project context, only notifications that name the project (and the apps it "
                        "allows) pop up -- its own filter (Settings > Project contexts). Outside one: Do Not "
                        "Disturb.",
             "none": "Notifications as usual."}
STYLE_SUB = {"dim": "Their windows go see-through while the block runs. Nothing is closed or blocked.",
             "delay": "A newly opened one waits out of sight behind \"Still want it?\"; Open it unlocks after the "
                      "wait. Not now keeps it there until the block ends. A browser on a listed site gets the "
                      "same question.",
             "both": "Dimmed, and newly opened ones wait behind \"Still want it?\"."}
BARS = " ▁▂▃▄▅▆▇█"


def minutes_text(m):
    m = int(round(m or 0))
    return f"{m // 60} h {m % 60:02d} min" if m >= 60 else f"{m} min"


def live_text(data, now=None):
    """The line under the main switch: off / in a block / noticing / idle."""
    if not data.get("on"):
        sub = "off: no focus blocks of its own (the launcher's \"focus\" is a plain focus round)"
    else:
        live = data.get("live") or {}
        block = live.get("block")
        now = now or datetime.datetime.now().timestamp()
        if block:
            left = max(0, int((block["due"] - now) // 60))
            sub = (f"in a focus block: {left} min left  ·  {block['dimmed']} distracting window"
                   f"{'s' if block['dimmed'] != 1 else ''}" + (f", {block['waiting']} waiting" if block["waiting"]
                                                               else ""))
        elif data.get("watching"):
            sub = "on, noticing" + (f" (quiet now: {live['quiet']})" if live.get("quiet") else "")
        else:
            sub = "on; noticing is off, so it only runs the blocks you start"
    if data.get("on") != data.get("enabled"):
        sub += "  ·  " + ("not started at login" if data.get("on") else "starts again at the next login")
    return sub


def numbers_text(n):
    if not n:
        return ""
    watched = n.get("watching_s", 0) // 60
    mins = n.get("window_s", 1200) // 60
    head = (f"Last {mins} min: {n['switches']} switches between {n['groups']} things "
            f"(it offers a block at {n['need']} switches among {n['need_groups']}+ things; a switch to a "
            "distraction counts twice)")
    if watched < mins:
        head += f"  ·  watching for {watched} min so far"
    return head


def week_lines(week):
    """[(day label, bar, text)] for the stats rows."""
    top = max([r["minutes"] for r in week] + [1])
    out = []
    for r in week:
        day = datetime.date.fromisoformat(r["day"])
        bar = BARS[max(1, min(8, round(8 * r["minutes"] / top)))] if r["minutes"] else "·"
        out.append((day.strftime("%a %d"), bar, f"{minutes_text(r['minutes'])}" +
                    (f" in {int(r['blocks'])} block{'s' if r['blocks'] != 1 else ''}" if r["blocks"] else "")))
    return out


class Page:
    def __init__(self):
        self.widget = page_box()
        w = self.widget
        self.updating = False
        self.data = None

        w.pack_start(heading("FOCUS GUARD"), False, False, 0)
        self.main_switch = self.switch(lambda on: self.act("set", "on" if on else "off"))
        grid, self.main_sub = row("", "Focus blocks with a guard",
                                  "A focus block quiets the notifications, dims the distracting apps (never "
                                  "blocks them) and ends with what you did. The bar's timer counts it down.",
                                  self.main_switch)
        w.pack_start(grid, False, False, 0)
        self.start_link = link("Start a focus block", self.start_stop)
        w.pack_start(links_row(self.start_link, link("Show the \"still want it?\" card",
                                                     lambda: self.act("sample", "app"))), False, False, 0)
        w.pack_start(sep(), False, False, 0)

        w.pack_start(heading("NOTICING"), False, False, 0)
        self.watch_switch = self.switch(lambda on: self.act("set", "detect", "on" if on else "off"))
        grid, self.watch_sub = row("", "Offer a block when I am scattered",
                                   "Follows which window has the focus, on this computer only: each one is "
                                   "reduced at once to its project or app, titles are not kept, private windows "
                                   "are not looked into. Also on the Privacy page.", self.watch_switch)
        w.pack_start(grid, False, False, 0)
        w.pack_start(dp.label("How sensitive", "ctl-sub"), False, False, 0)
        self.sensitivity = Chips(lambda key: self.set("sensitivity", key))
        w.pack_start(self.sensitivity.widget, False, False, 0)
        self.window = Slider("window_min", "Looking at the last", 10, 60, 5, " min", self.set)
        w.pack_start(self.window.widget, False, False, 0)
        self.cooldown = Slider("cooldown_min", "At most one offer every", 15, 480, 15, " min", self.set)
        w.pack_start(self.cooldown.widget, False, False, 0)
        w.pack_start(dp.label("When", "ctl-sub"), False, False, 0)
        self.when = Chips(lambda key: self.set("when", key))
        w.pack_start(self.when.widget, False, False, 0)
        self.numbers = dp.label("", "ctl-sub")
        self.numbers.set_line_wrap(True)
        self.numbers.set_xalign(0)
        w.pack_start(self.numbers, False, False, 0)
        note = dp.label("Unrelated means a different project or app: an editor and a terminal on the same repo are "
                        "one thing, and so is everything of the project context you are in. The offer is a "
                        "notification, or a card in the live suggestions strip when its \"Scattered? A focus "
                        "block\" kind is on there; never during a fullscreen window, a game, Do Not Disturb or a "
                        "block.", "ctl-sub")
        note.set_line_wrap(True)
        note.set_xalign(0)
        w.pack_start(note, False, False, 0)
        w.pack_start(links_row(link("Open Live suggestions", lambda: spawn(SETTINGS, "suggestions")),
                               link("Open Privacy", lambda: spawn(SETTINGS, "privacy"))), False, False, 0)
        w.pack_start(sep(), False, False, 0)

        w.pack_start(heading("THE BLOCK"), False, False, 0)
        self.length = Slider("minutes", "A block lasts", 5, 120, 5, " min", self.set)
        w.pack_start(self.length.widget, False, False, 0)
        w.pack_start(dp.label("Notifications during it", "ctl-sub"), False, False, 0)
        self.quiet = Chips(lambda key: self.set("quiet", key))
        w.pack_start(self.quiet.widget, False, False, 0)
        self.quiet_sub = dp.label("", "ctl-sub")
        self.quiet_sub.set_line_wrap(True)
        self.quiet_sub.set_xalign(0)
        w.pack_start(self.quiet_sub, False, False, 0)
        self.digest_switch = self.switch(lambda on: self.set("digest", "on" if on else "off"))
        grid, _ = row("", "Digest at the end", "What was held back, in one notification (with Do Not "
                      "Disturb this is the Notifications page's own digest).", self.digest_switch)
        w.pack_start(grid, False, False, 0)
        self.summary_switch = self.switch(lambda on: self.set("summary", "on" if on else "off"))
        grid, _ = row("", "\"What you did\" at the end", "Where the time went (from the activity history), "
                      "how much you switched, your commits in the block.", self.summary_switch)
        w.pack_start(grid, False, False, 0)
        w.pack_start(sep(), False, False, 0)

        w.pack_start(heading("DISTRACTIONS"), False, False, 0)
        self.style = Chips(lambda key: self.set("style", key))
        w.pack_start(self.style.widget, False, False, 0)
        self.style_sub = dp.label("", "ctl-sub")
        self.style_sub.set_line_wrap(True)
        self.style_sub.set_xalign(0)
        w.pack_start(self.style_sub, False, False, 0)
        self.dim = Slider("dim_pct", "Dimmed windows show at", 20, 90, 5, " %", self.set)
        w.pack_start(self.dim.widget, False, False, 0)
        self.delay = Slider("delay_s", "\"Open it\" unlocks after", 3, 30, 1, " s", self.set)
        w.pack_start(self.delay.widget, False, False, 0)
        grid, _ = row("", "Apps", "Window classes (discord, steam, org.telegram.desktop); the last part of "
                      "a dotted class is enough.")
        w.pack_start(grid, False, False, 0)
        self.apps_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        w.pack_start(self.apps_box, False, False, 0)
        self.app_entry = Gtk.ComboBoxText.new_with_entry()
        self.app_entry.get_child().set_placeholder_text("window class, e.g. discord")
        self.app_entry.get_child().set_width_chars(30)
        self.app_entry.get_child().connect("activate", lambda _e: self.add("apps", self.app_entry))
        w.pack_start(self.adder(self.app_entry, lambda: self.add("apps", self.app_entry)), False, False, 0)
        grid, _ = row("", "Sites", "A word in a browser window's title (youtube, reddit): while that tab is "
                      "showing, the window counts as a distraction.")
        w.pack_start(grid, False, False, 0)
        self.sites_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        w.pack_start(self.sites_box, False, False, 0)
        self.site_entry = Gtk.ComboBoxText.new_with_entry()      # the same look as the apps' box
        self.site_entry.get_child().set_placeholder_text("a site's name as its tab says it")
        self.site_entry.get_child().set_width_chars(30)
        self.site_entry.get_child().connect("activate", lambda _e: self.add("sites", self.site_entry))
        for word in ("youtube", "reddit", "instagram", "facebook", "tiktok", "twitch", "netflix", "twitter",
                     "hacker news", "linkedin", "bluesky", "mastodon"):
            self.site_entry.append_text(word)
        w.pack_start(self.adder(self.site_entry, lambda: self.add("sites", self.site_entry)), False, False, 0)
        w.pack_start(sep(), False, False, 0)

        w.pack_start(heading("BREAKS"), False, False, 0)
        self.breaks_switch = self.switch(lambda on: self.set("breaks", "on" if on else "off"))
        grid, _ = row("", "Pomodoro rhythm", "A break starts by itself after each block, a longer one every "
                      "few; off: the block just ends, with \"Focus again\".", self.breaks_switch)
        w.pack_start(grid, False, False, 0)
        self.brk = Slider("break_min", "A break", 1, 30, 1, " min", self.set)
        w.pack_start(self.brk.widget, False, False, 0)
        self.long_brk = Slider("long_break_min", "A long break", 5, 60, 5, " min", self.set)
        w.pack_start(self.long_brk.widget, False, False, 0)
        self.long_every = Slider("long_every", "The long one after every", 2, 8, 1, " blocks", self.set)
        w.pack_start(self.long_every.widget, False, False, 0)
        w.pack_start(sep(), False, False, 0)

        w.pack_start(heading("STATS"), False, False, 0)
        grid, self.today_sub = row("", "Today", "")
        w.pack_start(grid, False, False, 0)
        self.week_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        w.pack_start(self.week_box, False, False, 0)
        note = dp.label("Counts only (minutes, blocks, offers), kept 120 days; the daily brief and the journal show "
                        "the focus minutes.", "ctl-sub")
        note.set_line_wrap(True)
        note.set_xalign(0)
        w.pack_start(note, False, False, 0)
        self.msg = dp.label("", "ctl-sub")
        self.msg.set_line_wrap(True)
        w.pack_start(self.msg, False, False, 0)

    # -- pieces ----------------------------------------------------------------------
    def switch(self, on_change):
        sw = Gtk.Switch()
        sw.connect("state-set", lambda _s, state: self.switched(on_change, state))
        return sw

    def switched(self, on_change, state):
        if not self.updating:
            on_change(state)
        return True             # the switch moves when refresh() says the setting did

    def adder(self, entry, on_add):
        box = Gtk.Box(spacing=8)
        box.set_halign(Gtk.Align.END)
        box.pack_start(entry, False, False, 0)
        box.pack_start(link("Add", on_add), False, False, 0)
        return box

    def act(self, *args):
        def work():
            try:
                res = subprocess.run([GUARD, *args], capture_output=True, text=True, timeout=30)
                return "" if res.returncode == 0 else (res.stderr or res.stdout).strip()
            except (OSError, subprocess.SubprocessError) as exc:
                return str(exc)
        self.msg.set_text("")
        background(work, lambda err: (self.msg.set_text(err), self.refresh()))

    def set(self, key, value):
        if not self.updating:
            self.act("set", key, str(value))

    def add(self, key, entry):
        text = (entry.get_child() if isinstance(entry, Gtk.ComboBoxText) else entry).get_text().strip()
        if text:
            (entry.get_child() if isinstance(entry, Gtk.ComboBoxText) else entry).set_text("")
            self.act(key, "add", text)

    def start_stop(self):
        block = ((self.data or {}).get("live") or {}).get("block")
        self.act("stop" if block else "start")

    def refresh(self):
        background(lambda: run_json(GUARD, "get", "--json"), self.show)
        background(lambda: run_json("hyprctl", "clients", "-j"), self.show_classes)

    # -- drawing -----------------------------------------------------------------------
    def show_classes(self, clients):
        apps = set((self.data or {}).get("apps") or [])
        self.app_entry.remove_all()
        for cls in sorted({(c.get("class") or "").lower() for c in clients or [] if c.get("class")}):
            if cls not in apps and cls.rsplit(".", 1)[-1] not in apps:
                self.app_entry.append_text(cls)

    def show_list(self, box, key, words, icon):
        clear(box)
        for word in words:
            grid, _ = row(icon, word, "", link("Remove", lambda k=key, x=word: self.act(k, "remove", x)))
            box.pack_start(grid, False, False, 0)
        if not words:
            box.pack_start(dp.label("none", "ctl-sub"), False, False, 0)

    def show(self, data):
        if not data:
            self.msg.set_text("focus-guard.py did not answer (run it in a terminal to see why)")
            return
        self.data = data
        v, t = data["values"], data["timers"]
        now = datetime.datetime.now().timestamp()
        live = data.get("live") or {}
        self.updating = True
        try:
            for sw, on in ((self.main_switch, data["on"]), (self.watch_switch, data["watching"]),
                           (self.digest_switch, v["digest"] == "on"), (self.summary_switch, v["summary"] == "on"),
                           (self.breaks_switch, v["breaks"] == "on")):
                sw.set_active(on)
                sw.set_state(on)
            self.main_sub.set_text(live_text(data, now))
            self.start_link.set_label("Stop the focus block" if live.get("block") else "Start a focus block")
            self.sensitivity.set([(k, SENSITIVITY_TEXT[k]) for k in data["choices"]["sensitivity"]],
                                 v["sensitivity"])
            self.when.set([(k, WHEN_TEXT[k]) for k in data["choices"]["when"]], v["when"])
            self.window.show(int(v["window_min"]))
            self.cooldown.show(int(v["cooldown_min"]))
            self.numbers.set_text(numbers_text(live.get("numbers")) if data["watching"] and data["on"] else
                                  ("Turn on the guard and noticing to see the numbers it looks at."))
            self.length.show(int(t["minutes"]))
            self.quiet.set([(k, QUIET_TEXT[k]) for k in data["choices"]["quiet"]], v["quiet"])
            self.quiet_sub.set_text(QUIET_SUB[v["quiet"]])
            self.style.set([(k, STYLE_TEXT[k]) for k in data["choices"]["style"]], v["style"])
            self.style_sub.set_text(STYLE_SUB[v["style"]])
            self.dim.show(int(v["dim_pct"]))
            self.dim.widget.set_sensitive(v["style"] in ("dim", "both"))
            self.delay.show(int(v["delay_s"]))
            self.delay.widget.set_sensitive(v["style"] in ("delay", "both"))
            self.show_list(self.apps_box, "apps", data["apps"], "")
            self.show_list(self.sites_box, "sites", data["sites"], "")
            for slider, key in ((self.brk, "break_min"), (self.long_brk, "long_break_min"),
                                (self.long_every, "long_every")):
                slider.show(int(t[key]))
                slider.widget.set_sensitive(v["breaks"] == "on")
            today = data["today"]
            self.today_sub.set_text(f"{minutes_text(today['minutes'])} in focus blocks"
                                    f"  ·  {int(today['blocks'])} block{'s' if today['blocks'] != 1 else ''}"
                                    f"  ·  offered {int(today['offered'])}, taken {int(today['taken'])}"
                                    + (f"  ·  {int(today['waited'])} waited, {int(today['opened'])} opened anyway"
                                       if today["waited"] or today["opened"] else ""))
            clear(self.week_box)
            for day, bar, text in week_lines(data["week"]):
                line = Gtk.Box(spacing=12)
                line.pack_start(dp.label(day, "ctl-sub"), False, False, 0)
                line.pack_start(dp.label(bar, "ctl-value"), False, False, 0)
                line.pack_start(dp.label(text, "ctl-sub"), False, False, 0)
                self.week_box.pack_start(line, False, False, 0)
        finally:
            self.updating = False
        self.widget.show_all()
