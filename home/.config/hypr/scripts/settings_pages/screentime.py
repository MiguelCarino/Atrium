"""Settings page (a tab of Timers & alarms): Screen time -- how long you were at the computer today and
this week, in which apps, and the break reminders (screentime.py).

    TODAY           the total, a bar per hour, the apps that took the most
    THIS WEEK       a bar per day for the last seven
    BREAKS          "time for a break" after N minutes without a pause (off
                    as shipped), how long a pause counts as a break, snooze;
                    the 20-20-20 eye reminder (off as shipped)
    COUNTING        the switch for the whole thing (on as shipped), whether
                    idle time is known (hypridle's listener) or only the lock

The bars are drawn here (a Gtk.DrawingArea, the theme's own text colour);
everything else comes from `screentime.py status --json` and every control
runs `screentime.py set`.
"""
from .common import *  # noqa: F401,F403  (the shared helpers and paths; Gtk 3)

from gi.repository import GLib, Gtk  # noqa: E402,F401

import datetime as dt  # noqa: E402
import os  # noqa: E402

PAGE = {"id": "screentime", "title": "Screen time", "icon": "", "group": "Apps", "order": 25,
        "parent": "timers", "tab": "Screen time",
        "keywords": ["screen time", "usage", "time spent", "breaks", "break reminder", "pausa", "descanso",
                     "20-20-20", "eye strain", "eyes", "ojos", "wellbeing", "health", "tiempo de pantalla",
                     "apps used", "stand up"]}

SCREENTIME = os.path.join(HYPR, "screentime.py")
IDLE_SETTINGS = os.path.join(HYPR, "idle-settings.py")
EVERY = [("25", "25 min"), ("50", "50 min"), ("60", "1 h"), ("90", "1 h 30")]
LENGTH = [("2", "2 min"), ("5", "5 min"), ("10", "10 min")]
SNOOZE = [("5", "5 min"), ("10", "10 min"), ("20", "20 min")]
DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


# -- pure helpers (tests/test_screentime_page.py) --------------------------------------------
def hm(seconds):
    minutes = int((seconds or 0) // 60)
    return f"{minutes // 60} h {minutes % 60:02d}" if minutes >= 60 else f"{minutes} min"


def scale(values, height):
    """Bar heights in pixels for values, the biggest one height tall (all 0
    when nothing was counted); a value above zero is at least 1 px."""
    top = max(values or [0])
    if top <= 0:
        return [0 for _ in values]
    return [max(1, round(v / top * height)) if v > 0 else 0 for v in values]


def week_labels(week):
    """[(date, seconds)] -> the day names under the week's bars."""
    out = []
    for date, _ in week:
        try:
            out.append(DAY_NAMES[dt.date.fromisoformat(date).weekday()])
        except ValueError:
            out.append("?")
    return out


def choices(items, current):
    """A chips list with the current value in it even when it is not a preset."""
    current = str(current)
    return items if current in dict(items) else items + [(current, f"{current} min")]


def counting_text(data):
    """The line under "Count screen time"."""
    if data.get("conf", {}).get("count") != "on":
        return "off: nothing is counted or kept"
    if data.get("service") != "active":
        return f"on, but the service is {data.get('service', 'not running')}"
    if data.get("idle_source") == "hypridle":
        return "on: only while you use the keyboard or mouse, or a video plays"
    return "on, but only the lock pauses it until idle detection is turned on below"


def live_text(live):
    if not live:
        return ""
    state = "away" if live.get("idle") else "locked" if live.get("locked") else "active"
    text = f"now {state}  ·  {hm(live.get('streak_s', 0))} since your last break"
    if live.get("next_break_s") is not None and state == "active":
        text += f"  ·  reminder in {hm(live['next_break_s'])}"
    return text


class Bars(Gtk.DrawingArea):
    """Thin bars with labels under some of them, in the theme's text colour."""

    def __init__(self, height=90):
        super().__init__()
        self.values, self.labels = [], []
        self.set_size_request(-1, height)
        self.connect("draw", self.on_draw)

    def set(self, values, labels):
        self.values, self.labels = list(values), list(labels)
        self.queue_draw()

    def on_draw(self, widget, cr):
        width, height = widget.get_allocated_width(), widget.get_allocated_height()
        n = len(self.values)
        if not n:
            return False
        colour = widget.get_style_context().get_color(widget.get_state_flags())
        label_h = 14
        slot = width / n
        gap = max(1.0, slot * 0.2)
        for i, h in enumerate(scale(self.values, height - label_h - 4)):
            cr.set_source_rgba(colour.red, colour.green, colour.blue, 0.75 if h else 0.15)
            x = i * slot + gap / 2
            cr.rectangle(x, height - label_h - max(h, 1), slot - gap, max(h, 1))
            cr.fill()
        cr.set_source_rgba(colour.red, colour.green, colour.blue, 0.7)
        cr.set_font_size(10)
        for i, text in enumerate(self.labels):
            if not text:
                continue
            ext = cr.text_extents(text)
            cr.move_to(i * slot + slot / 2 - ext.width / 2, height - 2)
            cr.show_text(text)
        return False


class Page:
    def __init__(self):
        self.widget = page_box()
        w = self.widget
        self.updating = False

        w.pack_start(heading("TODAY"), False, False, 0)
        grid, self.today_sub = row("", "At the computer today", "")
        w.pack_start(grid, False, False, 0)
        self.hours = Bars()
        w.pack_start(self.hours, False, False, 0)
        self.apps = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        w.pack_start(self.apps, False, False, 0)
        w.pack_start(sep(), False, False, 0)

        w.pack_start(heading("THIS WEEK"), False, False, 0)
        self.week_sub = dp.label("", "ctl-sub")
        w.pack_start(self.week_sub, False, False, 0)
        self.week = Bars(110)
        w.pack_start(self.week, False, False, 0)
        w.pack_start(sep(), False, False, 0)

        w.pack_start(heading("BREAKS"), False, False, 0)
        self.breaks = Gtk.Switch()
        self.breaks.connect("state-set", lambda _s, on: self.set("breaks", "on" if on else "off"))
        grid, self.breaks_sub = row("", "Remind me to take a break", "", self.breaks)
        w.pack_start(grid, False, False, 0)
        self.every = Chips(lambda key: self.set("break_every", key))
        w.pack_start(dp.label("after this long without one", "ctl-sub"), False, False, 0)
        w.pack_start(self.every.widget, False, False, 0)
        self.length = Chips(lambda key: self.set("break_len", key))
        w.pack_start(dp.label("a pause this long counts as a break", "ctl-sub"), False, False, 0)
        w.pack_start(self.length.widget, False, False, 0)
        self.snooze = Chips(lambda key: self.set("snooze", key))
        w.pack_start(dp.label("Snooze puts it off by", "ctl-sub"), False, False, 0)
        w.pack_start(self.snooze.widget, False, False, 0)
        self.eyes = Gtk.Switch()
        self.eyes.connect("state-set", lambda _s, on: self.set("eyes", "on" if on else "off"))
        grid, _ = row("", "Rest your eyes (20-20-20)",
                      "every 20 minutes: look 20 feet (6 m) away for 20 seconds", self.eyes)
        w.pack_start(grid, False, False, 0)
        self.live = dp.label("", "ctl-sub")
        w.pack_start(self.live, False, False, 0)
        w.pack_start(sep(), False, False, 0)

        w.pack_start(heading("COUNTING"), False, False, 0)
        self.count = Gtk.Switch()
        self.count.connect("state-set", lambda _s, on: self.set("count", "on" if on else "off"))
        grid, self.count_sub = row("", "Count screen time", "", self.count)
        w.pack_start(grid, False, False, 0)
        self.idle_link = links_row(link("Turn on idle detection", self.idle_on))
        w.pack_start(self.idle_link, False, False, 0)
        self.more = dp.label("", "ctl-sub")
        self.more.set_line_wrap(True)
        self.more.set_selectable(True)
        w.pack_start(details(self.more), False, False, 0)

    def set(self, key, value):
        if not self.updating:
            background(lambda: run(SCREENTIME, "set", key, value, timeout=30),
                       lambda _o: GLib.timeout_add(300, lambda: (self.refresh(), False)[1]))
        return False

    def idle_on(self):
        """idle-settings.py rewrites hypridle.conf with the same timings, which
        adds the screentime listener, and restarts hypridle."""
        self.count_sub.set_text("adding the idle listener to hypridle...")
        background(lambda: run(IDLE_SETTINGS, "set", timeout=30), lambda _o: self.refresh())

    def refresh(self):
        background(lambda: run_json(SCREENTIME, "status", "--json", timeout=15) or {}, self.draw)

    def draw(self, data):
        if not data:
            self.today_sub.set_text("could not read screentime.py status")
            return
        self.updating = True
        conf = data.get("conf") or {}
        today = data.get("today") or {}
        self.today_sub.set_text(hm(today.get("active_s", 0)))
        self.hours.set(today.get("hours") or [0] * 24, [str(h) if h % 3 == 0 else "" for h in range(24)])
        clear(self.apps)
        for app, seconds in today.get("apps") or []:
            grid, _ = row("", app, "", dp.label(hm(seconds), "ctl-value"))
            self.apps.pack_start(grid, False, False, 0)
        week = data.get("week") or []
        total = sum(s for _, s in week)
        self.week_sub.set_text(f"{hm(total)} in 7 days  ·  {hm(total / 7 if week else 0)} a day")
        self.week.set([s for _, s in week], week_labels(week))
        self.breaks.set_active(conf.get("breaks") == "on")
        self.breaks_sub.set_text("a notification with Snooze" if conf.get("breaks") == "on" else "off")
        self.every.set(choices(EVERY, conf.get("break_every", 50)), str(conf.get("break_every", 50)))
        self.length.set(choices(LENGTH, conf.get("break_len", 5)), str(conf.get("break_len", 5)))
        self.snooze.set(choices(SNOOZE, conf.get("snooze", 10)), str(conf.get("snooze", 10)))
        self.eyes.set_active(conf.get("eyes") == "on")
        self.live.set_text(live_text(data.get("live")))
        self.count.set_active(conf.get("count") == "on")
        self.count_sub.set_text(counting_text(data))
        self.more.set_text(f"Kept for {conf.get('keep', 90)} days in {data.get('folder')}, one file a day: "
                           "minutes per app class and per hour, never window titles. Nothing leaves this "
                           f"computer. Settings: {data.get('conf_path')}. `screentime.py forget 0` deletes it all.")
        self.widget.show_all()
        self.idle_link.set_visible(conf.get("count") == "on" and data.get("idle_source") != "hypridle")
        for chips in (self.every, self.length, self.snooze):
            chips.widget.set_sensitive(conf.get("breaks") == "on")
        self.updating = False
