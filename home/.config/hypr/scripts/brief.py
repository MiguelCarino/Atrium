#!/usr/bin/env python3
"""The daily brief (morning) and the end-of-day journal.

    brief.py [show]              the brief now: one notification, a line per
                                 section; clicking it opens the panel
    brief.py panel               the brief as a panel (every line, buttons for
                                 the journal and Settings)
    brief.py text [--json]       the brief, printed
    brief.py say                 the brief read aloud now (tts.py; Settings >
                                 Speech's switches and quiet hours still count)
    brief.py auto [--tick|--rule]   the morning trigger, once a day (below):
                                 --tick from brief.timer, --rule from an
                                 automation's "brief" action
    brief.py journal [DATE] [--plain] [--dry-run] [--notify]
                                 write DATE's journal entry (default today):
                                 JOURNAL_DIR/YYYY-MM-DD.md, plus the draft time
                                 sheet when that is on. --plain: no model;
                                 --dry-run: print it, write nothing; --notify:
                                 say so when written (click: open it)
    brief.py timesheet [DATE]    only the draft time sheet (CSV), whatever the setting
    brief.py open [DATE]         open DATE's journal entry (today's by default)
    brief.py status --json       the settings, the two rules, the last brief and
                                 journal -- for Settings > Daily brief & journal
    brief.py set KEY VALUE       a setting (SETTINGS below)

THE BRIEF -- what you need to start the day, from what this desktop already
knows; nothing goes on the network (the weather is the bar's last answer):

    yesterday      the last day with activity before today: where the time went
                   (activity-log.py's history, by project and app), the window
                   you ended on, the minutes in focus blocks (focus-guard.py's
                   day_stats), and the last workspace session (sessions.py:
                   `sessions.py where-was-i` brings it back)
    repos          repos in your projects folder (desktop_conf.py) with uncommitted, untracked or unpushed work
                   (the bar's repos.py scan: git status only, no fetch)
    units          failed systemd units, yours (timers included) and the system's
    updates        what the updates pill last found (software-updates.py pending;
                   its cache, no dnf run)
    weather        today from wttr.py's saved answer (no request of its own)
    calendar       today's timed events still to come (Evolution's calendars,
                   through timers.py's reader)
    timers         alarms, timers and reminders still to ring today (timers.py)
    notifications  what came in that you have not seen (notify-digest.py's
                   reading of mako, plain counts)
    health         the last nightly checkup (health.py's report, not a new
                   run): what it fixed, what waits for your OK, the worst
                   problems in plain words; a backup (backup.py) that failed
                   or is over two days old; nothing when all was well

A section with nothing to say is left out; one that fails says so in one
line instead of taking the brief down.

WHEN -- automations.py's built-in rule "daily-brief" (when you come back
after being away, idle-end: `brief.py auto --rule`) and brief.timer
(`brief.py auto --tick` 90 s and 12 min after login, and at `at` with
morning=time) together, once per day:
    morning=unlock   the first time you are back at the computer after `after`
                     (05:00): idle-end after that hour, or a fresh login (the
                     timer, in the first LOGIN_S of a Hyprland session)
    morning=time     at `at` (08:30), or the first time back after it
The rule switched off (Settings or `automations.py disable daily-brief`) is
the brief off; the timer then does nothing either. While the screen is locked
it waits for the unlock (up to LOCK_WAIT_S). Your own automations can run the
"brief" action too (it then shows whether the built-in rule is on or not,
still once a day).

READ ALOUD -- with Settings > Speech's "the morning brief" on (tts.py's
speak_brief, off as shipped) the morning brief (auto(), not one asked for
by hand) is also said, in a few sentences (spoken(): the greeting, then each
section's title and first line), by tts.py's local Piper voice. tts.py
keeps it silent in gamemode, Do Not Disturb and the quiet hours; the
notification is there either way.

THE JOURNAL -- automations.py's built-in rule "end-of-day" (work-end, from
workhours.py) runs `brief.py journal --notify`; Settings and the launcher
("journal") run it on demand. The entry:

    Summary   a few sentences from the local worker model (llm-worker.py's
              ready()/ask(): local only, never a cloud model, never in gamemode
              or when the GPU is full); a plain summary when it cannot run
    Time      focused time per project / app (the activity history; a period is
              counted MAX_PERIOD_S at most). A project is a repo in your projects
              folder whose name is in the window title (a path, an editor's "- Name -"
              segment). Nothing is guessed about employers or clients: rows are
              repos and apps, as they are
    Focus     the minutes in focus blocks and how many (focus guard's
              counts; left out when there were none)
    Commits   today's commits across your projects folder by you (git config user.email),
              by repo
    Loose ends   the brief's repos, failed units and updates, as of now

Only the part between the "brief.py:start/end" markers is ever rewritten:
notes you write elsewhere in the file are kept when it runs again. Window
titles go into the entry (and to the model) only with titles=on: the journal
outlives the activity history's kept days, and titles can say a lot. Private
windows (activity-log.py: KeePassXC, private browsing, the apps in
Settings > Privacy) count as "private", nothing more.

The draft time sheet (timesheet=on, or `brief.py timesheet`):
JOURNAL_DIR/YYYY-MM-DD-timesheet.csv, "date,project,hours" with the hours
rounded to the quarter -- a draft to check, from focus time, not billing.

SETTINGS ($XDG_STATE_HOME/hypr/brief.conf, key=value; a missing key is its
default):
    sections   which brief sections, in order (default: all of SECTIONS)
    morning    unlock | time
    after      HH:MM   (morning=unlock: not before this)
    at         HH:MM   (morning=time)
    journal_dir   default ~/Documents/Journal
    titles     on | off (default off): window titles in the journal
    timesheet  on | off (default off): the CSV next to each entry
    model      on | off (default on): the summary by the local model
State (the last brief and journal days): $XDG_STATE_HOME/hypr/brief-state.json.
brief.timer's time of day follows `morning` / `at`: `set` (and each --tick)
writes brief.timer.d/schedule.conf (timer_dropin) when it differs, so the
timer fires once at `at` instead of polling every 5 minutes.
"""
import csv
import datetime as dt
import fcntl
import html
import importlib.util
import io
import json
import os
import re
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
NOTIFY = os.path.join(HERE, "notify")  # notify-send with the theme's mascot (mascot_notify.py)
WAYBAR = os.path.expanduser("~/.config/waybar/scripts")
STATE_DIR = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"), "hypr")
CONF = os.path.join(STATE_DIR, "brief.conf")
STATE = os.path.join(STATE_DIR, "brief-state.json")
AUTO_LOCK = os.path.join(STATE_DIR, "brief-auto.lock")
ACTIVITY = os.path.join(STATE_DIR, "activity.jsonl")
RUNTIME = os.environ.get("XDG_RUNTIME_DIR", "/tmp")
CACHE = os.path.join(RUNTIME, "brief.json")         # the last brief, for the panel
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import desktop_conf  # noqa: E402

PROJECTS = desktop_conf.projects_dir()               # your projects folder (desktop.conf)
APP = "Brief"
ICON = "x-office-calendar"

SECTIONS = ("yesterday", "repos", "units", "health", "updates", "weather", "calendar", "timers",
            "notifications")
SECTION_TITLES = {"yesterday": "Where you left off", "repos": "Repos with work in them",
                  "units": "Failed services", "health": "Health", "updates": "Updates", "weather": "Weather",
                  "calendar": "Today's calendar", "timers": "Timers & alarms",
                  "notifications": "Unread notifications"}
DEFAULTS = {"sections": ",".join(SECTIONS), "morning": "unlock", "after": "05:00", "at": "08:30",
            "journal_dir": "~/Documents/Journal", "titles": "off", "timesheet": "off", "model": "on"}
RULE_BRIEF, RULE_JOURNAL = "daily-brief", "end-of-day"
LOGIN_S = 20 * 60           # --tick in unlock mode: only this soon after Hyprland started
LOCK_WAIT_S = 30 * 60       # the brief waits this long for an unlock
MAX_PERIOD_S = 90 * 60      # one unbroken focus counts this much at most
LOOKBACK_DAYS = 7           # "yesterday" is the last day with activity in this many
START, END = "<!-- brief.py:start -->", "<!-- brief.py:end -->"
HM = re.compile(r"([01]?\d|2[0-3]):([0-5]\d)$")
# What window titles start with that is no part of the title: spinners and
# status glyphs (a coding agent's ◐◑, braille spinners, a bell).
TITLE_NOISE = re.compile(r"^[\s◐◑◒◓●○✳✻✽·⠀-⣿🔔*•]+")
SYSTEM = ("You write a short, factual end-of-day work journal entry for a software developer from the "
          "notes given. Plain sentences, no headings, no lists, no preamble. Use only what the notes say: "
          "never guess employers, clients, people or reasons, and do not judge productivity.")


_IMPORTING = threading.Lock()   # gather() runs sections side by side: one import at a time


def _module(name, filename, folder=HERE):
    with _IMPORTING:
        mod = sys.modules.get(name)
        if mod is None:
            spec = importlib.util.spec_from_file_location(name, os.path.join(folder, filename))
            mod = importlib.util.module_from_spec(spec)
            sys.modules[name] = mod
            try:
                spec.loader.exec_module(mod)
            except BaseException:
                del sys.modules[name]
                raise
        return mod


def run(*cmd, timeout=15, cwd=None):
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd)
        return out.stdout if out.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def span(seconds):
    m = int(seconds // 60)
    return f"{m // 60} h {m % 60:02d} min" if m >= 60 else f"{max(m, 1)} min"


# -- settings and state -------------------------------------------------------------
def settings(path=None):
    conf = dict(DEFAULTS)
    try:
        with open(path or CONF) as handle:
            for line in handle:
                key, sep, value = line.strip().partition("=")
                if sep and key.strip() in DEFAULTS:
                    conf[key.strip()] = value.strip()
    except OSError:
        pass
    return conf


def check_setting(key, value):
    """The value tidied, or ValueError saying why not."""
    value = value.strip()
    if key not in DEFAULTS:
        raise ValueError(f"no setting {key!r} ({', '.join(DEFAULTS)})")
    if key == "sections":
        names = [s.strip() for s in value.split(",") if s.strip()]
        bad = [s for s in names if s not in SECTIONS]
        if bad:
            raise ValueError(f"no section {', '.join(bad)} ({', '.join(SECTIONS)})")
        return ",".join(s for s in SECTIONS if s in names)        # always in the brief's order
    if key == "morning" and value not in ("unlock", "time"):
        raise ValueError("morning is unlock or time")
    if key in ("after", "at"):
        m = HM.match(value)
        if not m:
            raise ValueError(f"{key} is HH:MM")
        return f"{int(m[1]):02d}:{m[2]}"
    if key in ("titles", "timesheet", "model") and value not in ("on", "off"):
        raise ValueError(f"{key} is on or off")
    if key == "journal_dir" and not value:
        raise ValueError("journal_dir needs a folder")
    return value


def set_setting(key, value, path=None):
    value = check_setting(key, value)
    conf = settings(path)
    conf[key] = value
    path = path or CONF
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as handle:
        handle.write("# Daily brief & journal (brief.py; Settings > Daily brief & journal)\n")
        handle.writelines(f"{k}={conf[k]}\n" for k in DEFAULTS)
    os.replace(tmp, path)
    return value


TIMER_DROPIN = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"),
                            "systemd", "user", "brief.timer.d", "schedule.conf")


def timer_dropin(conf):
    """brief.timer's drop-in for these settings -- pure, for the tests.
    morning=time: an OnCalendar at `at` (the login ticks are in the timer
    itself). morning=unlock: none -- coming back (the idle-end rule) and the
    login ticks are the whole of it."""
    # No "OnCalendar=" reset line: an empty trigger setting clears ALL the
    # timer's triggers, the login ones in brief.timer too.
    head = ("# Written by ~/.config/hypr/scripts/brief.py from brief.conf (Settings > Daily brief):\n"
            "# edits here are overwritten.\n[Timer]\n")
    if conf.get("morning") == "time":
        return head + f"OnCalendar=*-*-* {conf.get('at') or DEFAULTS['at']}:00\n"
    return head


def schedule_timer(conf=None, path=None):
    """brief.timer.d/schedule.conf written when it differs, and systemd told
    (daemon-reload re-arms the timer). True when it changed."""
    path = path or TIMER_DROPIN
    text = timer_dropin(conf or settings())
    try:
        with open(path) as handle:
            if handle.read() == text:
                return False
    except OSError:
        pass
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path + ".tmp", "w") as handle:
            handle.write(text)
        os.replace(path + ".tmp", path)
        subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return False
    return True


def sections(conf):
    return [s for s in conf["sections"].split(",") if s in SECTIONS]


def journal_dir(conf):
    return os.path.expanduser(conf["journal_dir"])


def load_state():
    try:
        with open(STATE) as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(**change):
    data = {**load_state(), **change}
    os.makedirs(STATE_DIR, exist_ok=True)
    tmp = STATE + ".tmp"
    with open(tmp, "w") as handle:
        json.dump(data, handle)
    os.replace(tmp, STATE)


# -- the activity history ----------------------------------------------------------------
def read_activity(path=ACTIVITY):
    rows = []
    try:
        with open(path) as handle:
            for line in handle:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if isinstance(row, dict) and isinstance(row.get("t"), (int, float)):
                    rows.append(row)
    except OSError:
        return None
    return rows


def periods(rows, t0, t1, now=None):
    """[(start, end, class, title)] of focus within [t0, t1): each line lasts
    until the next (MAX_PERIOD_S at most); nothing focused is left out."""
    now = now or time.time()
    out = []
    for i, row in enumerate(rows):
        a = row["t"]
        b = rows[i + 1]["t"] if i + 1 < len(rows) else now
        b = min(b, a + MAX_PERIOD_S)
        a, b = max(a, t0), min(b, t1)
        if b > a and row.get("class"):
            out.append((a, b, row["class"], clean_title(row.get("title", ""))))
    return out


def clean_title(title):
    return TITLE_NOISE.sub("", title or "").strip()


def app_name(cls):
    """'org.mozilla.firefox' -> 'firefox', 'com.system76.CosmicTerm' -> 'CosmicTerm'."""
    if cls == "private":
        return "private"
    return cls.rsplit(".", 1)[-1] if "." in cls else cls


def repo_names(root=None):
    root = root or PROJECTS
    try:
        return sorted((n for n in os.listdir(root) if os.path.isdir(os.path.join(root, n, ".git"))),
                      key=len, reverse=True)
    except OSError:
        return []


def project_of(title, repos, folder=None):
    """The projects-folder repo a window title names, or None: a path into
    it (~/Projects/Name, /Projects/Name -- folder is the projects folder's
    own name, PROJECTS's by default), else a title segment (between " - ", " — ",
    " | ", ": ") that is exactly its name -- editors put the folder there.
    Names under four letters only count as a path: "TV" or "Law" alone in a
    page title is too likely to be something else."""
    if not title:
        return None
    folder = re.escape(folder or os.path.basename(PROJECTS))
    for name in repos:
        if re.search(rf"{folder}/{re.escape(name)}(?:/|\b|$)", title, re.I):
            return name
    segments = {s.strip().lower() for s in re.split(r"\s[-—–|]\s|:\s", title)}
    for name in repos:
        if len(name) >= 4 and name.lower() in segments:
            return name
    return None


def tally(spans, repos):
    """{"projects": [(name, s)], "apps": [(name, s)], "titles": [(app, title, s)],
    "total": s, "first": t, "last": t, "end": (app, title)} for a list of periods."""
    by_key, by_app, by_title = {}, {}, {}
    for a, b, cls, title in spans:
        app = app_name(cls)
        proj = project_of(title, repos) if cls != "private" else None
        key = proj or app
        by_key[key] = by_key.get(key, 0) + b - a
        by_app[app] = by_app.get(app, 0) + b - a
        if cls != "private" and title:
            by_title[(app, title)] = by_title.get((app, title), 0) + b - a
    ordered = lambda d: sorted(d.items(), key=lambda kv: -kv[1])    # noqa: E731
    last = next(((app_name(c), t) for _a, _b, c, t in reversed(spans) if c != "private"), None)
    return {"projects": ordered(by_key), "apps": ordered(by_app),
            "titles": [(app, t, s) for (app, t), s in ordered(by_title)],
            "total": sum(b - a for a, b, _c, _t in spans),
            "first": spans[0][0] if spans else None, "last": spans[-1][1] if spans else None, "end": last}


def day_bounds(day):
    start = dt.datetime.combine(day, dt.time())
    return start.timestamp(), (start + dt.timedelta(days=1)).timestamp()


def last_active_day(rows, today, lookback=LOOKBACK_DAYS):
    """The last day before `today` with any focus in it, or None."""
    for back in range(1, lookback + 1):
        day = today - dt.timedelta(days=back)
        t0, t1 = day_bounds(day)
        if periods(rows, t0, t1):
            return day
    return None


def day_word(day, today):
    back = (today - day).days
    return "yesterday" if back == 1 else day.strftime("%A")


# -- the brief's sections ------------------------------------------------------------------
def sec_yesterday(today):
    rows = read_activity()
    lines = []
    if rows is None:
        lines.append("The activity history is off or empty (Settings > Privacy).")
    else:
        day = last_active_day(rows, today)
        if day:
            t0, t1 = day_bounds(day)
            t = tally(periods(rows, t0, t1), repo_names())
            top = ", ".join(f"{k} {span(s)}" for k, s in t["projects"][:4])
            lines.append(f"{day_word(day, today).capitalize()}: {span(t['total'])} at the computer, "
                         f"{dt.datetime.fromtimestamp(t['first']):%H:%M}-{dt.datetime.fromtimestamp(t['last']):%H:%M}"
                         f" -- {top}")
            if t["end"]:
                lines.append(f"You ended on {t['end'][0]}: {t['end'][1][:90]}".rstrip(": "))
            focus = focus_stats(day)
            if focus:
                lines.append(f"Focus: {focus_text(focus)}.")
    try:
        sess = _module("sessions", "sessions.py")
        data = sess.last_session()
        if data:
            apps = sess.summary("last", data)["apps"]
            lines.append(f"The last session had {apps} -- \"where was I\" brings it back.")
    except Exception as err:       # sessions are extra
        lines.append(f"(the last session could not be read: {err})")
    return lines


def sec_repos(_today):
    repos = _module("repos", "repos.py", WAYBAR)
    rows = repos.scan()
    busy = [r for r in rows if r["changed"] or r["untracked"] or r["ahead"] or r.get("drift") or r["error"]]
    lines = [f"{r['name']}: {repos.describe(r)}" for r in busy[:8]]
    if len(busy) > 8:
        lines.append(f"... and {len(busy) - 8} more (the git pill's panel lists them all)")
    local = [r["name"] for r in rows if not r["upstream"] and not r["error"]]
    if local:
        lines.append(f"Never pushed anywhere: {', '.join(local[:6])}" + (" ..." if len(local) > 6 else ""))
    return lines


def failed_units(user=True):
    out = run("systemctl", *(["--user"] if user else []), "list-units", "--failed", "--plain",
              "--no-legend", "--no-pager", timeout=10) or ""
    return [line.split()[0] for line in out.splitlines() if line.split()]


def sec_units(_today):
    lines = []
    mine, system = failed_units(True), failed_units(False)
    if mine:
        lines.append("Yours: " + ", ".join(mine[:8]) + "  (journalctl --user -u NAME; Settings > Maintenance)")
    if system:
        lines.append("The system's: " + ", ".join(system[:8]) + "  (journalctl -u NAME)")
    return lines


def sec_updates(_today):
    p = _module("software_updates", "software-updates.py").pending()
    if not p or p.get("status") not in ("ok", None):
        return []
    n, flat = len(p.get("pkgs") or []), len(p.get("flatpaks") or [])
    if not n and not flat:
        return []
    bits = [f"{n} package{'s' if n != 1 else ''}"] if n else []
    if p.get("security"):
        bits.append(f"{p['security']} security")
    if p.get("kernel"):
        bits.append("a new kernel")
    if flat:
        bits.append(f"{flat} flatpak{'s' if flat != 1 else ''}")
    return [", ".join(bits) + " waiting (the updates pill; safe-upgrade from its panel)"]


def sec_weather(_today):
    wttr = _module("wttr", "wttr.py", WAYBAR)
    try:
        with open(wttr.RAW) as handle:
            weather = json.load(handle)
    except (OSError, ValueError):
        return []
    if not wttr.is_for_here(weather) or time.time() - os.path.getmtime(wttr.RAW) > 6 * 3600:
        return []
    cur = weather["current_condition"][0]
    day = (weather.get("weather") or [{}])[0]
    rain = max((int(h.get("chanceofrain", 0)) for h in day.get("hourly", [])), default=0)
    line = f"{cur['weatherDesc'][0]['value'].strip()}, {wttr.val(cur, 'temp_C')}{wttr.TEMP_UNIT} now"
    if day:
        line += f"; today {wttr.val(day, 'mintempC')}..{wttr.val(day, 'maxtempC')}{wttr.TEMP_UNIT}"
    if rain >= 30:
        line += f", {rain}% chance of rain"
    return [line]


def sec_calendar(_today):
    timers = _module("timers", "timers.py")
    now = dt.datetime.now()
    left = int((dt.datetime.combine(now.date() + dt.timedelta(days=1), dt.time()) - now).total_seconds() // 60)
    events = sorted(timers.upcoming_events(max(1, left)))
    return [f"{start:%H:%M}  {summary}" for start, summary, _key in events[:8]]


def sec_timers(_today):
    timers = _module("timers", "timers.py")
    now = time.time()
    _t0, t1 = day_bounds(dt.date.today())
    return [timers.describe(t, now) for t in timers.running()
            if t.get("due", 0) < t1 and not t.get("paused")][:6]   # paused: won't ring


def sec_notifications(_today):
    nd = _module("notify_digest", "notify-digest.py")
    n = nd.notifications()
    items = n.all_entries()
    got = nd.missed(items, max(n.read_id(n.SEEN), n.read_id(n.CLEARED)))
    got = [x for x in got if nd.app_of(x) != APP]
    if not got:
        return []
    return [f"{len(got)}: " + ", ".join(f"{app} {len(ns)}" for app, ns in nd.groups(got))]


def sec_health(_today):
    # the nightly checkup's findings, what railguard ended in the last day,
    # then the backup when it is overdue or failed (backup.py's saved state)
    return (_module("health", "health.py").brief_lines() + _module("railguard", "railguard.py").brief_lines()
            + _module("backup", "backup.py").brief_lines())


GATHER = {"yesterday": sec_yesterday, "repos": sec_repos, "units": sec_units, "health": sec_health,
          "updates": sec_updates, "weather": sec_weather, "calendar": sec_calendar, "timers": sec_timers,
          "notifications": sec_notifications}


def gather(conf=None, today=None, only=None):
    """[{"id", "title", "lines"}] for the chosen sections that have
    something to say; a failing one says so instead."""
    conf = conf or settings()
    today = today or dt.date.today()
    wanted = only or sections(conf)

    def one(sid):
        try:
            lines = GATHER[sid](today)
        except Exception as err:        # one broken source never takes the brief down
            lines = [f"(could not be read: {str(err)[:120]})"]
        return {"id": sid, "title": SECTION_TITLES[sid], "lines": lines}
    # Sources are independent and mostly wait on subprocesses: side by side.
    with ThreadPoolExecutor(max_workers=4) as pool:
        out = list(pool.map(one, wanted))
    return [s for s in out if s["lines"]]


def greeting(now=None):
    now = now or dt.datetime.now()
    word = "Good morning" if now.hour < 12 else "Good afternoon" if now.hour < 19 else "Good evening"
    return f"{word} -- {now:%A %d %B}"


def as_text(brief):
    return "\n\n".join(f"{s['title']}\n" + "\n".join(f"  {line}" for line in s["lines"]) for s in brief) \
        or "Nothing to report."


def short_body(brief):
    """One line per section, for the notification."""
    out = []
    for s in brief:
        first = s["lines"][0]
        more = f" (+{len(s['lines']) - 1})" if len(s["lines"]) > 1 else ""
        out.append(f"<b>{html.escape(s['title'])}</b>: {html.escape(first[:110])}{more}")
    return "\n".join(out) or "Nothing to report: no loose ends, nothing failed, nothing waiting."


def write_cache(brief):
    try:
        tmp = CACHE + ".tmp"
        with open(tmp, "w") as handle:
            json.dump({"made": time.time(), "brief": brief}, handle)
        os.replace(tmp, CACHE)
    except OSError:
        pass


EAR = ((re.compile(r"\s*\([^)]*\)"), ""),                                   # (journalctl …), (+3)
       (re.compile(r"\b[\w@.:-]+\.(service|timer|socket|mount|path)\b"), "a service"),
       (re.compile(r"a service(, a service)+"), "several services"),
       (re.compile(r"(\d+) h (\d+) min\b"), r"\1 hours \2 minutes"),
       (re.compile(r"(\d+) min\b"), r"\1 minutes"),
       (re.compile(r"(\d\d:\d\d)-(\d\d:\d\d)"), r"\1 to \2"),
       (re.compile(r"(\d)\.\.(-?\d)"), r"\1 to \2"),                          # 12..18°C
       (re.compile(r"~(?=[/.\s]|$)"), "home"),
       (re.compile(r" -- "), ". "))


def spoken(brief, now=None):
    """The brief as a few sentences for the ear (READ ALOUD): the greeting,
    each section's title and first line, without unit names, commands and
    abbreviations."""
    parts = [greeting(now).replace(" -- ", ". ") + "."]
    for s in brief:
        line = s["lines"][0].strip()
        for pattern, words in EAR:
            line = pattern.sub(words, line)
        parts.append(f"{s['title']}: {line.rstrip('.')}.")
    return "\n".join(parts) if brief else parts[0] + "\nNothing to report."


def say_aloud(brief, feature="brief"):
    """tts.py says it (its own switch, gamemode and DND checks). True: queued."""
    try:
        return bool(_module("tts", "tts.py").speak(spoken(brief), lang="en", feature=feature))
    except Exception as err:    # noqa: BLE001 -- no voice costs nothing else
        print(f"brief: not read aloud: {type(err).__name__}: {err}", file=sys.stderr, flush=True)
        return False


def show(aloud=False):
    """The brief as a notification (waits for its click: run detached).
    aloud: the morning one -- also read aloud when Settings > Speech says so."""
    brief = gather()
    write_cache(brief)
    if aloud:
        say_aloud(brief)
    # Not marked "shown" here: only auto() does that, so the brief asked for
    # by hand (Settings, `brief.py show`) at 1 am still leaves the morning's.
    argv =[NOTIFY, "-a", APP, "-i", ICON, "--wait", "-A", "default=Open the brief",
            greeting(), short_body(brief) + "\n<i>Click for all of it</i>"]
    try:
        picked = subprocess.run(argv, capture_output=True, text=True, timeout=4 * 3600).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return
    if picked == "default":
        detach([sys.executable, os.path.abspath(__file__), "panel"])


def detach(argv):
    subprocess.Popen(argv, start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def unit(argv):
    """As a transient service, like automations.py's: outlives the caller."""
    return ["systemd-run", "--user", "--quiet", "--collect", "--"] + argv


# -- when ------------------------------------------------------------------------------------
def rule_on(rid):
    try:
        auto = _module("automations", "automations.py")
        rule = auto.find(auto.load()[0], rid)
        return bool(rule and rule.get("enabled", True))
    except Exception:       # an unreadable automations.json: the shipped default (on)
        return True


def locked():
    return run("pidof", "hyprlock", timeout=3) is not None


def session_age():
    """Seconds since this Hyprland started, or None."""
    out = run("ps", "-o", "etimes=", "-C", "Hyprland", timeout=3) or ""
    ages = [int(x) for x in out.split() if x.isdigit()]
    return min(ages) if ages else None


def hm(text):
    m = HM.match(text or "")
    return dt.time(int(m[1]), int(m[2])) if m else dt.time(5, 0)


def due(conf, now, tick, shown, age):
    """Is the morning brief due? (yes, why) -- pure, for the tests.
    tick: the timer asked (not you coming back); shown: the day it was
    last shown (ISO); age: seconds since Hyprland started."""
    if shown == now.date().isoformat():
        return False, "shown today already"
    if conf["morning"] == "time":
        if now.time() < hm(conf["at"]):
            return False, f"not {conf['at']} yet"
        return True, "time"
    if now.time() < hm(conf["after"]):
        return False, f"before {conf['after']}"
    if tick and (age is None or age > LOGIN_S):
        return False, "waiting for you to come back (idle-end)"
    return True, "back" if not tick else "login"


def auto(tick=False, from_rule=False, now=None):
    """The morning trigger (the docstring's WHEN). Returns what it did.
    from_rule: an automation's "brief" action ran it -- that rule is on.
    One at a time (AUTO_LOCK): the timer and the rule can fire in the same
    second, and both would see "not shown yet"."""
    now = now or dt.datetime.now()
    if load_state().get("shown") == now.date().isoformat():
        return "shown today already"        # the usual answer, before anything is imported
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(AUTO_LOCK, "w") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return "another check is running"
        return _auto(tick, from_rule, now)


def _auto(tick, from_rule, now):
    if not from_rule and not rule_on(RULE_BRIEF):
        return "the daily-brief rule is off"
    ok, why = due(settings(), now, tick, load_state().get("shown"), session_age())
    if not ok:
        return why
    if locked():
        if tick:
            return "locked: after the unlock"
        waited = 0
        while locked() and waited < LOCK_WAIT_S:
            time.sleep(5)
            waited += 5
        if locked():
            return "still locked"
    save_state(shown=dt.date.today().isoformat())
    detach(unit([sys.executable, os.path.abspath(__file__), "show", "--aloud"]))
    return f"shown ({why})"


# -- the journal -------------------------------------------------------------------------------
def git_email():
    return (run("git", "config", "--global", "user.email", timeout=5) or "").strip()


def commits_in(path, t0, t1, email):
    """[(HH:MM, short hash, subject)] of your commits in [t0, t1) on any branch.
    No email (none global, none in the repo): none -- --all also holds what
    others pushed and you fetched today, and those are not yours."""
    email = email or (run("git", "-C", path, "config", "user.email", timeout=5) or "").strip()
    if not email:
        return []
    argv = ["git", "-C", path, "--no-optional-locks", "log", "--all", "--no-merges",
            f"--since=@{int(t0)}", f"--until=@{int(t1)}", "--format=%h%x1f%ad%x1f%s",
            "--date=format-local:%H:%M", "--fixed-strings", f"--author={email}"]
    out = run("nice", "-n", "19", *argv, timeout=20) or ""
    rows = []
    for line in out.splitlines():
        parts = line.split("\x1f")
        if len(parts) == 3:
            rows.append((parts[1], parts[0], parts[2]))
    return sorted(set(rows))


def commits(day, root=None):
    """{repo: [(HH:MM, hash, subject)]} for `day`."""
    root = root or PROJECTS
    t0, t1 = day_bounds(day)
    email = git_email()
    names = repo_names(root)
    with ThreadPoolExecutor(max_workers=8) as pool:
        found = pool.map(lambda n: (n, commits_in(os.path.join(root, n), t0, t1, email)), names)
    return {n: rows for n, rows in sorted(found, key=lambda x: x[0].lower()) if rows}


def journal_facts(day, conf, now=None):
    """What the entry is made of (the model sees the same)."""
    rows = read_activity()
    t0, t1 = day_bounds(day)
    t = tally(periods(rows or [], t0, t1, now), repo_names()) if rows is not None else None
    loose = []
    if day == dt.date.today():
        for s in gather(conf, only=["repos", "units", "updates"]):
            loose.append(f"{s['title']}: " + "; ".join(s["lines"]))
    return {"day": day, "tally": t, "commits": commits(day), "loose": loose,
            "titles": conf["titles"] == "on", "activity_off": rows is None, "focus": focus_stats(day)}


def focus_stats(day):
    """Focus guard's counts for `day` (focus-guard.py's day_stats: minutes in
    focus blocks, blocks, ...), or None -- none, or focus guard not there."""
    try:
        return _module("focus_guard", "focus-guard.py").day_stats(day)
    except Exception:       # focus guard is extra
        return None


def focus_text(focus):
    n = int(focus.get("blocks") or 0)
    return f"{span(focus['minutes'] * 60)} in focus blocks ({n} block{'s' if n != 1 else ''})"


def quarter_hours(seconds):
    return round(seconds / 900) / 4


def timesheet_rows(facts):
    """[(date, project, hours)] -- projects and apps over a quarter hour."""
    t = facts["tally"]
    if not t:
        return []
    return [(facts["day"].isoformat(), k, quarter_hours(s)) for k, s in t["projects"]
            if quarter_hours(s) > 0 and k != "private"]


def timesheet_csv(facts):
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["date", "project", "hours", "note"])
    for day, proj, hours in timesheet_rows(facts):
        w.writerow([day, proj, f"{hours:.2f}", "draft: focus time from the activity history"])
    return out.getvalue()


def notes_for_model(facts):
    t, lines = facts["tally"], []
    if t:
        lines.append(f"Time at the computer: {span(t['total'])}.")
        lines += [f"- {k}: {span(s)}" for k, s in t["projects"][:10]]
        if facts["titles"]:
            lines.append("Busiest windows:")
            lines += [f"- {app}: {title[:100]} ({span(s)})" for app, title, s in t["titles"][:12]]
    if facts.get("focus"):
        lines.append(f"Deliberate focus: {focus_text(facts['focus'])}.")
    for repo, rows in facts["commits"].items():
        lines.append(f"Commits in {repo}: " + "; ".join(subject for _h, _c, subject in rows[:12]))
    if facts["loose"]:
        lines.append("Loose ends now: " + "; ".join(facts["loose"][:8]))
    return "\n".join(lines)


def plain_summary(facts):
    t, bits = facts["tally"], []
    if t and t["projects"]:
        bits.append("Most of the time went to " + ", ".join(f"{k} ({span(s)})" for k, s in t["projects"][:3])
                    + f", {span(t['total'])} in all.")
    n = sum(len(r) for r in facts["commits"].values())
    if n:
        repos = list(facts["commits"])
        names = ", ".join(repos[:6]) + (f" and {len(repos) - 6} more repos" if len(repos) > 6 else "")
        bits.append(f"{n} commit{'s' if n != 1 else ''} in {names}.")
    if not bits:
        bits.append("Nothing was logged for this day.")
    return " ".join(bits)


def model_summary(facts):
    """(text, None) from the local worker model, or (None, why not)."""
    notes = notes_for_model(facts)
    if not notes:
        return None, "nothing to summarise"
    worker = _module("llm_worker", "llm-worker.py")
    model, why = worker.ready("worker")
    if model is None:
        return None, why
    prompt = ("Write 3 to 5 sentences about this day's work, grouped by project, from these notes. "
              "Mention the commits' subjects where they say what was done.\n\n" + notes)
    try:
        text = worker.ask(model, prompt, system=SYSTEM).replace("**", "").strip()
    except Exception as err:
        return None, f"{model.name} failed: {err}"
    return (text, None) if text else (None, f"{model.name} answered nothing")


def entry_block(facts, summary, how):
    t = facts["tally"]
    out = [START, "", "## Summary", "", summary, "", f"<sub>{how}</sub>", "", "## Time", ""]
    if facts["activity_off"]:
        out.append("The activity history is off (Settings > Privacy): no time to show.")
    elif not t or not t["projects"]:
        out.append("Nothing logged.")
    else:
        out += ["| Project / app | Time |", "|---|---|"]
        out += [f"| {k} | {span(s)} |" for k, s in t["projects"][:15]]
        out += ["", f"{span(t['total'])} focused, {dt.datetime.fromtimestamp(t['first']):%H:%M}-"
                    f"{dt.datetime.fromtimestamp(t['last']):%H:%M} (the activity history; a project is a "
                    "repo in your projects folder named in the window title)."]
        if facts["titles"] and t["titles"]:
            out += ["", "Busiest windows:", ""]
            out += [f"- {app}: {title[:100]} ({span(s)})" for app, title, s in t["titles"][:10]]
    if facts.get("focus"):
        out += ["", "## Focus", "", f"{focus_text(facts['focus']).capitalize()} (focus guard; Settings > Focus)."]
    out += ["", "## Commits", ""]
    if facts["commits"]:
        for repo, rows in facts["commits"].items():
            out.append(f"**{repo}** ({len(rows)})")
            out += [f"- {when} `{h}` {subject}" for when, h, subject in rows]
            out.append("")
    else:
        out += ["None.", ""]
    if facts["loose"]:
        out += ["## Loose ends", ""] + [f"- {line}" for line in facts["loose"]] + [""]
    out.append(END)
    return "\n".join(out)


def merge_entry(old, block, day):
    """The file's text with `block` in place of the old generated part;
    a new file gets a heading and a Notes section for you."""
    if old and START in old and END in old:
        head, _, rest = old.partition(START)
        _, _, tail = rest.partition(END)
        return head + block + tail
    if old:
        return old.rstrip("\n") + "\n\n" + block + "\n"
    return (f"# {day:%A %d %B %Y}\n\n<!-- brief.py writes between the markers below (again at each end of day);"
            f" anything else in this file is yours and kept. -->\n\n{block}\n\n## Notes\n\n")


def entry_path(conf, day):
    return os.path.join(journal_dir(conf), f"{day.isoformat()}.md")


def write_journal(day=None, use_model=True, dry_run=False, conf=None):
    """(path, how) after writing DAY's entry (and the time sheet when on)."""
    conf = conf or settings()
    day = day or dt.date.today()
    facts = journal_facts(day, conf)
    summary, how = None, "a plain summary"
    if use_model and conf["model"] == "on":
        summary, why = model_summary(facts)
        if summary:
            how = "summary by the local model: check it"
        else:
            how = f"a plain summary (the model: {why})"
    summary = summary or plain_summary(facts)
    block = entry_block(facts, summary, how)
    path = entry_path(conf, day)
    if dry_run:
        print(block)
        return path, how
    os.makedirs(journal_dir(conf), exist_ok=True)
    try:
        with open(path) as handle:
            old = handle.read()
    except OSError:
        old = ""
    tmp = path + ".tmp"
    with open(tmp, "w") as handle:
        handle.write(merge_entry(old, block, day))
    os.replace(tmp, path)
    if conf["timesheet"] == "on":
        write_timesheet(facts, conf)
    if day == dt.date.today():
        save_state(journal=day.isoformat())
    return path, how


def write_timesheet(facts, conf):
    path = os.path.join(journal_dir(conf), f"{facts['day'].isoformat()}-timesheet.csv")
    os.makedirs(journal_dir(conf), exist_ok=True)
    with open(path, "w", newline="") as handle:
        handle.write(timesheet_csv(facts))
    return path


def parse_day(argv):
    for a in argv:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", a):
            return dt.date.fromisoformat(a)
        if a in ("yesterday", "ayer"):
            return dt.date.today() - dt.timedelta(days=1)
    return dt.date.today()


# -- the panel ---------------------------------------------------------------------------------
def panel():
    sys.path.insert(0, WAYBAR)
    import panelui
    from gi.repository import GLib, Gtk
    import threading

    def lab(text, cls, wrap=True):
        w = Gtk.Label(label=text)
        w.get_style_context().add_class(cls)
        w.set_xalign(0)
        if wrap:
            w.set_line_wrap(True)
            w.set_max_width_chars(70)
        w.set_selectable(cls == "ctl-sub")
        return w

    def button(text, argv):
        b = Gtk.Button(label=text)
        b.get_style_context().add_class("ctl-link")
        b.connect("clicked", lambda _b: (detach(argv), Gtk.main_quit()))
        return b

    class BriefPanel(panelui.Panel):
        def build(self):
            self.card.pack_start(lab(greeting(), "kb-heading", False), False, False, 0)
            scroll = Gtk.ScrolledWindow()
            scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            scroll.set_propagate_natural_height(True)
            scroll.set_max_content_height(620)
            scroll.set_min_content_width(520)
            self.body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            scroll.add(self.body)
            self.card.pack_start(scroll, True, True, 0)
            me = [sys.executable, os.path.abspath(__file__)]
            row = Gtk.Box(spacing=6)
            row.set_halign(Gtk.Align.END)
            for text, argv in (("Write today's journal", me + ["journal", "--notify"]),
                               ("Journal folder", ["xdg-open", journal_dir(settings())]),
                               ("Settings", [os.path.join(HERE, "settings.py"), "brief"])):
                row.pack_start(button(text, argv), False, False, 0)
            self.card.pack_start(row, False, False, 6)
            cached = self.cached()
            if cached is not None:
                self.fill(cached)
            else:
                self.body.pack_start(lab("Gathering…", "ctl-sub"), False, False, 0)
                threading.Thread(target=lambda: GLib.idle_add(self.fill, gather()), daemon=True).start()

        @staticmethod
        def cached():
            """Today's brief from the last show(), if under an hour old."""
            try:
                with open(CACHE) as handle:
                    data = json.load(handle)
                return data["brief"] if time.time() - data["made"] < 3600 else None
            except (OSError, ValueError, KeyError):
                return None

        def fill(self, brief):
            for child in self.body.get_children():
                self.body.remove(child)
            for s in brief or [{"title": "Nothing to report", "lines": ["No loose ends, nothing failed."]}]:
                self.body.pack_start(lab(s["title"].upper(), "kb-heading", False), False, False, 4)
                for line in s["lines"]:
                    self.body.pack_start(lab(line, "ctl-sub"), False, False, 0)
            self.body.show_all()
            return False

    panelui.run(BriefPanel)


# -- status, for Settings ------------------------------------------------------------------------
def status():
    conf = settings()
    today = dt.date.today()
    path = entry_path(conf, today)
    try:
        wh = _module("workhours", "workhours.py").hours()
        work = {"start": wh[0].strftime("%H:%M"), "end": wh[1].strftime("%H:%M"),
                "days": [d for d in range(7) if d in wh[2]]}
    except Exception:
        work = None
    return {"settings": conf, "sections": list(SECTIONS), "titles": SECTION_TITLES,
            "rules": {"brief": rule_on(RULE_BRIEF), "journal": rule_on(RULE_JOURNAL)},
            "state": load_state(), "journal_today": path if os.path.exists(path) else "",
            "journal_dir": journal_dir(conf), "workhours": work}


def main(argv):
    cmd = argv[0] if argv else "show"
    if cmd == "show":
        show(aloud="--aloud" in argv)
    elif cmd == "say":
        if not say_aloud(gather(), feature=None):
            sys.exit(f"brief: not read aloud: {getattr(sys.modules.get('tts'), 'last_reason', '') or 'no voice'}")
    elif cmd == "panel":
        panel()
    elif cmd == "text":
        brief = gather()
        print(json.dumps(brief, ensure_ascii=False) if "--json" in argv else greeting() + "\n\n" + as_text(brief))
    elif cmd == "auto":
        if "--tick" in argv:
            schedule_timer()                # brief.timer's time of day, once it is set up
        print(f"brief: {auto(tick='--tick' in argv, from_rule='--rule' in argv)}", flush=True)
    elif cmd == "journal":
        path, how = write_journal(parse_day(argv[1:]), use_model="--plain" not in argv, dry_run="--dry-run" in argv)
        if "--dry-run" not in argv:
            print(f"brief: journal written: {path} ({how})", flush=True)
            if "--notify" in argv:
                picked = subprocess.run([NOTIFY, "-a", APP, "-i", ICON, "--wait", "-A", "default=Open it",
                                         "Journal written", f"{path.replace(os.path.expanduser('~'), '~')}\n{how}"],
                                        capture_output=True, text=True).stdout.strip()
                if picked == "default":
                    detach(["xdg-open", path])
    elif cmd == "timesheet":
        conf = settings()
        print(write_timesheet(journal_facts(parse_day(argv[1:]), conf), conf))
    elif cmd == "open":
        path = entry_path(settings(), parse_day(argv[1:]))
        if not os.path.exists(path):
            write_journal(parse_day(argv[1:]), use_model=False)
        detach(["xdg-open", path])
    elif cmd == "status":
        print(json.dumps(status(), ensure_ascii=False))
    elif cmd == "set" and len(argv) == 3:
        try:
            print(set_setting(argv[1], argv[2]))
            if argv[1] in ("morning", "at"):
                schedule_timer()
        except ValueError as err:
            sys.exit(f"brief: {err}")
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
