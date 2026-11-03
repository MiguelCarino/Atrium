#!/usr/bin/env python3
"""Open-Meteo, in wttr.in's shape: the weather pill's second source.

wttr.in is one volunteer-run server, and it goes away -- connections
refused for hours, from some networks for good -- and then the pill sat on
"--" everywhere. wttr.py asks this module when wttr.in does not answer:
Open-Meteo (open-meteo.com: free, no key, no account) for the same place,
its answer rewritten as wttr.in's format=j1 so that nothing that reads the
saved answer (weather_panel.py, mascot_mood.py, wallpaper-motion.py,
brief.py, ambient.py, launcher.py, region.py) has to know where it came
from. Marked "_source": "open-meteo".

    openmeteo.py PLACE      the j1-shaped answer as JSON (to look at it)

The place is wttr.py's LOCATION (region.conf's weather=): "lat,lon" is used
as it is; anything else is looked up with Open-Meteo's geocoding -- "City",
"City, Country" or "City, State" (the part after the comma picks among the
matches), "~Landmark" by its name. An airport code, or an empty place
(wttr.in goes by the internet address; Open-Meteo cannot), finds nothing:
then the pill stays stale, as before. A looked-up place is remembered in
$XDG_RUNTIME_DIR (GEO_CACHE) so the retries ask once.

What is rewritten (only the fields the readers use):

    current_condition[0]  temp_C/F, FeelsLikeC/F, weatherCode (WWO, below),
                          weatherDesc, humidity, windspeedKmph/Miles,
                          winddir16Point, uvIndex
    weather[0..2]         date, mintempC/F, maxtempC/F,
                          astronomy[0].sunrise/sunset ("06:37 AM"),
                          hourly[8]: time ("0" .. "2100"), tempC/F,
                          weatherCode, weatherDesc, chanceofrain
    nearest_area[0]       areaName, region, country, latitude, longitude

Open-Meteo's codes are WMO's (0 clear .. 99 thunderstorm with hail); WMO
maps them onto the WWO codes wttr.in uses, so wttr.py's KINDS -- the glyph,
the colour, the wallpaper's rain -- read them unchanged.
"""

import json
import os
import re
import sys
from datetime import datetime

GEOCODE = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST = "https://api.open-meteo.com/v1/forecast"
TIMEOUT = 10
RUNTIME = os.environ.get("XDG_RUNTIME_DIR", "/tmp")
GEO_CACHE = os.path.join(RUNTIME, "waybar-weather-geo.json")
LATLON = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$")

# WMO weather code -> (WWO code, description). The WWO code is chosen for
# the kind wttr.py's KINDS gives it: 2 partly cloudy is 116 (partly),
# 63 moderate rain 302 (heavy) would be too much, so 299 (rain).
WMO = {
    0: (113, "Clear"), 1: (113, "Mainly clear"), 2: (116, "Partly cloudy"), 3: (122, "Overcast"),
    45: (248, "Fog"), 48: (260, "Freezing fog"),
    51: (266, "Light drizzle"), 53: (266, "Drizzle"), 55: (263, "Dense drizzle"),
    56: (281, "Freezing drizzle"), 57: (284, "Heavy freezing drizzle"),
    61: (296, "Light rain"), 63: (299, "Rain"), 65: (308, "Heavy rain"),
    66: (311, "Light freezing rain"), 67: (314, "Freezing rain"),
    71: (326, "Light snow"), 73: (332, "Snow"), 75: (338, "Heavy snow"), 77: (326, "Snow grains"),
    80: (353, "Light showers"), 81: (356, "Showers"), 82: (359, "Violent showers"),
    85: (368, "Light snow showers"), 86: (371, "Snow showers"),
    95: (389, "Thunderstorm"), 96: (392, "Thunderstorm with hail"), 99: (392, "Thunderstorm with hail"),
}
POINTS = ("N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
          "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW")


def wwo(code):
    """(WWO code, description) for a WMO code; unknown ones are clouds."""
    try:
        return WMO.get(int(code), (119, "Cloudy"))
    except (TypeError, ValueError):
        return (119, "Cloudy")


def compass(degrees):
    try:
        return POINTS[int((float(degrees) % 360) / 22.5 + 0.5) % 16]
    except (TypeError, ValueError):
        return ""


def fahrenheit(c):
    return round(float(c) * 9 / 5 + 32)


def clock(iso):
    """"2026-11-02T06:37" -> "06:37 AM" (wttr.in's astronomy format)."""
    try:
        return datetime.strptime(iso, "%Y-%m-%dT%H:%M").strftime("%I:%M %p")
    except (TypeError, ValueError):
        return ""


def get(url, params):
    import requests             # only the network path needs it
    reply = requests.get(url, params=params, timeout=TIMEOUT)
    reply.raise_for_status()
    return reply.json()


# -- the place --------------------------------------------------------------------
def pick(results, hint):
    """The geocoding match the part after the comma names (a country, its
    code, a state), else the first."""
    hint = hint.strip().lower()
    if hint:
        for r in results:
            names = {str(r.get(k, "")).lower() for k in ("country", "country_code", "admin1", "admin2")}
            if hint in names:
                return r
    return results[0] if results else None


def geocode(location):
    """{"lat", "lon", "name", "region", "country"} for a place name, or None."""
    name, _, hint = location.lstrip("~").partition(",")
    name = name.strip()
    if not name:
        return None
    found = get(GEOCODE, {"name": name, "count": 10, "language": "en", "format": "json"})
    r = pick(found.get("results") or [], hint)
    if not r:
        return None
    return {"lat": r["latitude"], "lon": r["longitude"], "name": r.get("name", name),
            "region": r.get("admin1", ""), "country": r.get("country", "")}


def read_cache():
    try:
        with open(GEO_CACHE, encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def place(location):
    """Where `location` is, or None when Open-Meteo cannot tell."""
    location = (location or "").strip()
    m = LATLON.match(location)
    if m:
        return {"lat": float(m.group(1)), "lon": float(m.group(2)), "name": location,
                "region": "", "country": ""}
    if not location:
        return None             # wttr.in's "where my internet address is"
    cache = read_cache()
    if location in cache:
        return cache[location]
    found = geocode(location)
    if found:
        cache[location] = found
        try:
            with open(GEO_CACHE, "w", encoding="utf-8") as handle:
                json.dump(cache, handle)
        except OSError:
            pass
    return found


# -- the answer --------------------------------------------------------------------
def to_j1(forecast, where, location):
    """Open-Meteo's forecast as wttr.in's format=j1 (see the top)."""
    cur = forecast["current"]
    code, desc = wwo(cur.get("weather_code"))
    wind = float(cur.get("wind_speed_10m") or 0)
    current = {
        "temp_C": str(round(cur["temperature_2m"])),
        "temp_F": str(fahrenheit(cur["temperature_2m"])),
        "FeelsLikeC": str(round(cur.get("apparent_temperature", cur["temperature_2m"]))),
        "FeelsLikeF": str(fahrenheit(cur.get("apparent_temperature", cur["temperature_2m"]))),
        "weatherCode": str(code),
        "weatherDesc": [{"value": desc}],
        "humidity": str(round(cur.get("relative_humidity_2m") or 0)),
        "windspeedKmph": str(round(wind)),
        "windspeedMiles": str(round(wind / 1.609344)),
        "winddir16Point": compass(cur.get("wind_direction_10m")),
        "uvIndex": str(round(cur.get("uv_index") or 0)),
    }
    hourly = forecast.get("hourly", {})
    by_time = {t: i for i, t in enumerate(hourly.get("time", []))}
    daily = forecast["daily"]
    days = []
    for d, date in enumerate(daily["time"]):
        hours = []
        for hour in range(0, 24, 3):
            i = by_time.get(f"{date}T{hour:02d}:00")
            if i is None:
                continue
            h_code, h_desc = wwo(hourly["weather_code"][i])
            temp = hourly["temperature_2m"][i]
            rain = (hourly.get("precipitation_probability") or [None] * (i + 1))[i]
            hours.append({"time": str(hour * 100), "tempC": str(round(temp)), "tempF": str(fahrenheit(temp)),
                          "weatherCode": str(h_code), "weatherDesc": [{"value": h_desc}],
                          "chanceofrain": str(round(rain or 0))})
        lo, hi = daily["temperature_2m_min"][d], daily["temperature_2m_max"][d]
        days.append({"date": date,
                     "mintempC": str(round(lo)), "mintempF": str(fahrenheit(lo)),
                     "maxtempC": str(round(hi)), "maxtempF": str(fahrenheit(hi)),
                     "astronomy": [{"sunrise": clock(daily["sunrise"][d]), "sunset": clock(daily["sunset"][d])}],
                     "hourly": hours})
    area = {"areaName": [{"value": where["name"]}], "region": [{"value": where["region"]}],
            "country": [{"value": where["country"]}],
            "latitude": str(where["lat"]), "longitude": str(where["lon"])}
    return {"current_condition": [current], "weather": days, "nearest_area": [area],
            "_location": location, "_source": "open-meteo"}


def fetch(location):
    """The j1-shaped answer for `location`; raises when there is none."""
    where = place(location)
    if where is None:
        raise LookupError(f"Open-Meteo cannot place {location!r}" if location else
                          "Open-Meteo needs a place (Settings > Date, time & region)")
    forecast = get(FORECAST, {
        "latitude": where["lat"], "longitude": where["lon"], "timezone": "auto", "forecast_days": 3,
        "current": "temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,"
                   "wind_speed_10m,wind_direction_10m,uv_index",
        "hourly": "temperature_2m,weather_code,precipitation_probability",
        "daily": "temperature_2m_max,temperature_2m_min,sunrise,sunset",
    })
    return to_j1(forecast, where, location)


if __name__ == "__main__":
    print(json.dumps(fetch(" ".join(sys.argv[1:])), indent=1))
