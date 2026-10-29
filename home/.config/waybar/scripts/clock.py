#!/usr/bin/env python3
"""The bar's clock, in whichever of three readings you last asked for.

    clock.py watch    continuous JSON for custom/clock — a line whenever the
                      reading changes (every second with seconds shown, else
                      every minute); it also redraws custom/day when the date
                      changes and custom/menuclock each minute in the menu-
                      bar layout (bar_signals "day", signal 10), so those
                      two need no polling interval of their own
    clock.py cycle    local → UTC → epoch → local, redrawn immediately (the
                      pill's right click; its left click opens the clock
                      card, clock_panel.py)
    clock.py day      one-shot JSON for custom/day, which opens the calendar
    clock.py menubar  one-shot JSON for custom/menuclock: the date and time
                      as one menu-bar reading at the bar's far right,
                      "Tue 27 Oct  21:21" (a theme with bar.clock=menubar)
    clock.py logo     one-shot JSON for custom/logo: the theme's glyph
                      (bar.logo=), the bar's first item
    clock.py power    one-shot JSON for custom/power: the power button --
                      empty (so hidden) when the theme has a bar.logo=,
                      whose click already opens the same power menu

Local time is the default and what you get back after a full cycle; UTC is for
reading logs and talking to people elsewhere; epoch is for pasting into things
that want seconds. The mode is shared through a file rather than held in the
watcher, so custom/day and the calendar panel can follow it too — a UTC clock
next to a local date would be a trap.

How it is written comes from ~/.config/hypr/region.conf (hypr/scripts/
region.py; Settings > Date, time & region): clock=24|12, seconds=on|off and
date=short|dmy|iso. The watcher re-reads it whenever its mtime moves -- one
stat() a tick -- and region.py also wakes it with SIGUSR1, so a change shows
on the same second. A tick is a second while the reading has seconds, else
up to 5 s (sleep_for: the minute boundary, capped so a resume from suspend
is caught), and a line is printed only when it differs from the last one. Without region.py (a copy of the bar elsewhere) the
defaults are the old fixed look: 24-hour with seconds, "Tue, Oct 20".

A time zone change (timedatectl set-timezone) rewrites /etc/localtime under
a running watcher; time.tzset() each tick makes the C library look again,
so the local reading follows without restarting the bar.

The menu-bar layout (orchard's bar.clock=menubar; theme.py writes it to
~/.config/waybar/generated/bar.conf as clock= and logo=): the date and time
leave the centre for the far right, in one reading with no seconds --
"Tue 27 Oct  21:21", or "Tue 27 Oct  9:21 PM" with region.conf clock=12,
"10月27日(火)  21:21" for a ja theme. custom/day and custom/clock then
print an empty text (waybar hides an empty custom module) and the watcher
keeps running, so switching back shows the centre clock on the next tick.
Without bar.conf (an older theme.py, a fresh copy) nothing changes.

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
# The longest the watcher sleeps in one go (see sleep_for).
MAX_SLEEP = 5


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


BAR_CONF = os.path.expanduser("~/.config/waybar/generated/bar.conf")
_bar = {"mtime": None, "conf": {}}


def bar_style(path=None):
    """bar.conf as a dict ({"clock": "menubar", "logo": ""} ...), {} when
    missing. Re-read only when its mtime moves: the watcher asks every tick."""
    path = path or BAR_CONF
    try:
        mtime = os.stat(path).st_mtime_ns
    except OSError:
        _bar.update(mtime=None, conf={})
        return {}
    if mtime != _bar["mtime"]:
        conf = {}
        try:
            with open(path) as handle:
                for line in handle:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        key, sep, value = line.partition("=")
                        if sep:
                            conf[key.strip()] = value.strip()
        except OSError:
            pass
        _bar.update(mtime=mtime, conf=conf)
    return dict(_bar["conf"])


def menubar(conf=None):
    """Is the menu-bar layout on (bar.clock=menubar)?"""
    return (conf if conf is not None else bar_style()).get("clock") == "menubar"


def menubar_text(moment, conf=None, language=None):
    """The menu bar's one reading: "Tue 27 Oct  21:21" -- the weekday, the
    day without a leading zero, the month, two spaces, the time as
    region.conf says but never with seconds ("9:21 PM" at clock=12). ja:
    "10月27日(火)  21:21". English names whatever the locale: the bar's
    other words are English too."""
    short = dict(conf if conf is not None else prefs(), seconds="off")
    when = hms(moment, short) if region else moment.strftime("%H:%M")
    if (language or lang()) == "ja":
        return f"{moment.month}月{moment.day}日({JA_WEEKDAYS[moment.weekday()]})  {when}"
    weekday = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")[moment.weekday()]
    month = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov",
             "Dec")[moment.month - 1]
    return f"{weekday} {moment.day} {month}  {when}"


POWER_GLYPH = "\uf011"      # Font Awesome: power-off


def power_pill(style):
    """custom/power's JSON. The power menu is on the bar once: a theme with
    a logo (bar.logo=, custom/logo at the top left -- orchard's leaf, and
    orchard-dark's, which inherits it) opens it from that mark, as a menu
    bar's mark would, so the power pill prints nothing and waybar hides it.
    Every other theme keeps the pill at the far right. The taskbar's start
    button does not count as "elsewhere": it opens the launcher, which has
    Lock but no power menu, log out, reboot or power off."""
    if style.get("logo"):
        return {"text": "", "class": "elsewhere"}
    return {"text": POWER_GLYPH, "tooltip": "Power menu  (Super+Esc)", "class": "power"}


def emit(kind):
    time.tzset()        # follow a time zone change (see the docstring)
    style = bar_style()
    if kind == "logo":
        print(json.dumps({"text": style.get("logo", ""), "class": "logo"}), flush=True)
        return
    if kind == "power":
        print(json.dumps(power_pill(style)), flush=True)
        return
    if kind == "menubar":
        # Always local: the menu bar is the wall clock; UTC and epoch stay
        # one right click away on the clock card.
        moment = now_in("local")
        text = menubar_text(moment) if menubar(style) else ""
        print(json.dumps({"text": text, "class": "menubar"}), flush=True)
        # Signal 10 is how a theme switch reaches the bar (theme.py): tell the
        # watcher too, which may be in a minute-long step and would otherwise
        # notice the new layout only at its next tick.
        poke()
        return
    print(json.dumps(reading(kind, style)), flush=True)


def reading(kind, style=None):
    """custom/clock's or custom/day's JSON (not printed). No tooltip: both
    modules have "tooltip": false -- the clock card and the calendar are the
    long form -- so none is built, every second, for nobody."""
    style = bar_style() if style is None else style
    current = mode()
    moment = now_in(current)
    if menubar(style):
        text = ""       # the reading lives at the far right (custom/menuclock)
    elif kind == "clock":
        conf = prefs()
        pin = pinned_zone()
        text = clock_text(current, moment, conf) + ("" if current == "epoch" else pin_text(pin, conf, moment))
    else:
        text = day_text(current, moment)
    return {"text": text, "class": current}


def tick_step(current, conf, style):
    """How often the watcher's reading can change: every second while it
    shows seconds (or the epoch), else once a minute -- the menu-bar layout
    (the centre is empty; custom/menuclock has minutes only) and a clock
    with seconds=off."""
    if menubar(style):
        return 60
    if current == "epoch" or conf.get("seconds", "on") != "off":
        return 1
    return 60


def sleep_for(now, step, cap=MAX_SLEEP):
    """Seconds to the next whole `step` boundary (+5 ms, to land just after
    it), never more than `cap`: the sleep runs on the monotonic clock, which
    stands still in a suspend, so a long one would leave a stale minute on
    screen after a resume."""
    return min(step - (now % step) + 0.005, cap)


def due_signals(before, after, menubar_on):
    """Which waybar redraws a tick owes, from the previous and the current
    local (date, minute) keys: custom/day when the date changed, and every
    minute in the menu-bar layout, where custom/menuclock is a one-shot
    module with no interval of its own (both are signal 10, "day")."""
    if before is None or before == after:
        return False
    return before[0] != after[0] or (menubar_on and before[1] != after[1])

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

    last_line = None
    last_key = None
    while True:
        time.tzset()        # follow a time zone change (see the docstring)
        style = bar_style()
        line = json.dumps(reading("clock", style))
        if line != last_line:   # waybar redraws on every line, same or not
            print(line, flush=True)
            last_line = line
        local = datetime.now()
        key = (local.date(), local.strftime("%H:%M"))
        if due_signals(last_key, key, menubar(style)):
            redraw_day()
        last_key = key
        if _pending:
            _pending = False
            continue
        try:
            _sleeping = True
            # Land just after the next boundary rather than drifting a few
            # milliseconds later on every iteration.
            time.sleep(sleep_for(time.time(), tick_step(mode(), prefs(), style)))
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


def redraw_day():
    """custom/day, custom/logo, custom/menuclock and custom/power re-run
    (bar_signals "day", signal 10). A direct kill of the waybar, no pkill
    fork."""
    try:
        import bar_signals
        bar_signals.poke("day")
    except Exception:       # a bar without the hypr scripts: nothing to redraw
        pass


def cycle():
    set_mode(MODES[(MODES.index(mode()) + 1) % len(MODES)])
    poke()
    redraw_day()


def main():
    action = sys.argv[1] if len(sys.argv) > 1 else "watch"
    try:
        if action == "cycle":
            cycle()
        elif action in ("day", "menubar", "logo", "power"):
            emit(action)
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
