#!/usr/bin/env python3
"""Timers, alarms, reminders, focus rounds and a stopwatch, for the launcher
(ALT+E: "timer 5m tea", "alarm 7:30 weekdays", "remind me in 40 min to call
the lab", "focus", "stopwatch") and the bar's countdown pill (custom/timers).

    timers.py timer DURATION [LABEL...] [then ACTION]
                        ring in DURATION: "5m", "1h30m", "90s", "10"
                        (minutes), "1:30" (m:ss), "1:00:00", "5 min", "2 horas"
    timers.py alarm TIME [REPEAT] [LABEL...] [then ACTION] [-- LABEL...]
                        ring at TIME ("7:30", "7am", "19:45", "7:30 pm"), the
                        next time it comes; REPEAT makes it ring every time:
                        daily / every day / diario, weekdays / workdays /
                        entre semana, weekends, or day names ("mon wed fri",
                        "lunes jueves"). Words after "--" are the label as
                        typed, never a repeat or a "then" (the clock card
                        sends its label field this way: "take meds then
                        sleep" is a label, not a suspend)
    timers.py remind (in DURATION | at TIME) MESSAGE...
                        a notification that leads with MESSAGE, one chime,
                        Snooze 5 / 15 / 60 min
    timers.py focus [MINUTES]
                        a focus round (default 25 min, focus_min): Do Not Disturb on
                        while it runs, then a ring and a break starts on its
                        own -- 5 min, every fourth 15 -- and its end rings with
                        "Focus again"; the rounds done today are counted.
                        With focus guard running (focus-guard.py), the
                        round is its focus block: its quiet mode, its
                        breaks setting, distractions dimmed
    timers.py cancel ID|all
    timers.py edit ID TIME [REPEAT|once] [-- LABEL...]
                        change an alarm in place: its time, its repeat
                        (left out: kept; "once": a one-off) and, after "--",
                        its label (left out: kept; "--" alone: none). It is
                        armed again under a new id; "then" and a pause stay
    timers.py pause ID / timers.py resume ID
                        an alarm off without deleting it: its systemd timer
                        stopped, the entry kept with "paused" (restore does
                        not arm it, the bar and the launcher say "paused");
                        resume arms it for its next time -- a countdown's
                        alarm whose moment passed while paused is dropped
                        instead ("that moment has passed")
    timers.py snooze ID / timers.py stop ID
                        a ringing timer or alarm, as its notification's
                        Snooze / Stop buttons (the clock card's ringing row)
    timers.py ringing [--json]   what is ringing right now
    timers.py countdown add [--alarm] DATE [TIME] [LABEL...] [-- LABEL...]
                        a countdown to a date ("2027-01-01 00:00 New Year",
                        "2026-12-24 dinner": midnight when no time), kept
                        until removed; --alarm also sets a one-off alarm at
                        that moment. After "--" the label as typed: neither
                        a time ("5:00 shift" after a bare date) nor the flag
    timers.py countdown alarm ID on|off   that alarm, later
    timers.py countdown remove ID
    timers.py countdown list [--json]
    timers.py stopwatch start|pause|toggle|reset|lap
                        lap: the elapsed time kept as a lap (in the state
                        file, so the clock card shows them after reopening;
                        reset clears them)
    timers.py list
    timers.py bar [watch]      JSON for waybar (watch: a line on each change)
    timers.py click-right      the bar's right click: pause / resume the stopwatch
    timers.py restore          at login (timers.service): arm again what a
                               reboot dropped -- repeating alarms always, the
                               rest if still to come; a one-off whose time
                               passed while the machine was off is said in a
                               notification ("Missed while off")
    timers.py calendar [on|off]
                        every 5 min (timers-calendar.timer): an alarm
                        cal_lead_min before each timed event in Evolution's
                        enabled calendars (the same ones mascot_mood.py and
                        GNOME Calendar read); on/off switches it
    timers.py calendars [--json]          the calendars, and which ring
    timers.py calendars use|skip UID      ring for one calendar, or not
    timers.py fire ID          (systemd runs this when one is due)
    timers.py status [--json]  all of it for Settings > Timers & alarms
    timers.py list --json      what is set, as JSON
    timers.py settings [--json]
    timers.py set KEY VALUE    a setting (below)
    timers.py try-sound        the alarm sound once, as the settings have it

Settings ($XDG_STATE_HOME/hypr/timers.conf, key=value; a missing key is
its default, which is how this behaved before there were settings):
focus_min 25, break_min 5, long_break_min 15, long_every 4 (the focus
rounds); snooze_min 5; sound theme | chime | none (what a ring plays: the
theme's alarm, a quiet chime, nothing) and volume 100 (%); cal_lead_min 10
(calendar alarms this long before the event); cal_skip (calendar uids,
comma-separated, that never ring). Settings > Timers & alarms sets them.

ACTION, after "then": suspend (sleep, suspender), lock (bloquear), pause
music (pause, pausar), shutdown (poweroff, apagar), or "!" and a shell
command. It does not ring: a notification "Suspending in 30 s" with Cancel,
and the action unless Cancel is picked.

Each one is a transient systemd user timer (hypr-timer-<id>.timer), so it
rings with the launcher closed or the bar restarted; a repeating alarm is one
transient timer with a recurring OnCalendar. Transient units end at logout,
hence `restore`. `systemctl --user list-timers 'hypr-timer-*'` shows them.

Ringing: a critical notification (it shows through Do Not Disturb) with
Snooze 5 min (snooze_min) and Stop, the theme's alarm sound (else the
freedesktop one; the sound setting) over and over until one is picked or the
notification closed, at most RING_S.

State: $XDG_STATE_HOME/hypr/timers.json -- {"timers": [{"id", "kind":
timer|alarm|reminder|focus|break|calendar, "label", "due", "secs", "repeat"
(systemd weekdays, "*" every day), "hm", "then", "dnd", "paused",
"countdown" (the countdown an alarm rings for)}], "stopwatch": {"start":
epoch|null, "acc": s, "laps": [elapsed s]}, "focus": {"date", "rounds"},
"calendar": {"off": bool, "seen": [event keys]}, "countdowns": [{"id",
"label", "at": epoch, "alarm": timer id|null}]}. Several processes write it
-- the ring (fire), restore at login, the clock card's commands, the
launcher -- so every load-modify-save holds locked() (an flock on
timers.json.lock) and save() writes through a tmp file of its own pid: two
at once neither mix one file nor lose the other's change. The lock is held
only around the state edit, never around a notification (ask() can wait
RING_S) or systemd-run, so the card never waits on a ring.

While a timer or alarm rings, $XDG_RUNTIME_DIR/hypr-timers/ring-<id>.json
says so (its label, since when, the ringing process's pid); `snooze` / `stop`
write pick-<id> next to it, which the ringing process polls every
RING_POLL_S and answers as if the button had been pressed -- the
notification is dismissed and the same snooze code runs. A ring that times
out (nobody there for RING_S) leaves its notification on screen: the one
trace that it rang. ring_start clears a pick left over from an earlier ring
of the same id (a repeating alarm keeps its id), so yesterday's Stop never
answers today's ring; ringing() sweeps any pick with no ring beside it. Runtime, not
timers.json: a ring is over at logout, and the ringing process never writes
timers.json under a card that is writing it too.
"""

import contextlib
import datetime as dt
import fcntl
import json
import os
import re
import subprocess
import sys
import threading
import time

STATE = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"),
                     "hypr", "timers.json")
UNIT = "hypr-timer-"
SOUND = "/usr/share/sounds/freedesktop/stereo/alarm-clock-elapsed.oga"   # without a theme one


def alarm_sound():
    """The desktop theme's alarm (~/.config/themes/<theme>/sounds/alarm.wav,
    make-theme-sounds.py: low and round, no shrill bell), else SOUND."""
    try:
        with open(os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"),
                               "hypr", "display.conf")) as handle:
            name = next((l.split("=", 1)[1].strip() for l in handle if l.startswith("theme=")), "cyberpunk")
    except OSError:
        name = "cyberpunk"
    path = os.path.expanduser(f"~/.config/themes/{name}/sounds/alarm.wav")
    return path if os.path.exists(path) else SOUND
CHIME = "/usr/share/sounds/freedesktop/stereo/message-new-instant.oga"
RING_S = 60
RING_POLL_S = 0.5           # how often a ringing one looks for the card's Snooze / Stop
RING_DIR = os.path.join(os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}", "hypr-timers")
THEN_WAIT_S = 30            # "Suspending in 30 s": the time to cancel
CAL_AHEAD_MIN = 30          # calendar alarms are armed for events starting within this
                            # (or the lead time + 10 min, when that is longer)
HERE = os.path.dirname(os.path.abspath(__file__))
NOTIFY = os.path.join(HERE, "notify")  # notify-send with the theme's mascot (mascot_notify.py)

# -- settings (timers.py set KEY VALUE; Settings > Timers & alarms) ----------------------
# Kept in $XDG_STATE_HOME/hypr/timers.conf, one "key=value" a line, only the
# ones changed from these defaults (which are how it behaved before there
# was a file). Read afresh on every use, so the launcher daemon and a timer
# firing later both see a change at once.
CONF = os.path.join(os.path.dirname(STATE), "timers.conf")
DEFAULTS = {
    "focus_min": 25,        # a focus round
    "break_min": 5,         # the break after it
    "long_break_min": 15,   # ... and after every long_every-th round
    "long_every": 4,
    "snooze_min": 5,        # "Snooze 5 min" on a ringing timer or alarm
    "sound": "theme",       # theme: the theme's alarm; chime: a quiet chime; none: silent
    "volume": 100,          # % of full, for every sound timers.py plays
    "cal_lead_min": 10,     # calendar alarms: this long before the event
    "cal_skip": "",         # calendars (Evolution source uids, comma-separated) not to ring for
}
LIMITS = {"focus_min": (1, 240), "break_min": (1, 120), "long_break_min": (1, 120), "long_every": (2, 12),
          "snooze_min": (1, 120), "volume": (5, 100), "cal_lead_min": (0, 240)}
SOUNDS = ("theme", "chime", "none")


def settings():
    """DEFAULTS with timers.conf on top; a line that does not parse or is
    out of range is ignored, so a bad hand edit falls back to the default."""
    out = dict(DEFAULTS)
    try:
        with open(CONF) as handle:
            lines = handle.read().splitlines()
    except OSError:
        lines = []
    for line in lines:
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        try:
            out[key] = check_setting(key, value)
        except ValueError:
            pass
    return out


def check_setting(key, value):
    """The value timers.conf keeps for KEY, or ValueError with why not."""
    if key not in DEFAULTS:
        raise ValueError(f"no setting {key!r} (have: {', '.join(DEFAULTS)})")
    if key == "sound":
        if value not in SOUNDS:
            raise ValueError(f"sound is one of {', '.join(SOUNDS)}")
        return value
    if key == "cal_skip":
        return ",".join(u for u in (p.strip() for p in str(value).split(",")) if u)
    try:
        number = int(str(value).removesuffix("%").removesuffix("min").strip())
    except ValueError:
        raise ValueError(f"{key} is a whole number, not {value!r}") from None
    lo, hi = LIMITS[key]
    if not lo <= number <= hi:
        raise ValueError(f"{key} goes from {lo} to {hi}")
    return number


def set_setting(key, value):
    """Write one setting to timers.conf (dropping it when it is back at the
    default); returns the value kept."""
    value = check_setting(key, value)
    values = settings()
    values[key] = value
    changed = {k: v for k, v in values.items() if v != DEFAULTS[k]}
    if not changed:             # all back at the defaults: no file, as before there were settings
        try:
            os.remove(CONF)
        except FileNotFoundError:
            pass
        return value
    os.makedirs(os.path.dirname(CONF), exist_ok=True)
    tmp = f"{CONF}.{os.getpid()}.tmp"       # its own name, so two quick clicks cannot mix files
    with open(tmp, "w") as handle:
        handle.write("# timers.py settings (timers.py set KEY VALUE); missing keys are the defaults\n")
        for k, v in changed.items():
            handle.write(f"{k}={v}\n")
    os.replace(tmp, CONF)
    return value


def setting(key):
    return settings()[key]


# The old constants, still read by other scripts (launcher.py's "focus" and
# "timers" rows): `timers.FOCUS_MIN` and the rest come from the settings, so
# they follow a change without the launcher daemon restarting. A module-level
# __getattr__ only answers for names the module does not define.
_OLD_NAMES = {"FOCUS_MIN": "focus_min", "BREAK_MIN": "break_min", "LONG_BREAK_MIN": "long_break_min",
              "LONG_EVERY": "long_every", "CAL_LEAD_MIN": "cal_lead_min"}


def __getattr__(name):
    if name in _OLD_NAMES:
        return setting(_OLD_NAMES[name])
    if name == "SNOOZE_S":
        return setting("snooze_min") * 60
    raise AttributeError(f"module 'timers' has no attribute {name!r}")


def play_argv(path):
    """pw-play for path at the volume setting (no --volume at 100 %, as before)."""
    volume = setting("volume")
    return ["pw-play"] + ([f"--volume={volume / 100:.2f}"] if volume != 100 else []) + [path]


def sounds_for(loop_sound, chime):
    """What ask() plays, after the sound setting: theme leaves both as the
    caller asked (the theme's alarm looping, a freedesktop sound once);
    chime swaps either for the quiet chime; none plays nothing."""
    choice = setting("sound")
    if choice == "none":
        return None, None
    if choice == "chime":
        return (CHIME if loop_sound else None), (CHIME if chime else None)
    return loop_sound, chime

ICONS = {"timer": "",     # hourglass-half (Font Awesome 6, as escapes
         "alarm": "",     # bell             like the other bar scripts)
         "reminder": "",  # note-sticky
         "focus": "",     # bullseye
         "break": "",     # mug-saucer
         "calendar": "",  # calendar
         "stopwatch": ""}
NAMES = {"timer": "timer", "alarm": "alarm", "reminder": "reminder", "focus": "focus",
         "break": "break", "calendar": "event"}

UNITS = {"s": 1, "sec": 1, "secs": 1, "second": 1, "seconds": 1, "seg": 1, "segundo": 1, "segundos": 1,
         "m": 60, "min": 60, "mins": 60, "minute": 60, "minutes": 60, "minuto": 60, "minutos": 60,
         "h": 3600, "hr": 3600, "hrs": 3600, "hour": 3600, "hours": 3600, "hora": 3600, "horas": 3600}
DAYS = {"mon": 0, "monday": 0, "lun": 0, "lunes": 0, "tue": 1, "tues": 1, "tuesday": 1, "mar": 1,
        "martes": 1, "wed": 2, "wednesday": 2, "mie": 2, "miercoles": 2, "thu": 3, "thur": 3,
        "thurs": 3, "thursday": 3, "jue": 3, "jueves": 3, "fri": 4, "friday": 4, "vie": 4,
        "viernes": 4, "sat": 5, "saturday": 5, "sab": 5, "sabado": 5, "sun": 6, "sunday": 6,
        "dom": 6, "domingo": 6}
SD_DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
REPEATS = [  # (phrase, weekdays), longest first so "every weekday" is not "every"
    ("todos los dias", range(7)), ("every day", range(7)), ("everyday", range(7)),
    ("daily", range(7)), ("diario", range(7)), ("diariamente", range(7)),
    ("every weekday", range(5)), ("weekdays", range(5)), ("workdays", range(5)),
    ("entre semana", range(5)), ("lunes a viernes", range(5)), ("mon-fri", range(5)),
    ("weekends", (5, 6)), ("fines de semana", (5, 6)), ("fin de semana", (5, 6)),
]
THEN = {"suspend": ("Suspending", ["systemctl", "suspend"]),
        "lock": ("Locking the screen", ["loginctl", "lock-session"]),
        "pause": ("Pausing the music", ["playerctl", "--all-players", "pause"]),
        "shutdown": ("Shutting down", ["systemctl", "poweroff"])}
THEN_WORDS = {"suspend": "suspend", "sleep": "suspend", "suspender": "suspend", "dormir": "suspend",
              "lock": "lock", "lock screen": "lock", "lock the screen": "lock", "bloquear": "lock",
              "pause": "pause", "pause music": "pause", "pause the music": "pause",
              "stop music": "pause", "stop the music": "pause", "pausar": "pause",
              "pausar musica": "pause", "pausar la musica": "pause",
              "shutdown": "shutdown", "shut down": "shutdown", "poweroff": "shutdown",
              "power off": "shutdown", "apagar": "shutdown"}


# -- parsing -----------------------------------------------------------------------------
def fold(text):
    """Lower case, accents off: "Miércoles" -> "miercoles"."""
    import unicodedata
    text = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in text if not unicodedata.combining(c))


def parse_duration(text):
    """(seconds, the rest of the words) for a duration at the start of
    text, else (None, text). "1h 30m tea" -> (5400, "tea"); a bare number
    is minutes."""
    words = text.strip().split()
    if not words:
        return None, text
    m = re.fullmatch(r"(?:(\d+):)?(\d{1,2}):(\d{2})", words[0])
    if m:
        h, mi, s = int(m[1] or 0), int(m[2]), int(m[3])
        return h * 3600 + mi * 60 + s, " ".join(words[1:])
    total, used, i = 0, False, 0
    while i < len(words):
        w = words[i].lower().rstrip(",")
        if w in ("and", "y") and used:
            i += 1
            continue
        parts = re.findall(r"(\d+(?:\.\d+)?)([a-z]+)", w)        # "1h30m", "90s", "2.5h"
        if parts and "".join(n + u for n, u in parts) == w and all(u in UNITS for _, u in parts):
            total += sum(float(n) * UNITS[u] for n, u in parts)
            used, i = True, i + 1
            continue
        if re.fullmatch(r"\d+(?:\.\d+)?", w):                     # "5 min"; "10" alone: minutes
            nxt = words[i + 1].lower().rstrip(",") if i + 1 < len(words) else ""
            if nxt in UNITS:
                total += float(w) * UNITS[nxt]
                used, i = True, i + 2
                continue
            if not used:
                total += float(w) * 60
                used, i = True, i + 1
            break
        break
    if not used or total <= 0:
        return None, text
    return int(round(total)), " ".join(words[i:])


def parse_hm(text):
    """((hour, minute), the rest) for "7:30", "7am", "7:30 pm", "19:45" at
    the start of text, else (None, text)."""
    m = re.match(r"\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm|a\.m\.|p\.m\.)?(?=\s|$)", text.lower())
    if not m or (m[2] is None and m[3] is None):
        return None, text
    h, mi = int(m[1]), int(m[2] or 0)
    if m[3]:
        if not 1 <= h <= 12:
            return None, text
        h = h % 12 + (12 if m[3].startswith("p") else 0)
    if h > 23 or mi > 59:
        return None, text
    return (h, mi), text[m.end():].strip()


def next_at(hm, days=range(7), now=None):
    """The next datetime at hour:minute on one of `days` (0 = Monday)."""
    now = now or dt.datetime.now()
    when = now.replace(hour=hm[0], minute=hm[1], second=0, microsecond=0)
    for _ in range(8):
        if when > now and when.weekday() in days:
            return when
        when += dt.timedelta(days=1)
    return None


def parse_clock(text, now=None):
    """(datetime of the next TIME, the rest) -- parse_hm, then next_at."""
    hm, rest = parse_hm(text)
    return (next_at(hm, now=now), rest) if hm else (None, text)


def parse_repeat(text):
    """(weekdays tuple, the rest) for a repeat at the start of text --
    "weekdays tea", "mon wed fri", "lunes y jueves" -- else (None, text)."""
    t = " ".join(fold(text).replace(",", " ").split())
    for phrase, days in REPEATS:
        if t == phrase or t.startswith(phrase + " "):
            return tuple(days), " ".join(text.split()[len(phrase.split()):])
    words, days, i = t.split(), set(), 0
    while i < len(words):
        w = words[i]
        w = w[:-1] if w not in DAYS and w[:-1] in DAYS else w      # "mondays"
        if w in DAYS:
            days.add(DAYS[w])
        elif w not in ("and", "y", "every", "cada", "on", "los"):
            break
        i += 1
    if not days:
        return None, text
    return tuple(sorted(days)), " ".join(text.split()[i:])


def parse_then(text):
    """(text without it, action key or "!cmd" or None) -- a trailing
    "then suspend", "y luego apagar", "then !notify-send hi"."""
    m = re.search(r"\s*\b(?:then|and then|luego|y luego|despues)\s+(.+)$", text, re.I)
    if not m:
        return text, None
    what = m[1].strip()
    if what.startswith("!") and len(what) > 1:
        return text[:m.start()].strip(), what
    key = THEN_WORDS.get(" ".join(fold(what).split()))
    return (text[:m.start()].strip(), key) if key else (text, None)


def then_text(then):
    if not then:
        return ""
    return f"then runs {then[1:]}" if then.startswith("!") else f"then {THEN[then][0].lower()}"


def days_text(days):
    days = tuple(days)
    if days == tuple(range(7)):
        return "every day"
    if days == tuple(range(5)):
        return "weekdays"
    if days == (5, 6):
        return "weekends"
    return " ".join(SD_DAYS[d] for d in days)


def clock(secs):
    """4:05, 1:02:03."""
    secs = max(0, int(secs))
    h, rest = divmod(secs, 3600)
    m, s = divmod(rest, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def span(secs):
    """5 min, 1 h 30 min, 45 s -- a duration in words."""
    secs = int(secs)
    h, rest = divmod(secs, 3600)
    m, s = divmod(rest, 60)
    out = ([f"{h} h"] if h else []) + ([f"{m} min"] if m else []) + ([f"{s} s"] if s else [])
    return " ".join(out) or "0 s"


# -- state -------------------------------------------------------------------------------
def load():
    try:
        with open(STATE) as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    data.setdefault("timers", [])
    data.setdefault("stopwatch", None)
    return data


def save(data):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    # Its own name: a shared "timers.json.tmp" let two writers truncate the
    # same inode, rename a half-written file into place (load() reads that
    # as {} -- every timer gone) and fail the second os.replace.
    tmp = f"{STATE}.{os.getpid()}.tmp"
    with open(tmp, "w") as fh:
        json.dump(data, fh)
    os.replace(tmp, STATE)


_lock = threading.RLock()       # the threads of one process (the launcher daemon)
_lock_fd = [None, 0]            # the flock's fd, and how deep this process holds it


@contextlib.contextmanager
def locked():
    """Hold the state lock (fcntl.flock on timers.json.lock) for one
    load-modify-save. Re-entrant: countdown_alarm calls schedule() and
    cancel() between its own load and save, and a second flock of the same
    file from one process would wait for itself."""
    with _lock:
        if _lock_fd[1] == 0:
            os.makedirs(os.path.dirname(STATE), exist_ok=True)
            fd = os.open(STATE + ".lock", os.O_RDWR | os.O_CREAT, 0o600)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX)
            except OSError:
                os.close(fd)
                raise
            _lock_fd[0] = fd
        _lock_fd[1] += 1
        try:
            yield
        finally:
            _lock_fd[1] -= 1
            if _lock_fd[1] == 0:
                os.close(_lock_fd[0])       # closing the fd releases the flock
                _lock_fd[0] = None


def kept(t, now):
    """Whether an entry still belongs in the state: a repeating or paused
    one always, a one-off until two minutes after its time (after that the
    machine was off when it was due, and restore says it was missed)."""
    return bool(t.get("repeat") or t.get("paused")) or t.get("due", 0) > now - 120


def hm_of(t):
    """An alarm's hour and minute: its "hm" (repeating ones, and one-offs
    edited or paused here), else read off its due time."""
    if t.get("hm"):
        return tuple(map(int, t["hm"].split(":")))
    when = dt.datetime.fromtimestamp(t["due"])
    return when.hour, when.minute


def next_due(t, now=None):
    """When a paused alarm would ring if resumed now: a repeating one on its
    next day at its hm; a one-off at its due time while that is still to
    come, else the next time its hm comes round (pausing a 7:30 alarm for a
    week and resuming it means tomorrow's 7:30, not a missed one). A
    countdown's alarm keeps its date even once it has passed: resume()
    drops that one instead."""
    now = now or dt.datetime.now()
    if t.get("repeat"):
        return next_at(hm_of(t), t.get("days", range(7)), now).timestamp()
    if t.get("due", 0) > now.timestamp() + 1 or t.get("countdown"):     # a countdown's is its date
        return t["due"]
    return next_at(hm_of(t), now=now).timestamp()


def running():
    """Everything set, soonest first, the paused ones last (a one-off whose
    time is long gone -- the machine was off -- is left out). A paused
    alarm comes back as a copy whose due is when it would ring if resumed,
    so a list that counts down to `due` still shows something sensible."""
    now = time.time()
    out = []
    for t in load()["timers"]:
        if not kept(t, now):
            continue
        if t.get("paused"):
            t = dict(t, due=next_due(t))
        out.append(t)
    return sorted(out, key=lambda t: (bool(t.get("paused")), t["due"]))


def stopwatch(data=None):
    """(elapsed seconds, running?) or None."""
    sw = (data or load())["stopwatch"]
    if not sw:
        return None
    acc = sw.get("acc", 0.0)
    if sw.get("start"):
        return acc + time.time() - sw["start"], True
    return acc, False


def laps(data=None):
    """The stopwatch's laps, as the elapsed time at each (oldest first)."""
    sw = (data or load())["stopwatch"] or {}
    return [float(x) for x in sw.get("laps") or [] if isinstance(x, (int, float))]


def lap_rows(marks):
    """[(n, split, total)] for laps taken at `marks` elapsed seconds,
    newest first, as the clock card and `stopwatch lap` show them."""
    out, last = [], 0.0
    for n, total in enumerate(marks, 1):
        out.append((n, total - last, total))
        last = total
    return out[::-1]


def rounds_today():
    f = load().get("focus") or {}
    return f.get("rounds", 0) if f.get("date") == dt.date.today().isoformat() else 0


# -- arming ------------------------------------------------------------------------------
def systemctl(*args, timeout=20):
    """systemctl --user's exit code; 1 when it failed to run or hung."""
    try:
        return subprocess.run(["systemctl", "--user", *args], stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL, timeout=timeout).returncode
    except (OSError, subprocess.SubprocessError):
        return 1


def arm(entry):
    """The systemd timer that rings `entry`: at its due time, or on every
    one of its repeat days at its hm."""
    if entry.get("repeat"):
        cal = f"{entry['repeat']} *-*-* {entry['hm']}:00"
    else:
        cal = dt.datetime.fromtimestamp(entry["due"]).strftime("%Y-%m-%d %H:%M:%S")
    what = f"{NAMES[entry['kind']].capitalize()}{': ' + entry['label'] if entry['label'] else ''}"
    argv = ["systemd-run", "--user", "--quiet", f"--unit={UNIT}{entry['id']}",
            f"--on-calendar={cal}", "--timer-property=AccuracySec=1s",
            f"--description={what}", sys.executable, os.path.join(HERE, "timers.py"),
            "fire", entry["id"]]
    try:
        subprocess.run(argv, check=True, stdout=subprocess.DEVNULL, timeout=30)
    except subprocess.TimeoutExpired as exc:
        # A hung user manager: the callers' "could not arm it" path.
        raise subprocess.CalledProcessError(124, argv) from exc


def new_id():
    time.sleep(0.002)       # two in one call (focus -> break) get different ids
    return f"{int(time.time() * 1000) % 10**10:010d}"


def schedule(kind, due, label="", secs=None, **extra):
    """A one-off ringing at epoch `due` (or, with repeat= and hm=, a
    repeating alarm whose first ring is `due`). Returns its entry."""
    entry = {"id": new_id(), "kind": kind, "label": label, "due": due, "secs": secs, **extra}
    arm(entry)
    with locked():
        data = load()
        now = time.time()
        data["timers"] = [t for t in data["timers"] if kept(t, now)] + [entry]
        save(data)
    return entry


def start_timer(secs, label="", then=None):
    return schedule("timer", time.time() + secs, label, secs, then=then)


def start_alarm(when, label="", then=None, days=None):
    if days:
        when = next_at((when.hour, when.minute), days)
        return schedule("alarm", when.timestamp(), label, repeat=",".join(SD_DAYS[d] for d in days),
                        days=list(days), hm=f"{when:%H:%M}", then=then)
    return schedule("alarm", when.timestamp(), label, then=then)


def start_reminder(due, message):
    return schedule("reminder", due, message)


def start_focus(minutes=None, guard=True):
    """A focus round: Do Not Disturb on (if it was off; the round's end
    turns it off again), the pill a bullseye counting down. While focus
    guard's service runs (focus-guard.py), the round is its focus block
    instead -- its quiet mode, breaks and dimming -- and this only asks it;
    guard=False (focus guard's own fallback) never asks."""
    minutes = minutes or setting("focus_min")
    if guard:
        reply = guard_start(minutes)
        if reply is not None:
            return reply
    dnd = False
    if "do-not-disturb" not in makoctl("mode").split():
        makoctl("mode", "-a", "do-not-disturb")
        dnd = True
        bell()
    return schedule("focus", time.time() + minutes * 60, "", minutes * 60, dnd=dnd)


def guard_start(minutes):
    """focus-guard.sock's "start": its reply, or None when it is not
    running (or did not answer) -- then the plain round goes ahead."""
    import socket
    path = os.path.join(os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}", "focus-guard.sock")
    if not os.path.exists(path):
        return None
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(10)
            sock.connect(path)
            sock.sendall(json.dumps({"op": "start", "minutes": minutes}).encode() + b"\n")
            data = b""
            while not data.endswith(b"\n"):
                chunk = sock.recv(65536)
                if not chunk:
                    break
                data += chunk
        reply = json.loads(data or b"null")
    except (OSError, ValueError):
        return None
    return reply if isinstance(reply, dict) else None


def cancel(tid):
    with locked():
        data = load()
        ids = [t["id"] for t in data["timers"]] if tid == "all" else [tid]
        dnd = any(t["id"] in ids and t.get("dnd") for t in data["timers"])
        data["timers"] = [t for t in data["timers"] if t["id"] not in ids]
        save(data)
    for i in ids:
        systemctl("stop", f"{UNIT}{i}.timer", f"{UNIT}{i}.service")
    if dnd:
        makoctl("mode", "-r", "do-not-disturb")
        dnd_released()


@locked()
def stopwatch_do(action):
    """start / pause / toggle / reset / lap. A lap is only taken from a
    stopwatch that has run (0.0 elapsed is not a lap); it returns the lap's
    elapsed time, the rest None."""
    data = load()
    sw = data["stopwatch"] or {"start": None, "acc": 0.0}
    now = time.time()
    taken = None
    if action == "toggle":
        action = "pause" if sw.get("start") else "start"
    if action == "start" and not sw.get("start"):
        sw["start"] = now
    elif action == "pause" and sw.get("start"):
        sw["acc"] = sw.get("acc", 0.0) + now - sw["start"]
        sw["start"] = None
    elif action == "reset":
        sw = None
    elif action == "lap":
        if not data["stopwatch"]:
            return None
        taken = sw.get("acc", 0.0) + (now - sw["start"] if sw.get("start") else 0.0)
        if taken <= 0 or (sw.get("laps") and taken <= sw["laps"][-1]):
            return None             # paused since the last lap: the same moment twice is no lap
        sw["laps"] = (sw.get("laps") or []) + [round(taken, 2)]
    data["stopwatch"] = sw
    save(data)
    return taken


# -- editing and pausing alarms (the clock card's Alarms tab) ----------------------------
def find(data, tid):
    return next((t for t in data["timers"] if t["id"] == tid), None)


KEEP = object()         # edit_alarm: this part stays as it is


def edit_alarm(tid, hm=KEEP, days=KEEP, label=KEEP):
    """Change an alarm's time (hour, minute), repeat (a weekday tuple, or
    None for a one-off) and label, each left as it is when KEEP. It gets a
    new id: the new systemd timer is armed first and only then is the old
    one stopped, so a failure to arm leaves the old alarm ringing. A paused
    alarm stays paused (not armed). Returns the new entry; ValueError when
    there is no such alarm, or it rings for a countdown (change that
    instead: its date is not a time of day)."""
    data = load()
    old = find(data, tid)
    if old is None or old["kind"] != "alarm":
        raise ValueError(f"no alarm {tid}")
    if old.get("countdown"):
        raise ValueError("this alarm rings for a countdown: change the countdown instead")
    hm = hm_of(old) if hm is KEEP else tuple(hm)
    if days is KEEP:
        days = tuple(old.get("days") or ()) if old.get("repeat") else None
    days = tuple(sorted(set(days))) if days else None
    entry = {k: v for k, v in old.items() if k not in ("repeat", "days")}
    entry.update(id=new_id(), hm=f"{hm[0]:02d}:{hm[1]:02d}",
                 label=old.get("label", "") if label is KEEP else " ".join(label.split()))
    if days:
        entry.update(repeat=",".join(SD_DAYS[d] for d in days), days=list(days))
    entry["due"] = next_at(hm, days or range(7)).timestamp()
    if not entry.get("paused"):
        arm(entry)
    systemctl("stop", f"{UNIT}{tid}.timer", f"{UNIT}{tid}.service")
    with locked():              # only here: arm() and systemctl stay outside the lock
        data = load()           # again: arming took a moment, and the old entry is replaced where it was
        data["timers"] = [entry if t["id"] == tid else t for t in data["timers"]]
        if not find(data, entry["id"]):
            data["timers"].append(entry)
        save(data)
    return entry


def pause(tid):
    """An alarm off without deleting it: its systemd timer stopped, the
    entry kept with paused and its hm (so resume knows the time of day of
    a one-off too). Returns the entry; ValueError when it is not an alarm."""
    with locked():
        data = load()
        entry = find(data, tid)
        if entry is None or entry["kind"] != "alarm":
            raise ValueError(f"no alarm {tid}")
        if entry.get("paused"):
            return entry
        h, m = hm_of(entry)
        entry.update(paused=True, hm=f"{h:02d}:{m:02d}")
        save(data)
    # After the save: a ring in between finds it paused and stays quiet.
    systemctl("stop", f"{UNIT}{tid}.timer", f"{UNIT}{tid}.service")
    return entry


def resume(tid):
    """A paused alarm armed again for its next time (next_due). A
    countdown's alarm whose moment passed while it was paused has nothing
    left to ring: armed, its fixed OnCalendar in the past would never
    elapse, and unpaused, kept() would drop it on the next save without a
    word -- so it is dropped here, its countdown's bell turned off, and
    ValueError says why."""
    data = load()
    entry = find(data, tid)
    if entry is None or entry["kind"] != "alarm":
        raise ValueError(f"no alarm {tid}")
    if not entry.get("paused"):
        return entry
    if entry.get("countdown") and entry["due"] <= time.time():
        with locked():
            data = load()
            data["timers"] = [t for t in data["timers"] if t["id"] != tid]
            for c in data.get("countdowns") or []:
                if isinstance(c, dict) and c.get("alarm") == tid:
                    c["alarm"] = None
            save(data)
        raise ValueError("that moment has passed: the countdown's alarm is off")
    entry["due"] = next_due(entry)
    entry.pop("paused")
    arm(entry)                  # outside the lock: systemd-run takes a moment
    with locked():
        data = load()
        if find(data, tid) is None:     # cancelled meanwhile: not brought back
            systemctl("stop", f"{UNIT}{tid}.timer", f"{UNIT}{tid}.service")
            return entry
        data["timers"] = [entry if t["id"] == tid else t for t in data["timers"]]
        save(data)
    return entry


# -- countdowns to a date (the clock card's Timer tab) -----------------------------------
def parse_date(text, now=None):
    """(datetime, the rest) for "2027-01-01", "2027-01-01 00:00",
    "2027-01-01T18:30", "2026-12-24 7pm" at the start of text -- midnight
    when no time follows -- else (None, text)."""
    m = re.match(r"\s*(\d{4})-(\d{1,2})-(\d{1,2})(?:T(\d{1,2}):(\d{2}))?(?=\s|$)", text)
    if not m:
        return None, text
    try:
        day = dt.datetime(int(m[1]), int(m[2]), int(m[3]))
    except ValueError:
        return None, text
    rest = text[m.end():].strip()
    if m[4] is not None:
        hm = (int(m[4]), int(m[5]))
        if hm[0] > 23 or hm[1] > 59:
            return None, text
    else:
        hm, rest = parse_hm(rest)
        hm = hm or (0, 0)
    return day.replace(hour=hm[0], minute=hm[1]), rest


def until_text(secs):
    """What a countdown to a date shows: "412 d 3 h", "3 h 20 min",
    "12 min", "45 s", and "now" / "passed" once it is (within a minute)."""
    secs = int(secs)
    if secs < -60:
        return "passed"
    if secs < 1:
        return "now"
    d, rest = divmod(secs, 86400)
    h, rest = divmod(rest, 3600)
    m, s = divmod(rest, 60)
    if d:
        return f"{d} d {h} h" if h else f"{d} d"
    if h:
        return f"{h} h {m} min" if m else f"{h} h"
    return f"{m} min" if m else f"{s} s"


def countdowns(data=None):
    """The countdowns to a date, soonest first."""
    items = [c for c in (data or load()).get("countdowns") or [] if isinstance(c, dict) and "at" in c]
    return sorted(items, key=lambda c: c["at"])


def countdown_add(when, label="", alarm=False):
    """A countdown to the datetime `when` (ValueError once it has passed),
    with a one-off alarm at that moment when alarm. Returns its entry."""
    if when.timestamp() <= time.time():
        raise ValueError(f"{when:%Y-%m-%d %H:%M} has passed")
    entry = {"id": "c" + new_id(), "label": " ".join(label.split()), "at": when.timestamp(), "alarm": None}
    if alarm:
        entry["alarm"] = schedule("alarm", entry["at"], entry["label"] or "Countdown",
                                  countdown=entry["id"])["id"]
    with locked():
        data = load()
        data["countdowns"] = countdowns(data) + [entry]
        save(data)
    return entry


def countdown_alarm(cid, on):
    """Its alarm on (a one-off at the moment, if still to come) or off."""
    data = load()
    entry = next((c for c in countdowns(data) if c["id"] == cid), None)
    if entry is None:
        raise ValueError(f"no countdown {cid}")
    armed = entry.get("alarm") and find(data, entry["alarm"])
    if on and not armed:
        if entry["at"] <= time.time():
            raise ValueError("that moment has passed")
        entry["alarm"] = schedule("alarm", entry["at"], entry["label"] or "Countdown", countdown=cid)["id"]
    elif not on and armed:
        cancel(entry["alarm"])
        entry["alarm"] = None
    elif not armed:
        entry["alarm"] = None
    with locked():
        data = load()
        data["countdowns"] = [entry if c["id"] == cid else c for c in countdowns(data)]
        save(data)
    return entry


def countdown_remove(cid):
    entry = next((c for c in countdowns() if c["id"] == cid), None)
    if entry and entry.get("alarm"):
        cancel(entry["alarm"])
    with locked():
        data = load()
        data["countdowns"] = [c for c in countdowns(data) if c["id"] != cid]
        save(data)


def countdown_armed(c, data=None):
    """Whether a countdown's alarm is still set (it is gone once it rang)."""
    return bool(c.get("alarm")) and find(data or load(), c["alarm"]) is not None


# -- ringing: what rings now, and the card's Snooze / Stop -------------------------------
def ring_path(tid, what="ring"):
    return os.path.join(RING_DIR, f"{what}-{tid}" + (".json" if what == "ring" else ""))


def alive(pid):
    try:
        os.kill(int(pid), 0)
    except (OSError, ValueError, TypeError):
        return False
    return True


def ringing():
    """[{"id", "kind", "label", "since", "pid", "snooze"}] of what rings
    now: the ring files whose process is still there (a file left behind
    by a ring that was killed is ignored, and removed)."""
    out = []
    try:
        names = sorted(os.listdir(RING_DIR))
    except OSError:
        return out
    for name in names:
        if name.startswith("pick-") and not name.endswith(".tmp") \
                and f"ring-{name[5:]}.json" not in names:
            # An orphan: ring_pick checked the ring, then the ring ended (its
            # own button, at the same moment) before the pick landed. Not a
            # .tmp -- ring_pick may still be writing that one.
            try:
                os.remove(os.path.join(RING_DIR, name))
            except OSError:
                pass
            continue
        if not (name.startswith("ring-") and name.endswith(".json")):
            continue
        path = os.path.join(RING_DIR, name)
        try:
            with open(path) as handle:
                ring = json.load(handle)
        except (OSError, ValueError):
            continue
        if not isinstance(ring, dict) or not alive(ring.get("pid")) \
                or time.time() - ring.get("since", 0) > RING_S + 30:
            for stale in (path, ring_path(name[5:-5], "pick")):
                try:
                    os.remove(stale)
                except OSError:
                    pass
            continue
        out.append(ring)
    return out


def ring_pick(tid, what):
    """The card's Snooze / Stop for what rings as tid: written for the
    ringing process to answer (ask() polls it). False when nothing rings
    under that id."""
    if what not in ("snooze", "stop"):
        raise ValueError(what)
    if not any(r["id"] == tid for r in ringing()):
        return False
    tmp = ring_path(tid, "pick") + f".{os.getpid()}.tmp"
    with open(tmp, "w") as handle:
        handle.write(what)
    os.replace(tmp, ring_path(tid, "pick"))
    return True


def ring_start(entry, snooze):
    os.makedirs(RING_DIR, exist_ok=True)
    # A pick left from an earlier ring under this id (a repeating alarm
    # keeps its id day after day) would answer this one at the first poll.
    # No real pick is lost: ring_pick refuses until the ring file below is.
    try:
        os.remove(ring_path(entry["id"], "pick"))
    except OSError:
        pass
    tmp = ring_path(entry["id"]) + ".tmp"
    with open(tmp, "w") as handle:
        json.dump({"id": entry["id"], "kind": entry["kind"], "label": entry.get("label") or "",
                   "since": time.time(), "pid": os.getpid(), "snooze": snooze}, handle)
    os.replace(tmp, ring_path(entry["id"]))


def ring_end(tid):
    for what in ("ring", "pick"):
        try:
            os.remove(ring_path(tid, what))
        except OSError:
            pass


def read_pick(tid):
    try:
        with open(ring_path(tid, "pick")) as handle:
            return handle.read().strip()
    except OSError:
        return ""


def restore():
    """After a login: arm again what is not armed. A one-off that passed
    while the machine was off is dropped, and said."""
    with locked():
        missed = _restore()
    if missed:
        lines = [f"{dt.datetime.fromtimestamp(t['due']):%a %H:%M}  {t['label'] or NAMES[t['kind']]}"
                 for t in missed]
        try:
            subprocess.run([NOTIFY, "-a", "Timer", "-i", "alarm-symbolic", "Missed while off",
                            "\n".join(lines)], timeout=30)
        except (OSError, subprocess.SubprocessError):
            pass


def _restore():
    """restore()'s state edit, under its lock (at login, before the card
    can be open: arming here holds it a moment). Returns the missed ones."""
    data = load()
    now = time.time()
    keep, missed = [], []
    for t in data["timers"]:
        if t.get("paused"):         # paused: kept as it is, and never armed
            keep.append(t)
            continue
        armed = systemctl("is-active", "--quiet", f"{UNIT}{t['id']}.timer") == 0
        if t.get("repeat"):
            if not armed:
                t["due"] = next_at(tuple(map(int, t["hm"].split(":"))), t["days"]).timestamp()
                arm(t)
            keep.append(t)
        elif t["due"] > now + 1:
            if not armed:
                arm(t)
            keep.append(t)
        elif not armed and t["kind"] in ("alarm", "reminder", "timer", "calendar"):
            missed.append(t)
    data["timers"] = keep
    save(data)
    return missed


# -- ringing -----------------------------------------------------------------------------
def makoctl(*args):
    try:
        return subprocess.run(["makoctl", *args], capture_output=True, text=True, timeout=3).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def bell():
    """Redraw the bar's notification bell (bar_signals.py "notifications")."""
    try:
        if HERE not in sys.path:
            sys.path.insert(0, HERE)
        import bar_signals
        return bar_signals.poke("notifications")
    except Exception:       # noqa: BLE001 - no bar: nothing to redraw
        return 0


def loop_argv(path):
    """sh running path's player over and over -- the player's argv goes in
    as the script's own arguments ("$@"), never pasted into the shell text,
    so no sound path (a quote, a $ in a theme folder) can break or inject.
    The quiet chime is a short blip, so it gets a pause between rings; the
    theme's alarm plays back to back (a pause only when the player fails)."""
    gap = "; sleep 2" if path == CHIME else " || sleep 2"
    return ["sh", "-c", f'while :; do "$@"{gap}; done', "sh", *play_argv(path)]


def dnd_released():
    """A focus round took its Do Not Disturb away: the bell, and auto-dnd.py
    woken (as notify-settings.py's poke_auto_dnd does) so a game, a screen
    share or the quiet hours still going put it back now, not at its next
    30 s rescan. Only when it runs: SIGUSR1 without its handler would end it."""
    bell()
    try:
        if subprocess.run(["systemctl", "--user", "is-active", "--quiet", "auto-dnd.service"],
                          timeout=3).returncode == 0:
            subprocess.run(["systemctl", "--user", "kill", "--signal=USR1", "auto-dnd.service"], timeout=3)
    except (OSError, subprocess.SubprocessError):
        pass


def ask(title, body, actions, loop_sound=None, chime=None, wait=RING_S, urgency="critical", ring=None):
    """A notification with buttons, the picked one's key back ("" if it
    was closed or timed out); loop_sound plays until then. Both go through
    the sound and volume settings (sounds_for, play_argv). With ring (a
    timer id), the clock card can answer too: see wait_pick()."""
    loop = once = None
    loop_sound, chime = sounds_for(loop_sound, chime)
    if loop_sound:
        loop = subprocess.Popen(loop_argv(loop_sound), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                start_new_session=True)
    elif chime:
        once = subprocess.Popen(play_argv(chime), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    argv = [NOTIFY, "-a", "Timer", "-u", urgency, "-i", "alarm-symbolic", "--wait"]
    for key, text in actions:
        argv += ["-A", f"{key}={text}"]
    try:
        if ring:
            out = wait_pick(argv + [title, body], ring, wait)
        else:
            out = subprocess.run(argv + [title, body], capture_output=True, text=True,
                                 timeout=wait).stdout.strip()
    except subprocess.TimeoutExpired:
        out = ""
    finally:
        if loop is not None:
            try:
                os.killpg(loop.pid, 15)
                loop.wait(timeout=3)        # reaped, not a zombie
            except (OSError, subprocess.SubprocessError):
                pass
        if once is not None:
            try:
                once.wait(timeout=5)        # a chime is a second long
            except subprocess.TimeoutExpired:
                once.kill()
                once.wait()
    return out


def wait_pick(argv, tid, wait):
    """notify-send --wait for a ringing one, while the clock card may pick
    for it: the notification's own button, or a pick-<tid> file (ring_pick),
    whichever comes first, as the action's key. On a card pick the
    notification is dismissed (makoctl, by the id -p printed: stdbuf so it
    arrives at once rather than when notify-send exits). On a timeout
    (`wait` with no answer) notify-send is stopped but the notification
    stays, as it did before the card could answer: a ring nobody heard
    leaves that toast as its only trace."""
    import queue
    import threading
    lines = queue.Queue()
    import shutil
    line_buffered = ["stdbuf", "-oL"] if shutil.which("stdbuf") else []
    proc = subprocess.Popen(line_buffered + argv[:1] + ["-p"] + argv[1:], stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, text=True)

    def read():
        for line in proc.stdout:
            lines.put(line.strip())
        lines.put(None)
    threading.Thread(target=read, daemon=True).start()
    nid, out, end, card = None, "", time.monotonic() + wait, False
    try:
        while time.monotonic() < end:
            picked = read_pick(tid)
            if picked:
                out, card = picked, True
                break
            try:
                line = lines.get(timeout=RING_POLL_S)
            except queue.Empty:
                continue
            if line is None:                    # notify-send is done: closed, or a button
                break
            if nid is None and line.isdigit():
                nid = line
            elif line:
                out = line
                break
    finally:
        if proc.poll() is None:
            proc.kill()
            if nid and card:
                makoctl("dismiss", "-n", nid)
    return out


def do_then(then, label):
    """The action after a timer: said first, with THEN_WAIT_S to cancel."""
    if then.startswith("!"):
        what, argv = f"Running {then[1:]}", ["sh", "-c", then[1:]]
    else:
        what, argv = THEN[then]
    picked = ask(f"{what} in {THEN_WAIT_S} s", label or "the timer is up",
                 [("cancel", "Cancel"), ("now", "Now")], chime=CHIME, wait=THEN_WAIT_S)
    if picked != "cancel":
        subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)


def fire(tid):
    # The lock only around the state edits: the ring below waits up to
    # RING_S, and the card's commands must not wait with it.
    with locked():
        data = load()
        entry = next((t for t in data["timers"] if t["id"] == tid), None)
        if entry is None or entry.get("paused"):      # paused: a timer that was not stopped in time
            return
        if entry.get("repeat"):     # rings again on its next day: only the due moves
            entry["due"] = next_at(tuple(map(int, entry["hm"].split(":"))), entry["days"],
                                   dt.datetime.now() + dt.timedelta(minutes=1)).timestamp()
        else:
            data["timers"] = [t for t in data["timers"] if t["id"] != tid]
        save(data)
    kind, label = entry["kind"], entry["label"]

    if entry.get("then"):
        do_then(entry["then"], label)
        return

    if kind == "focus":
        if entry.get("dnd"):
            makoctl("mode", "-r", "do-not-disturb")
            dnd_released()
        with locked():
            data = load()
            today = dt.date.today().isoformat()
            f = data.get("focus") or {}
            n = (f.get("rounds", 0) if f.get("date") == today else 0) + 1
            data["focus"] = {"date": today, "rounds": n}
            save(data)
        if entry.get("nobreak"):    # focus guard's block with breaks off: its summary says the end
            return
        conf = settings()
        rest = conf["long_break_min"] if n % conf["long_every"] == 0 else conf["break_min"]
        schedule("break", time.time() + rest * 60, "", rest * 60)
        picked = ask(f"Focus round {n} done", f"{rest} min break started  ·  {n} today",
                     [("skip", "Skip the break"), ("stop", "Stop")], chime=SOUND, wait=20,
                     urgency="normal")
        if picked in ("skip", "stop"):
            for t in load()["timers"]:
                if t["kind"] == "break":
                    cancel(t["id"])
            if picked == "skip":
                start_focus(round((entry.get("secs") or setting("focus_min") * 60) / 60))
        return

    if kind == "break":
        picked = ask("Break's over", f"{rounds_today()} focus rounds today",
                     [("focus", f"Focus again ({setting('focus_min')} min)"), ("stop", "Stop")],
                     loop_sound=alarm_sound(), wait=RING_S)
        if picked == "focus":
            start_focus()
        return

    if kind == "reminder":
        set_at = dt.datetime.now().strftime("%H:%M")
        picked = ask(label or "Reminder", f"reminder  ·  {set_at}",
                     [("5", "In 5 min"), ("15", "15 min"), ("60", "1 hour"), ("done", "Done")],
                     chime=CHIME, wait=3600)
        if picked in ("5", "15", "60"):
            start_reminder(time.time() + int(picked) * 60, label)
        return

    if kind == "calendar":
        title = label or "Event"
        body = f"starts at {dt.datetime.fromtimestamp(entry['event_at']):%H:%M}" \
            if entry.get("event_at") else "coming up"
        # "Remind me at the start" only when the start is still to come (with
        # cal_lead_min 0 the alarm already is the start).
        later = bool(entry.get("event_at")) and entry["event_at"] > time.time() + 30
        picked = ask(title, body, ([("snooze", "Remind me at the start")] if later else []) + [("ok", "OK")],
                     chime=SOUND, wait=600)
        if picked == "snooze" and entry.get("event_at") and entry["event_at"] > time.time() + 30:
            schedule("calendar", entry["event_at"], label, event_at=entry["event_at"])
        return

    title = label or ("Time's up" if kind == "timer" else "Alarm")
    body = (f"{span(entry['secs'])} timer" if kind == "timer" and entry.get("secs")
            else dt.datetime.now().strftime("%H:%M alarm")
            + (f"  ·  {days_text(entry['days'])}" if entry.get("repeat") else ""))
    snooze = setting("snooze_min") * 60
    ring_start(entry, snooze)
    try:
        picked = ask(title, body, [("snooze", f"Snooze {span(snooze)}"), ("stop", "Stop")],
                     loop_sound=alarm_sound(), ring=tid)
    finally:
        ring_end(tid)
    if picked == "snooze":
        schedule("timer" if kind == "timer" else "alarm", time.time() + snooze, label,
                 snooze if kind == "timer" else None)


# -- calendar ----------------------------------------------------------------------------
def calendar_registry():
    """Evolution's source registry and its EDataServer module (the same
    calendars GNOME Calendar and mascot_mood.py read)."""
    import gi
    gi.require_version("EDataServer", "1.2")
    from gi.repository import EDataServer
    return EDataServer.SourceRegistry.new_sync(None), EDataServer


def calendars():
    """[{uid, name, account, enabled, used}] for every calendar Evolution
    knows. enabled: switched on in Evolution / GNOME Calendar (an off one is
    never read); used: not in the cal_skip setting, so it rings."""
    reg, eds = calendar_registry()
    skip = set(filter(None, setting("cal_skip").split(",")))
    out = []
    for src in reg.list_sources(eds.SOURCE_EXTENSION_CALENDAR):
        parent = reg.ref_source(src.get_parent()) if src.get_parent() else None
        out.append({"uid": src.get_uid(), "name": src.get_display_name() or src.get_uid(),
                    "account": parent.get_display_name() if parent else "",
                    "enabled": bool(src.get_enabled()), "used": src.get_uid() not in skip})
    return sorted(out, key=lambda c: (not c["enabled"], c["account"].lower(), c["name"].lower()))


def calendar_use(uid, on):
    """Ring (on) or not for one calendar: its uid off or on the cal_skip list."""
    skip = [u for u in setting("cal_skip").split(",") if u and u != uid]
    set_setting("cal_skip", ",".join(skip + ([] if on else [uid])))


def cal_ahead_min():
    """How far ahead calendar_sync looks: far enough that an event is seen
    (every 5 min) before its alarm is due, however long the lead time."""
    return max(CAL_AHEAD_MIN, setting("cal_lead_min") + 10)


def upcoming_events(minutes):
    """[(start datetime, summary, key)] of timed events in Evolution's
    enabled calendars (less the ones in cal_skip) starting within `minutes`
    (mascot_mood's reader)."""
    sys.path.insert(0, HERE)
    import mascot_mood
    import gi
    gi.require_version("ICalGLib", "3.0")
    gi.require_version("ECal", "2.0")
    gi.require_version("EDataServer", "1.2")
    from gi.repository import ECal, EDataServer, ICalGLib
    now = dt.datetime.now().replace(second=0, microsecond=0)
    end = now + dt.timedelta(minutes=minutes)
    day = dt.datetime.combine(now.date(), dt.time())
    out = []
    skip = set(filter(None, setting("cal_skip").split(",")))
    reg = EDataServer.SourceRegistry.new_sync(None)
    for src in reg.list_sources(EDataServer.SOURCE_EXTENSION_CALENDAR):
        if not src.get_enabled() or src.get_uid() in skip:
            continue
        try:
            client = ECal.Client.connect_sync(src, ECal.ClientSourceType.EVENTS, 1, None)
            _ok, objs = client.get_object_list_as_comps_sync("#t", None)
        except Exception:
            continue
        for obj in objs or []:
            comp = obj.get_icalcomponent()
            if comp.isa() == ICalGLib.ComponentKind.VCALENDAR_COMPONENT:
                comp = comp.get_first_component(ICalGLib.ComponentKind.VEVENT_COMPONENT) or comp
            try:
                whens, all_day = mascot_mood._occurrences(comp, day, day + dt.timedelta(days=2))
            except Exception:
                continue
            if all_day:
                continue
            summary = (comp.get_summary() or "").strip() or "an event"
            for w in whens:
                if now <= w < end:
                    out.append((w, summary, f"{comp.get_uid()}@{w:%Y%m%dT%H%M}"))
    return out


def calendar_sync():
    """Arm an alarm cal_lead_min (a setting) before each event starting
    within cal_ahead_min(), once per event (its uid and start)."""
    data = load()
    cal = data.get("calendar") or {}
    if cal.get("off"):
        return
    try:
        events = upcoming_events(cal_ahead_min())
    except Exception as exc:
        print(f"timers.py: calendar unavailable ({exc})", file=sys.stderr)
        return
    seen = set(cal.get("seen", []))
    lead = setting("cal_lead_min") * 60
    for start, summary, key in events:
        if key in seen:
            continue
        seen.add(key)
        due = max(time.time() + 5, start.timestamp() - lead)
        schedule("calendar", due, summary, event_at=start.timestamp())
    cutoff = (dt.datetime.now() - dt.timedelta(days=2)).strftime("%Y%m%d")
    with locked():
        data = load()
        data["calendar"] = {"off": False, "seen": [k for k in seen if k.rsplit("@", 1)[-1][:8] >= cutoff]}
        save(data)


@locked()
def calendar_switch(on):
    data = load()
    cal = data.get("calendar") or {}
    cal["off"] = not on
    data["calendar"] = cal
    save(data)


def calendar_on():
    return not (load().get("calendar") or {}).get("off")


# -- the bar -----------------------------------------------------------------------------
def describe(t, now):
    """"tea  (at 15:04)", "gym  (at Mon 07:30  ·  weekdays)"; a paused
    alarm "gym  (paused · 07:30  ·  weekdays)" -- the launcher's list and
    the bar's tooltip both say it this way."""
    at = dt.datetime.fromtimestamp(t["due"]).strftime("%a %H:%M" if t["due"] - now > 86400 / 2 else "%H:%M")
    if t.get("paused"):
        at = "paused · {:02d}:{:02d}".format(*hm_of(t))
    else:
        at = f"at {at}"
    extra = f"  ·  {days_text(t['days'])}" if t.get("repeat") else ""
    extra += f"  ·  {then_text(t['then'])}" if t.get("then") else ""
    return f"{t['label'] or NAMES[t['kind']]}  ({at}{extra})"


def bar_line():
    items = running()
    sw = stopwatch()
    now = time.time()
    rings = ringing()
    lines = [f"{ICONS['alarm']}  ringing  {r['label'] or NAMES.get(r['kind'], 'alarm')}" for r in rings]
    lines += [f"{ICONS[t['kind']]}  {'paused' if t.get('paused') else clock(t['due'] - now)}  {describe(t, now)}"
              for t in items]
    if sw:
        lines.append(f"{ICONS['stopwatch']}  {clock(sw[0])}  stopwatch{'' if sw[1] else ' (paused)'}")
    n = rounds_today()
    if n:
        lines.append(f"{ICONS['focus']}  {n} focus round{'s' if n > 1 else ''} today")
    # The pill: the soonest within a day (a repeating alarm a week out is
    # not worth the space), else the stopwatch.
    soon = [t for t in items if t["due"] - now < 86400 and not t.get("paused")]
    if rings:                   # ringing: said on the bar too, until Snooze or Stop
        r = rings[0]
        text, cls = f"{ICONS['alarm']} {r['label'] or NAMES.get(r['kind'], 'alarm')}", "ringing"
    elif soon:
        t = soon[0]
        text = f"{ICONS[t['kind']]} {clock(t['due'] - now)}" + (f" +{len(soon) - 1}" if len(soon) > 1 else "")
        cls = t["kind"]
    elif sw:
        text, cls = f"{ICONS['stopwatch']} {clock(sw[0])}", "stopwatch" if sw[1] else "paused"
    else:
        text, cls = "", "idle"
    tip = "\n".join(lines + ["", "click: the list (cancel, start)  ·  right click: pause / resume the stopwatch"]) \
        if lines else ""
    return json.dumps({"text": text, "class": cls, "tooltip": tip})


def bar(watch):
    if not watch:
        print(bar_line(), flush=True)
        return
    last = None
    while True:
        line = bar_line()
        if line != last:
            print(line, flush=True)
            last = line
        time.sleep(1.0 - time.time() % 1.0 + 0.02)     # on the second, like the clock


def status():
    """Everything Settings > Timers & alarms shows, in one go (timers.py
    status --json): what is set, the stopwatch, today's focus rounds, the
    settings, calendar alarms and their systemd timer, the calendars."""
    now = time.time()
    items = [{"id": t["id"], "kind": t["kind"], "label": t.get("label") or "", "name": NAMES[t["kind"]],
              "due": t["due"], "left": max(0, round(t["due"] - now)),
              "repeat": days_text(t["days"]) if t.get("repeat") else "", "paused": bool(t.get("paused")),
              "then": then_text(t.get("then")), "describe": describe(t, now)} for t in running()]
    data = load()
    sw = stopwatch(data)
    try:
        cals, cal_error = calendars(), ""
    except Exception as exc:          # no Evolution data server: the rest still shows
        cals, cal_error = [], str(exc)
    unit = {}
    for what in ("is-enabled", "is-active"):
        try:
            unit[what] = subprocess.run(["systemctl", "--user", what, "timers-calendar.timer"],
                                        capture_output=True, text=True, timeout=5).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            unit[what] = ""
    return {"timers": items,
            "stopwatch": {"elapsed": round(sw[0]), "running": sw[1], "laps": laps(data)} if sw else None,
            "countdowns": [dict(c, left=round(c["at"] - now), armed=countdown_armed(c, data))
                           for c in countdowns(data)],
            "ringing": ringing(),
            "rounds_today": rounds_today(), "settings": settings(), "defaults": DEFAULTS, "conf": CONF,
            "theme_sound": alarm_sound() != SOUND,
            "calendar": {"on": calendar_on(), "ahead_min": cal_ahead_min(), "calendars": cals,
                         "error": cal_error, "timer_enabled": unit["is-enabled"],
                         "timer_active": unit["is-active"]}}


def parse_edit(words):
    """`edit ID` 's arguments -> (hm, days, label), KEEP for what is left
    out: TIME [REPEAT|once] [-- LABEL...]. ValueError for a time that is not
    one, or words before "--" that are neither a repeat nor "once"."""
    words = list(words)
    label = KEEP
    if "--" in words:
        cut = words.index("--")
        words, label = words[:cut], " ".join(words[cut + 1:])
    text = " ".join(words)
    hm, text = parse_hm(text)
    if hm is None:
        raise ValueError(f"not a time: {' '.join(words)!r}")
    if not text:
        return hm, KEEP, label
    if fold(text) in ("once", "una vez"):
        return hm, None, label
    days, rest = parse_repeat(text)
    if days is None or rest:
        raise ValueError(f"not a repeat: {text!r} (daily, weekdays, weekends, mon wed fri, once)")
    return hm, days, label


def parse_alarm(words, now=None):
    """`alarm` 's arguments -> (datetime of the next TIME or None, days or
    None, label, then): TIME [REPEAT] [LABEL...] [then ACTION] [-- LABEL...].
    Only the words before "--" are read for the time, the repeat and the
    "then" -- the clock card puts its free-text label after it, where "take
    meds then sleep" must stay a label (parse_then would have made it a
    suspend, "then !cmd" a shell command) and "mon review" must not make a
    Monday alarm. Without "--" it reads as it always did."""
    words = list(words)
    literal = None
    if "--" in words:
        cut = words.index("--")
        words, literal = words[:cut], " ".join(words[cut + 1:])
    text, then = parse_then(" ".join(words))
    when, text = parse_clock(text, now)
    if not when:
        return None, None, "", then
    days, label = parse_repeat(text)
    if literal is not None:
        label = " ".join(w for w in (label, literal) if w)
    return when, days, " ".join(label.split()), then


def countdown_main(argv):
    """timers.py countdown add|alarm|remove|list ..."""
    sub, args = argv[0], argv[1:]
    if sub == "add" and args:
        # Words after "--" are the label as typed (the clock card's field):
        # neither the flag nor a time for a date given without one.
        literal = None
        if "--" in args:
            cut = args.index("--")
            args, literal = args[:cut], " ".join(args[cut + 1:])
        alarm = "--alarm" in args
        when, label = parse_date(" ".join(a for a in args if a != "--alarm"))
        if when is None:
            raise ValueError(f"not a date: {' '.join(args)!r} (2027-01-01 00:00 New Year)")
        if literal is not None:
            label = " ".join(w for w in (label, literal) if w)
        c = countdown_add(when, label, alarm)
        print(f"{c['label'] or 'countdown'}: {until_text(c['at'] - time.time())} to {when:%a %d %b %Y %H:%M}"
              + (", with an alarm" if c["alarm"] else ""))
    elif sub == "alarm" and len(args) == 2 and args[1] in ("on", "off"):
        countdown_alarm(args[0], args[1] == "on")
    elif sub == "remove" and len(args) == 1:
        countdown_remove(args[0])
    elif sub == "list":
        data, now = load(), time.time()
        items = countdowns(data)
        if args == ["--json"]:
            print(json.dumps([dict(c, left=round(c["at"] - now), armed=countdown_armed(c, data)) for c in items]))
            return
        for c in items:
            print(f"{c['id']}  {until_text(c['at'] - now):>12}  {dt.datetime.fromtimestamp(c['at']):%Y-%m-%d %H:%M}"
                  f"  {c['label'] or 'countdown'}{'  (alarm)' if countdown_armed(c, data) else ''}")
    else:
        raise ValueError("countdown add [--alarm] DATE [TIME] [LABEL...] [-- LABEL...] | alarm ID on|off"
                         " | remove ID | list")


def main(argv):
    cmd = argv[0] if argv else "list"
    rest = " ".join(argv[1:])
    if cmd == "timer" and rest:
        rest, then = parse_then(rest)
        secs, label = parse_duration(rest)
        if not secs:
            sys.exit(f"timers.py: not a duration: {rest!r}")
        t = start_timer(secs, label, then)
        print(f"timer {span(secs)}, rings at {dt.datetime.fromtimestamp(t['due']):%H:%M:%S}")
    elif cmd == "alarm" and rest:
        when, days, label, then = parse_alarm(argv[1:])
        if not when:
            sys.exit(f"timers.py: not a time: {' '.join(argv[1:])!r}")
        t = start_alarm(when, label, then, days)
        print(f"alarm at {dt.datetime.fromtimestamp(t['due']):%a %H:%M}"
              + (f", {days_text(days)}" if days else ""))
    elif cmd == "remind" and rest:
        words = rest.split(None, 1)
        if words[0] == "in" and len(words) > 1:
            secs, msg = parse_duration(words[1])
            due = time.time() + secs if secs else None
        else:
            when, msg = parse_clock(words[1] if words[0] in ("at", "a") and len(words) > 1 else rest)
            due = when.timestamp() if when else None
        if not due:
            sys.exit("timers.py: remind in DURATION MESSAGE, or remind at TIME MESSAGE")
        msg = re.sub(r"^(?:to|que|de)\s+", "", msg)
        start_reminder(due, msg)
    elif cmd == "focus":
        start_focus(int(argv[1]) if len(argv) > 1 and argv[1].isdigit() else None)
    elif cmd == "cancel" and rest:
        cancel(argv[1])
    elif cmd == "edit" and len(argv) >= 3:
        try:
            hm, days, label = parse_edit(argv[2:])
            t = edit_alarm(argv[1], hm, days, label)
        except ValueError as exc:
            sys.exit(f"timers.py: {exc}")
        except subprocess.CalledProcessError:
            sys.exit("timers.py: systemd-run could not arm it (the alarm is as it was)")
        print(f"alarm {'paused at' if t.get('paused') else 'at'} {t['hm']}"
              + (f", {days_text(t['days'])}" if t.get("repeat") else "") + f"  (id {t['id']})")
    elif cmd in ("pause", "resume") and len(argv) == 2:
        try:
            t = (pause if cmd == "pause" else resume)(argv[1])
        except ValueError as exc:
            sys.exit(f"timers.py: {exc}")
        except subprocess.CalledProcessError:
            sys.exit("timers.py: systemd-run could not arm it (it stays paused)")
        print(f"{t['label'] or 'alarm'} paused" if cmd == "pause"
              else f"{t['label'] or 'alarm'} rings at {dt.datetime.fromtimestamp(t['due']):%a %H:%M}")
    elif cmd in ("snooze", "stop") and len(argv) == 2:
        if not ring_pick(argv[1], cmd):
            sys.exit(f"timers.py: nothing is ringing as {argv[1]}")
    elif cmd == "ringing":
        rings = ringing()
        if rest == "--json":
            print(json.dumps(rings))
        for r in rings if rest != "--json" else ():
            print(f"{r['id']}  {r['kind']:8}  {r['label'] or NAMES.get(r['kind'], '')}")
    elif cmd == "countdown" and len(argv) >= 2:
        try:
            countdown_main(argv[1:])
        except ValueError as exc:
            sys.exit(f"timers.py: {exc}")
    elif cmd == "stopwatch" and len(argv) > 1 and argv[1] == "lap":
        taken = stopwatch_do("lap")
        if taken is None:
            sys.exit("timers.py: no lap: the stopwatch has not run (since the last one)")
        n, split, _ = lap_rows(laps())[0]
        print(f"lap {n}  {clock(split)}  (total {clock(taken)})")
    elif cmd == "stopwatch" and len(argv) > 1 and argv[1] in ("start", "pause", "toggle", "reset"):
        stopwatch_do(argv[1])
    elif cmd == "click-right":
        if stopwatch():
            stopwatch_do("toggle")
    elif cmd == "fire" and rest:
        fire(argv[1])
    elif cmd == "restore":
        restore()
    elif cmd == "calendar":
        if rest in ("on", "off"):
            calendar_switch(rest == "on")
        else:
            calendar_sync()
    elif cmd == "bar":
        bar(len(argv) > 1 and argv[1] == "watch")
    elif cmd == "list" and rest == "--json":
        print(json.dumps(status()["timers"]))
    elif cmd == "status":
        print(json.dumps(status(), indent=None if rest == "--json" else 1))
    elif cmd == "settings":
        values = settings()
        if rest == "--json":
            print(json.dumps({"values": values, "defaults": DEFAULTS, "limits": LIMITS, "conf": CONF}))
        else:
            for key, value in values.items():
                print(f"{key}={value}" + ("" if value == DEFAULTS[key] else f"   (default {DEFAULTS[key]})"))
    elif cmd == "set" and len(argv) >= 3:
        try:
            value = set_setting(argv[1], " ".join(argv[2:]))
        except ValueError as exc:
            sys.exit(f"timers.py: {exc}")
        print(f"{argv[1]}={value}")
    elif cmd == "calendars":
        if len(argv) == 3 and argv[1] in ("use", "skip"):
            calendar_use(argv[2], argv[1] == "use")
        elif rest == "--json":
            print(json.dumps(calendars()))
        else:
            for c in calendars():
                state = "rings" if c["enabled"] and c["used"] else ("skipped" if c["enabled"] else "off in Evolution")
                print(f"{c['uid']}  {state:16}  {c['account'] + ' / ' if c['account'] else ''}{c['name']}")
    elif cmd == "try-sound":
        loop_sound, _ = sounds_for(alarm_sound(), None)
        if loop_sound:
            try:
                subprocess.run(play_argv(loop_sound), timeout=30)
            except (OSError, subprocess.SubprocessError) as exc:
                sys.exit(f"timers.py: could not play {loop_sound} ({exc})")
    elif cmd == "list":
        now = time.time()
        for t in running():
            left = "paused" if t.get("paused") else clock(t["due"] - now)
            print(f"{t['id']}  {t['kind']:8}  {left:>9}  {describe(t, now)}")
        sw = stopwatch()
        if sw:
            print(f"stopwatch  {clock(sw[0])}{'' if sw[1] else '  (paused)'}"
                  + (f"  ·  {len(laps())} laps" if laps() else ""))
        for c in countdowns():
            print(f"{c['id']}  until     {until_text(c['at'] - now):>9}  {c['label'] or 'countdown'}")
        print(f"focus rounds today: {rounds_today()}  ·  calendar alarms: {'on' if calendar_on() else 'off'}")
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
