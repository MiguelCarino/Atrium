#!/usr/bin/env python3
"""Screen time and breaks: how long you are actually at the computer each
day, and in which apps -- and, when you want them, reminders to take a break
and to rest your eyes. screentime.service; Settings > Screen time.

    screentime.py run                the service: count, remind
    screentime.py status [--json]    today, the last 7 days, the top apps, the
                                     live streak, the settings
    screentime.py day [YYYY-MM-DD] [--json]   one day's minutes, apps and hours
    screentime.py set KEY VALUE      a setting (SETTINGS below)
    screentime.py snooze [MINUTES]   put off the break reminder (default: snooze=)
    screentime.py idle on|off        hypridle's word (sent cheaply by
                                     scripts/screentime-idle, sh + ncat)
    screentime.py forget [DAYS]      delete the saved days older than DAYS
                                     (default: keep=), or all with 0

WHAT COUNTS -- "active" is: the screen not locked, and keyboard or mouse used
in the last IDLE_LAG seconds (hypridle's listener, below), or something
holding idle off (a video playing full screen is screen time too). Each
active second goes to the app class that has the focus then (Hyprland's
activewindow event); none focused is "desktop".

HOW, cheaply -- one long-running process, no fork per event: it follows
Hyprland's event socket (socket2) for activewindow lines only, takes
"idle on|off" words on a datagram socket ($XDG_RUNTIME_DIR/screentime.sock),
and wakes every TICK_S to credit the time, look whether hyprlock is up (a
read of /proc) and ring a due reminder. The day is written every FLUSH_S, at
midnight and on exit, to $XDG_STATE_HOME/hypr/screentime/YYYY-MM-DD.json:

    {"date": "2026-10-28", "active_s": 21600, "apps": {"firefox": 9000, ...},
     "hours": [0, 0, ..., 3400, ...]}      (24 numbers: active seconds per hour)

The idle listener: hypridle runs `screentime-idle on` after IDLE_LAG
seconds without input and `off` at the next input. idle-settings.py writes
it into hypridle.conf (next to the presence one) the next time it saves;
until then only the lock pauses the count, and status says
"idle_source": "lock only". As "idle on" arrives IDLE_LAG seconds late, those
seconds are taken back.

SETTINGS -- ~/.config/hypr/screentime.conf, key=value (HYPR_SCREENTIME_CONF
for the tests):

    count=on          the counting (on as shipped; off stops the service)
    breaks=off        "time for a break" after break_every minutes of activity
                      without a break_len-minute pause (OFF as shipped)
    break_every=50    minutes
    break_len=5       minutes away (idle or locked) that count as a break
    snooze=10         minutes "Snooze" puts it off
    eyes=off          20-20-20: every 20 minutes active, look 20 feet (6 m)
                      away for 20 seconds (OFF as shipped)
    keep=90           days of history kept

Nothing leaves this computer; only app classes are kept, never window titles.
"""
import datetime as dt
import json
import os
import select
import signal
import socket
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
HOME = os.path.expanduser("~")
CONF = os.environ.get("HYPR_SCREENTIME_CONF") or os.path.join(
    os.environ.get("XDG_CONFIG_HOME") or os.path.join(HOME, ".config"), "hypr", "screentime.conf")
STATE_DIR = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.join(HOME, ".local", "state"),
                         "hypr", "screentime")
RUNTIME = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
SOCK = os.path.join(RUNTIME, "screentime.sock")
LIVE = os.path.join(RUNTIME, "screentime.json")
HYPRIDLE = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.join(HOME, ".config"), "hypr", "hypridle.conf")
NOTIFY = os.path.join(HERE, "notify")    # notify-send with the theme's mascot (mascot_notify.py)
UNIT = "screentime.service"
APP = "Screen time"

TICK_S = 30
MAX_GAP_S = 120             # a longer silence between ticks is a suspend, not screen time
FLUSH_S = 300
IDLE_LAG = 60               # hypridle's listener timeout (idle-settings.py writes the same number)
EYES_EVERY_S = 20 * 60
DESKTOP = "desktop"         # no window focused
DEFAULTS = {"count": "on", "breaks": "off", "break_every": 50, "break_len": 5, "snooze": 10,
            "eyes": "off", "keep": 90}
SWITCHES = ("count", "breaks", "eyes")
NUMBERS = {"break_every": (10, 240), "break_len": (1, 60), "snooze": (1, 120), "keep": (1, 3650)}


# -- settings (pure) ----------------------------------------------------------------------
def parse_conf(text):
    conf = dict(DEFAULTS)
    for line in (text or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = (part.strip() for part in line.partition("="))
        try:
            conf[key] = check_setting(key, value)
        except ValueError:
            pass
    return conf


def check_setting(key, value):
    """The value to keep for KEY, or ValueError saying why not."""
    value = str(value).strip().lower()
    if key in SWITCHES:
        if value not in ("on", "off"):
            raise ValueError(f"{key} is on or off")
        return value
    if key in NUMBERS:
        low, high = NUMBERS[key]
        if not value.isdigit() or not low <= int(value) <= high:
            raise ValueError(f"{key} is a number of {'days' if key == 'keep' else 'minutes'}, {low}-{high}")
        return int(value)
    raise ValueError(f"unknown setting {key!r} ({', '.join(DEFAULTS)})")


def render_conf(conf):
    return "# screentime.py's settings (Settings > Screen time)\n" + "".join(
        f"{k}={conf.get(k, DEFAULTS[k])}\n" for k in DEFAULTS)


# -- counting (pure) ----------------------------------------------------------------------
def empty_day(date):
    return {"date": date, "active_s": 0, "apps": {}, "hours": [0] * 24}


def credit(days, start, end, app, tz=None):
    """Add the wall-clock span [start, end) to days ({date: day}), split at
    every hour boundary so each piece lands in its own hour and day."""
    t = start
    while t < end:
        here = dt.datetime.fromtimestamp(t, tz)
        next_hour = (here.replace(minute=0, second=0, microsecond=0) + dt.timedelta(hours=1)).timestamp()
        piece_end = min(end, next_hour)
        seconds = piece_end - t
        date = here.date().isoformat()
        day = days.setdefault(date, empty_day(date))
        day["active_s"] += seconds
        day["apps"][app] = day["apps"].get(app, 0) + seconds
        day["hours"][here.hour] += seconds
        t = piece_end


def uncredit(days, end, seconds, app, tz=None):
    """Take back up to `seconds` before `end` from app (the idle listener
    arrives IDLE_LAG late); never below zero."""
    here = dt.datetime.fromtimestamp(max(0, end - 1), tz)
    day = days.get(here.date().isoformat())
    if not day:
        return
    take = min(seconds, day["apps"].get(app, 0), day["active_s"], day["hours"][here.hour])
    if take <= 0:
        return
    day["active_s"] -= take
    day["apps"][app] -= take
    day["hours"][here.hour] -= take


class Tracker:
    """The count and the break clock, fed events with their times -- no
    clock, files or sockets of its own, so the tests drive it.

    streak: active seconds since the last break (a pause of break_len
    minutes); eyes: active seconds since the last eye rest (any pause of
    20 s or more)."""

    def __init__(self, now, app=DESKTOP, conf=None, days=None):
        self.conf = conf or dict(DEFAULTS)
        self.days = days if days is not None else {}
        self.last = now
        self.app = app or DESKTOP
        self.idle = self.locked = False
        self.away_since = None          # when the current pause began
        self.streak = 0.0
        self.eyes = 0.0
        self.remind_at = self.conf["break_every"] * 60
        self.eyes_at = EYES_EVERY_S

    @property
    def active(self):
        return not (self.idle or self.locked)

    def advance(self, now):
        """Credit the time since the last call (when active)."""
        if now <= self.last:
            self.last = max(self.last, now)
            return
        if self.active and self.conf["count"] == "on":
            credit(self.days, self.last, now, self.app)
            self.streak += now - self.last
            self.eyes += now - self.last
        self.last = now

    def skip(self, now):
        """The computer was asleep (or this process stopped) since the last
        call: that time is not screen time, and counts as a pause -- a long
        enough one is a break."""
        if now <= self.last:
            return
        if self.active:
            self._pause(self.last)
            self.last = now
            self._resume(now)
        else:
            self.last = now

    def set_app(self, app, now):
        app = app or DESKTOP
        if app != self.app:
            self.advance(now)
            self.app = app

    def _pause(self, began):
        if self.away_since is None:
            self.away_since = began

    def _resume(self, now):
        if self.active and self.away_since is not None:
            away = now - self.away_since
            if away >= self.conf["break_len"] * 60:
                self.streak = 0.0
                self.remind_at = self.conf["break_every"] * 60
            if away >= 20:
                self.eyes = 0.0
                self.eyes_at = EYES_EVERY_S
            self.away_since = None

    def set_idle(self, on, now, lag=IDLE_LAG):
        self.advance(now)
        if on and not self.idle:
            was_active = self.active
            self.idle = True
            if was_active:
                back = min(lag, self.streak)
                if self.conf["count"] == "on":
                    uncredit(self.days, now, back, self.app)
                self.streak -= back
                self.eyes = max(0.0, self.eyes - back)
                self._pause(now - back)
        elif not on and self.idle:
            self.idle = False
            self._resume(now)

    def set_locked(self, on, now):
        self.advance(now)
        if on and not self.locked:
            if self.active:
                self._pause(now)
            self.locked = True
        elif not on and self.locked:
            self.locked = False
            self._resume(now)

    def snooze(self, minutes):
        self.remind_at = self.streak + minutes * 60

    def due(self):
        """[(kind)] of the reminders to ring now: "break", "eyes"."""
        out = []
        if not self.active:
            return out
        if self.conf["breaks"] == "on" and self.streak >= self.remind_at:
            out.append("break")
            self.remind_at = self.streak + self.conf["snooze"] * 60     # again later if no break is taken
        if self.conf["eyes"] == "on" and self.eyes >= self.eyes_at:
            out.append("eyes")
            self.eyes_at = self.eyes + EYES_EVERY_S
        return out

    def live(self, now):
        return {"t": now, "app": self.app, "idle": self.idle, "locked": self.locked,
                "streak_s": round(self.streak), "next_break_s": max(0, round(self.remind_at - self.streak))
                if self.conf["breaks"] == "on" else None, "pid": os.getpid()}


def parse_event(line):
    """socket2 line -> the app class, for "activewindow>>class,title" only
    (None for every other event; "" for nothing focused)."""
    if not line.startswith("activewindow>>"):
        return None
    return line[len("activewindow>>"):].split(",", 1)[0]


def is_locked_comm(comms):
    return any(c.strip() == "hyprlock" for c in comms)


# -- reading the days (pure) --------------------------------------------------------------
def top_apps(day, n=8):
    """[(app, seconds)] most first."""
    return sorted(((a, s) for a, s in (day.get("apps") or {}).items() if s >= 1), key=lambda kv: -kv[1])[:n]


def week(days_by_date, today, n=7):
    """[(date, active seconds)] for the n days ending today, oldest first."""
    out = []
    for back in range(n - 1, -1, -1):
        date = (today - dt.timedelta(days=back)).isoformat()
        out.append((date, (days_by_date.get(date) or {}).get("active_s", 0)))
    return out


def hm(seconds):
    """"3 h 05 min", "42 min", "0 min"."""
    minutes = int(seconds // 60)
    return f"{minutes // 60} h {minutes % 60:02d} min" if minutes >= 60 else f"{minutes} min"


def merge_day(saved, live):
    """A saved day file plus what the daemon counted since (live wins: it
    started from the saved one)."""
    return live if live else saved


def old_files(names, today, keep):
    """The YYYY-MM-DD.json names older than keep days."""
    cut = today - dt.timedelta(days=keep)
    out = []
    for name in names:
        try:
            if dt.date.fromisoformat(name.removesuffix(".json")) < cut:
                out.append(name)
        except ValueError:
            continue
    return out


def idle_source(hypridle_text):
    return "hypridle" if "screentime-idle" in (hypridle_text or "") else "lock only"


# -- files ---------------------------------------------------------------------------------
def load_conf(path=None):
    try:
        with open(path or CONF) as handle:
            return parse_conf(handle.read())
    except OSError:
        return dict(DEFAULTS)


def save_conf(conf, path=None):
    path = path or CONF
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as handle:
        handle.write(render_conf(conf))
    os.replace(tmp, path)


def day_path(date):
    return os.path.join(STATE_DIR, f"{date}.json")


def load_day(date):
    try:
        with open(day_path(date)) as handle:
            day = json.load(handle)
        if isinstance(day, dict) and isinstance(day.get("hours"), list) and len(day["hours"]) == 24:
            day.setdefault("apps", {})
            day.setdefault("active_s", 0)
            return day
    except (OSError, ValueError):
        pass
    return empty_day(date)


def save_day(day):
    os.makedirs(STATE_DIR, exist_ok=True)
    rounded = dict(day, active_s=round(day["active_s"]), apps={a: round(s) for a, s in day["apps"].items() if s >= 1},
                   hours=[round(h) for h in day["hours"]])
    tmp = day_path(day["date"]) + ".tmp"
    with open(tmp, "w") as handle:
        json.dump(rounded, handle)
    os.replace(tmp, day_path(day["date"]))


def write_live(data):
    try:
        tmp = LIVE + ".tmp"
        with open(tmp, "w") as handle:
            json.dump(data, handle)
        os.replace(tmp, LIVE)
    except OSError:
        pass


def read_live():
    try:
        with open(LIVE) as handle:
            data = json.load(handle)
        os.kill(int(data.get("pid", 0)), 0)
        return data
    except (OSError, ValueError, TypeError):
        return None


def read_text(path):
    try:
        with open(path) as handle:
            return handle.read()
    except OSError:
        return ""


def proc_comms(proc="/proc"):
    out = []
    try:
        pids = [p for p in os.listdir(proc) if p.isdigit()]
    except OSError:
        return out
    for pid in pids:
        try:
            with open(f"{proc}/{pid}/comm") as handle:
                out.append(handle.read())
        except OSError:
            continue
    return out


# -- the service ---------------------------------------------------------------------------
def hypr_dir():
    sig = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")
    return os.path.join(RUNTIME, "hypr", sig) if sig else None


def current_app():
    """The focused window's class now, over Hyprland's request socket (no
    hyprctl fork)."""
    folder = hypr_dir()
    if not folder:
        return DESKTOP
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(2)
            s.connect(os.path.join(folder, ".socket.sock"))
            s.sendall(b"j/activewindow")
            data = b""
            while True:
                chunk = s.recv(65536)
                if not chunk:
                    break
                data += chunk
        return (json.loads(data or b"{}") or {}).get("class") or DESKTOP
    except (OSError, ValueError, AttributeError):
        return DESKTOP


def connect_events():
    folder = hypr_dir()
    if not folder:
        return None
    import hyprbus      # the shared relay (only what parse_event reads), or socket2 directly
    try:
        return hyprbus.connect({"activewindow"}, direct=os.path.join(folder, ".socket2.sock"))
    except OSError:
        return None


def notify_reminder(kind, conf):
    """The reminder, with Snooze on the break one; returns the notify-send
    child (its stdout says which button was pressed) or None."""
    if kind == "break":
        argv = [NOTIFY, "-a", APP, "-u", "normal", "-i", "appointment-soon", "--wait",
                "-A", f"snooze=Snooze {conf['snooze']} min", "-A", "ok=OK",
                "Time for a break", f"{conf['break_every']} minutes at the screen: stand up, stretch, look "
                f"out of the window for {conf['break_len']} minutes."]
    else:
        argv = [NOTIFY, "-a", APP, "-u", "low", "-i", "view-reveal-symbolic", "-t", "20000",
                "Rest your eyes", "Look at something 20 feet (6 m) away for 20 seconds."]
    try:
        return subprocess.Popen(argv, stdout=subprocess.PIPE if kind == "break" else subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, text=True)
    except OSError:
        return None


def serve():
    conf = load_conf()
    if conf["count"] != "on":
        print("screentime: counting is off (screentime.conf count=off)")
        return 0
    os.makedirs(RUNTIME, exist_ok=True)
    try:
        os.unlink(SOCK)
    except OSError:
        pass
    ctrl = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    ctrl.bind(SOCK)
    os.chmod(SOCK, 0o600)
    now = time.time()
    today = dt.date.today().isoformat()
    tracker = Tracker(now, current_app(), conf, {today: load_day(today)})
    events, buf = connect_events(), b""
    reminder = None                     # the break notification waiting for a button
    last_flush, last_connect = now, now
    stop = []

    def flush():
        for date, day in list(tracker.days.items()):
            save_day(day)
            if date != dt.date.today().isoformat():
                del tracker.days[date]          # a past day is finished: written, not kept in memory
        write_live(tracker.live(time.time()))

    signal.signal(signal.SIGTERM, lambda *_: stop.append(1))
    signal.signal(signal.SIGINT, lambda *_: stop.append(1))
    print(f"screentime: counting (idle from {idle_source(read_text(HYPRIDLE))})", flush=True)
    while not stop:
        watch = [ctrl] + ([events] if events else []) + ([reminder.stdout] if reminder else [])
        try:
            ready, _, _ = select.select(watch, [], [], TICK_S)
        except InterruptedError:
            ready = []
        now = time.time()
        if now - tracker.last > MAX_GAP_S:
            tracker.skip(now)               # back from suspend: the sleep is not counted
        if events in ready:
            try:
                chunk = events.recv(65536)
            except OSError:
                chunk = b""
            if not chunk:
                events.close()
                events = None
            buf += chunk
            *lines, buf = buf.split(b"\n")
            for raw in lines:
                app = parse_event(raw.decode(errors="replace"))
                if app is not None:
                    tracker.set_app(app, now)
        if ctrl in ready:
            word = ctrl.recv(256).decode(errors="replace").split()
            if word[:1] == ["idle"] and word[1:2] in (["on"], ["off"]):
                tracker.set_idle(word[1] == "on", now)
            elif word[:1] == ["snooze"]:
                tracker.snooze(int(word[1]) if word[1:2] and word[1].isdigit() else conf["snooze"])
            elif word[:1] == ["reload"]:
                tracker.advance(now)
                conf = load_conf()
                tracker.conf = conf
                tracker.remind_at = max(conf["break_every"] * 60, tracker.streak + 60)
            elif word[:1] == ["flush"]:
                tracker.advance(now)
                flush()
                last_flush = now
        if reminder and reminder.stdout in ready:
            answer = reminder.stdout.read().strip()
            reminder.wait()
            reminder = None
            if answer == "snooze":
                tracker.snooze(conf["snooze"])
        if events is None and now - last_connect > 10:
            last_connect = now
            events = connect_events()
            if events:
                tracker.set_app(current_app(), now)
        if not tracker.idle or tracker.locked:
            tracker.set_locked(is_locked_comm(proc_comms()), now)
        tracker.advance(now)
        for kind in tracker.due():
            if kind == "break" and reminder:
                continue
            child = notify_reminder(kind, conf)
            if kind == "break":
                reminder = child
        new_day = len(tracker.days) > 1 or (tracker.days and dt.date.today().isoformat() not in tracker.days)
        if now - last_flush >= FLUSH_S or new_day:
            flush()
            last_flush = now
        else:
            write_live(tracker.live(now))
    tracker.advance(time.time())
    flush()
    try:
        os.unlink(SOCK)
    except OSError:
        pass
    return 0


# -- commands ------------------------------------------------------------------------------
def tell(text):
    """A word to the running service; False when it is not running."""
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as s:
            s.sendto(text.encode(), SOCK)
        return True
    except OSError:
        return False


def all_days(n=7, today=None):
    today = today or dt.date.today()
    return {d: load_day(d) for d, _ in week({}, today, n)}


def status(today=None):
    today = today or dt.date.today()
    tell("flush")
    time.sleep(0.15)        # the service writes the day file; a stale one is fine too
    days = all_days(7, today)
    day = days[today.isoformat()]
    conf = load_conf()
    service = subprocess.run(["systemctl", "--user", "is-active", UNIT], capture_output=True,
                             text=True).stdout.strip()
    return {"conf": conf, "today": {"date": day["date"], "active_s": round(day["active_s"]), "hours": day["hours"],
                                    "apps": top_apps(day), "text": hm(day["active_s"])},
            "week": week(days, today), "live": read_live(), "service": service or "unknown",
            "idle_source": idle_source(read_text(HYPRIDLE)), "conf_path": CONF, "folder": STATE_DIR}


def status_text(data):
    lines = [f"today       {data['today']['text']}"]
    lines += [f"  {app:<20} {hm(s)}" for app, s in data["today"]["apps"]]
    lines.append("last 7 days " + "  ".join(f"{d[5:]} {hm(s)}" for d, s in data["week"]))
    live = data.get("live") or {}
    if live:
        lines.append(f"now         {'idle' if live.get('idle') else 'locked' if live.get('locked') else 'active'}"
                     f", {hm(live.get('streak_s', 0))} since the last break")
    c = data["conf"]
    lines.append(f"settings    count {c['count']}, breaks {c['breaks']} (every {c['break_every']} min, "
                 f"{c['break_len']} min away), eyes {c['eyes']}; idle from {data['idle_source']}")
    return "\n".join(lines)


def set_setting(key, value):
    conf = load_conf()
    conf[key] = check_setting(key, value)
    save_conf(conf)
    if key == "count":
        verb = ["enable", "--now"] if conf["count"] == "on" else ["disable", "--now"]
        subprocess.run(["systemctl", "--user", *verb, UNIT], capture_output=True, timeout=20)
    else:
        tell("reload")


def forget(days):
    try:
        names = os.listdir(STATE_DIR)
    except OSError:
        return 0
    today = dt.date.today()
    gone = [n for n in names if n.endswith(".json")] if days == 0 else old_files(names, today, days)
    for name in gone:
        try:
            os.remove(os.path.join(STATE_DIR, name))
        except OSError:
            pass
    return len(gone)


def main(argv):
    cmd = argv[0] if argv else "status"
    as_json = "--json" in argv
    if cmd == "run":
        sys.exit(serve())
    elif cmd == "status":
        data = status()
        print(json.dumps(data) if as_json else status_text(data))
    elif cmd == "day":
        rest = [a for a in argv[1:] if a != "--json"]
        try:
            date = dt.date.fromisoformat(rest[0]).isoformat() if rest else dt.date.today().isoformat()
        except ValueError:
            sys.exit("screentime: a date is YYYY-MM-DD")
        day = load_day(date)
        if as_json:
            print(json.dumps(day))
        else:
            print(f"{date}: {hm(day['active_s'])}")
            for app, s in top_apps(day, 20):
                print(f"  {app:<24} {hm(s)}")
    elif cmd == "set" and len(argv) == 3:
        try:
            set_setting(argv[1], argv[2])
        except ValueError as exc:
            sys.exit(f"screentime: {exc}")
    elif cmd == "snooze":
        minutes = argv[1] if len(argv) > 1 and argv[1].isdigit() else ""
        if not tell(f"snooze {minutes}".strip()):
            sys.exit("screentime: the service is not running")
    elif cmd == "idle" and argv[1:2] in (["on"], ["off"]):
        tell(f"idle {argv[1]}")
    elif cmd == "forget":
        days = int(argv[1]) if len(argv) > 1 and argv[1].isdigit() else load_conf()["keep"]
        print(f"screentime: {forget(days)} days deleted")
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
