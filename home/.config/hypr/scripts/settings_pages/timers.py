"""Settings page: timers, alarms, reminders, focus rounds, the stopwatch and
calendar alarms (timers.py), and work hours (workhours.py).

What is set right now, soonest first, each with Cancel (a paused alarm --
the clock card's pause, `timers.py pause` -- last, saying "paused" instead
of a countdown, with Resume: it would not ring); the stopwatch when
there is one; the focus round's lengths; what a ring sounds like (the
theme's alarm, a quiet chime, or nothing), how loud, and how long Snooze
waits; calendar alarms on or off, how long before the event, and which of
Evolution's calendars ring. Work hours get one row here -- on or off, and
whether it is work time now -- and a link to their own page (Work hours,
settings_pages/workhours.py), which has the hours, days and day off.

Nothing is kept here: every control runs timers.py (set KEY VALUE, cancel,
calendar on|off, calendars use|skip) or workhours.py (enable, disable),
which write $XDG_STATE_HOME/hypr/timers.conf,
timers.json and ~/.config/hypr/workhours.conf, and the page redraws from `timers.py status --json` and
`workhours.py status --json`. Setting a timer is the launcher's job (ALT+E:
"timer 5m tea", "alarm 7:30 weekdays"), so this page only lists, resumes and
cancels.
While the page is on screen the countdowns tick once a second from the last
answer, with no command run; when one of them comes due it asks again.
"""
from gi.repository import GLib, Gtk  # noqa: F401

from .common import *  # noqa: F401,F403  (the shared helpers and paths)

import datetime as dt  # noqa: E402
import os  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402
import time  # noqa: E402

# The Work hours page's helpers, for this page's one work-hours row (and
# importable from here as before: tests/test_settings_timers.py).
from .workhours import DAYS, clock_chips, days_arg  # noqa: E402,F401

PAGE = {"id": "timers", "title": "Timers & alarms", "icon": "", "group": "Apps", "order": 20,
        "keywords": ["timer", "temporizador", "alarm", "alarma", "reminder", "recordatorio", "stopwatch",
                     "cronometro", "focus", "pomodoro", "countdown", "snooze", "alarm sound", "ring",
                     "calendar alarms", "evolution", "work hours", "horario", "day off"]}

TIMERS = os.path.join(HYPR, "timers.py")
WORKHOURS = os.path.join(HYPR, "workhours.py")
SETTINGS = os.path.join(HYPR, "settings.py")

# Font Awesome 6 glyphs, as escapes like the other pages.
KIND_ICON = {"timer": "", "alarm": "", "reminder": "", "focus": "",
             "break": "", "calendar": ""}
STOPWATCH_ICON = ""

# The chips for each setting, in minutes; a value set some other way (the
# CLI, a hand edit) gets a chip of its own, kept in order.
FOCUS = [15, 20, 25, 30, 45, 50, 60, 90]
BREAK = [3, 5, 10, 15]
LONG_BREAK = [10, 15, 20, 30]
LONG_EVERY = [2, 3, 4, 5, 6]
SNOOZE = [1, 3, 5, 10, 15, 30]
LEAD = [0, 5, 10, 15, 30, 60]
SOUNDS = [("theme", "Theme alarm"), ("chime", "Quiet chime"), ("none", "None")]


# -- pure helpers (tests/test_settings_timers.py) ---------------------------------------
def minutes(n):
    """5 -> "5 min", 60 -> "1 h", 90 -> "1 h 30 min"."""
    h, m = divmod(int(n), 60)
    return " ".join(([f"{h} h"] if h else []) + ([f"{m} min"] if m or not h else []))


def minute_chips(options, current, zero=None):
    """(key, caption) chips for minute values, plus current when it is not
    one of them; `zero` captions 0 ("At the start")."""
    return [(str(v), zero if v == 0 and zero else minutes(v)) for v in sorted(set(options) | {current})]


def left_text(secs):
    """A countdown: 0:45, 4:05, 1:02:03, then "2 d 3 h" past a day."""
    secs = max(0, int(secs))
    if secs >= 86400:
        d, rest = divmod(secs, 86400)
        return f"{d} d {rest // 3600} h"
    h, rest = divmod(secs, 3600)
    m, s = divmod(rest, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def nth(n):
    """2 -> "2nd", 3 -> "3rd", 4 -> "4th", 11 -> "11th"."""
    n = int(n)
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def item_title(t):
    """"Tea" for a labelled one, "Timer" / "Alarm" / "Focus" otherwise."""
    return t["label"] or t["name"].capitalize()


def item_sub(t, now=None):
    """What it is and when it rings: "timer  ·  rings at 14:05  ·  then
    suspend", with the weekday when it is more than half a day away. A
    paused alarm says "paused": its due (status gives when it WOULD ring if
    resumed) is no time it rings at."""
    now = now or time.time()
    at = dt.datetime.fromtimestamp(t["due"])
    when = at.strftime("%a %H:%M" if t["due"] - now > 43200 else "%H:%M")
    verb = {"focus": "ends", "break": "ends", "calendar": "rings"}.get(t["kind"], "rings")
    state = "paused" if t.get("paused") else f"{verb} at {when}"
    bits = [t["name"] if t["label"] else "", state, t.get("repeat") or "", t.get("then") or ""]
    return "  ·  ".join(b for b in bits if b)


def work_note(work):
    """The work-hours row's tooltip, from `workhours.py status
    --json`: what the pill says, and which holidays are free."""
    if not work.get("enabled", True):
        return ("Off: no ~/.config/hypr/workhours.conf. On, the bar shows a pill with the time left during "
                "work hours, and `workhours.py check` tells a git hook it is work time.")
    hol = {"mx": "Mexico's statutory rest days are free on their own"}.get(work.get("holidays") or "",
                                                                         "no public holidays are set")
    tz = f" Hours in {work['timezone']}." if work.get("timezone") else ""
    return (f"The bar shows a \"{work.get('label') or 'Work'}\" pill with the time left, and `workhours.py "
            f"check` tells a git hook it is work time; {hol} "
            f"(label, time zone, holidays: {work.get('conf', 'workhours.conf')}).{tz}")


def calendar_sub(cal):
    """The line under the calendar alarms switch."""
    if not cal["on"]:
        return "off"
    if cal.get("timer_enabled") not in ("enabled", "static") or cal.get("timer_active") != "active":
        return "on, but its check is not running: turn it on in Startup > Timers"
    return f"looks {cal['ahead_min']} min ahead for timed events (not all-day ones)"


def attempt(*cmd, timeout=30):
    """Run a backend command; "" when it worked, else the last line it said
    on stderr (timers.py and workhours.py exit with a readable one), so the
    page can show why a click did nothing. Called from background() only."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        return f"{os.path.basename(cmd[0])}: {exc}"
    if r.returncode == 0:
        return ""
    return (r.stderr.strip().splitlines() or [f"{os.path.basename(cmd[0])} failed ({r.returncode})"])[-1]


def make_chips(on_pick, per_line=9):
    """Chips on one line where they fit (see power.py: a FlowBox packed at
    the start shrinks to one chip a line unless told the minimum)."""
    chips = Chips(on_pick)
    chips.widget.set_max_children_per_line(per_line)
    chips.widget.set_halign(Gtk.Align.START)
    chips.widget.set_margin_start(36)
    plain_set = chips.set

    def set_items(items, active):
        plain_set(items, active)
        chips.widget.set_min_children_per_line(max(1, min(len(items), per_line)))
    chips.set = set_items
    return chips


def wrap(text):
    lab = dp.label(text, "ctl-sub")
    lab.set_line_wrap(True)
    lab.set_max_width_chars(90)
    return lab


class Page:
    def __init__(self):
        self.widget = page_box()
        w = self.widget
        self.data, self.work, self.fetched = None, None, 0.0
        self.updating = False
        # (label, moment, title, counts_up) for each clock on screen: a
        # countdown to `moment`, or the stopwatch counting up from it.
        self.ticks = []
        self.error = dp.label("", "ctl-sub")
        self.error.set_line_wrap(True)
        self.error.set_no_show_all(True)
        w.pack_start(self.error, False, False, 0)

        # -- what is set ----------------------------------------------------------
        w.pack_start(heading("SET NOW"), False, False, 0)
        self.items = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        w.pack_start(self.items, False, False, 0)
        w.pack_start(wrap("Set them from the launcher (ALT+E): \"timer 5m tea\", \"alarm 7:30\"."),
                     False, False, 0)
        w.pack_start(details(wrap("Also \"alarm 7:30 weekdays\", \"remind me in 40 min to call the lab\", "
                                  "\"focus\", \"stopwatch\". They ring with every window closed and come back "
                                  "after a restart; the bar counts the next one down.")), False, False, 0)
        w.pack_start(sep(), False, False, 0)

        # -- focus rounds ---------------------------------------------------------
        w.pack_start(heading("FOCUS ROUNDS"), False, False, 0)
        self.chips, self.subs = {}, {}
        for key, icon, title, sub in (
                ("focus_min", KIND_ICON["focus"], "Focus round",
                 "default length; Do Not Disturb while it runs"),
                ("break_min", KIND_ICON["break"], "Break", "starts when a round ends"),
                ("long_break_min", KIND_ICON["break"], "Long break", ""),
                ("long_every", "", "Long break every", "")):
            grid, self.subs[key] = row(icon, title, sub)
            w.pack_start(grid, False, False, 0)
            self.chips[key] = make_chips(lambda k, key=key: self.set(key, k))
            w.pack_start(self.chips[key].widget, False, False, 0)
        w.pack_start(links_row(link("Start a focus round now", lambda: self.do(TIMERS, "focus"))),
                     False, False, 0)
        w.pack_start(sep(), False, False, 0)

        # -- ringing --------------------------------------------------------------
        w.pack_start(heading("RINGING"), False, False, 0)
        grid, self.subs["sound"] = row("", "Alarm sound", "")
        w.pack_start(grid, False, False, 0)
        self.chips["sound"] = make_chips(lambda k: self.set("sound", k))
        w.pack_start(self.chips["sound"].widget, False, False, 0)
        self.volume = Slider("volume", "Volume of every timer sound", 5, 100, 5, " %",
                             lambda _k, v: self.set("volume", str(int(v))))
        self.volume.widget.set_margin_start(36)
        w.pack_start(self.volume.widget, False, False, 0)
        # Under the sound and its volume: what it plays.
        self.try_sound = link("Play it once", lambda: spawn(TIMERS, "try-sound"))
        self.try_sound.set_tooltip_text("The alarm sound once, at this volume")
        w.pack_start(links_row(self.try_sound), False, False, 0)
        grid, self.subs["snooze_min"] = row("", "Snooze", "")
        w.pack_start(grid, False, False, 0)
        self.chips["snooze_min"] = make_chips(lambda k: self.set("snooze_min", k))
        w.pack_start(self.chips["snooze_min"].widget, False, False, 0)
        w.pack_start(sep(), False, False, 0)

        # -- calendar alarms ------------------------------------------------------
        w.pack_start(heading("CALENDAR ALARMS"), False, False, 0)
        self.cal_switch = Gtk.Switch()
        self.cal_switch.connect("state-set", lambda _s, on: self.toggle(
            lambda: self.do(TIMERS, "calendar", "on" if on else "off")))
        grid, self.cal_sub = row(KIND_ICON["calendar"], "Ring before calendar events", "", self.cal_switch)
        w.pack_start(grid, False, False, 0)
        grid, self.subs["cal_lead_min"] = row("", "How long before", "")
        w.pack_start(grid, False, False, 0)
        self.chips["cal_lead_min"] = make_chips(lambda k: self.set("cal_lead_min", k))
        w.pack_start(self.chips["cal_lead_min"].widget, False, False, 0)
        self.cals = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        w.pack_start(self.cals, False, False, 0)
        buttons = [link("Check again", self.refresh)]
        if shutil.which("gnome-calendar"):
            buttons.insert(0, link("Open GNOME Calendar", lambda: spawn("gnome-calendar")))
        w.pack_start(links_row(*buttons), False, False, 0)
        w.pack_start(sep(), False, False, 0)

        # -- work hours -----------------------------------------------------------
        w.pack_start(heading("WORK HOURS"), False, False, 0)
        self.work_switch = Gtk.Switch()
        self.work_switch.connect("state-set", lambda _s, on: self.toggle(
            lambda: self.do(WORKHOURS, "enable" if on else "disable")))
        self.work_row, self.work_sub = row("", "Work hours", "", self.work_switch)
        w.pack_start(self.work_row, False, False, 0)
        # The hours, days, label, time zone, holidays and day off: their page.
        w.pack_start(links_row(link("Open Work hours", lambda: spawn(SETTINGS, "workhours"))),
                     False, False, 0)

        GLib.timeout_add_seconds(1, self.tick)

    # -- actions ---------------------------------------------------------------------
    def do(self, *cmd):
        """Every control: the command in the background, then redraw from
        what the scripts report, with the complaint on top if it failed."""
        background(lambda: attempt(*cmd), self.done)

    def done(self, error):
        self.error.set_text(f"!  {error}" if error else "")
        self.error.set_visible(bool(error))
        self.refresh()

    def set(self, key, value):
        if not self.updating:
            self.do(TIMERS, "set", key, value)

    def toggle(self, act):
        """A switch flipped by hand (not by show()): run it. The switch
        itself moves when the redraw says it did."""
        if not self.updating:
            act()
        return True

    def confirm_link(self, text, again, act):
        """A link that needs two clicks: the first turns it into `again`
        for 4 s, the second runs act. For cancels the page cannot undo (all
        of them at once, a repeating alarm)."""
        b = link(text, lambda: None)

        def clicked(_b):
            if b.get_label() == again:
                act()
                return
            b.set_label(again)
            GLib.timeout_add_seconds(4, lambda: (b.get_label() == again and b.set_label(text), False)[1])
        b.connect("clicked", clicked)
        return b

    # -- drawing ---------------------------------------------------------------------
    def refresh(self):
        if self.data is None:
            clear(self.items)
            self.items.pack_start(dp.label("checking…", "ctl-sub"), False, False, 0)
            self.items.show_all()
        background(lambda: (run_json(TIMERS, "status", "--json", timeout=20),
                            run_json(WORKHOURS, "status", "--json", timeout=10)), self.show)

    def tick(self):
        """Once a second while the page is on screen: the countdowns move
        on from the last answer; one that came due means ask again."""
        if not self.widget.get_mapped() or not self.ticks:
            return True
        now = time.time()
        for lab, moment, title, up in self.ticks:
            lab.set_text(f"{title}  ·  {left_text(now - moment if up else moment - now)}")
        # Only for one that came due since the last answer: a one-off whose
        # time passed while the machine was off stays listed for 2 min, and
        # must not make the page ask every few seconds.
        if any(not up and self.fetched < moment <= now - 1 for _l, moment, _t, up in self.ticks) \
                and now - self.fetched > 3:
            self.fetched = now
            self.refresh()
        return True

    def show(self, result):
        data, work = result
        self.fetched = time.time()
        self.updating = True
        try:
            if data:
                self.data = data
                self.show_items(data)
                self.show_settings(data)
                self.show_calendar(data)
            else:
                clear(self.items)
                self.items.pack_start(wrap("timers.py did not answer (run `timers.py status` in a terminal "
                                           "to see why)"), False, False, 0)
            if work:
                self.work = work
                self.show_work(work)
            else:
                self.work_sub.set_text("workhours.py did not answer")
            self.widget.show_all()
        finally:
            self.updating = False

    def show_items(self, data):
        clear(self.items)
        self.ticks = []
        now = time.time()
        for t in data["timers"]:
            title = item_title(t)
            if t.get("repeat"):     # gone for every day it repeats on: ask twice
                cancel = self.confirm_link("Cancel", "Cancel for good?",
                                           lambda i=t["id"]: self.do(TIMERS, "cancel", i))
            else:
                cancel = link("Cancel", lambda i=t["id"]: self.do(TIMERS, "cancel", i))
            icon = KIND_ICON.get(t["kind"], "")
            if t.get("paused"):
                # Not ticking: it does not ring, so a countdown to its would-be
                # time would only ask timers.py again, for nothing, at that moment.
                box = Gtk.Box(spacing=6)
                box.pack_start(link("Resume", lambda i=t["id"]: self.do(TIMERS, "resume", i)), False, False, 0)
                box.pack_start(cancel, False, False, 0)
                grid, _sub = row(icon, "", item_sub(t, now), box)
                grid.get_child_at(1, 0).set_text(f"{title}  ·  paused")
            else:
                grid, _sub = row(icon, "", item_sub(t, now), cancel)
                lab = grid.get_child_at(1, 0)
                lab.set_text(f"{title}  ·  {left_text(t['due'] - now)}")
                self.ticks.append((lab, t["due"], title, False))
            self.items.pack_start(grid, False, False, 0)
        if len(data["timers"]) > 1:
            n = len(data["timers"])
            self.items.pack_start(links_row(self.confirm_link(f"Cancel all {n}", f"Click again to cancel all {n}",
                                                              lambda: self.do(TIMERS, "cancel", "all"))),
                                  False, False, 0)
        sw = data.get("stopwatch")
        if sw:
            pause = link("Pause" if sw["running"] else "Resume",
                         lambda: self.do(TIMERS, "stopwatch", "toggle"))
            reset = link("Reset", lambda: self.do(TIMERS, "stopwatch", "reset"))
            box = Gtk.Box(spacing=6)
            box.pack_start(pause, False, False, 0)
            box.pack_start(reset, False, False, 0)
            sub = "running" if sw["running"] else "paused"
            grid, _sub = row(STOPWATCH_ICON, "", sub, box)
            lab = grid.get_child_at(1, 0)
            lab.set_text(f"Stopwatch  ·  {left_text(sw['elapsed'])}")
            if sw["running"]:
                self.ticks.append((lab, now - sw["elapsed"], "Stopwatch", True))
            self.items.pack_start(grid, False, False, 0)
        if not data["timers"] and not sw:
            self.items.pack_start(dp.label("Nothing set.", "ctl-sub"), False, False, 0)
        n = data.get("rounds_today") or 0
        if n:
            self.items.pack_start(dp.label(f"{n} focus round{'s' if n != 1 else ''} done today.", "ctl-sub"),
                                  False, False, 0)
        self.items.show_all()

    def show_settings(self, data):
        v = data["settings"]
        self.chips["focus_min"].set(minute_chips(FOCUS, v["focus_min"]), str(v["focus_min"]))
        self.chips["break_min"].set(minute_chips(BREAK, v["break_min"]), str(v["break_min"]))
        self.chips["long_break_min"].set(minute_chips(LONG_BREAK, v["long_break_min"]), str(v["long_break_min"]))
        self.chips["long_every"].set([(str(n), f"{n} rounds") for n in sorted(set(LONG_EVERY) | {v["long_every"]})],
                                     str(v["long_every"]))
        self.subs["long_break_min"].set_text(f"after every {nth(v['long_every'])} round")
        self.subs["long_every"].set_text(f"{v['long_every'] - 1} short break"
                                         f"{'s' if v['long_every'] != 2 else ''}, then a long one")
        self.chips["sound"].set(SOUNDS, v["sound"])
        sub = {"theme": ("the theme's alarm, until Snooze or Stop" if data.get("theme_sound") else
                         "the system alarm clock, until Snooze or Stop"),
               "chime": "a quiet chime, until Snooze or Stop",
               "none": "only the notification"}[v["sound"]]
        self.subs["sound"].set_text(sub)
        self.volume.show(v["volume"])
        self.volume.widget.set_sensitive(v["sound"] != "none")
        self.try_sound.set_sensitive(v["sound"] != "none")
        self.chips["snooze_min"].set(minute_chips(SNOOZE, v["snooze_min"]), str(v["snooze_min"]))
        self.subs["snooze_min"].set_text("for timers and alarms; reminders offer 5 min, 15 min, 1 h")

    def show_calendar(self, data):
        cal, v = data["calendar"], data["settings"]
        self.cal_switch.set_state(cal["on"])
        self.cal_switch.set_active(cal["on"])
        self.cal_sub.set_text(calendar_sub(cal))
        self.chips["cal_lead_min"].set(minute_chips(LEAD, v["cal_lead_min"], zero="At the start"),
                                       str(v["cal_lead_min"]))
        self.subs["cal_lead_min"].set_text(
            "rings as the event starts" if not v["cal_lead_min"] else
            f"rings {minutes(v['cal_lead_min'])} before the event")
        self.chips["cal_lead_min"].widget.set_sensitive(cal["on"])
        clear(self.cals)
        if cal.get("error"):
            self.cals.pack_start(wrap(f"Could not read the calendars: {cal['error']}"), False, False, 0)
        elif not cal["calendars"]:
            self.cals.pack_start(wrap("No calendars: add one in GNOME Calendar."), False, False, 0)
        for c in cal["calendars"]:
            sw = Gtk.Switch()
            sw.set_state(c["enabled"] and c["used"])
            sw.set_active(c["enabled"] and c["used"])
            sw.set_sensitive(cal["on"] and c["enabled"])
            sw.connect("state-set", lambda _s, on, uid=c["uid"]: self.toggle(
                lambda: self.do(TIMERS, "calendars", "use" if on else "skip", uid)))
            sub = (c["account"] + "  ·  " if c["account"] else "") + (
                "rings" if c["enabled"] and c["used"] else
                "does not ring" if c["enabled"] else
                "off in GNOME Calendar")
            grid, _s = row(KIND_ICON["calendar"], c["name"], sub, sw)
            grid.set_margin_start(36)
            self.cals.pack_start(grid, False, False, 0)
        self.cals.show_all()

    def show_work(self, work):
        names = dict(DAYS)
        on = work.get("enabled", True)
        self.work_switch.set_state(on)
        self.work_switch.set_active(on)
        self.work_row.set_tooltip_text(work_note(work))
        if not on:
            self.work_sub.set_text("off")
        elif work["working"] and work.get("until"):
            left = int(work["until"] - time.time()) // 60
            state = f"work time, {left // 60} h {left % 60:02d} min left"
        else:
            state = f"free now ({work['reason']})"
        days = work["days"]
        span = ("Mon–Fri" if days == ["mon", "tue", "wed", "thu", "fri"] else
                ", ".join(names[d] for d in days) if days else "no days")
        if on:
            self.work_sub.set_text(f"{state}  ·  {work['start']}–{work['end']}, {span}")
