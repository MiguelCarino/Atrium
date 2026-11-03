"""waybar/scripts/openmeteo.py, the weather pill's second source, and
wttr.py's fallback to it. Nothing here reaches the network: Open-Meteo's
answer is canned, and every fetch is stubbed."""
import importlib.util
import os
import sys
import unittest
from unittest import mock

import helpers

WAYBAR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "waybar", "scripts")
if WAYBAR not in sys.path:
    sys.path.insert(0, WAYBAR)


def load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(WAYBAR, f"{name}.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


os.environ.setdefault("XDG_RUNTIME_DIR", os.path.join(helpers.SCRATCH, "runtime"))
openmeteo = load("openmeteo")
wttr = load("wttr")

HOURS = [f"2026-11-0{d}T{h:02d}:00" for d in (2, 3, 4) for h in range(24)]
FORECAST = {
    "current": {"temperature_2m": 16.4, "apparent_temperature": 15.0, "relative_humidity_2m": 59,
                "weather_code": 61, "wind_speed_10m": 16.1, "wind_direction_10m": 310, "uv_index": 2.6},
    "hourly": {"time": HOURS, "temperature_2m": [10.0 + i % 24 / 2 for i in range(72)],
               "weather_code": [95 if i == 15 else 2 for i in range(72)],
               "precipitation_probability": [40 if i == 15 else 0 for i in range(72)]},
    "daily": {"time": ["2026-11-02", "2026-11-03", "2026-11-04"],
              "temperature_2m_max": [26.3, 27.1, 26.6], "temperature_2m_min": [12.8, 11.2, 11.0],
              "sunrise": ["2026-11-02T06:37"] * 3, "sunset": ["2026-11-02T18:02"] * 3},
}
WHERE = {"lat": 19.428, "lon": -99.128, "name": "Mexico City", "region": "Mexico City", "country": "Mexico"}


class Shape(unittest.TestCase):
    """The rewritten answer reads like wttr.in's j1 to everything that reads it."""

    def setUp(self):
        self.j1 = openmeteo.to_j1(FORECAST, WHERE, "Mexico City")

    def test_current(self):
        cur = self.j1["current_condition"][0]
        self.assertEqual((cur["temp_C"], cur["temp_F"], cur["FeelsLikeC"]), ("16", "62", "15"))
        self.assertEqual(cur["weatherDesc"][0]["value"], "Light rain")
        self.assertEqual(wttr.kind_of(cur["weatherCode"]), "showers")
        self.assertEqual((cur["windspeedKmph"], cur["windspeedMiles"], cur["winddir16Point"]), ("16", "10", "NW"))
        self.assertEqual((cur["humidity"], cur["uvIndex"]), ("59", "3"))

    def test_days_hours_and_sun(self):
        days = self.j1["weather"]
        self.assertEqual([d["date"] for d in days], FORECAST["daily"]["time"])
        self.assertEqual([h["time"] for h in days[0]["hourly"]], [str(h * 100) for h in range(0, 24, 3)])
        storm = days[0]["hourly"][5]                        # 15:00
        self.assertEqual((wttr.kind_of(storm["weatherCode"]), storm["chanceofrain"]), ("storm", "40"))
        self.assertEqual(days[0]["astronomy"][0], {"sunrise": "06:37 AM", "sunset": "06:02 PM"})
        self.assertEqual((days[1]["mintempC"], days[1]["maxtempF"]), ("11", "81"))

    def test_the_readers(self):
        self.assertEqual(wttr.pill(self.j1)["class"], "showers")
        self.assertTrue(wttr.is_night(self.j1, openmeteo.datetime(2026, 11, 2, 20, 0)))   # after 18:02
        self.assertEqual(self.j1["nearest_area"][0]["areaName"][0]["value"], "Mexico City")
        self.assertEqual(self.j1["_location"], "Mexico City")
        self.assertEqual(self.j1["_source"], "open-meteo")

    def test_every_wmo_code_has_a_kind(self):
        for code in openmeteo.WMO:
            self.assertIn(wttr.kind_of(openmeteo.wwo(code)[0]), wttr.STYLE)
        self.assertEqual(openmeteo.wwo("odd"), (119, "Cloudy"))


class Place(unittest.TestCase):
    def test_coordinates_need_no_lookup(self):
        with mock.patch.object(openmeteo, "get", side_effect=AssertionError("no network")):
            got = openmeteo.place(" 19.43, -99.13 ")
        self.assertEqual((got["lat"], got["lon"]), (19.43, -99.13))

    def test_no_place_is_none(self):
        self.assertIsNone(openmeteo.place(""))

    def test_the_part_after_the_comma_picks(self):
        results = [{"country": "United States", "country_code": "US", "admin1": "Texas"},
                   {"country": "France", "country_code": "FR", "admin1": "Île-de-France"}]
        self.assertEqual(openmeteo.pick(results, " France")["country_code"], "FR")
        self.assertEqual(openmeteo.pick(results, "tx")["country_code"], "US")   # no match: the first
        self.assertIsNone(openmeteo.pick([], "x"))


class Fallback(unittest.TestCase):
    def test_wttr_first(self):
        with mock.patch.object(wttr, "fetch_wttr", return_value={"current_condition": [{}]}), \
             mock.patch("openmeteo.fetch", side_effect=AssertionError("not asked")):
            self.assertEqual(wttr.fetch(), {"current_condition": [{}]})

    def test_open_meteo_when_wttr_fails(self):
        j1 = openmeteo.to_j1(FORECAST, WHERE, wttr.LOCATION)
        with mock.patch.object(wttr, "fetch_wttr", side_effect=ConnectionError("refused")), \
             mock.patch("openmeteo.fetch", return_value=j1):
            self.assertEqual(wttr.fetch()["_source"], "open-meteo")

    def test_both_failing_names_both(self):
        with mock.patch.object(wttr, "fetch_wttr", side_effect=ConnectionError("refused")), \
             mock.patch("openmeteo.fetch", side_effect=LookupError("no place")):
            with self.assertRaises(RuntimeError) as caught:
                wttr.fetch()
        self.assertIn("wttr.in: refused", str(caught.exception))
        self.assertIn("Open-Meteo: no place", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
