#!/usr/bin/env python3
"""Desktop theme by time of day: one theme by day, an optional one for the
evening, another at night. Day and night switch at the night light's own
end / start (Settings > Screens > Night light, kept in nightlight.conf, so
moving those moves this too); the evening starts at its own time and runs
until the night.

    theme-schedule.py          switch if a new part of the day has begun since
                               the last switch (theme-schedule.timer, every 15 min)
    theme-schedule.py on|off   start / stop following the time of day
    theme-schedule.py day|evening|night <theme>|random   which theme each one uses
    theme-schedule.py evening off                        no evening: the day runs on
    theme-schedule.py evening-from HH:MM                 when the evening starts
    theme-schedule.py status [--json]     what it would pick now, and whether it is on

The picks live in $XDG_STATE_HOME/hypr/theme-schedule.conf (day=, evening=,
night=, evening_from=; Aero by day, no evening, Matrix at night, evening
from 17:00 until changed). "random" picks a different theme each time that
part of the day begins. Changing the pick for the part of the day it is now
switches at once when the schedule is on.

Like the night light, a theme you pick by hand stays until the next
boundary: each part of the day switches once, at its start (or at the
first tick after login / wake in it), then leaves the theme alone. A Steam
game on screen holds the switch -- it restarts the bar and the wallpapers
-- until the game closes, at the next tick.
"""
import datetime
import json
import os
import random
import re
import subprocess
import sys
import time

DEFAULTS = {"day": "aero", "evening": "", "night": "matrix", "evening_from": "17:00"}
PARTS = ("day", "evening", "night")
RANDOM = "random"
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import theme  # noqa: E402  (the theme list; no GTK)
import desk_common  # noqa: E402  (hypr_request: hyprctl over the socket)

NIGHTLIGHT = os.path.join(HERE, "nightlight.sh")
THEME = os.path.join(HERE, "theme.py")
STATE_DIR = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"), "hypr")
STATE = os.path.join(STATE_DIR, "theme-schedule")
PICKS = os.path.join(STATE_DIR, "theme-schedule.conf")
NIGHTLIGHT_CONF = os.path.join(STATE_DIR, "nightlight.conf")     # nightlight.sh's settings
TIMER = "theme-schedule.timer"


def picks():
    """The picks (see the top); a pick whose theme is gone falls back."""
    out = dict(DEFAULTS)
    try:
        with open(PICKS) as handle:
            for line in handle:
                key, _, value = line.strip().partition("=")
                value = value.strip()
                if key == "evening_from" and re.fullmatch(r"\d{1,2}:\d{2}", value):
                    out[key] = value
                elif key in PARTS and (value == RANDOM or theme.exists(value)
                                       or (key == "evening" and value == "")):
                    out[key] = value
    except OSError:
        pass
    return out


def save_picks(out):
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(PICKS, "w") as handle:
        handle.write("".join(f"{k}={v}\n" for k, v in out.items()))


def set_pick(kind, name):
    if kind == "evening" and name == "off":
        name = ""
    elif name != RANDOM and not theme.exists(name):
        sys.exit(f"theme-schedule: no theme {name!r} ({', '.join(n for n, _ in theme.themes())}, random)")
    out = picks()
    before = period()[0]
    out[kind] = name
    save_picks(out)
    if enabled() and kind in (before, period()[0]):
        try:
            os.remove(STATE)        # the pick for right now: switch to it now
        except OSError:
            pass
        tick()


def set_evening_from(value):
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", value)
    if not m or int(m[1]) > 23 or int(m[2]) > 59:
        sys.exit("theme-schedule: evening-from HH:MM")
    out = picks()
    out["evening_from"] = "%02d:%02d" % (int(m[1]), int(m[2]))
    save_picks(out)


def boundaries():
    """(START, END) as (h, m): the night light's own times. nightlight.conf
    (start= / end=, what Settings > Screens writes) first; for a key it does
    not have, the default at the top of nightlight.sh; 20:00 / 07:00 if
    neither can be read. Equal times (a hand edit) count as no conf at all,
    which is what nightlight.sh does with them too."""
    def read(path, pattern):
        found = {}
        try:
            with open(path) as handle:
                for line in handle:
                    m = re.match(pattern, line)
                    if m and int(m[2]) < 24 and int(m[3]) < 60:
                        found[m[1].upper()] = (int(m[2]), int(m[3]))
        except OSError:
            pass
        return found
    script = read(NIGHTLIGHT, r'(START|END)="(\d{1,2}):(\d{2})"')
    times = {"START": (20, 0), "END": (7, 0), **script}
    conf = {**times, **read(NIGHTLIGHT_CONF, r'(start|end)=\s*(\d{1,2}):(\d{2})\s*$')}
    if conf["START"] != conf["END"]:
        times = conf
    return times["START"], times["END"]


def evening_start():
    h, m = picks()["evening_from"].split(":")
    return int(h), int(m)


def period(now=None):
    """(part of the day, when it began): the last boundary at or before now.
    The evening counts only with a pick for it."""
    now = now or datetime.datetime.now()
    start, end = boundaries()
    bounds = [("night", start), ("day", end)]
    if picks()["evening"]:
        bounds.append(("evening", evening_start()))
    marks = []
    for days in (0, 1):
        day = now.date() - datetime.timedelta(days=days)
        for kind, (h, m) in bounds:
            at = datetime.datetime.combine(day, datetime.time(h, m))
            if at <= now:
                marks.append((at, kind))
    at, kind = max(marks)
    return kind, at


def game_running():
    clients = desk_common.hypr_request("clients", json=True, timeout=3)   # over the socket: no process
    return any(str(c.get("class") or "").startswith("steam_app_")
               for c in clients if isinstance(c, dict)) if isinstance(clients, list) else False


AMBIENT_LIVE = os.path.join(os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}", "ambient.json")
AMBIENT_FRESH_S = 120       # ambient.py rewrites it every 30 s while its daemon runs


def ambient_owns_theme():
    """Ambient's "theme follows ambience" output is on and its daemon is
    alive: it switches with these same picks (and to a focus theme during a
    focus block), so this stands aside instead of switching the theme away
    from the block's. The period is not marked done: once ambient's theme
    output is off again, the next tick switches as usual."""
    try:
        with open(AMBIENT_LIVE) as handle:
            live = json.load(handle)
        # an empty pick is ambient's "leave it" (away, a "random" part of the
        # day): then the schedule still switches, random included
        return time.time() - float(live.get("time", 0)) < AMBIENT_FRESH_S and bool((live.get("plan") or {}).get("theme"))
    except (OSError, ValueError, TypeError, AttributeError):
        return False


def current_theme():
    return subprocess.run([sys.executable, THEME, "current"], capture_output=True, text=True).stdout.strip()


def tick():
    kind, began = period()
    key = f"{kind} {began:%Y-%m-%dT%H:%M}"
    try:
        with open(STATE) as handle:
            if handle.read().strip() == key:
                return
    except OSError:
        pass
    if game_running() or ambient_owns_theme():
        return
    want, now = picks()[kind], current_theme()
    if want == RANDOM:
        others = [n for n, _ in theme.themes() if n != now]
        want = random.choice(others) if others else now
    if now != want:
        subprocess.run([sys.executable, THEME, "set", want])
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    with open(STATE, "w") as handle:
        handle.write(key + "\n")


def systemctl(*args):
    return subprocess.run(["systemctl", "--user", *args], capture_output=True, text=True)


def enabled():
    return systemctl("is-enabled", TIMER).stdout.strip() == "enabled"


def status_data():
    """`status --json` as a dict (desktopctl.py imports this)."""
    kind, _ = period()
    start, end = boundaries()
    return {"on": enabled(), "now": kind, **picks(),
            "day_from": "%02d:%02d" % end, "night_from": "%02d:%02d" % start}


def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else "tick"
    if arg == "tick":
        tick()
    elif arg == "on":
        try:
            os.remove(STATE)        # switch now, not at the next boundary
        except OSError:
            pass
        systemctl("enable", "--now", TIMER)
        tick()
    elif arg == "off":
        systemctl("disable", "--now", TIMER)
    elif arg in PARTS and len(sys.argv) == 3:
        set_pick(arg, sys.argv[2])
    elif arg == "evening-from" and len(sys.argv) == 3:
        set_evening_from(sys.argv[2])
    elif arg == "status":
        kind, began = period()
        on, p = enabled(), picks()
        (start, end) = boundaries()
        if "--json" in sys.argv:
            print(json.dumps(status_data()))
        else:
            evening = f", evening {p['evening']} from {p['evening_from']}" if p["evening"] else ""
            print(f"{'on' if on else 'off'}: {kind} since {began:%a %H:%M} -> "
                  f"{p[kind]} (day {p['day']}{evening}, night {p['night']})")
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
