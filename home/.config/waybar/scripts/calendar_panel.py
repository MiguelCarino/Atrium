#!/usr/bin/env python3
"""Calendar panel — what the date in the bar opens.

A month grid rather than the tooltip waybar's built-in clock offers: a tooltip
vanishes the moment you move the pointer toward it, which makes paging between
months impossible. This is a real window, so ‹ and › work, the scroll wheel
pages, and it stays until it is clicked away.

It follows clock.py's mode: with the bar showing UTC, "today" here means the
UTC day. A local calendar under a UTC clock is exactly the kind of thing that
sends you to the wrong meeting.

The first column is the week= preference in ~/.config/hypr/region.conf
(Monday, Sunday or Saturday; Settings > Date, time & region, via clock.py's
region import), read each time the panel opens. "week N" in the footer stays
the ISO week number, which is Monday-based whatever the first column is.

Events (hypr/scripts/calendar_events.py: the ICS files and subscriptions in
~/.config/hypr/calendars.conf, Evolution's calendars, khal's): a day with
any has a dot under its number; a click on a day lists its events under the
grid (today's when the panel opens), with the time, the title and where.
They are read in a thread once the panel is up -- Evolution can take a
second or two -- so the grid shows at once and the dots come after; a
subscription older than 15 minutes is fetched then too, and the dots
follow. With no calendar at all the list says where to add one.

    calendar_panel.py [x,y]   desktop position of the click that opened the panel
"""

import calendar
import os
import sys
import threading
from datetime import date, datetime, time, timedelta

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import clock  # noqa: E402
import panelui  # noqa: E402

sys.path.insert(0, os.path.expanduser("~/.config/hypr/scripts"))
try:
    import calendar_events  # noqa: E402  (no GTK; the parser and the sources)
except ImportError:
    calendar_events = None

COLUMNS = 7
ROWS = 6                    # fixed: a month that needs six rows must not
                            # resize the panel relative to one that needs five
MAX_LISTED = 6              # events listed under the grid before "+N more"
DOT = "\u2022"


def cell_markup(day, has_events):
    """A day cell: the number, and a small dot under it on a day with
    events (a blank line of the same height on one without, so the grid
    never changes height)."""
    mark = DOT if has_events else " "
    return f"{day}\n<span size='6000'>{mark}</span>"


def grid_range(first_shown):
    """The [start, end) dates the six-week grid shows from its first cell."""
    return first_shown, first_shown + timedelta(days=COLUMNS * ROWS)


def day_heading(day, today):
    """'Today', 'Tomorrow', 'Yesterday', else 'Friday 31 October'."""
    delta = (day - today).days
    return {0: "Today", 1: "Tomorrow", -1: "Yesterday"}.get(delta, day.strftime("%A %d %B"))


def month_start(day):
    return day.replace(day=1)


def shift_month(day, months):
    """Month arithmetic without dateutil: count months, then rebuild the date
    from the quotient and remainder so December wraps cleanly."""
    month = day.month - 1 + months
    year = day.year + month // 12
    return date(year, month % 12 + 1, 1)


class Calendar(panelui.Panel):
    def setup(self):
        self.today = self.today_in_mode()
        self.shown = month_start(self.today)
        self.first = clock.region.first_weekday(clock.prefs()) if clock.region else 0
        self.selected = self.today
        self.events = None          # calendar_events' parsed events, once read
        self.has_sources = True
        self.event_days = set()
        self.twelve = (clock.prefs() or {}).get("clock") == "12" if hasattr(clock, "prefs") else False

    @staticmethod
    def today_in_mode():
        mode = clock.mode()
        return clock.now_in(mode).date()

    # -- widgets ------------------------------------------------------------
    def build(self):
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        header.set_name("cal-header")

        self.prev = Gtk.Button(label="\uf053")      # chevron-left
        self.prev.set_name("cal-prev")
        self.prev.connect("clicked", lambda *_: self.page(-1))
        header.pack_start(self.prev, False, False, 0)

        self.month_label = Gtk.Label(label="")
        self.month_label.set_name("cal-month")
        self.month_label.set_hexpand(True)
        header.pack_start(self.month_label, True, True, 0)

        self.next = Gtk.Button(label="\uf054")      # chevron-right
        self.next.set_name("cal-next")
        self.next.connect("clicked", lambda *_: self.page(1))
        header.pack_end(self.next, False, False, 0)

        self.card.pack_start(header, False, False, 0)

        self.grid = Gtk.Grid()
        self.grid.set_name("cal-grid")
        self.grid.set_column_homogeneous(True)
        self.grid.set_row_homogeneous(True)
        self.card.pack_start(self.grid, False, False, 0)

        self.footer = Gtk.Label(label="")
        self.footer.set_name("cal-footer")
        self.card.pack_start(self.footer, False, False, 0)

        # The selected day's events (today's at first).
        self.day_title = Gtk.Label(label="", xalign=0)
        self.day_title.get_style_context().add_class("kb-heading")
        self.day_title.get_style_context().add_class("cal-events-title")
        self.card.pack_start(self.day_title, False, False, 0)
        self.event_list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.event_list.get_style_context().add_class("cal-events")
        self.card.pack_start(self.event_list, False, False, 0)

        # Paging with the wheel is the one gesture people try on a calendar
        # before they look for the arrows.
        self.add_events(Gdk.EventMask.SCROLL_MASK)
        self.connect("scroll-event", self.on_scroll)

        self.cells = []
        self.fill_grid()
        self.draw()

    def fill_grid(self):
        """Labels are made once and relabelled on every page: rebuilding the
        grid would drop the panel's size on the floor for a frame."""
        for column, weekday in enumerate(self.columns()):
            label = Gtk.Label(label=calendar.day_abbr[weekday][:2])
            label.get_style_context().add_class("cal-weekday")
            self.grid.attach(label, column, 0, 1, 1)

        for row in range(ROWS):
            for column in range(COLUMNS):
                label = Gtk.Label(label="")
                label.set_justify(Gtk.Justification.CENTER)
                # A click picks the day: an EventBox, since a Label has no
                # window of its own to take the click.
                box = Gtk.EventBox()
                box.add(label)
                index = len(self.cells)
                box.connect("button-press-event", lambda _w, _e, i=index: self.pick(i))
                self.grid.attach(box, column, row + 1, 1, 1)
                self.cells.append(label)

    def columns(self):
        """Weekday numbers (0 = Monday) in column order."""
        return [(self.first + i) % 7 for i in range(COLUMNS)]

    # -- state --------------------------------------------------------------
    def page(self, months):
        self.shown = shift_month(self.shown, months)
        self.draw()

    def on_scroll(self, _widget, event):
        if event.direction == Gdk.ScrollDirection.UP:
            self.page(-1)
        elif event.direction == Gdk.ScrollDirection.DOWN:
            self.page(1)
        return True

    def first_cell(self):
        """The grid always starts on the first-column weekday on or before
        the 1st, so the columns line up with the weekday headers."""
        return self.shown - timedelta(days=(self.shown.weekday() - self.first) % 7)

    def pick(self, index):
        self.selected = self.first_cell() + timedelta(days=index)
        if self.selected.month != self.shown.month:
            self.shown = month_start(self.selected)
        self.draw()
        return True

    def occurrences(self, start_day, end_day):
        """The events' occurrences between two dates (local midnight to
        midnight), [] before they are read."""
        if not self.events or calendar_events is None:
            return []
        zone = calendar_events.local_zone()     # DST rules too, not today's offset
        start = datetime.combine(start_day, time(0), zone)
        end = datetime.combine(end_day, time(0), zone)
        try:
            return calendar_events.occurrences(self.events, start, end, zone)
        except Exception as exc:      # noqa: BLE001  (a calendar this parser trips on)
            print(f"calendar_panel: {exc}", file=sys.stderr)
            return []

    def draw(self):
        self.month_label.set_text(self.shown.strftime("%B %Y"))

        first = self.first_cell()
        occs = self.occurrences(*grid_range(first))
        self.event_days = calendar_events.days_with_events(occs) if occs else set()
        for index, cell in enumerate(self.cells):
            day = first + timedelta(days=index)
            has = day in self.event_days
            cell.set_markup(cell_markup(day.day, has))
            style = cell.get_style_context()
            for name in ("cal-day", "cal-today", "cal-adjacent", "cal-selected", "cal-has-events"):
                style.remove_class(name)
            style.add_class("cal-day")
            if day == self.today:
                style.add_class("cal-today")
            elif day.month != self.shown.month:
                style.add_class("cal-adjacent")
            if day == self.selected and day != self.today:
                style.add_class("cal-selected")
            if has:
                style.add_class("cal-has-events")
        self.draw_day(occs)

        week = self.today.isocalendar()[1]
        self.footer.set_text(
            f"{self.today.strftime('%A %d %B %Y')} · week {week}"
            + ("" if clock.mode() == "local" else "  (UTC)"))

    def draw_day(self, occs):
        """The selected day's events under the grid."""
        day = self.selected
        self.day_title.set_text(day_heading(day, self.today).upper())
        for child in self.event_list.get_children():
            self.event_list.remove(child)
        if calendar_events is None:
            self.add_note("calendar_events.py is missing: no events")
        elif self.events is None:
            self.add_note("reading the calendars\u2026")
        elif not self.has_sources and not self.events:
            self.add_note("No calendars yet: list ICS files or URLs in ~/.config/hypr/calendars.conf "
                          "(or use Evolution / khal)")
        else:
            todays = calendar_events.on_day(occs, day)
            if not todays:
                self.add_note("Nothing on this day")
            for o in todays[:MAX_LISTED]:
                self.add_event(o, day)
            if len(todays) > MAX_LISTED:
                self.add_note(f"+{len(todays) - MAX_LISTED} more")
        self.event_list.show_all()
        self.resize(1, 1)           # shrink back when the list got shorter

    def add_note(self, text):
        note = Gtk.Label(label=text, xalign=0)
        note.get_style_context().add_class("ctl-sub")
        note.set_line_wrap(True)
        note.set_max_width_chars(36)
        self.event_list.pack_start(note, False, False, 0)

    def add_event(self, o, day):
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        row.get_style_context().add_class("cal-event")
        when = Gtk.Label(label=calendar_events.time_text(o, day, self.twelve), xalign=0)
        when.get_style_context().add_class("sn-label")
        when.set_width_chars(11)
        when.set_valign(Gtk.Align.START)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        title = Gtk.Label(label=o["summary"], xalign=0)
        title.get_style_context().add_class("sn-value")
        title.set_ellipsize(3)          # Pango.EllipsizeMode.END
        title.set_max_width_chars(30)
        text.pack_start(title, False, False, 0)
        if o.get("location"):
            where = Gtk.Label(label=o["location"].splitlines()[0], xalign=0)
            where.get_style_context().add_class("ctl-sub")
            where.set_ellipsize(3)
            where.set_max_width_chars(30)
            text.pack_start(where, False, False, 0)
        # Where it comes from; a subscription by its host only (its URL may
        # carry a private token).
        row.set_tooltip_text(calendar_events.source_label(o.get("source") or ""))
        row.pack_start(when, False, False, 0)
        row.pack_start(text, True, True, 0)
        self.event_list.pack_start(row, False, False, 0)

    # -- events, read off the GTK thread -----------------------------------------
    def load(self):
        """Read every source in a thread and draw what came back; then, when
        a subscription is older than 15 minutes, fetch it and read again --
        one after the other in the same thread, so an older read can never
        land after a newer one."""
        def read():
            try:
                sources, _opts = calendar_events.read_conf()
                events = calendar_events.load_events()
                has = bool(sources) or bool(calendar_events.khal_paths())
                stale = any(calendar_events.is_url(s) and calendar_events.stale(calendar_events.cache_path(s))
                            for s in sources)
            except Exception as exc:  # noqa: BLE001
                print(f"calendar_panel: {exc}", file=sys.stderr)
                events, has, stale = [], True, False
            GLib.idle_add(self.loaded, events, has)
            return stale

        def work():
            if read():
                try:
                    calendar_events.refresh()
                except Exception as exc:  # noqa: BLE001
                    print(f"calendar_panel: {exc}", file=sys.stderr)
                    return
                read()
        threading.Thread(target=work, daemon=True).start()

    def loaded(self, events, has_sources):
        self.events, self.has_sources = events, has_sources
        self.draw()
        return False

    def on_ready(self):
        # Nothing to poll (a calendar is not a clock): the events once, from
        # what is on disk, then again if a subscription had to be fetched.
        if calendar_events is not None:
            self.load()


def main():
    panelui.run(Calendar)


if __name__ == "__main__":
    main()
