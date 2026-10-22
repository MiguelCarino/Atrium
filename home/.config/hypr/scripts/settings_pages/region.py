"""Settings page: date, time & region (region.py).

    TIME ZONE        the system's zone, its offset and next summer-time change,
                     a search over every zone timedatectl knows (Set asks for
                     the password through polkit), and the zone nearest the
                     place saved on the Alerts page as a one-click suggestion
    NETWORK TIME     timedatectl's NTP switch (polkit too) and what chronyd
                     says: the server, and how far off this clock is
    THE BAR'S CLOCK  24 / 12 hours, the seconds, how the date is written
    CALENDAR         which day the calendar panel's weeks start on
    WEATHER          the weather pill's place and units (wttr.in); the
                     emergency-alerts place, read through
                     `emergency-alerts.py config` (never its file), with
                     "Use my Alerts place" (alerts -> weather) and "Use my
                     weather place" (weather -> alerts, through `region.py
                     alerts-place-from-weather`, which runs
                     `emergency-alerts.py place`; it asks first when the
                     country would change, as that resets the alert sources)
    LANGUAGE         read-only: the theme's lang= (the desktop's own words)
                     and the system locale (the apps')

Every control runs region.py, the same command the search bar and a
terminal use, and the page redraws from `region.py show --json`. The bar
follows by itself: clock.py notices a change within a second, the date and
the weather pill are signalled.
"""
from gi.repository import GLib, Gtk  # noqa: F401

from .common import *  # noqa: F401,F403  (the shared helpers and paths)

import os  # noqa: E402
import subprocess  # noqa: E402
from datetime import datetime  # noqa: E402

import region as rg  # noqa: E402  (scripts/region.py: its pure helpers, for the live examples)

PAGE = {"id": "region", "title": "Date, time & region", "icon": "", "group": "System", "order": 50,
        "keywords": ["date", "fecha", "time", "hora", "clock", "reloj", "time zone", "timezone", "ntp",
                     "network time", "12 hour", "24 hour", "am pm", "seconds", "date format", "calendar",
                     "first day of week", "weather", "units", "metric", "imperial", "celsius", "fahrenheit",
                     "language", "locale"]}

REGION = os.path.join(HYPR, "region.py")
SETTINGS = os.path.join(HYPR, "settings.py")
RESULTS = 12            # zones listed under the search; type more to narrow it


def set_chips(chips, items, active):
    """Chips.set. It takes new captions for the same keys too, so the clock
    chips' live examples ("24-hour (03:48:35)") follow the seconds and the
    12-hour choice instead of staying frozen at the first drawing."""
    chips.set(items, active)


def wrapped(text, cls="ctl-sub"):
    lab = dp.label(text, cls)
    lab.set_line_wrap(True)
    lab.set_max_width_chars(90)
    return lab


class Page:
    def __init__(self):
        self.widget = page_box()
        self.zones = None           # timedatectl's list, fetched once (it does not change)
        self.st = None              # the last `region.py show --json`
        self.updating = False       # True while refresh() sets switches
        self.ntp_error = ""         # a refused set-ntp, said once by the next draw
        w = self.widget

        # -- time zone ------------------------------------------------------
        w.pack_start(heading("TIME ZONE"), False, False, 0)
        self.zone_row, self.zone_sub = row("", "…", "checking…")
        w.pack_start(self.zone_row, False, False, 0)
        self.suggest_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        w.pack_start(self.suggest_box, False, False, 0)
        self.search = Gtk.SearchEntry()
        self.search.set_placeholder_text("Search time zones: a city or a region, e.g. madrid, tokyo, pacific")
        self.search.connect("search-changed", lambda _e: self.show_matches())
        w.pack_start(self.search, False, False, 0)
        self.matches = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        w.pack_start(self.matches, False, False, 0)
        self.zone_msg = wrapped("Setting a time zone asks for your password (polkit): it changes the "
                                "system's clock for every program and the logs, not just the bar.")
        w.pack_start(self.zone_msg, False, False, 0)
        w.pack_start(sep(), False, False, 0)

        # -- network time ---------------------------------------------------
        w.pack_start(heading("NETWORK TIME"), False, False, 0)
        self.ntp = Gtk.Switch()
        self.ntp.connect("state-set", self.toggle_ntp)
        self.ntp_row, self.ntp_sub = row("", "Set the time automatically", "", self.ntp)
        w.pack_start(self.ntp_row, False, False, 0)
        self.rtc_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        w.pack_start(self.rtc_box, False, False, 0)
        w.pack_start(sep(), False, False, 0)

        # -- the bar's clock ------------------------------------------------
        w.pack_start(heading("THE BAR'S CLOCK"), False, False, 0)
        self.clock_chips = Chips(lambda v: self.set_pref("clock", v))
        self.seconds_chips = Chips(lambda v: self.set_pref("seconds", v))
        self.date_chips = Chips(lambda v: self.set_pref("date", v))
        for caption, chips in (("Hours", self.clock_chips), ("Seconds", self.seconds_chips),
                               ("Date", self.date_chips)):
            w.pack_start(dp.label(caption, "ctl-sub"), False, False, 0)
            w.pack_start(chips.widget, False, False, 0)
        self.clock_note = wrapped("")
        w.pack_start(self.clock_note, False, False, 0)
        w.pack_start(sep(), False, False, 0)

        # -- calendar -------------------------------------------------------
        w.pack_start(heading("CALENDAR"), False, False, 0)
        w.pack_start(dp.label("Weeks start on", "ctl-sub"), False, False, 0)
        self.week_chips = Chips(lambda v: self.set_pref("week", v))
        w.pack_start(self.week_chips.widget, False, False, 0)
        w.pack_start(wrapped("The calendar panel opens from the date in the bar; its footer's week number "
                             "stays the ISO one (Monday-based)."), False, False, 0)
        w.pack_start(links_row(link("Open the calendar", lambda: spawn(PANEL, "toggle", "calendar"))),
                     False, False, 0)
        w.pack_start(sep(), False, False, 0)

        # -- weather --------------------------------------------------------
        w.pack_start(heading("WEATHER"), False, False, 0)
        place = Gtk.Box(spacing=8)
        self.place = Gtk.Entry()
        self.place.set_placeholder_text("a city, an airport code, ~a landmark or lat,lon; empty = by internet address")
        self.place.set_hexpand(True)
        self.place.connect("activate", lambda _e: self.save_place())
        place.pack_start(self.place, True, True, 0)
        place.pack_start(link("Save place", self.save_place), False, False, 0)
        w.pack_start(place, False, False, 0)
        self.place_sub = wrapped("")
        w.pack_start(self.place_sub, False, False, 0)
        w.pack_start(dp.label("Units", "ctl-sub"), False, False, 0)
        self.units_chips = Chips(lambda v: self.set_pref("units", v))
        w.pack_start(self.units_chips.widget, False, False, 0)
        w.pack_start(links_row(link("Use my Alerts place", self.place_from_alerts),
                               link("Forecast", lambda: spawn(PANEL, "toggle", "weather")),
                               link("Open wttr.in", lambda: spawn(os.path.join(WAYBAR, "wttr.py"), "open"))),
                     False, False, 0)
        # The alerts' place belongs to emergency-alerts.py (the Alerts page);
        # "Use my weather place" hands it the weather pill's place through
        # `region.py alerts-place-from-weather`, which asks emergency-alerts.py.
        alerts, self.alerts_sub = row("", "Emergency alerts place", "",
                                      link("Open Alerts", lambda: spawn(SETTINGS, "alerts")))
        w.pack_start(alerts, False, False, 0)
        self.alerts_note = ""       # what the last "Use my weather place" said
        # A new country also resets the Alerts page's sources and language to
        # that country's, so that case asks first (alerts_links / ask_alerts).
        self.alerts_actions = links_row()
        w.pack_start(self.alerts_actions, False, False, 0)
        self.alerts_links()
        w.pack_start(sep(), False, False, 0)

        # -- language -------------------------------------------------------
        w.pack_start(heading("LANGUAGE"), False, False, 0)
        self.lang_row, self.lang_sub = row("", "…", "", link("Open Theme", lambda: spawn(SETTINGS, "theme")))
        w.pack_start(self.lang_row, False, False, 0)
        self.locale_row, self.locale_sub = row("", "…", "")
        w.pack_start(self.locale_row, False, False, 0)
        self.conf_note = wrapped("")
        w.pack_start(self.conf_note, False, False, 0)

    # -- reading ------------------------------------------------------------------
    def refresh(self):
        background(lambda: run_json(REGION, "show", "--json"), self.draw)
        if self.zones is None:
            background(lambda: rg.all_zones(), self.got_zones)

    def got_zones(self, zones):
        self.zones = zones or []
        self.show_matches()

    def draw(self, st):
        if not st:              # keep the last drawing, and say why it is not new
            self.zone_sub.set_text("region.py did not answer (run it in a terminal to see why)")
            return
        self.st = st
        p = st["prefs"]
        self.updating = True

        # time zone
        title = self.zone_row.get_child_at(1, 0)
        title.set_text(st["timezone"].replace("_", " "))
        now = datetime.fromisoformat(st["now"])
        sub = f"{st['abbrev']}  ·  {st['offset']}  ·  now {st['date_now']}, {st['clock_now']}"
        change = st.get("next_change")
        if change:
            when = datetime.fromisoformat(change["local"])
            sub += (f"  ·  clocks change {when.strftime('%a %d %b %Y')} at "
                    f"{rg.time_text(when, dict(p, seconds='off'))} "
                    f"to {change['offset']}")
        else:
            sub += "  ·  no summer time: the offset stays the same all year"
        self.zone_sub.set_text(sub)
        clear(self.suggest_box)
        guess = st.get("suggested_zone")
        if guess and guess != st["timezone"]:
            grid, _ = row("", f"Suggested: {guess}", st.get("suggested_why", ""),
                          link("Use it", lambda z=guess: self.set_zone(z)))
            self.suggest_box.pack_start(grid, False, False, 0)
        self.suggest_box.show_all()

        # network time
        self.ntp.set_active(st["ntp"])
        self.ntp.set_state(st["ntp"])
        self.ntp.set_sensitive(st.get("can_ntp", True))
        if not st.get("can_ntp", True):
            self.ntp_sub.set_text("no time service installed (chrony or systemd-timesyncd)")
        elif not st["ntp"]:
            self.ntp_sub.set_text("off: the clock runs on its own and drifts. Turning it on asks for your "
                                  "password (polkit).")
        else:
            sync = st.get("sync") or {}
            text = "synchronised" if st["ntp_synced"] else "on, not synchronised yet (no server reached)"
            if sync.get("server"):
                text += f" with {sync['server']}"
            if sync.get("stratum"):
                text += f" (stratum {sync['stratum']})"
            if "offset_s" in sync:
                off = sync["offset_s"]
                text += f"  ·  this clock is {self.duration(abs(off))} {'ahead' if off > 0 else 'behind'}"
            self.ntp_sub.set_text(text + "  ·  by chronyd, the system's time service")
        if self.ntp_error:          # the polkit dialog cancelled, timedatectl refused...
            self.ntp_sub.set_text(f"Not changed: {self.ntp_error}")
            self.ntp_error = ""
        clear(self.rtc_box)
        if st.get("local_rtc"):
            self.rtc_box.pack_start(wrapped(
                "! The hardware clock keeps local time (what Windows does on a dual boot). Linux expects UTC: "
                "summer-time changes and a second system can shift the clock by hours. `timedatectl "
                "set-local-rtc 0` in a terminal switches it (asks for the password); Windows then needs "
                "RealTimeIsUniversal=1 in its registry."), False, False, 0)
        self.rtc_box.show_all()

        # the bar's clock -- the captions are the real look, from region.py's own formatter
        set_chips(self.clock_chips, [("24", f"24-hour  ({rg.time_text(now, dict(p, clock='24'))})"),
                              ("12", f"12-hour  ({rg.time_text(now, dict(p, clock='12'))})")], p["clock"])
        set_chips(self.seconds_chips, [("on", "Show"), ("off", "Hide")], p["seconds"])
        set_chips(self.date_chips, [(key, rg.date_text(now, {"date": key})) for key in rg.CHOICES["date"]], p["date"])
        note = "Click the time in the bar to cycle local → UTC → epoch; the date opens the calendar."
        if st.get("lang") == "ja":
            note += " This theme speaks Japanese, so the bar writes the date as 10月20日 (火) whatever is picked here."
        self.clock_note.set_text(note)

        # calendar
        set_chips(self.week_chips, [(d, d.capitalize()) for d in rg.CHOICES["week"]], p["week"])

        # weather
        if not self.place.has_focus():
            self.place.set_text(p["weather"])
        area = st.get("weather_area")
        place = p["weather"] or "wherever your internet address says you are"
        if area:
            self.place_sub.set_text(f"wttr.in reads \"{place}\" as {area}. The pill refreshes every 30 minutes; "
                                    "a new place is fetched right away.")
        else:
            self.place_sub.set_text(f"\"{place}\": not fetched yet -- the pill asks wttr.in on its next run "
                                    "(right away after Save). If it shows the wrong town, add the country: "
                                    "\"Paris, France\".")
        ap = st.get("alerts_place") or {}
        here = (f"{ap['lat']}, {ap['lon']}" + (f" ({ap['country']})" if ap.get("country") else "")
                if ap.get("lat") and ap.get("lon") else "not set")
        wp = st.get("weather_place")
        self.alerts_sub.set_text(
            f"Now {here}. Earthquake, tsunami and severe-weather alerts use their own place, kept by the "
            "Alerts page. " + (f"Use my weather place sets it to {wp['area']} ({wp['lat']:g}, {wp['lon']:g})."
                               if wp else "Use my weather place works once the weather pill has fetched "
                               "its place.") + (f"\n{self.alerts_note}" if self.alerts_note else ""))
        set_chips(self.units_chips, [("metric", "Metric  (°C, km/h)"), ("imperial", "Imperial  (°F, mph)")], p["units"])

        # language
        lang = {"en": "English", "ja": "Japanese (日本語)"}.get(st.get("lang"), st.get("lang") or "?")
        self.lang_row.get_child_at(1, 0).set_text(f"Desktop: {lang}")
        self.lang_sub.set_text(f"The desktop's own words -- the bar's date, the workspace numbers, the launcher's "
                               f"prompt -- come from the theme ({st.get('theme') or '?'}: lang={st.get('lang')} in "
                               "its theme.conf, en or ja). Pick another theme, or edit its lang=, to change them.")
        self.locale_row.get_child_at(1, 0).set_text(f"Apps: {st.get('locale') or 'unknown'}")
        self.locale_sub.set_text("The system locale: the language and formats apps use. It is the system's "
                                 "(localectl set-locale LANG=…, asks for the password) and applies from the "
                                 "next login.")
        self.conf_note.set_text(f"These bar preferences live in {st.get('conf')} (region.py's docstring "
                                "lists them), so they survive a reload and a new login.")
        self.widget.show_all()
        self.updating = False

    @staticmethod
    def duration(seconds):
        if seconds < 0.001:
            return f"{seconds * 1e6:.0f} µs"
        if seconds < 1:
            return f"{seconds * 1e3:.1f} ms"
        return f"{seconds:.1f} s"

    def show_matches(self):
        clear(self.matches)
        query = self.search.get_text().strip()
        if not query or self.zones is None:
            if query:
                self.matches.pack_start(dp.label("loading the time zones…", "ctl-sub"), False, False, 0)
            self.matches.show_all()
            return
        found = rg.match_zones(self.zones, query)
        current = self.st["timezone"] if self.st else None
        for r in rg.zone_rows(found[:RESULTS]):
            here = r["zone"] == current
            # "-03" style abbreviations only repeat the offset; CST, CEST, JST say more.
            abbrev = "" if r["abbrev"][:1] in "+-" else f"  ·  {r['abbrev']}"
            sub = f"{r['offset']}{abbrev}  ·  {r['time']} there now" + ("  ·  current" if here else "")
            grid, _ = row("\uf017", r["zone"].replace("_", " "), sub,
                          None if here else link("Set", lambda z=r["zone"]: self.set_zone(z)))
            self.matches.pack_start(grid, False, False, 0)
        if not found:
            self.matches.pack_start(dp.label("no time zone has that in its name -- try the nearest big city",
                                             "ctl-sub"), False, False, 0)
        elif len(found) > RESULTS:
            self.matches.pack_start(dp.label(f"{len(found) - RESULTS} more: type more of the name", "ctl-sub"),
                                    False, False, 0)
        self.matches.show_all()

    # -- writing ------------------------------------------------------------------
    def set_pref(self, key, value):
        """region.py set; a refusal (exit 2, the reason on stderr) is shown
        under the weather place or the clock instead of vanishing."""
        def work():
            out = subprocess.run([REGION, "set", key, value], capture_output=True, text=True, timeout=15)
            return out.returncode, (out.stderr or out.stdout).strip()

        def done(result):
            code, text = result
            if code != 0:
                where = self.place_sub if key in ("weather", "units") else self.clock_note
                where.set_text(f"Not saved: {text.removeprefix('region.py: ') or 'region.py failed'}")
                return
            self.refresh()

        background(lambda: self.safe(work), done)

    def save_place(self):
        text = self.place.get_text().strip()
        try:
            rg.normalise("weather", text)
        except ValueError as exc:
            self.place_sub.set_text(str(exc))
            return
        # Let go of the entry so the redraw may set it to what was saved (a
        # page box cannot take the focus itself, so the window drops it).
        top = self.place.get_toplevel()
        if isinstance(top, Gtk.Window):
            top.set_focus(None)
        self.set_pref("weather", text)

    def place_from_alerts(self):
        """The Alerts page's latitude,longitude as the weather place (asked of
        emergency-alerts.py, its owner, in the background)."""
        def done(conf):
            conf = conf or {}
            if conf.get("lat") and conf.get("lon"):
                self.place.set_text(f"{conf['lat']},{conf['lon']}")
                self.save_place()
            else:
                self.place_sub.set_text("no place saved on the Alerts page yet")

        background(lambda: run_json(EMERGENCY, "config"), done)

    def alerts_links(self):
        box = self.alerts_actions
        clear(box)
        box.pack_start(link("Use my weather place", self.ask_alerts), False, False, 0)
        box.show_all()

    def ask_alerts(self):
        """Move the alerts place straight away when the country stays the
        same; when it would change, swap the link for a question first (a
        new country resets the alert sources and their language)."""
        st = self.st or {}
        wp, ap = st.get("weather_place"), st.get("alerts_place") or {}
        if not wp:
            self.alerts_note = ("Not moved: the weather pill has no answer for its place yet "
                                "(Save place, then try again once the pill shows the weather).")
            self.refresh()
            return
        args = rg.place_args(wp, ap)
        if len(args) < 3:
            self.alerts_from_weather()
            return
        box = self.alerts_actions
        clear(box)
        question = wrapped(f"This also changes the country to {args[2]}, which resets the Alerts page's "
                           "sources and language to that country's. Move it?")
        question.set_max_width_chars(60)
        box.pack_start(question, False, False, 0)
        box.pack_start(link("Yes, move it", lambda: (self.alerts_links(), self.alerts_from_weather())),
                       False, False, 0)
        box.pack_start(link("Cancel", self.alerts_links), False, False, 0)
        box.show_all()

    def alerts_from_weather(self):
        """The weather pill's place (where wttr.in put it) as the emergency
        alerts' place: `region.py alerts-place-from-weather` in the
        background, its answer under the row, then a redraw."""
        self.alerts_sub.set_text("moving the alerts place…")

        def work():
            out = subprocess.run([REGION, "alerts-place-from-weather"], capture_output=True, text=True,
                                 timeout=40)
            return out.returncode, (out.stdout or out.stderr).strip()

        def done(result):
            code, text = result
            self.alerts_note = text if code == 0 else f"Not moved: {text or 'region.py failed'}"
            self.refresh()

        background(lambda: self.safe(work), done)

    def set_zone(self, zone):
        """timedatectl waits for the polkit dialog, so this runs in a thread
        with a long timeout; the page says what happened."""
        self.zone_msg.set_text(f"Setting {zone}… (enter your password in the dialog)")

        def work():
            out = subprocess.run([REGION, "timezone", zone], capture_output=True, text=True, timeout=180)
            return out.returncode, (out.stdout or out.stderr).strip()

        def done(result):
            code, text = result
            self.zone_msg.set_text(text if code == 0 else f"Not changed: {text}")
            if code == 0:
                self.search.set_text("")
            self.refresh()

        background(lambda: self.safe(work), done)

    @staticmethod
    def safe(work):
        try:
            return work()
        except (OSError, subprocess.SubprocessError) as exc:
            return 1, str(exc)

    def toggle_ntp(self, _switch, state):
        if self.updating:
            return False
        self.ntp_sub.set_text("asking… (enter your password in the dialog)")

        def work():
            out = subprocess.run([REGION, "ntp", "on" if state else "off"], capture_output=True, text=True,
                                 timeout=180)
            return out.returncode, (out.stdout or out.stderr).strip()

        def done(result):
            code, text = result
            if code != 0:
                self.ntp_error = text or "timedatectl refused"
            GLib.timeout_add(500, lambda: (self.refresh(), False)[1])

        background(lambda: self.safe(work), done)
        return True         # the switch moves when the redraw says it did
