#!/usr/bin/env python3
"""The bar's clock, in whichever of three readings you last asked for.

    clock.py watch    continuous JSON for custom/clock — one line a second
    clock.py cycle    local → UTC → epoch → local, redrawn immediately
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


def tooltip(moment):
    """Whichever readings are not on screen, so the other two are one hover
    away instead of two clicks."""
    local = moment.astimezone() if moment.tzinfo else moment
    utc = local.astimezone(timezone.utc)
    return "\n".join([
        f"<b>{local.strftime('%A, %d %B %Y')}</b>",
        f"local  {hms(local)} {local.strftime('%Z')}",
        f"UTC    {hms(utc)}",
        f"epoch  {int(local.timestamp())}",
        "",
        "<i>click to cycle · the date opens the calendar</i>",
    ])


def emit(kind):
    time.tzset()        # follow a time zone change (see the docstring)
    current = mode()
    moment = now_in(current)
    text = clock_text(current, moment) if kind == "clock" else day_text(current, moment)
    print(json.dumps({
        "text": text,
        "tooltip": tooltip(moment),
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


def cycle():
    set_mode(MODES[(MODES.index(mode()) + 1) % len(MODES)])
    try:
        with open(PID_FILE) as handle:
            os.kill(int(handle.read().strip()), signal.SIGUSR1)
    except (OSError, ValueError):
        pass        # no watcher: the next tick picks the new mode up anyway
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
