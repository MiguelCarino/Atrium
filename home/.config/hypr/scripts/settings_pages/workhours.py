"""Settings page: work hours (workhours.py) -- on or off, and everything
about them in one place: when they start and end, the work days, the
pill's word, the time zone they are kept in, the public holidays that are
free on their own, and today as a day off.

Off as shipped (no ~/.config/hypr/workhours.conf). On, the bar shows a pill
with the time left during work hours, the daily brief writes the journal
when they end, focus blocks can be limited to them, and `workhours.py
check` tells a git hook it is work time.

Start, end, days, the label, on / off and the day off are workhours.py's
own commands (enable, disable, set, off-today, on). The time zone and the
holidays have no command: this page writes them with workhours.py's
write_conf(), which keeps every other line of the file, after checking the
zone is a real IANA name and the holiday set is one workhours.py knows.
The page redraws from `workhours.py status --json` after each change.
"""
from gi.repository import GLib, Gtk  # noqa: F401

from .common import *  # noqa: F401,F403  (the shared helpers and paths)

import os  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402

PAGE = {"id": "workhours", "title": "Work hours", "icon": "", "group": "Apps", "order": 21,
        "parent": "timers", "tab": "Work hours",
        "keywords": ["work hours", "horario", "working hours", "office hours", "work days", "day off",
                     "vacation", "holidays", "dias festivos", "work pill", "end of day"]}

WORKHOURS = os.path.join(HYPR, "workhours.py")
STARTS = ["07:00", "08:00", "08:30", "09:00", "09:30", "10:00"]
ENDS = ["16:00", "17:00", "17:30", "18:00", "18:30", "19:00"]
DAYS = [("mon", "Mon"), ("tue", "Tue"), ("wed", "Wed"), ("thu", "Thu"), ("fri", "Fri"), ("sat", "Sat"),
        ("sun", "Sun")]
# workhours.py's holiday sets, by their key; a key not named here shows as itself.
HOLIDAY_NAMES = {"": "None", "mx": "Mexico"}


def _wh():
    """workhours.py as a module (no GTK, cheap): HOLIDAYS and write_conf."""
    if HYPR not in sys.path:
        sys.path.insert(0, HYPR)
    import workhours
    return workhours


# -- pure helpers (tests/test_settings_desk.py) ----------------------------------------
def clock_chips(base, current):
    """The chips for a time: the usual ones, plus the one set when it is
    not among them (kept in order)."""
    items = list(base)
    if current and current not in items:
        items = sorted(items + [current])
    return [(t, t) for t in items]


def days_arg(days, toggled):
    """`workhours.py set days` after clicking one day: added or taken away,
    in week order; "none" when none is left."""
    picked = set(days) ^ {toggled}
    return ",".join(d for d, _ in DAYS if d in picked) or "none"


def minutes(text):
    """'7:45' -> 465; None when it is not H:MM / HH:MM."""
    try:
        h, m = (int(x) for x in text.strip().split(":"))
    except ValueError:
        return None
    return h * 60 + m if 0 <= h < 24 and 0 <= m < 60 else None


def custom_order(start, end, current_end):
    """The two `set` commands for a typed "start-end", in an order that
    never leaves the day ending before it begins in between: the end first
    when the new start is at or after the end set now."""
    s, e = start.strip(), end.strip()
    new_start, old_end = minutes(s), minutes(current_end)
    if new_start is not None and old_end is not None and new_start >= old_end:
        return ("end", e), ("start", s)
    return ("start", s), ("end", e)


def check_zone(text, zones=None):
    """The zone to store ("" = this computer's), or ValueError."""
    text = (text or "").strip()
    if not text:
        return ""
    if zones is None:
        try:
            from zoneinfo import available_timezones
            zones = available_timezones()
        except ImportError:
            zones = set()
    if text in zones:
        return text
    folded = {z.lower(): z for z in zones}
    if text.lower() in folded:
        return folded[text.lower()]
    raise ValueError(f"{text!r} is not a time zone name (like America/New_York)")


def holiday_items(keys):
    """[(key, caption)]: None first, then each holiday set workhours.py knows."""
    return [("", HOLIDAY_NAMES[""])] + [(k, HOLIDAY_NAMES.get(k, k.upper())) for k in sorted(keys)]


def state_text(work, now=None):
    """The line under the switch."""
    if not work.get("enabled"):
        return "off: no pill, no end-of-day, and `workhours.py check` always says free time"
    now = now or time.time()
    if work.get("working") and work.get("until"):
        left = max(0, int(work["until"] - now)) // 60
        state = f"work time, {left // 60} h {left % 60:02d} min left"
    else:
        state = f"free now ({work.get('reason', '')})"
    days = work.get("days") or []
    week = [d for d, _ in DAYS]
    span = ("Mon–Fri" if days == week[:5] else "every day" if days == week else
            ", ".join(dict(DAYS)[d] for d in days if d in dict(DAYS)) or "no days")
    return f"{state}  ·  {work['start']}–{work['end']}, {span}"


def attempt(*cmd, timeout=15):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        return f"{os.path.basename(cmd[0])}: {exc}"
    if r.returncode == 0:
        return ""
    return (r.stderr.strip().splitlines() or [f"{os.path.basename(cmd[0])} failed ({r.returncode})"])[-1]


def write_key(key, value):
    """timezone / holidays straight into workhours.conf ("" on success)."""
    try:
        wh = _wh()
        if wh.load() is None:
            return "work hours are off: switch them on first"
        wh.write_conf({key: value})
        try:
            wh.refresh_bar()
        except Exception:         # noqa: BLE001  (the pill catches up at its next run)
            pass
        return ""
    except Exception as exc:      # noqa: BLE001
        return str(exc)


class Page:
    def __init__(self):
        self.widget = page_box()
        w = self.widget
        self.updating = False
        self.work = None
        self.error = dp.label("", "ctl-sub")
        self.error.set_line_wrap(True)
        self.error.set_no_show_all(True)
        w.pack_start(self.error, False, False, 0)

        w.pack_start(heading("WORK HOURS"), False, False, 0)
        self.switch = Gtk.Switch()
        self.switch.connect("state-set", lambda _s, on: self.toggle(lambda: self.do(WORKHOURS, "enable" if on else "disable")))
        grid, self.sub = row("", "Work hours", "checking…", self.switch)
        w.pack_start(grid, False, False, 0)

        self.box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        w.pack_start(self.box, False, False, 0)
        b = self.box
        grid, self.start_sub = row("", "Start", "on a work day")
        b.pack_start(grid, False, False, 0)
        self.start = self.chips(lambda k: self.do(WORKHOURS, "set", "start", k))
        b.pack_start(self.start.widget, False, False, 0)
        grid, self.end_sub = row("", "End", "the same day")
        b.pack_start(grid, False, False, 0)
        self.end = self.chips(lambda k: self.do(WORKHOURS, "set", "end", k))
        b.pack_start(self.end.widget, False, False, 0)
        self.custom = Gtk.Entry()
        self.custom.set_placeholder_text("another time: 07:45-16:15")
        self.custom.set_width_chars(24)
        self.custom.connect("activate", lambda _e: self.set_custom())
        line = Gtk.Box(spacing=6)
        line.set_margin_start(36)
        line.pack_start(self.custom, False, False, 0)
        b.pack_start(line, False, False, 0)

        grid, self.days_sub = row("", "Work days", "")
        b.pack_start(grid, False, False, 0)
        self.day_buttons = {}
        days = Gtk.Box(spacing=4)
        days.set_margin_start(36)
        for key, caption in DAYS:
            btn = Gtk.Button(label=caption)
            btn.get_style_context().add_class("dev-pick")
            btn.set_can_focus(False)
            btn.connect("clicked", lambda _b, k=key: self.toggle_day(k))
            self.day_buttons[key] = btn
            days.pack_start(btn, False, False, 0)
        b.pack_start(days, False, False, 0)

        self.label_entry = Gtk.Entry()
        self.label_entry.set_width_chars(16)
        self.label_entry.set_max_length(24)
        self.label_entry.connect("activate", lambda e: self.do(WORKHOURS, "set", "label", e.get_text()))
        grid, self.label_sub = row("", "The pill's word", "Enter saves it", self.label_entry)
        b.pack_start(grid, False, False, 0)

        self.zone_entry = Gtk.Entry()
        self.zone_entry.set_width_chars(22)
        self.zone_entry.set_placeholder_text("this computer's")
        self.zone_entry.connect("activate", lambda e: self.set_zone(e.get_text()))
        grid, self.zone_sub = row("", "Time zone of the hours", "", self.zone_entry)
        b.pack_start(grid, False, False, 0)

        grid, self.hol_sub = row("", "Public holidays", "")
        b.pack_start(grid, False, False, 0)
        self.holidays = self.chips(self.set_holidays)
        b.pack_start(self.holidays.widget, False, False, 0)

        self.off_switch = Gtk.Switch()
        self.off_switch.connect("state-set", lambda _s, on: self.toggle(
            lambda: self.do(WORKHOURS, "off-today" if on else "on")))
        grid, self.off_sub = row("", "Today is a day off", "", self.off_switch)
        b.pack_start(grid, False, False, 0)

        more = dp.label("workhours.py keeps all of it in ~/.config/hypr/workhours.conf (switching off keeps "
                        "it beside, as workhours.conf.off, for switching on again). The git side -- asking "
                        "before a commit to your own repos in work time -- is a hook you wire yourself: "
                        "`workhours.py personal && ! workhours.py check`.", "ctl-sub")
        more.set_line_wrap(True)
        more.set_xalign(0)
        w.pack_start(details(more), False, False, 0)

    @staticmethod
    def chips(on_pick):
        chips = Chips(on_pick)
        chips.widget.set_max_children_per_line(8)
        chips.widget.set_halign(Gtk.Align.START)
        chips.widget.set_margin_start(36)
        plain_set = chips.set

        def set_items(items, active):
            plain_set(items, active)
            chips.widget.set_min_children_per_line(max(1, min(len(items), 8)))
        chips.set = set_items
        return chips

    # -- actions ---------------------------------------------------------------------
    def do(self, *cmd):
        if not self.updating:
            background(lambda: attempt(*cmd), self.done)

    def done(self, error):
        self.error.set_text(f"!  {error}" if error else "")
        self.error.set_visible(bool(error))
        self.refresh()

    def toggle(self, act):
        if not self.updating:
            act()
        return True

    def toggle_day(self, key):
        if self.work:
            self.do(WORKHOURS, "set", "days", days_arg(self.work.get("days") or [], key))

    def set_custom(self):
        text = self.custom.get_text().replace("–", "-").strip()
        start, sep_, end = text.partition("-")
        if not sep_:
            self.done("write it as start-end, like 07:45-16:15")
            return
        self.custom.set_text("")
        first, second = custom_order(start, end, (self.work or {}).get("end", "18:00"))
        background(lambda: attempt(WORKHOURS, "set", *first) or attempt(WORKHOURS, "set", *second), self.done)

    def set_zone(self, text):
        try:
            zone = check_zone(text)
        except ValueError as exc:
            self.done(str(exc))
            return
        background(lambda: write_key("timezone", zone), self.done)

    def set_holidays(self, key):
        if self.updating:
            return
        if key not in ("",) and key not in getattr(_wh(), "HOLIDAYS", {}):
            self.done(f"workhours.py knows no holidays called {key!r}")
            return
        background(lambda: write_key("holidays", key), self.done)

    # -- drawing ---------------------------------------------------------------------
    def refresh(self):
        background(lambda: run_json(WORKHOURS, "status", "--json", timeout=15), self.draw)

    def draw(self, work):
        if not work:
            self.sub.set_text("workhours.py did not answer")
            return
        self.updating = True
        self.work = work
        on = bool(work.get("enabled"))
        self.switch.set_state(on)
        self.switch.set_active(on)
        self.sub.set_text(state_text(work))
        self.box.set_sensitive(on)
        self.start.set(clock_chips(STARTS, work["start"]), work["start"])
        self.end.set(clock_chips(ENDS, work["end"]), work["end"])
        for key, btn in self.day_buttons.items():
            ctx = btn.get_style_context()
            (ctx.add_class if key in work.get("days", []) else ctx.remove_class)("active")
        self.days_sub.set_text("none picked: work time never starts" if not work.get("days") else
                               "click a day to add or take it away")
        if not self.label_entry.has_focus():
            self.label_entry.set_text(work.get("label") or "Work")
        self.label_sub.set_text("the pill says it while work time runs  ·  Enter saves it")
        if not self.zone_entry.has_focus():
            self.zone_entry.set_text(work.get("timezone") or "")
        self.zone_sub.set_text((f"hours kept in {work['timezone']}, shown in yours" if work.get("timezone")
                                else "this computer's") + "  ·  an IANA name, Enter saves it")
        try:
            keys = list(getattr(_wh(), "HOLIDAYS", {}))
        except Exception:         # noqa: BLE001
            keys = []
        self.holidays.set(holiday_items(keys), work.get("holidays") or "")
        if work.get("holiday"):
            self.hol_sub.set_text(f"today is one: {work['holiday']}")
        elif work.get("next_holiday"):
            day, name = work["next_holiday"]
            self.hol_sub.set_text(f"free on their own  ·  next: {name}, {day}")
        else:
            self.hol_sub.set_text("free on their own, whatever the days say")
        self.off_switch.set_state(bool(work.get("off_today")))
        self.off_switch.set_active(bool(work.get("off_today")))
        self.off_sub.set_text("free until midnight" if work.get("off_today") else
                              "vacation, a sick day: free until midnight")
        self.widget.show_all()
        self.error.set_visible(bool(self.error.get_text()))
        self.updating = False
