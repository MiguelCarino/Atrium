#!/usr/bin/env python3
"""Timers, alarms, reminders, focus rounds and a stopwatch, for the launcher
(ALT+E: "timer 5m tea", "alarm 7:30 weekdays", "remind me in 40 min to call
the lab", "focus", "stopwatch") and the bar's countdown pill (custom/timers).

    timers.py timer DURATION [LABEL...] [then ACTION]
                        ring in DURATION: "5m", "1h30m", "90s", "10"
                        (minutes), "1:30" (m:ss), "1:00:00", "5 min", "2 horas"
    timers.py alarm TIME [REPEAT] [LABEL...] [then ACTION]
                        ring at TIME ("7:30", "7am", "19:45", "7:30 pm"), the
                        next time it comes; REPEAT makes it ring every time:
                        daily / every day / diario, weekdays / workdays /
                        entre semana, weekends, or day names ("mon wed fri",
                        "lunes jueves")
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
    timers.py stopwatch start|pause|toggle|reset
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
(systemd weekdays, "*" every day), "hm", "then", "dnd"}], "stopwatch":
{"start": epoch|null, "acc": s}, "focus": {"date", "rounds"}, "calendar":
{"off": bool, "seen": [event keys]}}.
"""

import datetime as dt
import json
import os
import re
import subprocess
import sys
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
THEN_WAIT_S = 30            # "Suspending in 30 s": the time to cancel
CAL_AHEAD_MIN = 30          # calendar alarms are armed for events starting within this
                            # (or the lead time + 10 min, when that is longer)
HERE = os.path.dirname(os.path.abspath(__file__))

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
BELL_SIGNAL = 14            # custom/notifications in waybar/config (notifications.py SIGNAL)

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
    tmp = STATE + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(data, fh)
    os.replace(tmp, STATE)


def running():
    """Everything still to ring, soonest first (a one-off whose time is
    long gone -- the machine was off -- is left out)."""
    now = time.time()
    return sorted((t for t in load()["timers"] if t.get("repeat") or t.get("due", 0) > now - 120),
                  key=lambda t: t["due"])


def stopwatch():
    """(elapsed seconds, running?) or None."""
    sw = load()["stopwatch"]
    if not sw:
        return None
    acc = sw.get("acc", 0.0)
    if sw.get("start"):
        return acc + time.time() - sw["start"], True
    return acc, False


def rounds_today():
    f = load().get("focus") or {}
    return f.get("rounds", 0) if f.get("date") == dt.date.today().isoformat() else 0


# -- arming ------------------------------------------------------------------------------
def systemctl(*args):
    return subprocess.run(["systemctl", "--user", *args], stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL).returncode


def arm(entry):
    """The systemd timer that rings `entry`: at its due time, or on every
    one of its repeat days at its hm."""
    if entry.get("repeat"):
        cal = f"{entry['repeat']} *-*-* {entry['hm']}:00"
    else:
        cal = dt.datetime.fromtimestamp(entry["due"]).strftime("%Y-%m-%d %H:%M:%S")
    what = f"{NAMES[entry['kind']].capitalize()}{': ' + entry['label'] if entry['label'] else ''}"
    subprocess.run(["systemd-run", "--user", "--quiet", f"--unit={UNIT}{entry['id']}",
                    f"--on-calendar={cal}", "--timer-property=AccuracySec=1s",
                    f"--description={what}", sys.executable, os.path.join(HERE, "timers.py"),
                    "fire", entry["id"]], check=True, stdout=subprocess.DEVNULL)


def new_id():
    time.sleep(0.002)       # two in one call (focus -> break) get different ids
    return f"{int(time.time() * 1000) % 10**10:010d}"


def schedule(kind, due, label="", secs=None, **extra):
    """A one-off ringing at epoch `due` (or, with repeat= and hm=, a
    repeating alarm whose first ring is `due`). Returns its entry."""
    entry = {"id": new_id(), "kind": kind, "label": label, "due": due, "secs": secs, **extra}
    arm(entry)
    data = load()
    now = time.time()
    data["timers"] = [t for t in data["timers"] if t.get("repeat") or t["due"] > now - 120] + [entry]
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
    data = load()
    ids = [t["id"] for t in data["timers"]] if tid == "all" else [tid]
    for t in data["timers"]:
        if t["id"] in ids and t.get("dnd"):
            makoctl("mode", "-r", "do-not-disturb")
            dnd_released()
    for i in ids:
        systemctl("stop", f"{UNIT}{i}.timer", f"{UNIT}{i}.service")
    data["timers"] = [t for t in data["timers"] if t["id"] not in ids]
    save(data)


def stopwatch_do(action):
    data = load()
    sw = data["stopwatch"] or {"start": None, "acc": 0.0}
    now = time.time()
    if action == "toggle":
        action = "pause" if sw.get("start") else "start"
    if action == "start" and not sw.get("start"):
        sw["start"] = now
    elif action == "pause" and sw.get("start"):
        sw["acc"] = sw.get("acc", 0.0) + now - sw["start"]
        sw["start"] = None
    elif action == "reset":
        sw = None
    data["stopwatch"] = sw
    save(data)


def restore():
    """After a login: arm again what is not armed. A one-off that passed
    while the machine was off is dropped, and said."""
    data = load()
    now = time.time()
    keep, missed = [], []
    for t in data["timers"]:
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
    if missed:
        lines = [f"{dt.datetime.fromtimestamp(t['due']):%a %H:%M}  {t['label'] or NAMES[t['kind']]}"
                 for t in missed]
        subprocess.run(["notify-send", "-a", "Timer", "-i", "alarm-symbolic", "Missed while off",
                        "\n".join(lines)])


# -- ringing -----------------------------------------------------------------------------
def makoctl(*args):
    try:
        return subprocess.run(["makoctl", *args], capture_output=True, text=True, timeout=3).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def bell():
    subprocess.run(["pkill", f"-RTMIN+{BELL_SIGNAL}", "-x", "waybar"])


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


def ask(title, body, actions, loop_sound=None, chime=None, wait=RING_S, urgency="critical"):
    """A notification with buttons, the picked one's key back ("" if it
    was closed or timed out); loop_sound plays until then. Both go through
    the sound and volume settings (sounds_for, play_argv)."""
    loop = None
    loop_sound, chime = sounds_for(loop_sound, chime)
    if loop_sound:
        # The theme's alarm plays back to back, as it always has; the quiet
        # chime is a short blip, so it gets a pause between rings.
        gap = "; sleep 2" if loop_sound == CHIME else " || sleep 2"
        play = " ".join(f'"{a}"' for a in play_argv(loop_sound))
        loop = subprocess.Popen(["sh", "-c", f"while :; do {play}{gap}; done"],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                start_new_session=True)
    elif chime:
        subprocess.Popen(play_argv(chime), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    argv = ["notify-send", "-a", "Timer", "-u", urgency, "-i", "alarm-symbolic", "--wait"]
    for key, text in actions:
        argv += ["-A", f"{key}={text}"]
    try:
        out = subprocess.run(argv + [title, body], capture_output=True, text=True,
                             timeout=wait).stdout.strip()
    except subprocess.TimeoutExpired:
        out = ""
    finally:
        if loop is not None:
            os.killpg(loop.pid, 15)
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
    data = load()
    entry = next((t for t in data["timers"] if t["id"] == tid), None)
    if entry is None:
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
    picked = ask(title, body, [("snooze", f"Snooze {span(snooze)}"), ("stop", "Stop")],
                 loop_sound=alarm_sound())
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
    data = load()
    cutoff = (dt.datetime.now() - dt.timedelta(days=2)).strftime("%Y%m%d")
    data["calendar"] = {"off": False, "seen": [k for k in seen if k.rsplit("@", 1)[-1][:8] >= cutoff]}
    save(data)


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
    at = dt.datetime.fromtimestamp(t["due"]).strftime("%a %H:%M" if t["due"] - now > 86400 / 2 else "%H:%M")
    extra = f"  ·  {days_text(t['days'])}" if t.get("repeat") else ""
    extra += f"  ·  {then_text(t['then'])}" if t.get("then") else ""
    return f"{t['label'] or NAMES[t['kind']]}  (at {at}{extra})"


def bar_line():
    items = running()
    sw = stopwatch()
    now = time.time()
    lines = [f"{ICONS[t['kind']]}  {clock(t['due'] - now)}  {describe(t, now)}" for t in items]
    if sw:
        lines.append(f"{ICONS['stopwatch']}  {clock(sw[0])}  stopwatch{'' if sw[1] else ' (paused)'}")
    n = rounds_today()
    if n:
        lines.append(f"{ICONS['focus']}  {n} focus round{'s' if n > 1 else ''} today")
    # The pill: the soonest within a day (a repeating alarm a week out is
    # not worth the space), else the stopwatch.
    soon = [t for t in items if t["due"] - now < 86400]
    if soon:
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
              "repeat": days_text(t["days"]) if t.get("repeat") else "",
              "then": then_text(t.get("then")), "describe": describe(t, now)} for t in running()]
    sw = stopwatch()
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
            "stopwatch": {"elapsed": round(sw[0]), "running": sw[1]} if sw else None,
            "rounds_today": rounds_today(), "settings": settings(), "defaults": DEFAULTS, "conf": CONF,
            "theme_sound": alarm_sound() != SOUND,
            "calendar": {"on": calendar_on(), "ahead_min": cal_ahead_min(), "calendars": cals,
                         "error": cal_error, "timer_enabled": unit["is-enabled"],
                         "timer_active": unit["is-active"]}}


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
        rest, then = parse_then(rest)
        when, rest = parse_clock(rest)
        if not when:
            sys.exit(f"timers.py: not a time: {' '.join(argv[1:])!r}")
        days, label = parse_repeat(rest)
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
            print(f"{t['id']}  {t['kind']:8}  {clock(t['due'] - now):>9}  {describe(t, now)}")
        sw = stopwatch()
        if sw:
            print(f"stopwatch  {clock(sw[0])}{'' if sw[1] else '  (paused)'}")
        print(f"focus rounds today: {rounds_today()}  ·  calendar alarms: {'on' if calendar_on() else 'off'}")
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
