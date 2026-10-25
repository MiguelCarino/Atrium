#!/usr/bin/env python3
"""The bar's clock, in whichever of three readings you last asked for.

    clock.py watch    continuous JSON for custom/clock — one line a second
    clock.py cycle    local → UTC → epoch → local, redrawn immediately (the
                      pill's right click; its left click opens the clock
                      card, clock_panel.py)
    clock.py day      one-shot JSON for custom/day, which opens the calendar

Local time is the default and what you get back after a full cycle; UTC is for
reading logs and talking to people elsewhere; epoch is for pasting into things
that want seconds. The mode is shared through a file rather than held in the
watcher, so custom/day and the calendar panel can follow it too — a UTC clock
next to a local date would be a trap.

How it is written comes from ~/.config/hypr/region.conf (hypr/scripts/
region.py; Settings > Date, time & region): clock=24|12, seconds=on|off and
date=short|dmy|iso. The watcher re-reads it whenever its mtime moves -- one
stat() a tick -- and region.py also wakes it with SIGUSR1, so a change shows
on the same second. Without region.py (a copy of the bar elsewhere) the
defaults are the old fixed look: 24-hour with seconds, "Tue, Oct 20".

A time zone change (timedatectl set-timezone) rewrites /etc/localtime under
a running watcher; time.tzset() each tick makes the C library look again,
so the local reading follows without restarting the bar.

A world clock pinned in the clock card (its pin toggle; "pin" in
$XDG_STATE_HOME/hypr/world-clocks.json, next to the zones) is a second,
short reading after the local or UTC one: "15:04:05 · TYO 06:04" (minutes
only, a three-letter code: zone_code). Not in epoch mode -- that one is
for pasting. The watcher stat()s the file each tick and reads it only when
its mtime moves (the card also sends SIGUSR1, so a pin shows at once), the
same bargain as region.conf.
"""

import json
import os
import signal
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.expanduser("~/.config/hypr/scripts"))
try:
    import region       # the preferences (no GTK; cheap to import)
except ImportError:     # a bar without the hypr scripts: the fixed look
    region = None


def prefs():
    return region.prefs() if region else {}


try:
    from zoneinfo import ZoneInfo
except ImportError:     # no zoneinfo: no pinned world clock
    ZoneInfo = None

STATE_DIR = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"), "hypr")
ZONES_FILE = os.path.join(STATE_DIR, "world-clocks.json")
# Codes people know for the cities most often added, where the first three
# letters would read wrong (TOK, NEW, LOS); the rest: zone_code's rule.
ZONE_CODES = {"Tokyo": "TYO", "New_York": "NYC", "Los_Angeles": "LAX", "Mexico_City": "MEX",
              "Sao_Paulo": "SAO", "Buenos_Aires": "BUE", "Hong_Kong": "HKG", "Kolkata": "CCU",
              "Calcutta": "CCU", "Shanghai": "SHA", "Singapore": "SIN", "Seoul": "SEL",
              "Sydney": "SYD", "Chicago": "CHI", "Denver": "DEN", "Moscow": "MOW",
              "Johannesburg": "JNB", "Dubai": "DXB", "Madrid": "MAD", "Bogota": "BOG"}


def zone_code(zone):
    """Three letters for a zone on the bar: ZONE_CODES for the usual
    cities, else the initials of a two- or three-word city ("Port_Moresby"
    -> "PM"), else the city's first three letters ("Europe/Lisbon" ->
    "LIS"); "UTC" stays."""
    city = zone.rsplit("/", 1)[-1]
    if city in ZONE_CODES:
        return ZONE_CODES[city]
    words = [w for w in city.replace("-", "_").split("_") if w]
    if len(words) > 1:
        return "".join(w[0] for w in words[:3]).upper()
    return city[:3].upper()


def parse_zones(data):
    """world-clocks.json's two shapes -> (zones or None, pin or None): the
    old plain list of zones, or {"zones": [...], "pin": zone}. None zones
    when the file is neither (the card then shows its defaults); a pin is
    only one of the zones."""
    if isinstance(data, dict):
        zones, pin = data.get("zones"), data.get("pin")
    else:
        zones, pin = data, None
    if not isinstance(zones, list):
        return None, None
    zones = [z for z in zones if isinstance(z, str)]
    return zones, (pin if pin in zones else None)


_pin = {"mtime": None, "zone": None}


def pinned_zone(path=None):
    """The pinned zone, re-read only when the file's mtime moved (one
    stat() a tick)."""
    path = path or ZONES_FILE
    try:
        mtime = os.stat(path).st_mtime_ns
    except OSError:
        _pin.update(mtime=None, zone=None)
        return None
    if mtime != _pin["mtime"]:
        try:
            with open(path) as handle:
                zone = parse_zones(json.load(handle))[1]
        except (OSError, ValueError):
            zone = None
        _pin.update(mtime=mtime, zone=zone)
    return _pin["zone"]


def pin_text(zone, conf=None, now=None):
    """" · TYO 06:04" for a pinned zone (no seconds, whatever the main
    reading does), "" for none or a zone this Python does not know."""
    if not zone or ZoneInfo is None:
        return ""
    try:
        there = (now or datetime.now(timezone.utc)).astimezone(ZoneInfo(zone))
    except Exception:       # an unknown zone name: no second reading
        return ""
    short = dict(conf if conf is not None else prefs(), seconds="off")
    return f" · {zone_code(zone)} {hms(there, short)}"

RUNTIME = os.environ.get("XDG_RUNTIME_DIR", "/tmp")
MODE_FILE = os.path.join(RUNTIME, "waybar-clock.mode")
PID_FILE = os.path.join(RUNTIME, "waybar-clock.pid")

MODES = ("local", "utc", "epoch")
# custom/day is a plain interval module; this is the SIGRTMIN offset waybar
# listens on for it, so a mode change shows up there without a minute's wait.
DAY_SIGNAL = 10


def mode():
    try:
        with open(MODE_FILE) as handle:
            value = handle.read().strip()
    except OSError:
        return MODES[0]
    return value if value in MODES else MODES[0]


def set_mode(value):
    try:
        with open(MODE_FILE, "w") as handle:
            handle.write(value)
    except OSError:
        pass


def now_in(current):
    """Always tz-aware: a naive datetime formats %Z as an empty string, which
    reads as a missing timezone rather than the local one."""
    return datetime.now(timezone.utc) if current != "local" \
        else datetime.now().astimezone()


def hms(moment, conf=None):
    """The time as the preferences say (region.time_text), else 15:04:05."""
    if region:
        return region.time_text(moment, conf if conf is not None else prefs())
    return moment.strftime("%H:%M:%S")


def clock_text(current, moment, conf=None):
    if current == "epoch":
        return str(int(moment.timestamp()))
    if current == "utc":
        return f"{hms(moment, conf)} Z"
    return hms(moment, conf)


LANG_FILE = os.path.expanduser("~/.config/waybar/generated/lang")
JA_WEEKDAYS = "月火水木金土日"     # Monday first, as datetime.weekday() counts


def lang():
    """The desktop theme's language (theme.py writes it): "ja" or "en"."""
    try:
        with open(LANG_FILE) as handle:
            return handle.read().strip() or "en"
    except OSError:
        return "en"


def day_text(current, moment, conf=None):
    if lang() == "ja":
        # 10月18日 (日): month and day in kanji counters, the weekday's kanji.
        return f"{moment.month}月{moment.day}日 ({JA_WEEKDAYS[moment.weekday()]})"
    if region:
        return region.date_text(moment, conf if conf is not None else prefs())
    return moment.strftime("%a, %b %d")


def tooltip(moment, pin=None):
    """Whichever readings are not on screen, so the other two are one hover
    away instead of two clicks (and the pinned zone in full, with its day)."""
    local = moment.astimezone() if moment.tzinfo else moment
    utc = local.astimezone(timezone.utc)
    lines = [
        f"<b>{local.strftime('%A, %d %B %Y')}</b>",
        f"local  {hms(local)} {local.strftime('%Z')}",
        f"UTC    {hms(utc)}",
        f"epoch  {int(local.timestamp())}",
    ]
    if pin and ZoneInfo is not None:
        try:
            there = local.astimezone(ZoneInfo(pin))
            lines.append(f"{zone_code(pin):<6} {hms(there)} {there:%a}  ({pin.rsplit('/', 1)[-1].replace('_', ' ')})")
        except Exception:
            pass
    return "\n".join(lines + [
        "",
        "<i>click to cycle · the date opens the calendar</i>",
    ])


def emit(kind):
    time.tzset()        # follow a time zone change (see the docstring)
    current = mode()
    moment = now_in(current)
    pin = pinned_zone() if kind == "clock" else None
    if kind == "clock":
        conf = prefs()
        text = clock_text(current, moment, conf) + ("" if current == "epoch" else pin_text(pin, conf, moment))
    else:
        text = day_text(current, moment)
    print(json.dumps({
        "text": text,
        "tooltip": tooltip(moment, pin),
        "class": current,
    }), flush=True)


class Redraw(Exception):
    """Raised out of the sleep by SIGUSR1 so a mode change is instant."""


_sleeping = False   # the handler may only raise while watch() is in sleep
_pending = False    # a SIGUSR1 that arrived mid-emit, redrawn right after


def on_usr1(_signum, _frame):
    # Python retries an interrupted sleep unless the handler raises, so this
    # has to throw to get the loop moving again inside the same second. It
    # throws ONLY out of the sleep: raised during emit() it would escape the
    # loop, end the watcher and blank the clock until waybar restarted it.
    global _pending
    if _sleeping:
        raise Redraw
    _pending = True


def watch():
    global _sleeping, _pending
    with open(PID_FILE, "w") as handle:
        handle.write(str(os.getpid()))
    signal.signal(signal.SIGUSR1, on_usr1)

    while True:
        emit("clock")
        if _pending:
            _pending = False
            continue
        try:
            _sleeping = True
            # Land just after the next second rather than drifting a few
            # milliseconds later on every iteration.
            time.sleep(1.0 - (time.time() % 1.0) + 0.005)
        except Redraw:
            pass
        finally:
            _sleeping = False


def poke():
    """Wake the watcher (SIGUSR1) so a change shows on this second: a mode
    cycle, a pin set in the clock card."""
    try:
        with open(PID_FILE) as handle:
            os.kill(int(handle.read().strip()), signal.SIGUSR1)
    except (OSError, ValueError):
        pass        # no watcher: the next tick picks the change up anyway


def cycle():
    set_mode(MODES[(MODES.index(mode()) + 1) % len(MODES)])
    poke()
    os.system(f"pkill -SIGRTMIN+{DAY_SIGNAL} waybar")


def main():
    action = sys.argv[1] if len(sys.argv) > 1 else "watch"
    try:
        if action == "cycle":
            cycle()
        elif action == "day":
            emit("day")
        else:
            watch()
    except (KeyboardInterrupt, BrokenPipeError):
        # waybar closing the pipe on its way out is not an error worth logging.
        os._exit(0)
    except Exception as exc:    # never let waybar see a traceback
        print(json.dumps({"text": "", "tooltip": f"clock.py: {exc}",
                          "class": "error"}), flush=True)


if __name__ == "__main__":
    main()
