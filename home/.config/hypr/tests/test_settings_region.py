"""region.py (Settings > Date, time & region) and what reads it: the bar's
clock (clock.py), the calendar's first column, the weather pill (wttr.py).

Pure logic only, on fixed dates: nothing here runs timedatectl, signals the
bar or reads ~/.config/hypr/region.conf (REGION_CONF points at the scratch
folder before anything is imported)."""
import os
import sys
import time
import unittest
from datetime import date, datetime, timedelta, timezone

import helpers

os.environ["REGION_CONF"] = os.path.join(helpers.SCRATCH, "region.conf")
region = helpers.import_script("region.py", "region")
sys.path.insert(0, os.path.expanduser("~/.config/waybar/scripts"))
import clock  # noqa: E402
import wttr  # noqa: E402

AM = datetime(2026, 10, 20, 3, 4, 5)
PM = datetime(2026, 10, 20, 15, 4, 5)


class Conf(unittest.TestCase):
    def setUp(self):
        self.path = os.path.join(helpers.SCRATCH, f"region-{self._testMethodName}.conf")

    def test_never_the_real_file(self):
        self.assertTrue(region.CONF.startswith(helpers.SCRATCH))

    def test_defaults_without_a_file(self):
        self.assertEqual(region.prefs(os.path.join(helpers.SCRATCH, "missing.conf")), region.DEFAULTS)

    def test_parse_skips_comments_typos_and_bad_values(self):
        conf = region.parse("# clock=12\nclock=13\nseconds = off\nbogus=1\nweather= Paris, France \nweek")
        self.assertEqual(conf["clock"], "24")           # 13 is no choice: the default stays
        self.assertEqual(conf["seconds"], "off")
        self.assertEqual(conf["weather"], "Paris, France")
        self.assertNotIn("bogus", conf)

    def test_empty_weather_is_kept(self):
        self.assertEqual(region.parse("weather=\n")["weather"], "")

    def test_save_round_trip_and_cache_notices_change(self):
        region.save("clock", "12h", self.path)
        self.assertEqual(region.prefs(self.path)["clock"], "12")
        region.save("week", "Domingo", self.path)
        later = time.time() + 5         # mtime_ns may not move within one tick on some filesystems
        os.utime(self.path, (later, later))
        conf = region.prefs(self.path)
        self.assertEqual((conf["clock"], conf["week"]), ("12", "sunday"))
        self.assertFalse(os.path.exists(self.path + ".tmp"))

    def test_normalise(self):
        self.assertEqual(region.normalise("Units", "F"), ("units", "imperial"))
        self.assertEqual(region.normalise("seconds", "no"), ("seconds", "off"))
        self.assertEqual(region.normalise("weather", "  Mexico   City "), ("weather", "Mexico City"))
        for key, value in (("clock", "13"), ("nope", "1"), ("weather", "a/b"), ("weather", "x" * 81),
                           ("weather", "q?format=3")):
            with self.assertRaises(ValueError):
                region.normalise(key, value)

    def test_render_parses_back(self):
        conf = dict(region.DEFAULTS, clock="12", weather="~Eiffel Tower")
        self.assertEqual(region.parse(region.render(conf)), conf)


class Formats(unittest.TestCase):
    def test_time(self):
        self.assertEqual(region.time_text(AM, {"clock": "24", "seconds": "on"}), "03:04:05")
        self.assertEqual(region.time_text(PM, {"clock": "24", "seconds": "off"}), "15:04")
        self.assertEqual(region.time_text(PM, {"clock": "12", "seconds": "on"}), "3:04:05 PM")
        self.assertEqual(region.time_text(AM, {"clock": "12", "seconds": "off"}), "3:04 AM")

    def test_twelve_hour_noon_and_midnight(self):
        conf = {"clock": "12", "seconds": "off"}
        self.assertEqual(region.time_text(datetime(2026, 1, 1, 0, 5), conf), "12:05 AM")
        self.assertEqual(region.time_text(datetime(2026, 1, 1, 12, 5), conf), "12:05 PM")

    def test_date(self):
        self.assertEqual(region.date_text(AM, {"date": "short"}), "Tue, Oct 20")
        self.assertEqual(region.date_text(AM, {"date": "dmy"}), "Tue 20 Oct")
        self.assertEqual(region.date_text(AM, {"date": "iso"}), "2026-10-20")
        self.assertEqual(region.date_text(AM, {"date": "??"}), "Tue, Oct 20")

    def test_clock_uses_the_preferences(self):
        moment = PM.replace(tzinfo=timezone.utc)
        conf = {"clock": "12", "seconds": "off", "date": "iso"}
        self.assertEqual(clock.clock_text("local", moment, conf), "3:04 PM")
        self.assertEqual(clock.clock_text("utc", moment, conf), "3:04 PM Z")
        self.assertEqual(clock.clock_text("epoch", moment, conf), str(int(moment.timestamp())))
        if clock.lang() != "ja":
            self.assertEqual(clock.day_text("local", moment, conf), "2026-10-20")

    def test_clock_defaults_are_the_old_look(self):
        moment = PM.replace(tzinfo=timezone.utc)
        self.assertEqual(clock.clock_text("local", moment, dict(region.DEFAULTS)), "15:04:05")


class Week(unittest.TestCase):
    def test_columns(self):
        self.assertEqual(region.week_columns(0), [0, 1, 2, 3, 4, 5, 6])
        self.assertEqual(region.week_columns(6), [6, 0, 1, 2, 3, 4, 5])
        self.assertEqual(region.first_weekday({"week": "saturday"}), 5)

    def test_grid_start(self):
        october = date(2026, 10, 1)             # a Thursday
        self.assertEqual(region.grid_start(october, 0), date(2026, 9, 28))     # Monday
        self.assertEqual(region.grid_start(october, 6), date(2026, 9, 27))     # Sunday
        self.assertEqual(region.grid_start(october, 5), date(2026, 9, 26))     # Saturday
        self.assertEqual(region.grid_start(october, 3), october)               # starts on the 1st

    def test_grid_start_is_always_the_first_column(self):
        for first in range(7):
            for month in range(1, 13):
                start = region.grid_start(date(2027, month, 1), first)
                self.assertEqual(start.weekday(), first)
                self.assertLess(date(2027, month, 1) - start, timedelta(days=7))


class Zones(unittest.TestCase):
    NOW = datetime(2026, 10, 20, 9, 0, tzinfo=timezone.utc)

    def test_offset_text(self):
        self.assertEqual(region.offset_text(timedelta(hours=-6)), "UTC−06:00")
        self.assertEqual(region.offset_text(timedelta(hours=5, minutes=30)), "UTC+05:30")
        self.assertEqual(region.offset_text(timedelta(0)), "UTC")

    def test_zone_now(self):
        moment, offset = region.zone_now("Asia/Kolkata", self.NOW)
        self.assertEqual((moment.hour, moment.minute, offset), (14, 30, "UTC+05:30"))
        self.assertIsNone(region.zone_now("Nowhere/Atlantis", self.NOW))

    def test_next_change(self):
        when, offset = region.next_change("America/New_York", self.NOW)
        self.assertEqual(when, datetime(2026, 11, 1, 6, 0, tzinfo=timezone.utc))
        self.assertEqual(offset, "UTC−05:00")
        self.assertIsNone(region.next_change("America/Mexico_City", self.NOW))   # no DST since 2022
        self.assertIsNone(region.next_change("Nowhere/Atlantis", self.NOW))

    def test_match_zones(self):
        zones = ["America/Mexico_City", "Europe/London", "Mexico/General", "America/New_York",
                 "Asia/Tokyo", "Canada/Newfoundland"]
        self.assertEqual(region.match_zones(zones, "mexico")[0], "America/Mexico_City")
        self.assertEqual(region.match_zones(zones, "new york"), ["America/New_York"])
        self.assertEqual(region.match_zones(zones, "YORK america"), ["America/New_York"])
        self.assertEqual(region.match_zones(zones, "new", 1), ["America/New_York"])
        self.assertEqual(region.match_zones(zones, "zzz"), [])
        self.assertEqual(len(region.match_zones(zones, "  ")), len(zones))

    def test_iso6709(self):
        self.assertEqual(region.iso6709("+4230+00131"), (42.5, 1 + 31 / 60))
        lat, lon = region.iso6709("-0731-07928")
        self.assertAlmostEqual(lat, -(7 + 31 / 60))
        lat, lon = region.iso6709("+404251-0740023")
        self.assertAlmostEqual(lat, 40 + 42 / 60 + 51 / 3600)
        with self.assertRaises(ValueError):
            region.iso6709("north")

    def test_nearest_zone(self):
        table = region.zone_table("# comment\nMX\t+1924-09909\tAmerica/Mexico_City\tCentral Mexico\n"
                                  "ES\t+4024-00341\tEurope/Madrid\tSpain (mainland)\n"
                                  "JP\t+353916+1394441\tAsia/Tokyo\nbroken line\n")
        self.assertEqual(len(table), 3)
        self.assertEqual(region.nearest_zone(19.4, -99.1, table), "America/Mexico_City")
        self.assertEqual(region.nearest_zone(41.4, 2.2, table), "Europe/Madrid")     # Barcelona
        self.assertIsNone(region.nearest_zone(0, 0, []))

    def test_distance(self):
        self.assertAlmostEqual(region.distance_km(0, 0, 0, 1), 111.2, delta=0.2)


class SystemText(unittest.TestCase):
    def test_tracking(self):
        out = region.parse_tracking("Reference ID    : 84F81E03 (132.248.30.3)\nStratum         : 2\n"
                                    "System time     : 0.000261269 seconds slow of NTP time\n")
        self.assertEqual(out["server"], "132.248.30.3")
        self.assertEqual(out["stratum"], 2)
        self.assertAlmostEqual(out["offset_s"], -0.000261269)
        self.assertEqual(region.parse_tracking("506 Cannot talk to daemon"), {})

    def test_props(self):
        self.assertEqual(region.parse_props("Timezone=UTC\nNTP=yes\nnoise"), {"Timezone": "UTC", "NTP": "yes"})

    def test_area_name(self):
        weather = {"_location": "Paris", "nearest_area": [{"areaName": [{"value": "Paris"}],
                                                            "region": [{"value": "Ile-de-France"}],
                                                            "country": [{"value": "France"}]}]}
        self.assertEqual(region.area_name(weather, "Paris"), "Paris, Ile-de-France, France")
        self.assertEqual(region.area_name(weather, "Lyon"), "")         # an answer for another place
        unstamped = dict(weather)
        del unstamped["_location"]
        self.assertEqual(region.area_name(unstamped, "cdmx"), "Paris, Ile-de-France, France")
        self.assertEqual(region.area_name(None, "x"), "")

    def test_only_a_real_clock_watcher_is_signalled(self):
        self.assertFalse(region._is_clock_watcher(os.getpid()))     # this is not clock.py
        self.assertFalse(region._is_clock_watcher(2 ** 22 + 7))     # no such process


class Weather(unittest.TestCase):
    CUR = {"temp_C": "12", "temp_F": "54", "windspeedKmph": "8", "windspeedMiles": "5"}

    def test_val_units(self):
        self.assertEqual(wttr.val(self.CUR, "temp_C", "metric"), "12")
        self.assertEqual(wttr.val(self.CUR, "temp_C", "imperial"), "54")
        self.assertEqual(wttr.val(self.CUR, "windspeedKmph", "imperial"), "5")
        self.assertEqual(wttr.val({"tempC": "3"}, "tempC", "imperial"), "3")    # no twin: metric

    def test_urls(self):
        self.assertEqual(wttr.url_for("Paris, France"), "https://wttr.in/Paris,+France?format=j1")
        self.assertEqual(wttr.url_for("~Eiffel Tower", "u"), "https://wttr.in/~Eiffel+Tower?u")
        self.assertEqual(wttr.url_for("São Paulo"), "https://wttr.in/S%C3%A3o+Paulo?format=j1")
        self.assertEqual(wttr.url_for("19.43,-99.13"), "https://wttr.in/19.43,-99.13?format=j1")
        self.assertEqual(wttr.url_for(""), "https://wttr.in/?format=j1")

    def test_saved_answer_must_be_for_here(self):
        self.assertTrue(wttr.is_for_here({"_location": wttr.LOCATION}))
        self.assertFalse(wttr.is_for_here({"_location": wttr.LOCATION + "x"}))
        self.assertFalse(wttr.is_for_here(None))


if __name__ == "__main__":
    unittest.main()


class AlertsPlaceFromWeather(unittest.TestCase):
    """region.py alerts-place-from-weather: the weather pill's place (wttr.in's
    nearest_area) handed to `emergency-alerts.py place`. Pure parts only."""
    ISO = "# comment\nMX\tMexico\nFR\tFrance\nUS\tUnited States\n"

    @staticmethod
    def answer(location="cdmx", country="Mexico", lat="19.434", lon="-99.139"):
        return {"_location": location, "nearest_area": [{
            "areaName": [{"value": "Coyoacan"}], "region": [{"value": "Distrito Federal"}],
            "country": [{"value": country}], "latitude": lat, "longitude": lon}]}

    def test_country_code_from_the_tz_table_and_aliases(self):
        self.assertEqual(region.country_code("Mexico", self.ISO), "MX")
        self.assertEqual(region.country_code(" france ", self.ISO), "FR")
        self.assertEqual(region.country_code("United States of America", ""), "US")
        self.assertEqual(region.country_code("Atlantis", self.ISO), "")
        self.assertEqual(region.country_code("", self.ISO), "")

    def test_weather_place_reads_the_answer(self):
        place = region.weather_place(self.answer(), "cdmx", self.ISO)
        self.assertEqual((place["lat"], place["lon"], place["code"]), (19.434, -99.139, "MX"))
        self.assertIn("Coyoacan", place["area"])

    def test_an_answer_for_another_place_is_not_used(self):
        self.assertIsNone(region.weather_place(self.answer(location="paris"), "cdmx", self.ISO))
        self.assertIsNone(region.weather_place(self.answer(lat="north"), "cdmx", self.ISO))
        self.assertIsNone(region.weather_place(None, "cdmx", self.ISO))

    def test_country_only_when_it_changes(self):
        place = {"lat": 19.434, "lon": -99.139, "code": "MX"}
        self.assertEqual(region.place_args(place, {"country": "MX"}), ["19.434", "-99.139"])
        self.assertEqual(region.place_args(place, {"country": "fr"}), ["19.434", "-99.139", "MX"])
        self.assertEqual(region.place_args(dict(place, code=""), {"country": "FR"}), ["19.434", "-99.139"])
