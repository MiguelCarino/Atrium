#!/usr/bin/env python3
"""Clock panel — what the time in the bar opens: the time three ways, world
clocks, alarms, a countdown and a stopwatch, in one card.

    clock_panel.py [x,y]   desktop position of the click that opened the panel

The top of the card is always the same, whichever tab is open: the local
time large, the date under it, then UTC and the Unix epoch, each with a copy
button (wl-copy) -- the readings the bar's pill cycles through, side by side
here, so you never have to cycle to read one. (The pill still cycles: right
click, clock.py cycle.)

Below, four tabs (the last one used is reopened, in clock-panel.json):

  World      a row per time zone you added: the city, its time, how far it is
             from yours ("+7 h"), and "tomorrow" / "yesterday" when its date
             is not yours. Add one by typing a city or zone ("Tokyo",
             "Europe/Lisbon"; Tab completes from the system's zoneinfo), ✕
             removes it. Kept in $XDG_STATE_HOME/hypr/world-clocks.json.
  Alarms     the alarms set (timers.py: they ring with this card closed, the
             bar restarted, after a reboot), with ✕ to cancel; set a new one
             from a time ("7:30", "7am", "19:45"), Once / Daily / Weekdays /
             Weekends and an optional label.
  Timer      the countdowns running (timers, reminders, focus rounds), each
             with its time left and ✕; quick buttons 1 / 5 / 10 / 15 / 25 min
             and 1 h, or a free entry ("1h30m tea", "90s", "2:30").
  Stopwatch  timers.py's stopwatch -- the same one the bar's timers pill shows
             and the launcher's "stopwatch" starts -- with Start / Pause,
             Reset and laps (laps live only while the card is open).

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
from datetime import datetime, timezone

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
WIDTH = 420
TICK_MS = 250

ICON_COPY, ICON_DONE, ICON_X = "", "", ""      # Font Awesome


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
    zones = read_json(ZONES_FILE, None)
    if not isinstance(zones, list):
        return list(DEFAULT_ZONES)
    return [z for z in zones if isinstance(z, str)]


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


def utc_offset(delta):
    """A UTC offset as people write it: 'UTC−6', 'UTC+5:30', 'UTC'."""
    secs = int(delta.total_seconds()) if delta is not None else 0
    if not secs:
        return "UTC"
    sign = "+" if secs > 0 else "−"
    h, rest = divmod(abs(secs), 3600)
    return f"UTC{sign}{h}" + (f":{rest // 60:02d}" if rest else "")


def alarm_command(when, repeat, label):
    return [TIMERS, "alarm", when.strip()] + ([repeat] if repeat else []) + label.split()


def timer_command(text):
    return [TIMERS, "timer"] + text.split()


# -- the card ------------------------------------------------------------------------
class ClockPanel(panelui.Panel):
    def setup(self):
        self.zones = load_zones()
        self.ui = read_json(UI_FILE, {})
        self.tab = self.ui.get("tab") if self.ui.get("tab") in dict(TABS) else "world"
        self.laps = []
        self.rows_sig = {}          # tab -> what its list was built from (rebuild only on change)
        self.message = ""

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

    def section(self, title):
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
        chips = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self.repeat = ""
        self.repeat_buttons = {}
        for label, value in REPEATS:
            b = self.button(label, lambda v=value: self.pick_repeat(v), cls="dev-pick chip")
            chips.pack_start(b, True, True, 0)
            self.repeat_buttons[value] = b
        page.pack_start(chips, False, False, 0)
        page.pack_start(self.button("Set alarm", self.add_alarm), False, False, 4)
        self.pick_repeat("")
        return page

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
    def list_row(self, box, title, value, sub="", on_remove=None, tip=None):
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        row.get_style_context().add_class("clk-row")
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
            x = self.button(ICON_X, on_remove, cls="ctl-link", tip=tip)
            row.pack_end(x, False, False, 0)
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
        page = self.tab
        if page == "world":
            self.tick_world(now, conf)
        elif page == "alarms":
            self.tick_alarms()
        elif page == "timer":
            self.tick_timer()
        elif page == "stopwatch":
            self.tick_stopwatch()
        return True

    def tick_world(self, now, conf):
        sig = tuple(self.zones)
        if self.rows_sig.get("world") != sig:
            self.rows_sig["world"] = sig
            self.clear(self.world_list)
            self.world_rows = []
            if not self.zones:
                self.empty_row(self.world_list, "No other zones yet: add a city below.")
            for z in self.zones:
                v, s = self.list_row(self.world_list, zone_name(z), "", z,
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

    def timers_now(self, kinds):
        if timers is None:
            return []
        try:
            return [t for t in timers.running() if t.get("kind") in kinds]
        except Exception:
            return []

    def tick_alarms(self):
        alarms = self.timers_now(("alarm",))
        sig = tuple((t.get("id"), t.get("due"), t.get("label")) for t in alarms)
        if self.rows_sig.get("alarms") == sig:
            return
        self.rows_sig["alarms"] = sig
        self.clear(self.alarm_list)
        if not alarms:
            self.empty_row(self.alarm_list, "No alarms set.")
        for t in alarms:
            due = datetime.fromtimestamp(t["due"]).astimezone()
            when = clock.hms(due, dict(clock.prefs(), seconds="off"))
            sub = repeat_text(t) + f"  ·  next {due:%a %d %b}"
            self.list_row(self.alarm_list, t.get("label") or "Alarm", when, sub,
                          on_remove=lambda i=t["id"]: self.cancel(i), tip="Cancel this alarm")

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

    def tick_stopwatch(self):
        sw = timers.stopwatch() if timers else None
        elapsed, going = sw if sw else (0.0, False)
        self.sw_label.set_text(span(elapsed, tenths=True))
        self.sw_toggle.set_label("Pause" if going else ("Resume" if elapsed else "Start"))

    # actions -------------------------------------------------------------------
    def show_tab(self, key, save=True):
        self.tab = key
        self.stack.set_visible_child_name(key)
        for k, b in self.tab_buttons.items():
            ctx = b.get_style_context()
            (ctx.add_class if k == key else ctx.remove_class)("active")
        self.rows_sig.pop(key, None)
        self.say("")
        self.tick()
        if save:
            self.ui["tab"] = key
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
        self.say(text[0] if text else "")
        for key in ("alarms", "timer"):
            self.rows_sig.pop(key, None)
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

    def add_zone(self):
        z = find_zone(self.zone_entry.get_text())
        if not z:
            self.say("No such zone or city. Try a zone name, e.g. America/Bogota.")
            return
        if z not in self.zones:
            self.zones.append(z)
            write_json(ZONES_FILE, self.zones)
        self.zone_entry.set_text("")
        self.say("")
        self.tick()

    def remove_zone(self, z):
        self.zones = [x for x in self.zones if x != z]
        write_json(ZONES_FILE, self.zones)
        self.tick()

    def pick_repeat(self, value):
        self.repeat = value
        for v, b in self.repeat_buttons.items():
            ctx = b.get_style_context()
            (ctx.add_class if v == value else ctx.remove_class)("active")

    def add_alarm(self):
        when = self.alarm_time.get_text().strip()
        if not when:
            self.say("Type a time first: 7:30, 7am, 19:45.")
            self.alarm_time.grab_focus()
            return
        if self.run(alarm_command(when, self.repeat, self.alarm_label.get_text())):
            self.alarm_time.set_text("")
            self.alarm_label.set_text("")

    def start_timer(self, arg):
        text = arg or self.timer_entry.get_text().strip()
        if not text:
            self.say("Type a length first: 5m, 1h30m tea, 90s.")
            return
        if self.run(timer_command(text)) and not arg:
            self.timer_entry.set_text("")

    def cancel(self, ident):
        self.run([TIMERS, "cancel", str(ident)])

    def stopwatch(self, action):
        if action == "reset":
            self.laps = []
            self.clear(self.lap_list)
        self.run([TIMERS, "stopwatch", action])
        self.say("")

    def lap(self):
        sw = timers.stopwatch() if timers else None
        if not sw or not sw[1]:
            return
        total = sw[0]
        split = total - (self.laps[-1] if self.laps else 0.0)
        self.laps.append(total)
        lab = Gtk.Label(xalign=0)
        lab.get_style_context().add_class("sn-value")
        lab.set_text(f"Lap {len(self.laps):>2}   {span(split, True):>9}   {span(total, True):>9}")
        self.lap_list.pack_start(lab, False, False, 0)
        self.lap_list.reorder_child(lab, 0)
        lab.show()

    def on_key(self, widget, event):
        # Esc in a filled entry clears it first; the second Esc closes.
        focus = self.get_focus()
        if event.keyval == Gdk.KEY_Escape and isinstance(focus, Gtk.Entry) and focus.get_text():
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
