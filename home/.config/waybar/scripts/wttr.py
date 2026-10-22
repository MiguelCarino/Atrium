#!/usr/bin/env python3
"""Weather pill for waybar, and the shared icon logic for weather_panel.py.

    wttr.py           one JSON line for waybar (module runs it every 30 min)
    wttr.py open      the forecast on wttr.in in the browser (right-click)

The pill is a Font Awesome weather glyph in a condition colour plus the
temperature. FA rather than emoji: emoji are full-colour artwork that ignore
the bar's palette and come in at a different size from every other icon; FA
glyphs are monochrome and take whatever neon they are given.

Every run also saves wttr.in's full answer to $XDG_RUNTIME_DIR, which is what
the forecast panel (weather_panel.py, the pill's left-click) reads -- so
opening the panel costs no second request.

wttr.in resets connections fairly often; a failed fetch serves the last good
pill marked stale rather than blanking the module for half an hour.

The place and the units are preferences in ~/.config/hypr/region.conf
(hypr/scripts/region.py; Settings > Date, time & region): weather= anything
wttr.in takes -- a city, an airport code, "~Eiffel Tower", "lat,lon", or
empty for wherever your internet address is -- and units=metric|imperial.
wttr.in's j1 answer always carries both units, so the units only change what
is shown, never the saved answer (mascot_mood.py and wallpaper-motion.py
read it too, in °C). The saved answer is stamped with the place it is for
("_location"), so a new place is fetched on the next run instead of the old
place's answer being reused for twenty minutes.
"""

import json
import os
import subprocess
import sys
import time
import urllib.parse
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import themecolors  # noqa: E402  (no GTK: this runs in the bar)

sys.path.insert(0, os.path.expanduser("~/.config/hypr/scripts"))
try:
    import region       # the preferences (no GTK)
    PREFS = region.prefs()
except Exception:       # a bar without the hypr scripts, or an unreadable file
    PREFS = {}
LOCATION = PREFS.get("weather", "")     # read once: every run is a new process
UNITS = PREFS.get("units", "metric")
OLD_LOCATION = "cdmx"   # what an answer saved before the stamp existed is for


def place_path(location):
    """wttr.in's path for a place: spaces as +, the rest percent-encoded
    (an accent, a comma), but ~ , + and - left as wttr.in reads them."""
    return urllib.parse.quote(location.strip().replace(" ", "+"), safe="+,~-.@")


def url_for(location, query="format=j1"):
    return f"https://wttr.in/{place_path(location)}?{query}"


URL = url_for(LOCATION)

# wttr.in's metric field -> its imperial twin, for the units preference.
IMPERIAL = {"temp_C": "temp_F", "FeelsLikeC": "FeelsLikeF", "tempC": "tempF",
            "mintempC": "mintempF", "maxtempC": "maxtempF", "windspeedKmph": "windspeedMiles"}
WIND_UNIT = "mph" if UNITS == "imperial" else "km/h"
TEMP_UNIT = "°F" if UNITS == "imperial" else "°C"


def val(entry, key, units=None):
    """entry[key] in the preferred units: val(cur, "temp_C") is temp_F for
    imperial. Falls back to the metric field if the twin is missing."""
    if (units or UNITS) == "imperial" and IMPERIAL.get(key) in entry:
        return entry[IMPERIAL[key]]
    return entry[key]

RUNTIME = os.environ.get("XDG_RUNTIME_DIR", "/tmp")
CACHE = os.path.join(RUNTIME, "waybar-weather.json")       # last pill output
RAW = os.path.join(RUNTIME, "waybar-weather-raw.json")     # full wttr.in answer
REUSE_S = 20 * 60       # RAW younger than this is reused, not re-fetched

# WWO weather codes -> kind. wttr.in also emits a few codes outside the WWO
# table (149, smoky haze); anything unknown falls back to "cloud".
KINDS = {
    "sun": {113},
    "partly": {116},
    "cloud": {119, 122},
    "fog": {143, 149, 248, 260},
    "showers": {176, 263, 266, 293, 296, 353},
    "rain": {179, 182, 185, 281, 284, 299, 311, 314, 317, 350, 362, 365, 374, 377},
    "heavy": {302, 305, 308, 356, 359},
    "storm": {200, 386, 389, 392},
    "snow": {227, 230, 320, 323, 326, 329, 332, 335, 338, 368, 371, 395},
}

_C = themecolors.hex

# (day glyph, night glyph, colour). Font Awesome 6 Free Solid, as escapes:
# literal Private Use Area characters do not survive being copied around.
# The colours are the desktop theme's color.wx_* (theme.conf ->
# generated/colors.conf, see themecolors.py); the literals are cyberpunk's
# and the fallback.
STYLE = {
    "sun":     ("\uf185", "\uf186", _C("wx_sun", "#f9f002")),   # sun / moon
    "partly":  ("\uf6c4", "\uf6c3", _C("wx_sun", "#f9f002")),   # cloud-sun / cloud-moon
    "cloud":   ("\uf0c2", "\uf0c2", _C("wx_cloud", "#96d7e6")),
    "fog":     ("\uf75f", "\uf75f", _C("wx_cloud", "#96d7e6")),   # smog
    "showers": ("\uf743", "\uf73c", _C("wx_rain", "#00f0ff")),   # cloud-sun-rain / cloud-moon-rain
    "rain":    ("\uf73d", "\uf73d", _C("wx_rain", "#00f0ff")),   # cloud-rain
    "heavy":   ("\uf740", "\uf740", _C("wx_rain", "#00f0ff")),   # cloud-showers-heavy
    "storm":   ("\uf76c", "\uf76c", _C("wx_storm", "#b026ff")),   # cloud-bolt
    "snow":    ("\uf2dc", "\uf2dc", _C("wx_snow", "#e6fcff")),   # snowflake
}
MOON_TINT = _C("wx_moon", "#dcb0ff")       # a clear night is not yellow


def kind_of(code):
    try:
        code = int(code)
    except (TypeError, ValueError):
        return "cloud"
    for kind, codes in KINDS.items():
        if code in codes:
            return kind
    return "cloud"


def glyph(code, night=False):
    """(glyph, colour) for a weather code."""
    kind = kind_of(code)
    day, nite, colour = STYLE[kind]
    if night and kind in ("sun", "partly"):
        colour = MOON_TINT
    return (nite if night else day), colour


def parse_clock(text, on):
    """'07:29 AM' on a given date -> datetime, or None."""
    try:
        return datetime.combine(on, datetime.strptime(text.strip(), "%I:%M %p").time())
    except ValueError:
        return None


def is_night(weather, when=None):
    when = when or datetime.now()
    try:
        astro = weather["weather"][0]["astronomy"][0]
    except (KeyError, IndexError):
        return not 7 <= when.hour < 19
    rise = parse_clock(astro.get("sunrise", ""), when.date())
    sets = parse_clock(astro.get("sunset", ""), when.date())
    if not rise or not sets:
        return not 7 <= when.hour < 19
    return not rise <= when < sets


def pill(weather):
    cur = weather["current_condition"][0]
    sign, colour = glyph(cur["weatherCode"], is_night(weather))
    desc = cur["weatherDesc"][0]["value"].strip()
    return {
        "text": f"<span color='{colour}'>{sign}</span> {val(cur, 'temp_C')}°",
        # Not shown (the module's tooltip is off -- the panel replaces it), but
        # kept for anyone running this by hand.
        "tooltip": f"{desc}, {val(cur, 'temp_C')}{TEMP_UNIT} (feels {val(cur, 'FeelsLikeC')}{TEMP_UNIT})",
        "class": kind_of(cur["weatherCode"]),
    }


def serve_cached(reason):
    try:
        with open(CACHE) as handle:
            cached = json.load(handle)
    except (OSError, ValueError):
        print(json.dumps({"text": "\uf0c2 --", "tooltip": f"Weather unavailable: {reason}",
                          "class": "unavailable"}))
        return
    cached["tooltip"] = f"{cached.get('tooltip', '')} -- stale: {reason}"
    cached["class"] = "stale"
    print(json.dumps(cached))


def fetch():
    """wttr.in's answer for LOCATION, stamped with it (see the docstring)."""
    import requests             # only the network path needs it
    weather = requests.get(URL, timeout=10).json()
    if isinstance(weather, dict):
        weather["_location"] = LOCATION
    return weather


def is_for_here(weather):
    """Is a saved answer for the place the preferences name now?"""
    return isinstance(weather, dict) and weather.get("_location", OLD_LOCATION) == LOCATION


def open_site():
    query = "u" if UNITS == "imperial" else "m"
    subprocess.Popen(["xdg-open", url_for(LOCATION, query)], stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True)


def recent_raw():
    """The last full answer, if it is younger than REUSE_S -- else None.

    The bar runs this every 30 minutes, and then RAW is always older than
    that, so the regular run still fetches. A run between those -- signal 16,
    sent by ~/.config/hypr/scripts/theme.py when a theme switch changes the
    color.wx_* glyph colours, or a bar restart -- rebuilds the pill from the
    answer it already has, in the new colours, without asking wttr.in again.
    region.py sends the same signal after a units change (same answer, other
    fields) or a place change (the stamp no longer matches: fetched anew)."""
    try:
        if time.time() - os.path.getmtime(RAW) > REUSE_S:
            return None
        with open(RAW) as handle:
            weather = json.load(handle)
    except (OSError, ValueError):
        return None
    return weather if is_for_here(weather) else None


def main():
    if sys.argv[1:2] == ["open"]:
        open_site()
        return
    try:
        weather = recent_raw() or fetch()
        data = pill(weather)
    except Exception as exc:            # network down, odd JSON, rate-limited
        serve_cached(str(exc))
        return
    for path, payload in ((CACHE, data), (RAW, weather)):
        try:
            with open(path, "w") as handle:
                json.dump(payload, handle)
        except OSError:
            pass
    print(json.dumps(data))


if __name__ == "__main__":
    main()
