"""Settings page: emergency alerts (emergency-alerts.py)."""
from gi.repository import GLib, Gtk  # noqa: F401

from .common import *  # noqa: F401,F403  (the shared helpers and paths)

PAGE = {"id": "alerts", "title": "Emergency alerts", "icon": "\uf071", "group": "Safety", "order": 10,
        "keywords": ["emergency", "earthquake", "early warning", "sismo", "alerta sismica", "tsunami",
                     "weather warnings", "civil protection", "siren", "drill", "your place", "location",
                     "country"]}


class Page:
    REGION = {"meteoalarm_region": ("Weather region (MeteoAlarm)", "part of your area's name, e.g. Madrid"),
              "nina_ars": ("Regionalschlüssel (NINA)", "12 digits, from your district"),
              "jp_pref": ("Prefecture (JMA)", "e.g. 東京都")}

    def __init__(self):
        self.widget = page_box()
        w = self.widget
        w.pack_start(heading("YOUR PLACE"), False, False, 0)
        place = Gtk.Box(spacing=8)
        self.lat, self.lon, self.country = Gtk.Entry(), Gtk.Entry(), Gtk.Entry()
        for entry, hint, chars in ((self.lat, "latitude", 9), (self.lon, "longitude", 9), (self.country, "country", 4)):
            entry.set_placeholder_text(hint)
            entry.set_width_chars(chars)
            place.pack_start(entry, False, False, 0)
        save = link("Save place", self.save_place)
        place.pack_start(save, False, False, 0)
        w.pack_start(place, False, False, 0)
        self.place_sub = dp.label("", "ctl-sub")
        w.pack_start(self.place_sub, False, False, 0)
        w.pack_start(sep(), False, False, 0)
        w.pack_start(heading("SOURCES"), False, False, 0)
        self.sources = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        w.pack_start(self.sources, False, False, 0)
        self.extra = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        w.pack_start(self.extra, False, False, 0)
        w.pack_start(sep(), False, False, 0)
        w.pack_start(heading("TRY IT"), False, False, 0)
        w.pack_start(links_row(link("Silent drill (red screens only)", lambda: spawn(EMERGENCY, "test", "--quiet")),
                               link("Full drill (siren and voice)", lambda: spawn(EMERGENCY, "test"))),
                     False, False, 0)
        note = dp.label("These alerts come over the internet and can arrive late: the official sirens, radio "
                        "and your phone's emergency alerts come first.", "ctl-sub")
        note.set_line_wrap(True)
        w.pack_start(note, False, False, 0)
        self.updating = False

    def save_place(self):
        args = [self.lat.get_text().strip(), self.lon.get_text().strip()]
        country = self.country.get_text().strip()
        try:
            float(args[0]), float(args[1])
        except ValueError:
            self.place_sub.set_text("latitude and longitude are numbers, e.g. 19.43 and -99.13")
            return
        run(EMERGENCY, "place", *args, *([country] if country else []))
        self.refresh()

    def refresh(self):
        conf = run_json(EMERGENCY, "config") or {}
        info = run_json(EMERGENCY, "sources", "--json") or {"sources": []}
        status = run_json(EMERGENCY, "status") or {}
        self.updating = True
        self.lat.set_text(conf.get("lat", ""))
        self.lon.set_text(conf.get("lon", ""))
        self.country.set_text(conf.get("country", ""))
        self.place_sub.set_text(f"{conf.get('country', '?')}  ·  alarm language: {conf.get('lang', '?')}  ·  "
                                "a new country switches to its own default sources")
        clear(self.sources)
        for src in info["sources"]:
            sw = Gtk.Switch()
            sw.set_state(src["on"])
            sw.connect("state-set", lambda _s, state, i=src["id"]: self.toggle(i, state))
            st = status.get(src["id"], {})
            sub = src["kind"]
            if src["on"]:
                sub += f"  ·  checked {ago(st.get('last_ok_s_ago'))}"
                if st.get("error"):
                    sub += f"  ·  problem: {st['error'][:80]}"
                if st.get("last_alert"):
                    sub += f"  ·  last alert: {st['last_alert']['headline'][:60]}"
            grid, _ = row("", src["name"], sub, sw)
            self.sources.pack_start(grid, False, False, 0)
        clear(self.extra)
        on = {s["id"] for s in info["sources"] if s["on"]}
        if "sasmex" in on:
            chips = dp.Chips(lambda key: (run(EMERGENCY, "set", "preventive", key), self.refresh()))
            chips.set([("notify", "Notify"), ("alarm", "Full alarm"), ("off", "Off")], conf.get("preventive", "notify"))
            self.extra.pack_start(dp.label("SASMEX preventive alerts (\"Moderado\")", "ctl-sub"), False, False, 0)
            self.extra.pack_start(chips.widget, False, False, 0)
        for key, src in (("meteoalarm_region", "meteoalarm"), ("nina_ars", "nina"), ("jp_pref", "p2pquake")):
            if src in on:
                title, hint = self.REGION[key]
                entry = Gtk.Entry()
                entry.set_text(conf.get(key, ""))
                entry.set_placeholder_text(hint)
                entry.connect("activate", lambda e, k=key: (run(EMERGENCY, "set", k, e.get_text().strip()),
                                                            self.refresh()))
                grid, _ = row("", title, "Enter saves it", entry)
                self.extra.pack_start(grid, False, False, 0)
        self.widget.show_all()
        self.updating = False

    def toggle(self, source, state):
        if not self.updating:
            run(EMERGENCY, "enable" if state else "disable", source)
            GLib.timeout_add(300, lambda: (self.refresh(), False)[1])
        return True


