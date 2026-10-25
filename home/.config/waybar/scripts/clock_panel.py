#!/usr/bin/env python3
"""Clock panel — what the time in the bar opens: the time three ways, world
clocks, alarms, a countdown and a stopwatch, in one card.

    clock_panel.py [x,y]   desktop position of the click that opened the panel

The top of the card is always the same, whichever tab is open: the local
time large, the date under it, then UTC and the Unix epoch, each with a copy
button (wl-copy) -- the readings the bar's pill cycles through, side by side
here, so you never have to cycle to read one. (The pill still cycles: right
click, clock.py cycle.) While a timer or an alarm rings, a ringing row
comes up under them -- what rings, Snooze and Stop, the same as the
notification's buttons (timers.py snooze / stop ID) -- and goes once it is
answered, from here or from the notification.

Below, four tabs (the last one used is reopened, in clock-panel.json):

  World      a row per time zone you added: the city, its time, how far it is
             from yours ("+7 h"), and "tomorrow" / "yesterday" when its date
             is not yours. Add one by typing a city or zone ("Tokyo",
             "Europe/Lisbon"; Tab completes from the system's zoneinfo), ✕
             removes it, the pin puts it on the bar as a second short reading
             after the time ("· TYO 06:04", clock.py; one pin at a time,
             pressing it again takes it off). Kept in
             $XDG_STATE_HOME/hypr/world-clocks.json ({"zones", "pin"}; the
             old plain list still reads).
             Under them the MEETING PLANNER: pick one of your zones and a
             strip of today's 24 hours shows yours over theirs, each side's
             working hours lit and the hours where both are working marked
             (overlap). Yours are workhours.conf's start-end (in its own time
             zone, moved to yours) when work-hours mode is on, else 9-17;
             theirs 9-17. Each hour is a button: click it, or arrow along the
             strip, and the line under it says that hour on both sides.
  Alarms     the alarms set (timers.py: they ring with this card closed, the
             bar restarted, after a reboot). Each row: pause / resume (a
             paused alarm keeps its place and does not ring; timers.py pause),
             edit -- the row opens in place with its time, label and repeat,
             Save or Esc (timers.py edit; another tab closes it unsaved) --
             and ✕ to cancel. Set a new one from a time ("7:30", "7am",
             "19:45"), Once / Daily / Weekdays / Weekends and an optional
             label, sent after "--" so its words stay a label ("take meds
             then sleep" never suspends, "mon review" is no repeat).
  Timer      the countdowns running (timers, reminders, focus rounds), each
             with its time left and ✕; quick buttons 1 / 5 / 10 / 15 / 25 min
             and 1 h, or a free entry ("1h30m tea", "90s", "2:30"). Under
             them UNTIL A DATE: countdowns to a day ("2027-01-01 00:00",
             "New Year") with the days and hours left, the bell to ring at
             that moment (a one-off alarm), ✕ to drop it (timers.py
             countdown; kept in timers.json until removed).
  Stopwatch  timers.py's stopwatch -- the same one the bar's timers pill shows
             and the launcher's "stopwatch" starts -- with Start / Pause,
             Lap and Reset. Laps are timers.py's too (stopwatch lap), so they
             are still there when the card is opened again; Reset clears them.

Everything that rings goes through timers.py (a transient systemd timer per
alarm), so this card only reads its state file and runs its commands. How
times are written follows ~/.config/hypr/region.conf through clock.py
(24 / 12 hour, seconds). The card ticks four times a second while it is open,
and not at all once it is closed: it is a process of its own (panel.py).
"""

import json
import os
import subprocess
import sys
import time
from datetime import datetime, time as dtime, timedelta, timezone

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

try:
    from zoneinfo import ZoneInfo, available_timezones
except ImportError:         # Python without zoneinfo: no world clocks
    ZoneInfo = None

    def available_timezones():
        return set()

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import clock  # noqa: E402
import panelui  # noqa: E402

HYPR = os.path.expanduser("~/.config/hypr/scripts")
sys.path.insert(0, HYPR)
try:
    import timers           # the state file and its helpers (no GTK)
except ImportError:
    timers = None
try:
    import workhours        # your working hours, for the meeting planner (no GTK)
except ImportError:
    workhours = None
TIMERS = os.path.join(HYPR, "timers.py")

STATE_DIR = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"), "hypr")
ZONES_FILE = os.path.join(STATE_DIR, "world-clocks.json")
UI_FILE = os.path.join(STATE_DIR, "clock-panel.json")
# A first look that is not an empty list: three cities far apart. Removing
# them (or adding your own) writes the file, and the file wins from then on.
DEFAULT_ZONES = ["America/New_York", "Europe/London", "Asia/Tokyo"]
TABS = (("world", "World"), ("alarms", "Alarms"), ("timer", "Timer"), ("stopwatch", "Stopwatch"))
QUICK = (("1 min", "1m"), ("5 min", "5m"), ("10 min", "10m"), ("15 min", "15m"),
         ("25 min", "25m"), ("1 h", "1h"))
REPEATS = (("Once", ""), ("Daily", "daily"), ("Weekdays", "weekdays"), ("Weekends", "weekends"))
REPEAT_DAYS = {"": (), "daily": tuple(range(7)), "weekdays": tuple(range(5)), "weekends": (5, 6)}
DEFAULT_WORK = (9.0, 17.0)  # the planner's working hours, either side, without workhours.conf
WIDTH = 420
TICK_MS = 250

# Font Awesome 6 (copy, check, xmark, thumbtack, pause, play, pen, bell, bell-slash)
ICON_COPY, ICON_DONE, ICON_X = "", "", ""
ICON_PIN, ICON_PAUSE, ICON_PLAY, ICON_EDIT = "", "", "", ""
ICON_BELL, ICON_BELL_OFF = "", ""


# -- small pure helpers (tests/test_clock_panel.py) -----------------------------------
def read_json(path, default):
    try:
        with open(path) as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return default


def write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as handle:
        json.dump(data, handle)
    os.replace(tmp, path)


def load_zones():
    """The zones (the defaults until the file exists) and the pinned one
    (None): clock.parse_zones reads both of the file's shapes."""
    zones, pin = clock.parse_zones(read_json(ZONES_FILE, None))
    return (list(DEFAULT_ZONES), None) if zones is None else (zones, pin)


def save_zones(zones, pin):
    """The zones with the pin, as clock.py's watcher reads them; a pin that
    is not one of the zones is dropped."""
    write_json(ZONES_FILE, {"zones": list(zones), "pin": pin if pin in zones else None})


def zone_name(zone):
    """'America/Mexico_City' -> 'Mexico City'; 'UTC' stays."""
    return zone.rsplit("/", 1)[-1].replace("_", " ")


def find_zone(text, zones=None):
    """A zone for what was typed: an exact zone name, else a city that
    matches a zone's last part ('tokyo', 'new york', 'sao_paulo'), else
    None. Case and spaces / underscores do not matter."""
    zones = sorted(zones if zones is not None else available_timezones())
    want = text.strip()
    if not want:
        return None
    if want in zones:
        return want
    key = want.lower().replace(" ", "_")
    for z in zones:
        if z.lower() == key:
            return z
    for z in zones:
        if z.rsplit("/", 1)[-1].lower() == key:
            return z
    return None


def offset_text(seconds):
    """A difference from local time: '+7 h', '−5:30 h', 'same time'."""
    if seconds == 0:
        return "same time"
    sign = "+" if seconds > 0 else "−"
    h, rest = divmod(abs(int(seconds)), 3600)
    m = rest // 60
    return f"{sign}{h}:{m:02d} h" if m else f"{sign}{h} h"


def day_word(there, here):
    """'tomorrow' / 'yesterday' when the zone's date is not the local one."""
    delta = (there.date() - here.date()).days
    return {1: "tomorrow", -1: "yesterday"}.get(delta, "")


def span(seconds, tenths=False):
    """A duration for the Timer and Stopwatch tabs: 4:05, 1:02:03, 0:07.3."""
    seconds = max(0.0, seconds)
    whole = int(seconds)
    h, rest = divmod(whole, 3600)
    m, s = divmod(rest, 60)
    out = f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"
    if tenths:
        out += f".{int((seconds - whole) * 10)}"
    return out


def repeat_text(t):
    """An alarm's repeat in words: timers.py's own days_text() for its
    weekdays, "once" for a one-off."""
    if not t.get("repeat"):
        return "once"
    if timers is not None and t.get("days") is not None:
        return timers.days_text(t["days"])
    return "repeats"


def repeat_choice(t):
    """Which of the card's repeat chips an alarm is on: "" (once), "daily",
    "weekdays", "weekends" -- or None for other days ("mon wed fri"), which
    the editor keeps unless another chip is picked."""
    if not t.get("repeat"):
        return ""
    days = tuple(sorted(t.get("days") or ()))
    return next((k for k, v in REPEAT_DAYS.items() if v and v == days), None)


def utc_offset(delta):
    """A UTC offset as people write it: 'UTC−6', 'UTC+5:30', 'UTC'."""
    secs = int(delta.total_seconds()) if delta is not None else 0
    if not secs:
        return "UTC"
    sign = "+" if secs > 0 else "−"
    h, rest = divmod(abs(secs), 3600)
    return f"UTC{sign}{h}" + (f":{rest // 60:02d}" if rest else "")


def alarm_command(when, repeat, label):
    """timers.py alarm for the Set row. The label goes after "--", as in
    edit_command: timers.py reads the words before it as the time, repeat
    and "then" action, so a label "take meds then sleep" must not suspend
    the machine when it rings, nor "mon review" make a Monday alarm."""
    return [TIMERS, "alarm", when.strip()] + ([repeat] if repeat else []) + ["--"] + label.split()


def edit_command(ident, when, repeat, label):
    """timers.py edit for the in-place editor: repeat None keeps the alarm's
    own days (the "mon wed fri" kind no chip names), "" makes it a one-off;
    the label always goes after "--", so an emptied label is cleared."""
    words = [TIMERS, "edit", str(ident), when.strip()]
    if repeat is not None:
        words.append(repeat or "once")
    return words + ["--"] + label.split()


def timer_command(text):
    return [TIMERS, "timer"] + text.split()


def countdown_command(text, label, ring):
    """timers.py countdown add: the bell flag first, then the date, then the
    label after "--" -- so a label "5:00 shift" is not read as the time of a
    date typed without one, nor a label word "--alarm" as the flag."""
    return ([TIMERS, "countdown", "add"] + (["--alarm"] if ring else []) + text.split()
            + ["--"] + label.split())


def local_zone():
    """This computer's zone as a ZoneInfo (TZ, else /etc/localtime's link),
    so the planner's 24 hours follow a daylight-saving change inside the
    day; a fixed offset when neither names one."""
    name = os.environ.get("TZ", "").lstrip(":")
    if not name:
        link = os.path.realpath("/etc/localtime")
        name = link.split("zoneinfo/", 1)[1] if "zoneinfo/" in link else ""
    if name and ZoneInfo is not None:
        try:
            return ZoneInfo(name)
        except Exception:       # noqa: BLE001 -- an odd TZ: the offset below
            pass
    return datetime.now().astimezone().tzinfo


def my_work_hours(conf, day, here):
    """Your working hours on `day`, as hours from your local midnight
    (9.0, 17.0): workhours.conf's start-end when work-hours mode is on
    (conf: workhours.load(); None = off), moved from its time zone= to
    `here`, so they may run past 24 or start below 0; DEFAULT_WORK when off."""
    if conf is None or workhours is None:
        return DEFAULT_WORK
    start, end, _days = workhours.hours(conf)
    tz = workhours.zone(conf) or here

    def hours_from_midnight(t):
        # Your WALL CLOCK hour, the one planner() compares a cell's h + 0.5
        # with -- not the time elapsed since midnight. Subtracting aware
        # datetimes of two different zones gives elapsed time, an hour off
        # on a day the clocks change: here America/Chicago, tz
        # America/New_York, 2027-03-14, 10:00 New York came out 8.0 (CST
        # midnight to 9:00 CDT is 8 h), so a 9-17 day lit 8-16.
        w = datetime.combine(day, t, tz).astimezone(here)
        return (w.date() - day).days * 24 + w.hour + w.minute / 60
    return hours_from_midnight(start), hours_from_midnight(end)


def in_hours(hour, hours):
    """Whether `hour` (a cell's middle, 9.5) falls in hours (start, end),
    a day either side too, for a span that crosses midnight."""
    start, end = hours
    return any(start <= hour + k * 24 < end for k in (-1, 0, 1))


def planner(day, here, there, mine=DEFAULT_WORK, theirs=DEFAULT_WORK):
    """The meeting planner's 24 cells for `day`, one per local hour:
    {"hour", "here", "there" (aware datetimes), "mine", "theirs", "both"}.
    A cell is in someone's hours when its middle is (so a +5:30 zone's
    "14:30-15:30" counts as 15 for a 9-17 day)."""
    cells = []
    for h in range(24):
        at = datetime.combine(day, dtime(h), here)
        them = at.astimezone(there)
        mine_on = in_hours(h + 0.5, mine)
        theirs_on = in_hours(them.hour + them.minute / 60 + 0.5, theirs)
        cells.append({"hour": h, "here": at, "there": them, "mine": mine_on, "theirs": theirs_on,
                      "both": mine_on and theirs_on})
    return cells


def overlap_runs(cells):
    """[(first, last)] cells of each unbroken stretch both sides work."""
    runs, start = [], None
    for i, c in enumerate(cells):
        if c["both"] and start is None:
            start = i
        if not c["both"] and start is not None:
            runs.append((cells[start], cells[i - 1]))
            start = None
    if start is not None:
        runs.append((cells[start], cells[-1]))
    return runs


def hm_text(moment, conf=None):
    return clock.hms(moment, dict(conf or {}, seconds="off"))


def overlap_text(cells, name, conf=None):
    """The planner's summary: "Overlap 09:00–11:00 here = 16:00–18:00 in
    Lisbon · 2 h", one run per line, or that there is none."""
    runs = overlap_runs(cells)
    if not runs:
        return f"No working hours in common with {name} today."
    lines = []
    for first, last in runs:
        end_here, end_there = last["here"] + timedelta(hours=1), last["there"] + timedelta(hours=1)
        n = last["hour"] - first["hour"] + 1
        lines.append(f"Overlap {hm_text(first['here'], conf)}–{hm_text(end_here, conf)} here = "
                     f"{hm_text(first['there'], conf)}–{hm_text(end_there, conf)} in {name}  ·  {n} h")
    return "\n".join(lines)


def hour_text(hour, conf=None):
    """A planner cell's number: "09" on a 24-hour clock, "9" on a 12-hour
    one (whose AM / PM is in the line under the strip: a cell is 15 px)."""
    if (conf or {}).get("clock") == "12":
        return str(hour % 12 or 12)
    return f"{hour:02d}"


def cell_text(cell, name, conf=None):
    """What one planner hour is on both sides, and who works then."""
    who = {(True, True): "both working", (True, False): "you're working, they're not",
           (False, True): "they're working, you're not", (False, False): "neither working"}
    word = day_word(cell["there"].replace(tzinfo=None), cell["here"].replace(tzinfo=None))
    return (f"{hm_text(cell['here'], conf)} here = {hm_text(cell['there'], conf)} "
            f"{cell['there']:%a}{' (' + word + ')' if word else ''} in {name}  ·  "
            f"{who[(cell['mine'], cell['theirs'])]}")


def countdown_sub(at, conf=None):
    """A countdown's date line: "Fri 01 Jan 2027, 00:00"."""
    moment = datetime.fromtimestamp(at).astimezone()
    return f"{moment:%a %d %b %Y}, {hm_text(moment, conf)}"


# -- the card ------------------------------------------------------------------------
class ClockPanel(panelui.Panel):
    def setup(self):
        self.zones, self.pin = load_zones()
        self.ui = read_json(UI_FILE, {})
        self.tab = self.ui.get("tab") if self.ui.get("tab") in dict(TABS) else "world"
        self.rows_sig = {}          # tab -> what its list was built from (rebuild only on change)
        self.message = ""
        self.editing = None         # the alarm id open in the in-place editor
        self.edit_repeat = None
        self.ring_sig = None
        self.plan_zone = self.ui.get("plan")
        self.plan_hour = None       # the planner hour picked (None: the current one)
        self.cd_ring = False

    # widgets -------------------------------------------------------------------
    def build(self):
        self.card.set_size_request(WIDTH, -1)
        self.card.get_style_context().add_class("clk-card")

        top = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        top.get_style_context().add_class("clk-top")
        self.big = Gtk.Label(xalign=0)
        self.big.get_style_context().add_class("clk-big")
        self.date = Gtk.Label(xalign=0)
        self.date.get_style_context().add_class("ctl-sub")
        top.pack_start(self.big, False, False, 0)
        top.pack_start(self.date, False, False, 0)
        self.utc_value = self.readout(top, "UTC", lambda: self.utc_text(full=True))
        self.epoch_value = self.readout(top, "EPOCH", lambda: str(int(time.time())))
        self.card.pack_start(top, False, False, 0)

        # The ringing row: hidden until something rings (tick_ringing).
        self.ring_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.ring_box.get_style_context().add_class("clk-ringing")
        self.ring_box.set_no_show_all(True)
        self.card.pack_start(self.ring_box, False, False, 0)

        tabs = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        tabs.get_style_context().add_class("clk-tabs")
        self.tab_buttons = {}
        for key, label in TABS:
            b = Gtk.Button(label=label)
            b.get_style_context().add_class("dev-pick")
            b.get_style_context().add_class("chip")
            b.connect("clicked", lambda _b, k=key: self.show_tab(k))
            tabs.pack_start(b, True, True, 0)
            self.tab_buttons[key] = b
        self.card.pack_start(tabs, False, False, 0)

        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.stack.set_transition_duration(120)
        self.stack.set_vhomogeneous(False)
        self.stack.add_named(self.build_world(), "world")
        self.stack.add_named(self.build_alarms(), "alarms")
        self.stack.add_named(self.build_timer(), "timer")
        self.stack.add_named(self.build_stopwatch(), "stopwatch")
        self.card.pack_start(self.stack, False, False, 0)

        self.note = Gtk.Label(xalign=0)
        self.note.get_style_context().add_class("ctl-sub")
        self.note.set_line_wrap(True)
        self.note.set_no_show_all(True)
        self.card.pack_start(self.note, False, False, 0)

        self.tick()
        self.show_tab(self.tab, save=False)

    def readout(self, box, name, text_for):
        """A labelled reading with a copy button: UTC, EPOCH."""
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        row.get_style_context().add_class("clk-readout")
        key = Gtk.Label(label=name, xalign=0)
        key.get_style_context().add_class("sn-label")
        key.set_width_chars(6)
        value = Gtk.Label(xalign=0)
        value.get_style_context().add_class("sn-value")
        value.set_selectable(False)
        copy = Gtk.Button(label=ICON_COPY)
        copy.get_style_context().add_class("ctl-link")
        copy.set_tooltip_text(f"Copy the {name.lower()} reading")
        copy.connect("clicked", lambda b: self.copy(text_for(), b))
        row.pack_start(key, False, False, 0)
        row.pack_start(value, True, True, 0)
        row.pack_end(copy, False, False, 0)
        box.pack_start(row, False, False, 0)
        return value

    def section(self, title, box=None):
        if box is None:
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            box.get_style_context().add_class("clk-page")
        heading = Gtk.Label(label=title, xalign=0)
        heading.get_style_context().add_class("kb-heading")
        box.pack_start(heading, False, False, 0)
        return box

    def entry(self, placeholder, on_enter, width=None):
        e = Gtk.Entry()
        e.set_placeholder_text(placeholder)
        e.get_style_context().add_class("clk-entry")
        if width:
            e.set_width_chars(width)
        e.connect("activate", lambda *_: on_enter())
        return e

    def button(self, label, on_click, cls="dev-pick", tip=None):
        b = Gtk.Button(label=label)
        for c in cls.split():
            b.get_style_context().add_class(c)
        if tip:
            b.set_tooltip_text(tip)
        b.connect("clicked", lambda *_: on_click())
        return b

    @staticmethod
    def set_active(widget, on):
        ctx = widget.get_style_context()
        (ctx.add_class if on else ctx.remove_class)("active")

    def build_world(self):
        page = self.section("WORLD CLOCKS")
        self.world_list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        page.pack_start(self.world_list, False, False, 0)
        add = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.zone_entry = self.entry("Add a city or zone: Tokyo, Europe/Lisbon", self.add_zone)
        store = Gtk.ListStore(str)
        for z in sorted(available_timezones()):
            if "/" in z and not z.startswith(("Etc/", "SystemV/", "posix/", "right/")):
                store.append([z])
        completion = Gtk.EntryCompletion(model=store, text_column=0, inline_completion=True,
                                         popup_completion=True, minimum_key_length=2)
        completion.set_match_func(lambda _c, key, it, _d: key.lower().replace(" ", "_")
                                  in store[it][0].lower(), None)
        self.zone_entry.set_completion(completion)
        add.pack_start(self.zone_entry, True, True, 0)
        add.pack_start(self.button("Add", self.add_zone), False, False, 0)
        page.pack_start(add, False, False, 4)

        self.section("MEETING PLANNER", page)
        self.plan_chips = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=4,
                                      homogeneous=True, column_spacing=2, row_spacing=2)
        page.pack_start(self.plan_chips, False, False, 0)
        self.plan_grid = Gtk.Grid(column_spacing=1, row_spacing=2, column_homogeneous=False)
        self.plan_grid.get_style_context().add_class("clk-plan")
        page.pack_start(self.plan_grid, False, False, 2)
        self.plan_cell = Gtk.Label(xalign=0)
        self.plan_cell.get_style_context().add_class("sn-value")
        self.plan_cell.set_line_wrap(True)
        page.pack_start(self.plan_cell, False, False, 0)
        self.plan_note = Gtk.Label(xalign=0)
        self.plan_note.get_style_context().add_class("ctl-sub")
        self.plan_note.set_line_wrap(True)
        page.pack_start(self.plan_note, False, False, 0)
        return page

    def build_alarms(self):
        page = self.section("ALARMS")
        self.alarm_list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        page.pack_start(self.alarm_list, False, False, 0)
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.alarm_time = self.entry("7:30", self.add_alarm, width=7)
        self.alarm_label = self.entry("label (optional)", self.add_alarm)
        row.pack_start(self.alarm_time, False, False, 0)
        row.pack_start(self.alarm_label, True, True, 0)
        page.pack_start(row, False, False, 4)
        self.repeat = ""
        self.repeat_buttons = {}
        page.pack_start(self.repeat_chips(self.repeat_buttons, self.pick_repeat), False, False, 0)
        page.pack_start(self.button("Set alarm", self.add_alarm), False, False, 4)
        self.pick_repeat("")
        return page

    def repeat_chips(self, buttons, on_pick):
        chips = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        for label, value in REPEATS:
            b = self.button(label, lambda v=value: on_pick(v), cls="dev-pick chip")
            chips.pack_start(b, True, True, 0)
            buttons[value] = b
        return chips

    def build_timer(self):
        page = self.section("COUNTDOWN")
        self.timer_list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        page.pack_start(self.timer_list, False, False, 0)
        grid = Gtk.Grid(column_spacing=4, row_spacing=4, column_homogeneous=True)
        for i, (label, arg) in enumerate(QUICK):
            grid.attach(self.button(label, lambda a=arg: self.start_timer(a), cls="dev-pick chip"),
                        i % 3, i // 3, 1, 1)
        page.pack_start(grid, False, False, 4)
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.timer_entry = self.entry("1h30m tea · 90s · 2:30", lambda: self.start_timer(None))
        row.pack_start(self.timer_entry, True, True, 0)
        row.pack_start(self.button("Start", lambda: self.start_timer(None)), False, False, 0)
        page.pack_start(row, False, False, 0)

        self.section("UNTIL A DATE", page)
        self.cd_list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        page.pack_start(self.cd_list, False, False, 0)
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.cd_date = self.entry("2027-01-01 00:00", self.add_countdown, width=16)
        self.cd_label = self.entry("New Year", self.add_countdown)
        row.pack_start(self.cd_date, False, False, 0)
        row.pack_start(self.cd_label, True, True, 0)
        page.pack_start(row, False, False, 4)
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.cd_ring_button = self.button(f"{ICON_BELL}  Ring then", self.toggle_cd_ring, cls="dev-pick chip",
                                          tip="Also set an alarm at that moment")
        row.pack_start(self.cd_ring_button, False, False, 0)
        row.pack_end(self.button("Add", self.add_countdown), False, False, 0)
        page.pack_start(row, False, False, 0)
        return page

    def build_stopwatch(self):
        page = self.section("STOPWATCH")
        self.sw_label = Gtk.Label(xalign=0.5)
        self.sw_label.get_style_context().add_class("clk-big")
        page.pack_start(self.sw_label, False, False, 6)
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6, homogeneous=True)
        self.sw_toggle = self.button("Start", lambda: self.stopwatch("toggle"))
        row.pack_start(self.sw_toggle, True, True, 0)
        row.pack_start(self.button("Lap", self.lap), True, True, 0)
        row.pack_start(self.button("Reset", lambda: self.stopwatch("reset")), True, True, 0)
        page.pack_start(row, False, False, 0)
        self.lap_list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        page.pack_start(self.lap_list, False, False, 4)
        return page

    # list rows -----------------------------------------------------------------
    def list_row(self, box, title, value, sub="", on_remove=None, tip=None, buttons=(), cls=None):
        """A row: title and sub on the left, value on the right, then the
        icon buttons ((icon, on_click, tip, active) each) and ✕."""
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        row.get_style_context().add_class("clk-row")
        if cls:
            row.get_style_context().add_class(cls)
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        t = Gtk.Label(label=title, xalign=0)
        t.get_style_context().add_class("sn-label")
        t.set_ellipsize(3)          # Pango.EllipsizeMode.END
        left.pack_start(t, False, False, 0)
        s = Gtk.Label(label=sub, xalign=0)
        s.get_style_context().add_class("ctl-sub")
        s.set_no_show_all(not sub)
        left.pack_start(s, False, False, 0)
        v = Gtk.Label(label=value, xalign=1)
        v.get_style_context().add_class("sn-value")
        row.pack_start(left, True, True, 0)
        if on_remove:
            row.pack_end(self.button(ICON_X, on_remove, cls="ctl-link", tip=tip), False, False, 0)
        for icon, on_click, btip, active in reversed(buttons):
            b = self.button(icon, on_click, cls="ctl-link", tip=btip)
            self.set_active(b, active)
            row.pack_end(b, False, False, 0)
        row.pack_end(v, False, False, 0)
        box.pack_start(row, False, False, 0)
        row.show_all()
        return v, s

    def empty_row(self, box, text):
        lab = Gtk.Label(label=text, xalign=0)
        lab.get_style_context().add_class("ctl-sub")
        box.pack_start(lab, False, False, 2)
        lab.show()

    @staticmethod
    def clear(box):
        for child in box.get_children():
            box.remove(child)

    # readings ------------------------------------------------------------------
    def utc_text(self, full=False):
        now = datetime.now(timezone.utc)
        text = clock.hms(now)
        return f"{now:%Y-%m-%d} {text}" if full else text

    def tick(self):
        now = datetime.now().astimezone()
        conf = clock.prefs()
        self.big.set_text(clock.hms(now, conf))
        self.date.set_text(f"{now:%A %d %B %Y}  ·  {now.tzname()}, {utc_offset(now.utcoffset())}")
        utc = datetime.now(timezone.utc)
        self.utc_value.set_text(f"{clock.hms(utc, conf)}  ·  {utc:%a %d %b}")
        self.epoch_value.set_text(str(int(time.time())))
        self.tick_ringing()
        page = self.tab
        if page == "world":
            self.tick_world(now, conf)
            self.tick_planner(now, conf)
        elif page == "alarms":
            self.tick_alarms()
        elif page == "timer":
            self.tick_timer()
            self.tick_countdowns(conf)
        elif page == "stopwatch":
            self.tick_stopwatch()
        return True

    def tick_ringing(self):
        try:
            rings = timers.ringing() if timers else []
        except Exception:
            rings = []
        sig = tuple(r.get("id") for r in rings)
        if sig == self.ring_sig:
            return
        self.ring_sig = sig
        self.clear(self.ring_box)
        for r in rings:
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            what = Gtk.Label(xalign=0)
            what.get_style_context().add_class("clk-ring-title")
            name = timers.NAMES.get(r.get("kind"), "alarm") if timers else "alarm"
            what.set_text(f"{ICON_BELL}  {r.get('label') or name.capitalize()}")
            what.set_ellipsize(3)
            since = datetime.fromtimestamp(r.get("since", time.time()))
            sub = Gtk.Label(label=f"{name} ringing since {hm_text(since, clock.prefs())}", xalign=0)
            sub.get_style_context().add_class("ctl-sub")
            left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
            left.pack_start(what, False, False, 0)
            left.pack_start(sub, False, False, 0)
            row.pack_start(left, True, True, 0)
            snooze = timers.span(r.get("snooze") or 300) if timers else "5 min"
            row.pack_end(self.button("Stop", lambda i=r["id"]: self.ring_do("stop", i)), False, False, 0)
            row.pack_end(self.button(f"Snooze {snooze}", lambda i=r["id"]: self.ring_do("snooze", i)),
                         False, False, 0)
            self.ring_box.pack_start(row, False, False, 0)
        # show_all() stops at a no_show_all widget, so the rows are shown
        # one by one and the box itself by set_visible.
        for child in self.ring_box.get_children():
            child.show_all()
        self.ring_box.set_visible(bool(rings))

    def tick_world(self, now, conf):
        sig = (tuple(self.zones), self.pin)
        if self.rows_sig.get("world") != sig:
            self.rows_sig["world"] = sig
            self.clear(self.world_list)
            self.world_rows = []
            if not self.zones:
                self.empty_row(self.world_list, "No other zones yet: add a city below.")
            for z in self.zones:
                pinned = z == self.pin
                pin = (ICON_PIN, lambda z=z: self.toggle_pin(z),
                       f"Take {zone_name(z)} off the bar" if pinned
                       else f"Show {zone_name(z)} on the bar, after the time", pinned)
                v, s = self.list_row(self.world_list, zone_name(z), "", z, buttons=[pin],
                                     on_remove=lambda z=z: self.remove_zone(z), tip=f"Remove {zone_name(z)}")
                self.world_rows.append((z, v, s))
        short = dict(conf, seconds="off")
        for z, v, s in getattr(self, "world_rows", []):
            try:
                there = datetime.now(ZoneInfo(z))
            except Exception:
                v.set_text("?")
                continue
            diff = there.utcoffset().total_seconds() - now.utcoffset().total_seconds()
            v.set_text(clock.hms(there, short))
            word = day_word(there.replace(tzinfo=None), now.replace(tzinfo=None))
            s.set_text("  ·  ".join(p for p in (offset_text(diff), word, f"{there:%a}") if p))
            s.show()

    def tick_planner(self, now, conf):
        """The meeting planner: chips rebuilt with the zones, the 24 hour
        cells once per (zone, day, hours); after that only their classes
        change, so the keyboard focus stays where the arrows put it."""
        if self.plan_zone not in self.zones:
            self.plan_zone = self.zones[0] if self.zones else None
        chips_sig = (tuple(self.zones), self.plan_zone)
        if self.rows_sig.get("plan-chips") != chips_sig:
            self.rows_sig["plan-chips"] = chips_sig
            for child in self.plan_chips.get_children():
                self.plan_chips.remove(child)
            for z in self.zones:
                b = self.button(zone_name(z), lambda z=z: self.pick_plan(z), cls="dev-pick chip",
                                tip=f"Plan a meeting with {z}")
                self.set_active(b, z == self.plan_zone)
                self.plan_chips.add(b)
            self.plan_chips.show_all()
        if not self.plan_zone or ZoneInfo is None:
            self.clear(self.plan_grid)
            self.plan_cells = []
            # Forget the grid's signature with it: the same zone added back
            # the same day has the same (zone, day, hours, clock) and would
            # skip the rebuild, leaving the strip empty until a tab switch.
            self.rows_sig.pop("plan-grid", None)
            self.plan_cell.set_text("")
            self.plan_note.set_text("Add a zone above to plan a meeting with it.")
            return
        here = local_zone()
        try:
            there = ZoneInfo(self.plan_zone)
        except Exception:
            return
        day = now.date()
        try:
            mine = my_work_hours(workhours.load() if workhours else None, day, here)
        except Exception:
            mine = DEFAULT_WORK
        grid_sig = (self.plan_zone, day, mine, conf.get("clock"))
        if self.rows_sig.get("plan-grid") != grid_sig:
            self.rows_sig["plan-grid"] = grid_sig
            self.build_plan_grid(planner(day, here, there, mine), conf)
        name = zone_name(self.plan_zone)
        hour = self.plan_hour if self.plan_hour is not None else now.hour
        for c, top, bottom in self.plan_cells:
            for b, on in ((top, c["mine"]), (bottom, c["theirs"])):
                ctx = b.get_style_context()
                for cls, want in (("work", on), ("both", c["both"]), ("now", c["hour"] == now.hour),
                                  ("active", c["hour"] == hour)):
                    (ctx.add_class if want else ctx.remove_class)(cls)
        if self.plan_cells:
            self.plan_cell.set_text(cell_text(self.plan_cells[hour][0], name, conf))
            self.plan_note.set_text(overlap_text([c for c, _t, _b in self.plan_cells], name, conf))

    def build_plan_grid(self, cells, conf):
        self.clear(self.plan_grid)
        self.plan_cells = []
        for row, text in ((0, "here"), (1, clock.zone_code(self.plan_zone))):
            lab = Gtk.Label(label=text, xalign=0)
            lab.get_style_context().add_class("sn-label")
            lab.set_width_chars(4)
            self.plan_grid.attach(lab, 0, row, 1, 1)
        for c in cells:
            pair = []
            for row, moment in ((0, c["here"]), (1, c["there"])):
                b = Gtk.Button(label=hour_text(moment.hour, conf))
                b.get_style_context().add_class("clk-hour")
                b.set_hexpand(True)
                b.set_tooltip_text(f"{hm_text(c['here'], conf)} here = {hm_text(c['there'], conf)} there")
                b.connect("clicked", lambda _b, h=c["hour"]: self.pick_hour(h))
                b.connect("focus-in-event", lambda _b, _e, h=c["hour"]: self.pick_hour(h) or False)
                self.plan_grid.attach(b, c["hour"] + 1, row, 1, 1)
                pair.append(b)
            self.plan_cells.append((c, pair[0], pair[1]))
        self.plan_grid.show_all()

    def timers_now(self, kinds):
        if timers is None:
            return []
        try:
            return [t for t in timers.running() if t.get("kind") in kinds]
        except Exception:
            return []

    def tick_alarms(self):
        alarms = self.timers_now(("alarm",))
        sig = (tuple((t.get("id"), t.get("due"), t.get("label"), bool(t.get("paused"))) for t in alarms),
               self.editing)
        if self.rows_sig.get("alarms") == sig:
            return
        self.rows_sig["alarms"] = sig
        kept = self.editor_texts()
        self.clear(self.alarm_list)
        if not alarms:
            self.empty_row(self.alarm_list, "No alarms set.")
        if self.editing and not any(t["id"] == self.editing for t in alarms):
            self.editing = None     # it rang (a one-off) or was cancelled elsewhere
        short = dict(clock.prefs(), seconds="off")
        for t in alarms:
            if t["id"] == self.editing:
                self.alarm_editor(t, kept)
                continue
            due = datetime.fromtimestamp(t["due"]).astimezone()
            when = clock.hms(due, short)
            paused = bool(t.get("paused"))
            sub = repeat_text(t) + ("  ·  paused" if paused else f"  ·  next {due:%a %d %b}")
            buttons = [(ICON_PLAY if paused else ICON_PAUSE, lambda i=t["id"], p=paused: self.pause(i, p),
                        "Resume: ring again" if paused else "Pause: keep it, but do not ring", False)]
            if not t.get("countdown"):
                buttons.append((ICON_EDIT, lambda i=t["id"]: self.edit(i), "Change its time, repeat, label", False))
            self.list_row(self.alarm_list, t.get("label") or "Alarm", when, sub, buttons=buttons,
                          on_remove=lambda i=t["id"]: self.cancel(i), tip="Cancel this alarm",
                          cls="clk-paused" if paused else None)

    def editor_texts(self):
        """What the open editor holds, so a rebuild under it keeps it."""
        if not getattr(self, "edit_time", None) or not self.editing:
            return None
        return self.edit_time.get_text(), self.edit_label.get_text()

    def alarm_editor(self, t, kept=None):
        """The alarm's row opened in place: time, label, repeat, Save."""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.get_style_context().add_class("clk-row")
        box.get_style_context().add_class("clk-editing")
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        h, m = timers.hm_of(t) if timers else (7, 0)
        self.edit_time = self.entry("7:30", self.save_edit, width=7)
        self.edit_label = self.entry("label (optional)", self.save_edit)
        self.edit_time.set_text(kept[0] if kept else f"{h:02d}:{m:02d}")
        self.edit_label.set_text(kept[1] if kept else t.get("label") or "")
        row.pack_start(self.edit_time, False, False, 0)
        row.pack_start(self.edit_label, True, True, 0)
        box.pack_start(row, False, False, 0)
        self.edit_buttons = {}
        box.pack_start(self.repeat_chips(self.edit_buttons, self.pick_edit_repeat), False, False, 0)
        if self.edit_repeat is None and repeat_choice(t) is None:
            keep = Gtk.Label(label=f"repeats {repeat_text(t)}: kept unless you pick another", xalign=0)
            keep.get_style_context().add_class("ctl-sub")
            box.pack_start(keep, False, False, 0)
        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        actions.pack_end(self.button("Save", self.save_edit), False, False, 0)
        actions.pack_end(self.button("Cancel", self.close_edit, tip="Esc"), False, False, 0)
        box.pack_start(actions, False, False, 0)
        self.alarm_list.pack_start(box, False, False, 0)
        box.show_all()
        self.pick_edit_repeat(self.edit_repeat)
        if not kept:
            self.edit_time.grab_focus()

    def tick_timer(self):
        running = self.timers_now(("timer", "reminder", "focus", "break"))
        sig = tuple(t.get("id") for t in running)
        if self.rows_sig.get("timer") != sig:
            self.rows_sig["timer"] = sig
            self.clear(self.timer_list)
            self.timer_rows = []
            if not running:
                self.empty_row(self.timer_list, "No countdown running.")
            for t in running:
                title = t.get("label") or t.get("kind", "timer").capitalize()
                v, _ = self.list_row(self.timer_list, title, "", t.get("kind", ""),
                                     on_remove=lambda i=t["id"]: self.cancel(i), tip="Cancel it")
                self.timer_rows.append((t, v))
        for t, v in getattr(self, "timer_rows", []):
            v.set_text(span(t["due"] - time.time()))

    def tick_countdowns(self, conf):
        if timers is None:
            return
        try:
            data = timers.load()
            items = [(c, timers.countdown_armed(c, data)) for c in timers.countdowns(data)]
        except Exception:
            items = []
        sig = tuple((c["id"], c["at"], c.get("label"), armed) for c, armed in items)
        if self.rows_sig.get("countdowns") != sig:
            self.rows_sig["countdowns"] = sig
            self.clear(self.cd_list)
            self.cd_rows = []
            if not items:
                self.empty_row(self.cd_list, "No dates counted down to.")
            for c, armed in items:
                bell = (ICON_BELL if armed else ICON_BELL_OFF,
                        lambda i=c["id"], a=armed: self.run([TIMERS, "countdown", "alarm", i, "off" if a else "on"]),
                        "Rings then: click for no alarm" if armed else "No alarm: click to ring then", armed)
                v, _ = self.list_row(self.cd_list, c.get("label") or "Countdown", "", countdown_sub(c["at"], conf),
                                     buttons=[bell], on_remove=lambda i=c["id"]: self.run(
                                         [TIMERS, "countdown", "remove", i]), tip="Remove this countdown")
                self.cd_rows.append((c, v))
        for c, v in getattr(self, "cd_rows", []):
            v.set_text(timers.until_text(c["at"] - time.time()))

    def tick_stopwatch(self):
        data = timers.load() if timers else None
        sw = timers.stopwatch(data) if timers else None
        elapsed, going = sw if sw else (0.0, False)
        self.sw_label.set_text(span(elapsed, tenths=True))
        self.sw_toggle.set_label("Pause" if going else ("Resume" if elapsed else "Start"))
        marks = timers.laps(data) if timers else []
        if self.rows_sig.get("laps") != tuple(marks):
            self.rows_sig["laps"] = tuple(marks)
            self.clear(self.lap_list)
            for n, split, total in timers.lap_rows(marks) if timers else []:
                lab = Gtk.Label(xalign=0)
                lab.get_style_context().add_class("sn-value")
                lab.set_text(f"Lap {n:>2}   {span(split, True):>9}   {span(total, True):>9}")
                self.lap_list.pack_start(lab, False, False, 0)
                lab.show()

    # actions -------------------------------------------------------------------
    def show_tab(self, key, save=True):
        if key != "alarms" and self.editing:
            # Leaving the Alarms tab closes its editor: half-edited, unseen,
            # it would take the next Esc typed on another tab, and come back
            # unasked on the way back.
            self.editing = None
            self.edit_time = None
            self.rows_sig.pop("alarms", None)
        self.tab = key
        self.stack.set_visible_child_name(key)
        for k, b in self.tab_buttons.items():
            self.set_active(b, k == key)
        for sig in [k for k in self.rows_sig if k == key or k.startswith(("plan", "countdowns", "laps"))]:
            self.rows_sig.pop(sig, None)
        self.say("")
        self.tick()
        if save:
            self.save_ui()

    def save_ui(self):
        try:
            write_json(UI_FILE, self.ui)
        except OSError:
            pass

    def say(self, text):
        self.note.set_text(text)
        self.note.set_visible(bool(text))

    def run(self, cmd):
        """A timers.py command; its first line of output (or error) is shown."""
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        except (OSError, subprocess.SubprocessError) as exc:
            self.say(f"could not run timers.py: {exc}")
            return False
        text = (out.stdout or out.stderr).strip().splitlines()
        self.say(text[0].removeprefix("timers.py: ") if text else "")
        for key in ("alarms", "timer", "countdowns", "laps"):
            self.rows_sig.pop(key, None)
        self.ring_sig = None
        self.tick()
        return out.returncode == 0

    def copy(self, text, button):
        try:
            subprocess.run(["wl-copy"], input=text, text=True, timeout=3)
        except (OSError, subprocess.SubprocessError):
            self.say("wl-copy is not installed")
            return
        button.set_label(ICON_DONE)
        GLib.timeout_add(900, lambda: button.set_label(ICON_COPY) or False)

    def write_zones(self):
        save_zones(self.zones, self.pin)
        clock.poke()                # the bar's watcher shows a pin change on this second

    def add_zone(self):
        z = find_zone(self.zone_entry.get_text())
        if not z:
            self.say("No such zone or city. Try a zone name, e.g. America/Bogota.")
            return
        if z not in self.zones:
            self.zones.append(z)
            self.write_zones()
        self.zone_entry.set_text("")
        self.say("")
        self.tick()

    def remove_zone(self, z):
        self.zones = [x for x in self.zones if x != z]
        if self.pin == z:
            self.pin = None
        self.write_zones()
        self.tick()

    def toggle_pin(self, z):
        self.pin = None if self.pin == z else z
        self.write_zones()
        self.say(f"{zone_name(z)} is on the bar: {clock.pin_text(z).strip(' ·')}" if self.pin
                 else f"{zone_name(z)} is off the bar.")
        self.tick()

    def pick_plan(self, z):
        self.plan_zone = z
        self.plan_hour = None
        self.ui["plan"] = z
        self.save_ui()
        self.tick()

    def pick_hour(self, hour):
        if self.plan_hour != hour:
            self.plan_hour = hour
            self.tick()

    def pick_repeat(self, value):
        self.repeat = value
        for v, b in self.repeat_buttons.items():
            self.set_active(b, v == value)

    def add_alarm(self):
        when = self.alarm_time.get_text().strip()
        if not when:
            self.say("Type a time first: 7:30, 7am, 19:45.")
            self.alarm_time.grab_focus()
            return
        if self.run(alarm_command(when, self.repeat, self.alarm_label.get_text())):
            self.alarm_time.set_text("")
            self.alarm_label.set_text("")

    def pause(self, ident, paused):
        self.run([TIMERS, "resume" if paused else "pause", str(ident)])

    def edit(self, ident):
        alarm = next((t for t in self.timers_now(("alarm",)) if t["id"] == ident), None)
        self.editing = ident
        self.edit_repeat = repeat_choice(alarm) if alarm else None
        self.edit_time = None
        self.rows_sig.pop("alarms", None)
        self.tick()

    def pick_edit_repeat(self, value):
        self.edit_repeat = value
        for v, b in getattr(self, "edit_buttons", {}).items():
            self.set_active(b, v == value)

    def close_edit(self):
        self.editing = None
        self.edit_time = None
        self.rows_sig.pop("alarms", None)
        self.tick()

    def save_edit(self):
        if not self.editing or not self.edit_time:
            return
        when = self.edit_time.get_text().strip()
        if not when:
            self.say("Type a time first: 7:30, 7am, 19:45.")
            self.edit_time.grab_focus()
            return
        ident, label = self.editing, self.edit_label.get_text()
        if self.run(edit_command(ident, when, self.edit_repeat, label)):
            self.close_edit()

    def start_timer(self, arg):
        text = arg or self.timer_entry.get_text().strip()
        if not text:
            self.say("Type a length first: 5m, 1h30m tea, 90s.")
            return
        if self.run(timer_command(text)) and not arg:
            self.timer_entry.set_text("")

    def toggle_cd_ring(self):
        self.cd_ring = not self.cd_ring
        self.set_active(self.cd_ring_button, self.cd_ring)

    def add_countdown(self):
        text = self.cd_date.get_text().strip()
        if not text:
            self.say("Type a date first: 2027-01-01, or 2027-01-01 18:30.")
            self.cd_date.grab_focus()
            return
        if self.run(countdown_command(text, self.cd_label.get_text(), self.cd_ring)):
            self.cd_date.set_text("")
            self.cd_label.set_text("")

    def ring_do(self, what, ident):
        self.run([TIMERS, what, str(ident)])

    def cancel(self, ident):
        self.run([TIMERS, "cancel", str(ident)])

    def stopwatch(self, action):
        self.run([TIMERS, "stopwatch", action])
        self.say("")

    def lap(self):
        sw = timers.stopwatch() if timers else None
        if not sw or not sw[1]:
            return
        self.run([TIMERS, "stopwatch", "lap"])
        self.say("")

    def on_key(self, widget, event):
        focus = self.get_focus()
        if event.keyval == Gdk.KEY_Escape:
            # Esc in the alarm editor closes the editor, not the card (only
            # while it shows: show_tab closes it on the way out anyway).
            if self.editing and self.tab == "alarms":
                self.close_edit()
                return True
            # Esc in a filled entry clears it first; the second Esc closes.
            if isinstance(focus, Gtk.Entry) and focus.get_text():
                focus.set_text("")
                return True
        return super().on_key(widget, event)

    def on_ready(self):
        # Again now that the pages are shown: a Gtk.Stack ignores a switch to
        # a child that is not visible yet, so build()'s one did nothing.
        self.stack.set_visible_child_name(self.tab)
        GLib.timeout_add(TICK_MS, self.tick)


def main():
    panelui.run(ClockPanel)


if __name__ == "__main__":
    main()
