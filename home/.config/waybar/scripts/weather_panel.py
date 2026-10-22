#!/usr/bin/env python3
"""Weather panel — what the weather pill opens.

    NOW        big glyph and temperature, conditions, feels-like, humidity,
               wind, UV
    NEXT 24H   a temperature line over eight 3-hour slots, each with its
               glyph, temperature and chance of rain
    3 DAYS     a range bar per day: where that day's low..high sits within the
               whole three-day spread, so a cold day reads as a bar shifted
               left without reading a number
    footer     sunrise / sunset, when the data is from, and wttr.in

Reads the full answer wttr.py saved when it last ran (every 30 min), so
opening the panel costs no network request. If that file is missing, or more
than an hour old, it fetches once in the background and redraws.

Glyphs and colours come from wttr.py, so the panel and the pill can never
disagree about what "rain" looks like -- and so do the place and the units
(wttr.LOCATION / wttr.UNITS, from ~/.config/hypr/region.conf; Settings >
Date, time & region). A saved answer for another place (the preference just
changed) counts as missing: fetched again, never shown under the new name.

    weather_panel.py [x,y]   desktop position of the click that opened it
"""

import json
import os
import sys
import threading
import time
from datetime import datetime, timedelta

import cairo
import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import panelui  # noqa: E402
import wttr  # noqa: E402
from sensors_panel import Graph  # noqa: E402
import themecolors  # noqa: E402

STALE_AFTER = 3600
SLOTS = 8                   # 8 x 3h = the next 24 hours
# The temperature graph, and the two ends of the day's low-high bar: the
# theme's color.wx_temp / wx_cool / wx_warm (themecolors.py).
CYAN = themecolors.rgb("wx_temp", "#00f0ff")
COOL = themecolors.rgb("wx_cool", "#00f0ff")
WARM = themecolors.rgb("wx_warm", "#ff2a6d")


def load():
    """(weather dict or None, age in seconds)."""
    try:
        age = time.time() - os.path.getmtime(wttr.RAW)
        with open(wttr.RAW) as fh:
            weather = json.load(fh)
    except (OSError, ValueError):
        return None, None
    return (weather, age) if wttr.is_for_here(weather) else (None, None)


def hourly_slots(weather, now):
    """The next SLOTS 3-hour entries from now on, across day boundaries."""
    out = []
    for day in weather.get("weather", []):
        date = datetime.strptime(day["date"], "%Y-%m-%d")
        for hour in day.get("hourly", []):
            when = date + timedelta(hours=int(hour["time"]) // 100)
            if when + timedelta(hours=3) <= now:
                continue
            out.append((when, hour, day))
    return out[:SLOTS]


def markup_glyph(code, night, size):
    sign, colour = wttr.glyph(code, night)
    return f"<span color='{colour}' size='{size}'>{sign}</span>"


def label(text, cls, xalign=0.0, markup=False):
    widget = Gtk.Label()
    (widget.set_markup if markup else widget.set_text)(text)
    widget.get_style_context().add_class(cls)
    widget.set_xalign(xalign)
    return widget


class RangeBar(Gtk.DrawingArea):
    """A day's low..high as a lit segment on a track spanning [lo, hi]."""

    def __init__(self, low, high, lo, hi):
        super().__init__()
        self.low, self.high, self.lo, self.hi = low, high, lo, hi
        self.set_size_request(120, 10)
        self.connect("draw", self.on_draw)

    def on_draw(self, _w, cr):
        w, h = self.get_allocated_width(), self.get_allocated_height()
        y, t = h / 2 - 2, 4
        cr.set_source_rgba(*COOL, 0.10)
        cr.rectangle(0, y, w, t)
        cr.fill()
        span = max(self.hi - self.lo, 1)
        x0 = w * (self.low - self.lo) / span
        x1 = w * (self.high - self.lo) / span
        grad = cairo.LinearGradient(x0, 0, x1, 0)
        grad.add_color_stop_rgb(0, *COOL)     # cool end (cyan)
        grad.add_color_stop_rgb(1, *WARM)     # warm end (magenta)
        # Glow first (a padded copy at low alpha), then the bar itself.
        for pad, alpha in ((4, 0.30), (0, 1.0)):
            cr.push_group()
            cr.set_source(grad)
            cr.rectangle(x0 - pad / 2, y - pad / 2, max(x1 - x0, 2) + pad, t + pad)
            cr.fill()
            cr.pop_group_to_source()
            cr.paint_with_alpha(alpha)
        return False


class Weather(panelui.Panel):
    def build(self):
        self.body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.card.pack_start(self.body, False, False, 0)
        weather, age = load()
        if weather is None or age > STALE_AFTER:
            self.fetching = True
            self.body.pack_start(label("Fetching weather…", "ctl-sub"), False, False, 0)
            threading.Thread(target=self.fetch, daemon=True).start()
        else:
            self.fetching = False
        if weather is not None:
            self.render(weather, age)

    def fetch(self):
        try:
            weather = wttr.fetch()
            with open(wttr.RAW, "w") as fh:
                json.dump(weather, fh)
        except Exception as exc:                # network down, rate-limited
            GLib.idle_add(self.fetch_failed, str(exc))
            return
        GLib.idle_add(self.render, weather, 0)

    def fetch_failed(self, reason):
        if self.fetching:
            self.body.foreach(lambda c: c.destroy())
            self.body.pack_start(label(f"Weather unavailable: {reason}", "ctl-sub"),
                                 False, False, 0)
            self.body.show_all()
        return False

    # -- drawing --------------------------------------------------------------
    def render(self, weather, age):
        self.fetching = False
        self.body.foreach(lambda c: c.destroy())
        now = datetime.now()
        try:
            self.build_now(weather, now)
            self.build_hourly(weather, now)
            self.build_days(weather)
            self.build_footer(weather, age)
        except (KeyError, IndexError, ValueError) as exc:
            self.body.foreach(lambda c: c.destroy())
            self.body.pack_start(label(f"Unexpected data from wttr.in ({exc})", "ctl-sub"),
                                 False, False, 0)
        self.body.show_all()
        return False

    def heading(self, text, right=""):
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        row.pack_start(label(text, "kb-heading"), True, True, 0)
        if right:
            row.pack_end(label(right, "ctl-sub", 1.0), False, False, 0)
        self.body.pack_start(row, False, False, 0)

    def build_now(self, weather, now):
        cur = weather["current_condition"][0]
        area = weather.get("nearest_area", [{}])[0]
        place = area.get("areaName", [{}])[0].get("value", "")
        self.heading("WEATHER", f"{place} · {wttr.LOCATION.upper()}" if place and wttr.LOCATION else place)

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        row.get_style_context().add_class("wx-now")
        row.pack_start(label(markup_glyph(cur["weatherCode"], wttr.is_night(weather, now),
                                          "xx-large"),
                             "wx-big-glyph", markup=True), False, False, 0)
        row.pack_start(label(f"{wttr.val(cur, 'temp_C')}°", "wx-big-temp"), False, False, 0)

        facts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        facts.set_valign(Gtk.Align.CENTER)
        facts.pack_start(label(cur["weatherDesc"][0]["value"].strip(), "wx-desc"),
                         False, False, 0)
        facts.pack_start(label(
            f"feels {wttr.val(cur, 'FeelsLikeC')}°  ·  hum {cur['humidity']}%", "wx-fact"),
            False, False, 0)
        facts.pack_start(label(
            f"wind {wttr.val(cur, 'windspeedKmph')} {wttr.WIND_UNIT} {cur['winddir16Point']}  ·  UV {cur['uvIndex']}",
            "wx-fact"), False, False, 0)
        row.pack_start(facts, True, True, 0)
        self.body.pack_start(row, False, False, 0)

    def build_hourly(self, weather, now):
        slots = hourly_slots(weather, now)
        if not slots:
            return
        self.heading("NEXT 24H")
        temps = [int(wttr.val(h, "tempC")) for _w, h, _d in slots]
        graph = Graph(CYAN, min(temps) - 2, max(temps) + 2, capacity=len(slots))
        graph.set_size_request(-1, 34)
        graph.set_values(temps)
        graph.get_style_context().add_class("wx-graph")
        self.body.pack_start(graph, False, False, 0)

        grid = Gtk.Grid()
        grid.set_column_homogeneous(True)
        grid.get_style_context().add_class("wx-hours")
        for col, (when, hour, day) in enumerate(slots):
            night = wttr.is_night({"weather": [day]}, when + timedelta(minutes=90))
            grid.attach(label(when.strftime("%H"), "wx-hour", 0.5), col, 0, 1, 1)
            grid.attach(label(markup_glyph(hour["weatherCode"], night, "large"),
                              "wx-glyph", 0.5, markup=True), col, 1, 1, 1)
            grid.attach(label(f"{wttr.val(hour, 'tempC')}°", "wx-temp", 0.5), col, 2, 1, 1)
            rain = int(hour.get("chanceofrain", 0))
            grid.attach(label(f"{rain}%" if rain >= 10 else "", "wx-rain", 0.5),
                        col, 3, 1, 1)
        self.body.pack_start(grid, False, False, 0)

    def build_days(self, weather):
        days = weather["weather"][:3]
        self.heading("3 DAYS")
        lo = min(int(wttr.val(d, "mintempC")) for d in days)
        hi = max(int(wttr.val(d, "maxtempC")) for d in days)
        grid = Gtk.Grid()
        grid.set_column_spacing(10)
        grid.set_row_spacing(4)
        grid.get_style_context().add_class("wx-days")
        for row, day in enumerate(days):
            date = datetime.strptime(day["date"], "%Y-%m-%d")
            name = ("Today", "Tomorrow")[row] if row < 2 else date.strftime("%A")
            midday = day["hourly"][min(4, len(day["hourly"]) - 1)]
            rain = max(int(h.get("chanceofrain", 0)) for h in day["hourly"])
            grid.attach(label(name, "wx-day"), 0, row, 1, 1)
            grid.attach(label(markup_glyph(midday["weatherCode"], False, "medium"),
                              "wx-glyph", 0.5, markup=True), 1, row, 1, 1)
            low, high = wttr.val(day, "mintempC"), wttr.val(day, "maxtempC")
            grid.attach(label(f"{low}°", "wx-lo", 1.0), 2, row, 1, 1)
            bar = RangeBar(int(low), int(high), lo, hi)
            bar.set_valign(Gtk.Align.CENTER)
            grid.attach(bar, 3, row, 1, 1)
            grid.attach(label(f"{high}°", "wx-hi"), 4, row, 1, 1)
            grid.attach(label(f"\uf043 {rain}%", "wx-rain", 1.0), 5, row, 1, 1)
        self.body.pack_start(grid, False, False, 0)

    def build_footer(self, weather, age):
        astro = weather["weather"][0]["astronomy"][0]
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        row.get_style_context().add_class("wx-footer")
        rise = astro["sunrise"].lstrip("0")
        sets = astro["sunset"].lstrip("0")
        row.pack_start(label(f"\uf185 {rise}   \uf186 {sets}", "wx-fact"), False, False, 0)
        mins = int((age or 0) // 60)
        row.pack_start(label("  ·  updated now" if mins < 1 else f"  ·  {mins} min ago",
                             "wx-fact"), False, False, 0)
        link = Gtk.Button(label="wttr.in")
        link.get_style_context().add_class("ctl-link")
        link.connect("clicked", self.open_site)
        row.pack_end(link, False, False, 0)
        self.body.pack_start(row, False, False, 0)

    def open_site(self, _button):
        wttr.open_site()
        self.quit()


def main():
    panelui.run(Weather)


if __name__ == "__main__":
    main()
