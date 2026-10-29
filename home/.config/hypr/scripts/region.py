#!/usr/bin/env python3
"""Date, time and region: the time zone and network time (systemd-timedated),
how the bar writes the time and the date, which day starts the week in the
calendar panel, and the place and units of the weather pill.

    region.py show [--json]          everything below, as text or JSON
    region.py set <key> <value>      one region.conf preference (below), then
                                     the bar redraws: the clock at once, the
                                     date and the weather pill by signal
    region.py timezones [<search>] [--json]
                                     the time zones (timedatectl
                                     list-timezones), with their UTC offset
                                     and local time now; <search> matches
                                     any part of the name, spaces as _
    region.py timezone <Area/City>   set the time zone (timedatectl
                                     set-timezone: asks for your password
                                     through polkit), then redraw the clock
    region.py ntp on|off             network time (timedatectl set-ntp: asks
                                     too). Off only if you set the clock by
                                     hand on purpose
    region.py suggest                the time zone nearest to your place (the
                                     Alerts page's latitude / longitude), from
                                     the tz database's own coordinates
    region.py alerts-place-from-weather
                                     make the weather pill's place (where
                                     wttr.in put it: its latitude, longitude
                                     and country) the emergency alerts'
                                     place, through `emergency-alerts.py
                                     place` -- the country only when it
                                     differs (a new country resets the
                                     alert sources to that country's)

~/.config/hypr/region.conf (key=value; written with defaults on first set):
    clock=24        24 | 12       the bar's clock: 15:04 or 3:04 PM
    seconds=on      on | off      the second hand on the bar's clock
    date=short      short | dmy | iso
                                  the bar's date: "Tue, Oct 20",
                                  "Tue 20 Oct" or "2026-10-20" (lang=ja
                                  themes keep 10月20日 (火))
    week=monday     monday | sunday | saturday
                                  the first column of the calendar panel
    weather=        the weather pill's place (unset: the time zone's city,
                    zone_place), anything wttr.in takes: a city
                    ("Mexico City", "Paris, France"), an airport code (MEX),
                    "~Eiffel Tower" for a landmark, or "19.43,-99.13";
                    empty = wherever your internet address says you are
    units=metric    metric | imperial   °C and km/h, or °F and mph
REGION_CONF=<path> in the environment reads and writes another file instead
(the tests do; also a way to try a look without touching the bar).

Who reads it: waybar/scripts/clock.py (the clock and the date: it notices a
change within a second), calendar_panel.py (each time it opens), wttr.py and
weather_panel.py (each run). Importable without GTK -- prefs() is what they
call -- so this file is also the one place the defaults and the allowed
values live.

Why the time zone goes through timedatectl and not a preference here: it is
the system's, /etc/localtime, shared with every program and the logs, and
changing it is an admin action (polkit asks). Same for network time, which
Fedora runs with chronyd: `show` reads chronyc's tracking (no root needed)
for the server and how far off the clock is.

The desktop's language (the bar's day, the workspace numbers, the launcher's
prompt) is not here: it belongs to the theme, theme.conf lang= (theme.py).
The system locale (what apps speak, LANG=) is localectl's; `show` reports
both, read-only.
"""
import json
import math
import os
import re
import signal
import subprocess
import sys
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
# REGION_CONF points it elsewhere (the tests, trying a change without
# touching the bar's real preferences).
CONF = os.environ.get("REGION_CONF") or os.path.expanduser("~/.config/hypr/region.conf")
# The emergency-alerts place is asked of its owner (`emergency-alerts.py
# config`, JSON), not read from its file: that script decides the format and
# the defaults.
EMERGENCY = os.path.join(HERE, "emergency-alerts.py")
ZONE_TAB = "/usr/share/zoneinfo/zone1970.tab"
ISO_TAB = "/usr/share/zoneinfo/iso3166.tab"     # country code TAB name (the alerts place's country)
LANG_FILE = os.path.expanduser("~/.config/waybar/generated/lang")
RUNTIME = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
CLOCK_PID = os.path.join(RUNTIME, "waybar-clock.pid")     # clock.py watch writes it
WEATHER_RAW = os.path.join(RUNTIME, "waybar-weather-raw.json")  # wttr.py's last answer
# custom/day and custom/weather are redrawn through bar_signals.py ("day",
# "weather"), the one table of the bar's signal numbers.

DEFAULTS = {"clock": "24", "seconds": "on", "date": "short", "week": "monday",
            "weather": "", "units": "metric"}     # weather: filled in below
CHOICES = {"clock": ("24", "12"), "seconds": ("on", "off"), "date": ("short", "dmy", "iso"),
           "week": ("monday", "sunday", "saturday"), "units": ("metric", "imperial")}
# Words people type, folded onto the stored values, so `set clock 12h` and
# `set week domingo` do what they look like they do.
ALIASES = {"24h": "24", "12h": "12", "ampm": "12", "am/pm": "12", "yes": "on", "true": "on",
           "1": "on", "no": "off", "false": "off", "0": "off", "lunes": "monday", "mon": "monday",
           "domingo": "sunday", "sun": "sunday", "sabado": "saturday", "sábado": "saturday",
           "sat": "saturday", "c": "metric", "celsius": "metric", "si": "metric",
           "f": "imperial", "fahrenheit": "imperial", "us": "imperial", "mdy": "short"}
DATE_FORMATS = {"short": "%a, %b %d", "dmy": "%a %d %b", "iso": "%Y-%m-%d"}
WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
WEATHER_MAX = 80        # longer than any real place name; keeps the URL sane


# -- region.conf ---------------------------------------------------------------------
def parse(text):
    """region.conf text -> the full preference dict: defaults filled in, and
    any value that is not one of a key's choices replaced by the default
    (a typo in the file must not blank the bar's clock)."""
    conf = dict(DEFAULTS)
    for line in text.splitlines():
        if line.lstrip().startswith("#"):
            continue
        key, sep, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if not sep or key not in DEFAULTS:
            continue
        if key in CHOICES and value not in CHOICES[key]:
            continue
        conf[key] = value
    return conf


def render(conf):
    return ("# Date, time and region (scripts/region.py; its docstring explains).\n"
            "# Settings > Date, time & region writes this; editing by hand works too.\n"
            + "".join(f"{key}={conf.get(key, value)}\n" for key, value in DEFAULTS.items()))


_cache = {"mtime": None, "conf": dict(DEFAULTS)}


def prefs(path=None):
    """The preferences now. Re-read only when the file's mtime moves, so the
    bar's clock can ask every second for the price of one stat()."""
    path = path or CONF
    try:
        mtime = os.stat(path).st_mtime_ns
    except OSError:
        return dict(DEFAULTS)
    if _cache.get("path") != path or _cache["mtime"] != mtime:
        try:
            with open(path, encoding="utf-8") as handle:
                conf = parse(handle.read())
        except OSError:
            conf = dict(DEFAULTS)
        _cache.update(path=path, mtime=mtime, conf=conf)
    return dict(_cache["conf"])


def normalise(key, value):
    """(key, stored value) for what someone typed, or ValueError saying what
    the key takes."""
    key = key.strip().lower()
    if key not in DEFAULTS:
        raise ValueError(f"no setting {key!r} (have: {', '.join(DEFAULTS)})")
    value = value.strip()
    if key == "weather":
        if len(value) > WEATHER_MAX:
            raise ValueError(f"a place name of at most {WEATHER_MAX} characters")
        if any(ch in value for ch in "/?#&\n\t"):
            raise ValueError("a place has no / ? # or &: try \"Paris, France\" or \"48.85,2.35\"")
        return key, re.sub(r"\s+", " ", value)
    folded = ALIASES.get(value.lower(), value.lower())
    if folded not in CHOICES[key]:
        raise ValueError(f"{key} takes {' | '.join(CHOICES[key])}")
    return key, folded


def save(key, value, path=None):
    """Set one preference; returns the whole new dict. Written to a temporary
    file and renamed, so the clock never reads half a file."""
    path = path or CONF
    key, value = normalise(key, value)
    conf = prefs(path)
    conf[key] = value
    tmp = f"{path}.tmp"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(tmp, "w", encoding="utf-8") as handle:
        handle.write(render(conf))
    os.replace(tmp, path)
    return conf


# -- formatting, for the bar ---------------------------------------------------------
def time_text(moment, conf=None):
    """The bar's clock: 15:04:05, 15:04, 3:04:05 AM or 3:04 AM."""
    conf = conf or DEFAULTS
    secs = ":%S" if conf.get("seconds", "on") == "on" else ""
    if conf.get("clock", "24") == "12":
        # %I is zero-padded ("03"); a 12-hour clock reads "3:04 AM".
        return moment.strftime(f"%I:%M{secs} %p").lstrip("0")
    return moment.strftime(f"%H:%M{secs}")


def date_text(moment, conf=None):
    conf = conf or DEFAULTS
    return moment.strftime(DATE_FORMATS.get(conf.get("date"), DATE_FORMATS["short"]))


def first_weekday(conf=None):
    """0 = Monday ... 6 = Sunday, as datetime.weekday() counts."""
    conf = conf or DEFAULTS
    return WEEKDAYS.index(conf.get("week", "monday"))


def week_columns(first):
    """The weekday numbers in the calendar's column order."""
    return [(first + i) % 7 for i in range(7)]


def grid_start(month_first, first):
    """The day in the calendar grid's top-left cell: the first-of-the-month,
    or the nearest `first` weekday before it."""
    return month_first - timedelta(days=(month_first.weekday() - first) % 7)


# -- time zones ----------------------------------------------------------------------
def offset_text(delta):
    """timedelta -> "UTC+05:30" / "UTC−06:00" (a real minus sign) / "UTC"."""
    if delta is None:
        return "UTC"
    minutes = int(delta.total_seconds() // 60)
    if minutes == 0:
        return "UTC"
    sign = "+" if minutes > 0 else "−"
    hours, mins = divmod(abs(minutes), 60)
    return f"UTC{sign}{hours:02d}:{mins:02d}"


def zone_now(name, now=None):
    """(local datetime, offset text) in zone `name`, or None if the system has
    no such zone."""
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
    try:
        tz = ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return None
    moment = (now or datetime.now(timezone.utc)).astimezone(tz)
    return moment, offset_text(moment.utcoffset())


def next_change(name, now=None, days=400):
    """The next time zone `name` changes its UTC offset (summer time), as
    (UTC datetime, offset after) -- or None when it does not within `days`.
    A day-by-day walk to find the day, then halving down to the minute:
    about 400 + 11 offset lookups, a millisecond."""
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
    try:
        tz = ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return None
    start = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).replace(second=0, microsecond=0)
    before = start.astimezone(tz).utcoffset()
    lo = start
    for _ in range(days):
        hi = lo + timedelta(days=1)
        if hi.astimezone(tz).utcoffset() != before:
            while hi - lo > timedelta(minutes=1):
                mid = lo + (hi - lo) / 2
                mid = mid.replace(second=0, microsecond=0)
                if mid <= lo:
                    break
                if mid.astimezone(tz).utcoffset() == before:
                    lo = mid
                else:
                    hi = mid
            return hi, offset_text(hi.astimezone(tz).utcoffset())
        lo = hi
    return None


def match_zones(zones, query, limit=None):
    """The zones whose name holds every word of `query` (any order, any case,
    a space matching the tz database's _), best first: a city that starts
    with the query ("mexico" -> America/Mexico_City), then a whole name that
    does (the old Mexico/General style links), then the rest in order."""
    words = [w for w in re.split(r"\s+", query.strip().lower().replace("_", " ")) if w]
    if not words:
        found = list(zones)
    else:
        found = [z for z in zones if all(w in z.lower().replace("_", " ") for w in words)]
        phrase = " ".join(words)

        def rank(zone):
            plain = zone.lower().replace("_", " ")
            city = plain.rsplit("/", 1)[-1]
            return (0 if city.startswith(phrase) else 1 if plain.startswith(phrase) else
                    2 if phrase in city else 3, zone)
        found.sort(key=rank)
    return found[:limit] if limit else found


def all_zones():
    """timedatectl's list (what set-timezone accepts), or Python's own copy
    of the tz database when timedatectl is missing (a container)."""
    out = _run("timedatectl", "list-timezones", "--no-pager")
    zones = [line.strip() for line in out.splitlines() if line.strip()]
    if not zones:
        from zoneinfo import available_timezones
        zones = sorted(z for z in available_timezones() if "/" in z or z == "UTC")
    return zones


def iso6709(text):
    """"+1924-09909" or "+192400-0990900" -> (19.4, -99.15): zone1970.tab's
    coordinates, degrees-minutes(-seconds) with the sign in front."""
    m = re.fullmatch(r"([+-])(\d{2})(\d{2})(\d{2})?([+-])(\d{3})(\d{2})(\d{2})?", text.strip())
    if not m:
        raise ValueError(text)

    def deg(sign, d, mi, se):
        value = int(d) + int(mi) / 60 + (int(se) / 3600 if se else 0)
        return -value if sign == "-" else value
    return deg(*m.group(1, 2, 3, 4)), deg(*m.group(5, 6, 7, 8))


def zone_table(text):
    """zone1970.tab -> [(zone, lat, lon)]."""
    rows = []
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        cols = line.split("\t")
        if len(cols) < 3:
            continue
        try:
            lat, lon = iso6709(cols[1])
        except ValueError:
            continue
        rows.append((cols[2], lat, lon))
    return rows


def system_zone():
    """The system's zone name ("America/Mexico_City"): /etc/localtime's link
    target, or $TZ; "" when neither says (a container, a bare UTC box)."""
    zone = os.environ.get("TZ", "").lstrip(":")
    if not zone:
        try:
            zone = os.path.realpath("/etc/localtime").split("/zoneinfo/", 1)[1]
        except (OSError, IndexError):
            return ""
    return zone if "/" in zone else ""


def zone_place(zone=None, tab=ZONE_TAB):
    """Where the system's time zone says you are, as a first guess for the
    weather and the emergency alerts until you name your own place:
    {"city": "Mexico City", "lat": 19.4, "lon": -99.15, "country": "MX"}
    (the zone's principal city, zone1970.tab), or None. A guess at the city
    level only, from a file every machine has: nothing is looked up."""
    zone = system_zone() if zone is None else zone
    if not zone:
        return None
    try:
        with open(tab, encoding="utf-8") as handle:
            lines = handle.read().splitlines()
    except OSError:
        return None
    for line in lines:
        cols = line.split("\t")
        if len(cols) >= 3 and not line.startswith("#") and cols[2] == zone:
            try:
                lat, lon = iso6709(cols[1])
            except ValueError:
                return None
            city = zone.rsplit("/", 1)[-1].replace("_", " ")
            return {"city": city, "lat": round(lat, 2), "lon": round(lon, 2),
                    "country": cols[0].split(",")[0]}
    return None


def distance_km(lat1, lon1, lat2, lon2):
    """Great-circle distance (haversine), Earth as a 6371 km sphere."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 6371 * 2 * math.asin(min(1.0, math.sqrt(a)))


def nearest_zone(lat, lon, table):
    """The zone whose principal city is closest -- a good guess, not a
    border lookup (near a border it can pick the neighbour), which is why
    the page offers it rather than applying it."""
    best = min(table, key=lambda r: distance_km(lat, lon, r[1], r[2]), default=None)
    return best[0] if best else None


def alerts_place(conf):
    """(lat, lon) from an `emergency-alerts.py config` dict; (None, None)
    when it has none."""
    try:
        return float(conf["lat"]), float(conf["lon"])
    except (ValueError, KeyError, TypeError):
        return None, None


def alerts_config():
    """`emergency-alerts.py config` as a dict ({} when it did not answer)."""
    try:
        conf = json.loads(subprocess.run([EMERGENCY, "config"], capture_output=True, text=True,
                                         timeout=10).stdout or "null")
    except (OSError, subprocess.SubprocessError, ValueError):
        return {}
    return conf if isinstance(conf, dict) else {}


# wttr.in's country names that are not the tz database's (iso3166.tab) own.
COUNTRY_ALIASES = {"united states of america": "US", "usa": "US", "united kingdom": "GB", "uk": "GB",
                   "russian federation": "RU", "south korea": "KR", "korea, south": "KR", "north korea": "KP",
                   "vietnam": "VN", "viet nam": "VN", "iran": "IR", "syria": "SY", "laos": "LA",
                   "bolivia": "BO", "venezuela": "VE", "tanzania": "TZ", "czech republic": "CZ",
                   "taiwan": "TW", "moldova": "MD", "macedonia": "MK", "the netherlands": "NL"}


def country_code(name, iso_text):
    """"Mexico" -> "MX", from the tz database's iso3166.tab (code TAB name)
    and COUNTRY_ALIASES; "" when it is not one of them."""
    key = (name or "").strip().lower()
    if not key:
        return ""
    if key in COUNTRY_ALIASES:
        return COUNTRY_ALIASES[key]
    for line in iso_text.splitlines():
        if line.startswith("#") or "\t" not in line:
            continue
        code, country = line.split("\t", 1)
        if country.strip().lower() == key:
            return code.strip().upper()
    return ""


def weather_place(weather, location, iso_text=""):
    """{"lat", "lon", "country", "code", "area"} where wttr.in put the saved
    weather answer, if it is for `location` (like area_name), else None."""
    if not area_name(weather, location):
        return None
    area = weather["nearest_area"][0]
    try:
        lat, lon = float(area["latitude"]), float(area["longitude"])
    except (KeyError, TypeError, ValueError):
        return None
    try:
        country = area["country"][0]["value"].strip()
    except (KeyError, IndexError, TypeError, AttributeError):
        country = ""
    return {"lat": round(lat, 3), "lon": round(lon, 3), "country": country,
            "code": country_code(country, iso_text), "area": area_name(weather, location)}


def read_weather_place(location):
    try:
        with open(WEATHER_RAW, encoding="utf-8") as handle:
            weather = json.load(handle)
    except (OSError, ValueError):
        return None
    try:
        with open(ISO_TAB, encoding="utf-8") as handle:
            iso = handle.read()
    except OSError:
        iso = ""
    return weather_place(weather, location, iso)


def place_args(weather, alerts):
    """The `emergency-alerts.py place` arguments that move the alerts place
    to the weather place: lat lon, plus the country code only when it is
    known and not the one already set (a country change resets the sources)."""
    args = [f"{weather['lat']:g}", f"{weather['lon']:g}"]
    if weather.get("code") and weather["code"] != str(alerts.get("country", "")).upper():
        args.append(weather["code"])
    return args


def alerts_from_weather():
    """(ok, message): the weather place made the alerts place."""
    place = read_weather_place(prefs()["weather"])
    if not place:
        return False, "the weather pill has no answer for its place yet (wait for it, or Save place again)"
    args = place_args(place, alerts_config())
    try:
        out = subprocess.run([EMERGENCY, "place", *args], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"emergency-alerts.py did not run: {exc}"
    if out.returncode != 0:
        return False, (out.stderr or out.stdout).strip() or "emergency-alerts.py refused it"
    return True, f"alerts place: {place['area']} ({' '.join(args)})"


def suggest(conf=None):
    """(zone, place) near the emergency-alerts place, or (None, why).
    conf: an `emergency-alerts.py config` already read (status() reads it once)."""
    lat, lon = alerts_place(alerts_config() if conf is None else conf)
    if lat is None or lon is None:
        return None, "no place saved on the Alerts page"
    try:
        with open(ZONE_TAB, encoding="utf-8") as handle:
            table = zone_table(handle.read())
    except OSError:
        return None, f"{ZONE_TAB} is missing (tzdata)"
    return nearest_zone(lat, lon, table), "nearest to your place on the Alerts page"


# -- the system's side ---------------------------------------------------------------
def _run(*cmd, timeout=10):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def parse_props(text):
    """`timedatectl show` / `localectl` style key=value lines -> dict."""
    return dict(line.split("=", 1) for line in text.splitlines() if "=" in line)


def parse_tracking(text):
    """`chronyc tracking` -> {"server", "stratum", "offset_s"} (whatever it
    said). offset_s is positive when this clock is ahead."""
    out = {}
    for line in text.splitlines():
        key, _, value = line.partition(":")
        key, value = key.strip(), value.strip()
        if key == "Reference ID":
            m = re.search(r"\(([^)]*)\)", value)
            out["server"] = m.group(1) if m else value
        elif key == "Stratum":
            try:
                out["stratum"] = int(value)
            except ValueError:
                pass
        elif key == "System time":
            m = re.match(r"([\d.]+) seconds (fast|slow)", value)
            if m:
                out["offset_s"] = float(m.group(1)) * (1 if m.group(2) == "fast" else -1)
    return out


def area_name(weather, location):
    """"Coyoacán, Distrito Federal, Mexico": where wttr.in placed the saved
    answer, if that answer is for `location` (wttr.py stamps it), else ""."""
    if not isinstance(weather, dict) or weather.get("_location", "cdmx") != location:
        return ""
    try:
        area = weather["nearest_area"][0]
    except (KeyError, IndexError, TypeError):
        return ""
    parts = []
    for key in ("areaName", "region", "country"):
        try:
            value = area[key][0]["value"].strip()
        except (KeyError, IndexError, TypeError, AttributeError):
            continue
        if value and value not in parts:
            parts.append(value)
    return ", ".join(parts)


def weather_area(location):
    try:
        with open(WEATHER_RAW, encoding="utf-8") as handle:
            return area_name(json.load(handle), location)
    except (OSError, ValueError):
        return ""


def theme_lang():
    try:
        with open(LANG_FILE, encoding="utf-8") as handle:
            return handle.read().strip() or "en"
    except OSError:
        return "en"


def status():
    """Everything `show` reports, as one dict (what the Settings page draws)."""
    props = parse_props(_run("timedatectl", "show"))
    zone = props.get("Timezone") or "UTC"
    now = datetime.now(timezone.utc)
    here = zone_now(zone, now)
    change = next_change(zone, now)
    tracking = parse_tracking(_run("chronyc", "-n", "tracking", timeout=3)) \
        if props.get("NTP") == "yes" else {}
    m = re.search(r"\bLANG=(\S+)", _run("localectl", "status", timeout=3))
    locale = m.group(1) if m else os.environ.get("LANG", "")
    alerts = alerts_config()
    zone_guess, why = suggest(alerts)
    conf = prefs()
    local_now = here[0] if here else now
    return {
        "timezone": zone,
        "offset": here[1] if here else "UTC",
        "abbrev": local_now.strftime("%Z"),
        "now": local_now.isoformat(timespec="seconds"),
        "clock_now": time_text(local_now, conf),
        "date_now": date_text(local_now, conf),
        "next_change": {"utc": change[0].isoformat(), "offset": change[1],
                        "local": change[0].astimezone(here[0].tzinfo).isoformat()} if change and here else None,
        "ntp": props.get("NTP") == "yes",
        "ntp_synced": props.get("NTPSynchronized") == "yes",
        "can_ntp": props.get("CanNTP", "yes") == "yes",
        "local_rtc": props.get("LocalRTC") == "yes",
        "sync": tracking,
        "suggested_zone": zone_guess,
        "suggested_why": why,
        "prefs": conf,
        "weather_area": weather_area(conf["weather"]),
        "weather_place": read_weather_place(conf["weather"]),
        "alerts_place": {k: alerts.get(k, "") for k in ("lat", "lon", "country")} if alerts else None,
        "conf": CONF,
        "lang": theme_lang(),
        "theme": _run(os.path.join(HERE, "theme.py"), "current", timeout=5).strip(),
        "locale": locale,
    }


def _is_clock_watcher(pid):
    """Only signal the pid in waybar-clock.pid if it really is clock.py: a
    stale file's number may belong to something else by now, and SIGUSR1
    ends most programs that do not expect it."""
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as handle:
            return b"clock.py" in handle.read()
    except OSError:
        return False


def redraw(*what):
    """Tell the bar: "clock" wakes clock.py's watcher (SIGUSR1, the same as
    its own cycle), "day" and "weather" signal waybar's modules."""
    if "clock" in what:
        try:
            with open(CLOCK_PID) as handle:
                pid = int(handle.read().strip())
            if _is_clock_watcher(pid):
                os.kill(pid, signal.SIGUSR1)
        except (OSError, ValueError):
            pass        # no watcher: its next tick reads the file anyway
    names = [name for name in ("day", "weather") if name in what]
    if names:
        try:
            sys.path.insert(0, HERE)
            import bar_signals      # the numbers' one table (scripts/bar_signals.py)
            bar_signals.poke(*names)
        except ImportError:
            pass        # no table: the pills catch up at their own next run


# Which bar pieces each preference shows up in.
REDRAWS = {"clock": ("clock",), "seconds": ("clock",), "date": ("day",), "week": (),
           "weather": ("weather",), "units": ("weather",)}


def set_timezone(zone):
    """timedatectl set-timezone; returns (ok, message). polkit asks for the
    password (hyprpolkitagent shows the dialog); a cancel is an error here."""
    zones = all_zones()
    if zone not in zones:
        close = match_zones(zones, zone, 3)
        return False, f"no time zone {zone!r}" + (f" -- did you mean {', '.join(close)}?" if close else "")
    try:
        proc = subprocess.run(["timedatectl", "set-timezone", zone], capture_output=True, text=True,
                              timeout=120)
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)
    if proc.returncode != 0:
        return False, (proc.stderr.strip() or "timedatectl refused").splitlines()[-1]
    redraw("clock", "day")
    return True, f"time zone: {zone}"


def set_ntp(on):
    try:
        proc = subprocess.run(["timedatectl", "set-ntp", "true" if on else "false"],
                              capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)
    if proc.returncode != 0:
        return False, (proc.stderr.strip() or "timedatectl refused").splitlines()[-1]
    return True, f"network time {'on' if on else 'off'}"


# -- the command line ----------------------------------------------------------------
def show_text(st):
    p = st["prefs"]
    lines = [
        f"time zone     {st['timezone']} ({st['abbrev']}, {st['offset']})",
        f"now           {st['date_now']}  {st['clock_now']}",
    ]
    if st["next_change"]:
        lines.append(f"next change   {st['next_change']['local'][:16].replace('T', ' ')} "
                     f"-> {st['next_change']['offset']}")
    sync = "synchronised" if st["ntp_synced"] else "not synchronised yet"
    if st["sync"].get("server"):
        sync += f" with {st['sync']['server']}"
    lines += [
        f"network time  {'on, ' + sync if st['ntp'] else 'off'}",
        f"bar clock     {p['clock']}-hour, seconds {p['seconds']}, date {p['date']}",
        f"week starts   {p['week']}",
        f"weather       {p['weather'] or '(by internet address)'}, {p['units']}",
        f"language      desktop {st['lang']} (theme {st['theme'] or '?'}), system {st['locale'] or '?'}",
    ]
    if st["suggested_zone"] and st["suggested_zone"] != st["timezone"]:
        lines.append(f"suggestion    {st['suggested_zone']} ({st['suggested_why']})")
    return "\n".join(lines)


def zone_rows(zones, now=None):
    now = now or datetime.now(timezone.utc)
    conf = prefs()          # the bar's 12 / 24 hours, for "15:04 there now"
    rows = []
    for zone in zones:
        here = zone_now(zone, now)
        if here:
            rows.append({"zone": zone, "offset": here[1], "time": time_text(here[0], dict(conf, seconds="off")),
                         "abbrev": here[0].strftime("%Z")})
    return rows


# The weather's default place: the time zone's city (zone_place), so a new
# machine shows its own sky before anyone types a place; "" lets wttr.in
# guess from the connection.
_zone = zone_place()
DEFAULTS["weather"] = _zone["city"] if _zone else ""
_cache["conf"] = dict(DEFAULTS)


def main(argv):
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__.strip())
        return 0
    cmd, args = argv[0], argv[1:]
    as_json = "--json" in args
    args = [a for a in args if a != "--json"]
    if cmd == "show":
        st = status()
        print(json.dumps(st, ensure_ascii=False, indent=1) if as_json else show_text(st))
    elif cmd == "set" and len(args) >= 1:
        key = args[0]
        value = " ".join(args[1:])
        try:
            conf = save(key, value)
        except ValueError as exc:
            print(f"region.py: {exc}", file=sys.stderr)
            return 2
        redraw(*REDRAWS.get(normalise(key, value)[0], ()))
        print(f"{key.lower()}={conf[key.lower()]}")
    elif cmd == "timezones":
        found = match_zones(all_zones(), " ".join(args))
        rows = zone_rows(found)
        if as_json:
            print(json.dumps(rows, ensure_ascii=False))
        else:
            for r in rows:
                print(f"{r['zone']:<34} {r['offset']:<10} {r['time']}")
    elif cmd == "timezone" and len(args) == 1:
        ok, msg = set_timezone(args[0])
        print(msg, file=sys.stdout if ok else sys.stderr)
        return 0 if ok else 1
    elif cmd == "ntp" and len(args) == 1 and args[0] in ("on", "off"):
        ok, msg = set_ntp(args[0] == "on")
        print(msg, file=sys.stdout if ok else sys.stderr)
        return 0 if ok else 1
    elif cmd == "alerts-place-from-weather" and not args:
        ok, msg = alerts_from_weather()
        print(msg, file=sys.stdout if ok else sys.stderr)
        return 0 if ok else 1
    elif cmd == "suggest":
        zone, why = suggest()
        print(f"{zone}  ({why})" if zone else why)
        return 0 if zone else 1
    else:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
