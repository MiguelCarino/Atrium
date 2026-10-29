#!/usr/bin/env python3
"""Work-hours mode: your employer's hours are not time for personal projects,
and their commits should not land in them. Off until you set it up: with no
~/.config/hypr/workhours.conf there is no pill, no work-start / work-end, and
`check` always says free time.

    workhours.py status [--json]   "work", "free" or "off", and why, for humans
                                   (--json: that, the label, the hours, the
                                   days, the day off and the next holiday,
                                   for Settings > Timers & alarms)
    workhours.py bar               JSON for the waybar pill: a lit "<label>"
                                   badge with the time left while it is work
                                   time, empty (pill hidden) otherwise
    workhours.py check             exit 0 = free time (or off), 1 = work time
                                   (for a git hook)
    workhours.py personal [PATH]   exit 0 when the repo at PATH (default: here)
                                   is one of YOUR repos by the personal_ rules
                                   below, 1 when not (or off)
    workhours.py enable            turn it on: the last settings back (kept in
                                   workhours.conf.off), else Mon-Fri 09:00-18:00
    workhours.py disable           turn it off (workhours.conf -> .off, kept)
    workhours.py off-today         today is a day off (vacation, sick day,
                                   a bridge holiday): free until midnight
    workhours.py on                cancel off-today
    workhours.py set start HH:MM   when work time begins (default 09:00)
    workhours.py set end HH:MM     ... and ends (default 18:00), same day
    workhours.py set days mon,tue,wed,thu,fri
                                   the work days (default Monday to Friday;
                                   "none": never work time)
    workhours.py set label TEXT    the pill's word (default "Work")

~/.config/hypr/workhours.conf, key=value (a missing key is its default, a
line that does not parse keeps the default, unknown keys and comments stay
when `set` writes it; $HYPR_WORKHOURS_CONF points it elsewhere):

    label=Work                 the pill's word: your employer, "Work", ...
    days=mon,tue,wed,thu,fri   the work days ("none": never)
    start=09:00                when work time begins on a work day
    end=18:00                  when it ends, the same day, after start
    timezone=                  the employer's time zone (an IANA name,
                               America/New_York); empty = this computer's
    holidays=                  statutory rest days that are free on their
                               own: "mx" (Mexico, below) or empty for none
    personal_owners=           whose repos are yours, by where they push:
                               "you" = github.com/you, or host/owner
                               (gitlab.com/you), comma-separated
    personal_dirs=             folders whose repos are yours, comma-
                               separated; empty = your projects folder
                               (desktop_conf.py)

The holidays and the day off are checked whatever days are set. "mx":
Mexico's statutory rest days (Ley Federal del Trabajo, art. 74): Jan 1, the
first Monday of February, the third Monday of March, May 1, Sep 16, the third
Monday of November, Dec 25, and Oct 1 of each presidential transition year
(2030, 2036, ...). Anything else, off-today.

The git side is yours to wire: a global pre-commit hook (core.hooksPath) can
run `workhours.py personal && ! workhours.py check` and ask before a commit
to one of your own repos during work time. This script never touches git
beyond reading where a repo is and where it pushes.
"""

import datetime as dt
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

START, END = dt.time(9, 0), dt.time(18, 0)   # the defaults, before workhours.conf
WORKDAYS = range(0, 5)                      # Monday .. Friday
LABEL = "Work"
STATE_DIR = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
OFF_FILE = os.path.join(STATE_DIR, "workhours-off")
CONFIG_HOME = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
CONF = os.environ.get("HYPR_WORKHOURS_CONF") or os.path.join(CONFIG_HOME, "hypr", "workhours.conf")
DAY_NAMES = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
HEADER = ("# Work hours (scripts/workhours.py; its docstring explains every key).\n"
          "# Delete this file (or `workhours.py disable`) and work-hours mode is off.\n")

ICON = ""                             # briefcase


def nth_weekday(year, month, weekday, n):
    day = dt.date(year, month, 1)
    day += dt.timedelta(days=(weekday - day.weekday()) % 7)
    return day + dt.timedelta(weeks=n - 1)


def holiday_mx(day):
    """Mexico's statutory rest day's name, or None."""
    fixed = {(1, 1): "Año Nuevo", (5, 1): "Día del Trabajo",
             (9, 16): "Independencia", (12, 25): "Navidad"}
    if (day.month, day.day) in fixed:
        return fixed[(day.month, day.day)]
    if day == nth_weekday(day.year, 2, 0, 1):
        return "Día de la Constitución"
    if day == nth_weekday(day.year, 3, 0, 3):
        return "Natalicio de Benito Juárez"
    if day == nth_weekday(day.year, 11, 0, 3):
        return "Revolución Mexicana"
    if day.month == 10 and day.day == 1 and (day.year - 2024) % 6 == 0:
        return "Transmisión del Poder Ejecutivo"
    return None


HOLIDAYS = {"mx": holiday_mx}               # holidays= value -> its rule


# -- workhours.conf ----------------------------------------------------------------
def load(path=None):
    """The raw key=value dict, or None when there is no file (= off)."""
    try:
        with open(path or CONF) as handle:
            text = handle.read()
    except OSError:
        return None
    conf = {}
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            conf[key.strip()] = value.strip()
    return conf


def _conf(conf):
    """conf as given, or read now when the caller passed none."""
    return load() if conf is None else conf


def holiday(day, conf=None):
    """The statutory rest day's name, or None (always None when off or
    holidays= is empty)."""
    rule = HOLIDAYS.get(((_conf(conf) or {}).get("holidays") or "").strip().lower())
    return rule(day) if rule else None


def zone(conf=None):
    """The configured time zone (a ZoneInfo), or None for this computer's."""
    name = ((_conf(conf) or {}).get("timezone") or "").strip()
    if not name:
        return None
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(name)
    except Exception:           # noqa: BLE001 -- an unknown name: this computer's, like empty
        return None


def now_there(now=None, conf=None):
    """`now` (default: the clock) as a naive time in the work time zone. A
    naive `now` is this computer's local time, as everywhere else."""
    tz = zone(conf)
    if now is None:
        now = dt.datetime.now(tz) if tz else dt.datetime.now()
    elif tz:
        now = now.astimezone(tz)
    return now.replace(tzinfo=None) if tz else now


def parse_hm(text):
    """"9:00" / "09:30" -> dt.time, else ValueError."""
    hour, _, minute = str(text).strip().partition(":")
    return dt.time(int(hour), int(minute or 0))


def parse_days(text):
    """"mon,tue,fri" (or "mon tue fri", "Monday,...") -> sorted weekday
    numbers, 0 = Monday; ValueError for a word that is not a day."""
    days = set()
    for word in str(text).replace(",", " ").lower().split():
        if word == "none":                  # no work days: work-hours mode never starts
            continue
        if word[:3] not in DAY_NAMES:
            raise ValueError(f"not a day: {word!r}")
        days.add(DAY_NAMES.index(word[:3]))
    return tuple(sorted(days))


def hours(conf=None):
    """(start, end, work days) from workhours.conf over the defaults; a line
    that does not parse keeps its default, so a bad hand edit is harmless.
    Off (no file): no work days, so nothing ever starts."""
    conf = _conf(conf)
    if conf is None:
        return START, END, ()
    start, end, days = START, END, tuple(WORKDAYS)
    for key, value in conf.items():
        try:
            if key == "start":
                start = parse_hm(value)
            elif key == "end":
                end = parse_hm(value)
            elif key == "days":
                days = parse_days(value)
        except ValueError:
            pass
    if end <= start:                        # not a working day: back to the defaults
        start, end = START, END
    return start, end, days


def label(conf=None):
    """The pill's word (label=, at most 24 characters), else "Work"."""
    return " ".join(((_conf(conf) or {}).get("label") or "").split())[:24] or LABEL


def write_conf(updates, path=None):
    """Set keys in workhours.conf, keeping every other line (comments too);
    a value of None removes the key. Makes the file (= turns it on)."""
    path = path or CONF
    try:
        with open(path) as handle:
            lines = handle.read().splitlines()
    except OSError:
        lines = HEADER.splitlines()
    out, done = [], set()
    for line in lines:
        key = line.strip().partition("=")[0].strip()
        if not line.strip().startswith("#") and "=" in line and key in updates:
            if updates[key] is not None and key not in done:
                out.append(f"{key}={updates[key]}")
            done.add(key)
            continue
        out.append(line)
    out += [f"{k}={v}" for k, v in updates.items() if k not in done and v is not None]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w") as handle:
        handle.write("\n".join(out) + "\n")
    os.replace(tmp, path)


def set_hours(key, value):
    """Write start / end / days / label to workhours.conf, checked first:
    ValueError (with why) if it is not a time or a day list, the day would
    end before it begins, or work hours are off."""
    conf = load()
    if conf is None:
        raise ValueError("work hours are off: `workhours.py enable` first")
    if key == "label":
        value = " ".join(str(value).split())[:24]
        if not value:
            raise ValueError("the label needs a word")
        write_conf({"label": value})
        return
    start, end, days = hours(conf)
    if key == "start":
        start = parse_hm(value)
    elif key == "end":
        end = parse_hm(value)
    elif key == "days":
        days = parse_days(value)
    else:
        raise ValueError("set start HH:MM, set end HH:MM, set days mon,tue,... or set label TEXT")
    if end <= start:
        raise ValueError(f"work time would end ({end:%H:%M}) before it begins ({start:%H:%M})")
    write_conf({"start": f"{start:%H:%M}", "end": f"{end:%H:%M}",
                "days": ",".join(DAY_NAMES[d] for d in days) or "none"})


def enable():
    """On: the settings `disable` kept, else the defaults (no holidays, this
    computer's time zone, your projects folder as the personal repos)."""
    if os.path.exists(CONF):
        return
    if os.path.exists(CONF + ".off"):
        os.replace(CONF + ".off", CONF)
        return
    write_conf({"label": LABEL, "days": ",".join(DAY_NAMES[d] for d in WORKDAYS),
                "start": f"{START:%H:%M}", "end": f"{END:%H:%M}", "timezone": "", "holidays": "",
                "personal_owners": "", "personal_dirs": ""})


def disable():
    """Off, the file kept beside as workhours.conf.off for `enable`."""
    if os.path.exists(CONF):
        os.replace(CONF, CONF + ".off")


# -- which repos are yours -------------------------------------------------------------
def personal_dirs(conf):
    """personal_dirs= as absolute paths; empty: your projects folder."""
    raw = [d.strip() for d in ((conf or {}).get("personal_dirs") or "").split(",") if d.strip()]
    if not raw:
        try:
            import desktop_conf
            raw = [desktop_conf.projects_dir()]
        except Exception:       # noqa: BLE001 -- no projects folder: owners only
            raw = []
    return [os.path.normpath(os.path.expanduser(d)) for d in raw]


def personal_owners(conf):
    """["github.com/you", "gitlab.com/x"] from personal_owners= ("you" alone
    is GitHub)."""
    out = []
    for o in ((conf or {}).get("personal_owners") or "").split(","):
        o = o.strip().strip("/").lower()
        if o:
            out.append(o if "/" in o else f"github.com/{o}")
    return out


def is_personal(top, origin, conf):
    """The repo whose top folder is `top` and pushes to `origin`: yours? Off
    (conf None): never."""
    if conf is None or not top:
        return False
    top = os.path.normpath(top)
    if any(top == d or top.startswith(d + os.sep) for d in personal_dirs(conf)):
        return True
    url = (origin or "").lower().replace(":", "/")      # git@host:o/r -> git@host/o/r
    return any(f"{o}/" in url for o in personal_owners(conf))


def git_out(*args, cwd=None):
    try:
        return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


# -- the state -------------------------------------------------------------------------
def next_holiday(today, days=400, conf=None):
    """(date, name) of the next statutory rest day after today."""
    conf = _conf(conf)
    for n in range(1, days):
        day = today + dt.timedelta(days=n)
        name = holiday(day, conf)
        if name:
            return day, name
    return None, None


def day_off(today):
    try:
        with open(OFF_FILE) as handle:
            return handle.read().strip() == today.isoformat()
    except OSError:
        return False


def state(now=None):
    """(working, reason, end) -- end is today's END while working (naive, in
    the work time zone, like now_there())."""
    # WORKHOURS_NOW="2026-10-19 10:00" pretends it is then -- for testing the
    # git hook and the pill without waiting for a Monday.
    if now is None and os.environ.get("WORKHOURS_NOW"):
        now = dt.datetime.fromisoformat(os.environ["WORKHOURS_NOW"])
    conf = load()
    if conf is None:
        return False, "work hours off (no workhours.conf)", None
    now = now_there(now, conf)
    today = now.date()
    start, end, days = hours(conf)
    if today.weekday() not in days:
        return False, ("weekend" if today.weekday() >= 5 else "day off (not one of the work days)"), None
    name = holiday(today, conf)
    if name:
        return False, f"holiday: {name}", None
    if day_off(today):
        return False, "day off (workhours.py off-today)", None
    if not (start <= now.time() < end):
        return False, f"outside {start:%H:%M}-{end:%H:%M}", None
    return True, f"{label(conf)} hours, {start:%H:%M}-{end:%H:%M}", dt.datetime.combine(today, end)


def refresh_bar():
    """Redraw custom/workhours (bar_signals.py "workhours")."""
    try:
        if HERE not in sys.path:
            sys.path.insert(0, HERE)
        import bar_signals
        return bar_signals.poke("workhours")
    except Exception:       # noqa: BLE001 - no bar: nothing to redraw
        return 0


def main(argv):
    cmd = argv[0] if argv else "status"
    conf = load()
    working, reason, end = state()
    if cmd == "status" and argv[1:] == ["--json"]:
        start, end_t, days = hours(conf)
        today = now_there(None, conf).date()
        nxt, nxt_name = next_holiday(today, conf=conf)
        tz = zone(conf)
        until = (end.replace(tzinfo=tz) if tz else end).timestamp() if end else None
        print(json.dumps({"enabled": conf is not None, "label": label(conf),
                          "working": working, "reason": reason, "until": until,
                          "start": f"{start:%H:%M}", "end": f"{end_t:%H:%M}",
                          "days": [DAY_NAMES[d] for d in days], "off_today": day_off(today),
                          "timezone": (conf or {}).get("timezone", ""),
                          "holidays": (conf or {}).get("holidays", ""),
                          "holiday": holiday(today, conf),
                          "next_holiday": [nxt.isoformat(), nxt_name] if nxt else None,
                          "conf": CONF}))
    elif cmd == "status":
        print(("off" if conf is None else "work" if working else "free") + f"  ({reason})")
    elif cmd == "check":
        sys.exit(1 if working else 0)
    elif cmd == "personal":
        where = argv[1] if len(argv) > 1 else None
        top = git_out("rev-parse", "--show-toplevel", cwd=where)
        origin = git_out("remote", "get-url", "origin", cwd=where)
        sys.exit(0 if is_personal(top, origin, conf) else 1)
    elif cmd == "bar":
        if not working:
            print(json.dumps({"text": "", "tooltip": "", "class": "free"}))
            return
        now = now_there(dt.datetime.fromisoformat(os.environ["WORKHOURS_NOW"])
                        if os.environ.get("WORKHOURS_NOW") else None, conf)
        h_left, minutes = divmod(int((end - now).total_seconds()) // 60, 60)
        print(json.dumps({
            "text": f"{ICON} {label(conf)} {h_left}:{minutes:02d}",
            "tooltip": (f"Work hours until {end:%H:%M} ({h_left} h {minutes:02d} min left)\n"
                        "Commits to your own repos ask before they go through.\n\n"
                        "Right-click: today is a day off"),
            "class": "work",
        }))
    elif cmd == "off-today":
        os.makedirs(os.path.dirname(OFF_FILE), exist_ok=True)
        with open(OFF_FILE, "w") as handle:
            handle.write(now_there(None, conf).date().isoformat())
        refresh_bar()
        print("Free until midnight.")
    elif cmd == "set" and len(argv) >= 3:
        try:
            set_hours(argv[1], " ".join(argv[2:]))
        except ValueError as exc:
            sys.exit(f"workhours.py: {exc}")
        refresh_bar()
        start, end_t, days = hours()
        print(f"{label()} hours {start:%H:%M}-{end_t:%H:%M}, {' '.join(DAY_NAMES[d] for d in days) or 'no days'}.")
    elif cmd == "enable":
        enable()
        refresh_bar()
        print("Work hours on.")
    elif cmd == "disable":
        disable()
        refresh_bar()
        print("Work hours off.")
    elif cmd == "on":
        try:
            os.remove(OFF_FILE)
        except OSError:
            pass
        refresh_bar()
        print("Work hours back on.")
    else:
        print(__doc__.strip(), file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main(sys.argv[1:])
