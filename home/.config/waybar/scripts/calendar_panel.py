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

    calendar_panel.py [x,y]   desktop position of the click that opened the panel
"""

import calendar
import os
import sys
from datetime import date, timedelta

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gtk  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import clock  # noqa: E402
import panelui  # noqa: E402

COLUMNS = 7
ROWS = 6                    # fixed: a month that needs six rows must not
                            # resize the panel relative to one that needs five


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
                self.grid.attach(label, column, row + 1, 1, 1)
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

    def draw(self):
        self.month_label.set_text(self.shown.strftime("%B %Y"))

        # The grid always starts on the first-column weekday on or before the
        # 1st, so the columns line up with the weekday headers.
        first = self.shown - timedelta(days=(self.shown.weekday() - self.first) % 7)
        for index, cell in enumerate(self.cells):
            day = first + timedelta(days=index)
            cell.set_text(str(day.day))
            style = cell.get_style_context()
            for name in ("cal-day", "cal-today", "cal-adjacent"):
                style.remove_class(name)
            style.add_class("cal-day")
            if day == self.today:
                style.add_class("cal-today")
            elif day.month != self.shown.month:
                style.add_class("cal-adjacent")

        week = self.today.isocalendar()[1]
        self.footer.set_text(
            f"{self.today.strftime('%A %d %B %Y')} · week {week}"
            + ("" if clock.mode() == "local" else "  (UTC)"))

    def on_ready(self):
        pass                # nothing to poll: a calendar is not a clock


def main():
    panelui.run(Calendar)


if __name__ == "__main__":
    main()
