#!/usr/bin/env python3
"""Background tasks: small local jobs that run on their own and tell you
when something needs you -- a build that failed (and why), a price that
dropped, a Downloads folder that wants tidying, a folder of logs summed up
every morning. Followed by tasks.service.

    tasks.py run-daemon                 the daemon (tasks.service)
    tasks.py list [--json]              the tasks, in words, with status and last run
    tasks.py add JSON                   add a task given as JSON (checked first)
    tasks.py add-from-text "WORDS" [--yes|--json]
                                        the local "quick" model writes the task from
                                        plain words; it is checked, shown with what it
                                        may touch, and saved only after you say yes
                                        (--yes: no question; --json: only print it)
    tasks.py run TASK                   run it now (the daemon does, when it runs;
                                        automations' "task" action calls this)
    tasks.py stop TASK                  stop a command it is running (SIGTERM)
    tasks.py pause|resume TASK          switch one off / on
    tasks.py delete TASK                remove it, with its log and state
    tasks.py logs TASK [-n N]           its own log (the last N lines, default 40)
    tasks.py plan TASK [--json]         the moves a tidy task wants to make
    tasks.py approve TASK               make them (only within the folder, never
                                        deletes, never overwrites; logged for undo)
    tasks.py discard TASK               drop the plan, move nothing
    tasks.py undo TASK                  put the last approved batch of moves back
    tasks.py seen [TASK]                clear "needs attention" (all, or one)
    tasks.py watch-window [ADDRESS]     the job running in the focused terminal (or
                                        that window): tell me when it ends
    tasks.py on|off                     the master switch (the daemon idles when off)
    tasks.py set KEY VALUE              one setting (SETTINGS below)
    tasks.py status [--json]            the switch, the settings, the daemon
    tasks.py check                      validate tasks.json, exit 1 on problems
    tasks.py catalog                    JSON: the task types and their options
    tasks.py bar                        waybar's custom/tasks line

TASK is a task's id or its name. The tasks live in ~/.config/hypr/tasks.json,
human-editable:

    {"settings": {"enabled": true, ...},
     "tasks": [
       {"id": "build", "name": "Watch the build", "type": "watch-command",
        "params": {"command": "make -j24", "cwd": "~/src/thing"},
        "schedule": "once", "enabled": true}
     ]}

Every task has a TYPE from a fixed catalog (TYPES below) -- there is no way
to give it code to run -- with strictly checked params:

    watch-command     runs the command YOU typed (in a folder in your home),
                      keeps its output, and on a non-zero exit asks the worker
                      model what went wrong from the last lines. The model
                      never writes this command: a task written from plain
                      words keeps it only when it is word for word in what
                      you said.
    watch-file        follows a log file; a new line matching the pattern
                      (errors, by default) -> the cause, from the lines before
    watch-unit        a systemd unit (yours or the system's): when it fails or
                      restarts, the cause from its journal
    watch-process     a running program (watch-window picks the job in a
                      terminal): tells you when it ends -- not how, since a
                      process this did not start leaves no exit status
    watch-url         fetches a page (http/https, urllib, 2 MB at most), takes
                      one value out of it (a CSS-ish selector -- tag, .class,
                      #id, [attr=value], chained with spaces --, a pattern, or
                      the worker model asked for it in words) and compares it
                      with the last one: drops, rises, changes, below / above
    organise-folder   a PLAN of moves (by file type, or by month) into
                      sub-folders of that folder, shown for approval first;
                      only within your home, never deletes, never overwrites,
                      every approved batch logged for `undo`. Folders inside a
                      git work tree, your home itself and hidden ones are refused
    summarise-folder  the files matching a pattern that changed since the last
                      run, summed up by the worker model (plain counts of
                      errors and warnings, and the last ones, without it)
    nightly-checkup   built in, one task ("health-checkup", made by health.py,
                      edited in Settings > Desktop health; not offered for
                      adding): runs `health.py run --by tasks`, the
                      self-healing checkup -- see health.py

A SCHEDULE is one of: "watch" (all the time: the watchers), "once" (when
added or switched on), "every 30m" / "every 2h" / "every 1d", "daily 08:00",
"weekdays 08:00", "weekends 10:00", "mon,thu 18:30", "on-event" (when an
automation runs it: Settings > Automations, action "run a background task"),
and "manual" (only Run). A time missed while the computer was off runs once
when it is back. Each type says which schedules suit it.

Each task shows its PERMISSIONS -- the folders it reads or moves files in,
the site it fetches, the command it runs, the unit whose journal it reads --
and does nothing outside them (the params ARE the permissions: the code
touches nothing else). Reads refuse what looks secret (llm-worker.py's
looks_secret); writes, i.e. a tidy's moves, stay inside the folder.

Folder access (folder_access.py, Settings > Privacy > Folder access): a
file's text goes to the worker model only when its folder is open to
"tasks". The folder a task of yours works on (summarise-folder's folder,
watch-file's file's folder) counts as open by the task itself -- you set it
up, or said yes to it -- so nothing asks at 08:00 with nobody there; a Deny
for that folder (for tasks, or for all AI) wins, and then the task does its
plain work (counts, the error lines) without the model, saying why.

The models: the "quick" one writes tasks from plain words, the "worker" one
explains failures and sums up folders -- both local only (llm-worker.py's
ready() / ask(): never a cloud model, refused in gamemode or when the card
is full). When the model cannot run, the plain fallback says it: the last
error lines, or counts. Secrets that turn up in output (token=, password=,
Bearer ...) are masked before anything is logged or shown.

Gamemode: heavy scheduled work (a command, a summary, a tidy plan) waits
until it ends ("waiting: gamemode"); the watchers keep watching (a stat and
a read a few seconds apart) and explain in plain words meanwhile.

SETTINGS (tasks.json "settings"):

    enabled          the master switch (on)
    explain          the worker model explains failures and sums up (on)
    notify_ok        a notification when a watched command succeeds (on)
    gamemode_pause   heavy work waits for gamemode to end (on)
    web              watch-url tasks may fetch (on)
    url_min_minutes  the shortest "every" a watch-url task may have (15)

Where things are: each task's state, log, last output, tidy plan and undo
log in $XDG_STATE_HOME/hypr/tasks/<id>.{json,log,out,plan.json,undo.jsonl,
report.txt}; the daemon's own in $XDG_RUNTIME_DIR/tasks-daemon.json; asks
from the command line in $XDG_RUNTIME_DIR/tasks-poke/. Daemon log lines go
to the journal: journalctl --user -u tasks.

The bar (waybar custom/tasks, signal SIGNAL) shows only when a task needs
you -- a failure, a plan to approve -- with how many; click opens Settings >
Background tasks, right-click marks them seen. Settings > Background tasks
has all of the above.
"""
import collections
import datetime
import fcntl
import glob
import hashlib
import html.parser
import importlib.util
import json
import os
import queue
import re
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
HOME = os.path.expanduser("~")
CONFIG = os.path.expanduser("~/.config/hypr/tasks.json")
STATE_DIR = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"),
                         "hypr", "tasks")
RUNTIME = os.environ.get("XDG_RUNTIME_DIR", "/tmp")
DAEMON_STATE = os.path.join(RUNTIME, "tasks-daemon.json")
POKES = os.path.join(RUNTIME, "tasks-poke")
SETTINGS_PY = os.path.join(HERE, "settings.py")
APP, ICON, BAR_ICON = "Tasks", "system-run", "\uf0ae"
SIGNAL = 27                 # waybar custom/tasks

TICK_S = 2                  # the daemon's loop: pokes, files, processes, what is due
UNIT_POLL_S = 15            # a unit's state, between ticks
GAMEMODE_S = 20             # how long the gamemode answer is believed
ALERT_GAP_S = 60            # a watcher alerts at most this often
SETTLE_S = 3                # a watched file: lines that come together, one alert
MAX_TASKS = 50
MAX_FETCH = 2_000_000       # bytes of a page
FETCH_TIMEOUT = 20
MAX_OUT = 2_000_000         # bytes of a command's kept output
LOG_KEEP = 400              # lines of a task's log
TAIL_LINES = 40             # what a cause is read from, by default
MAX_PROMPT = 24_000         # characters sent to the model at once
MIN_EVERY_S = 300
ID = re.compile(r"[a-z0-9][a-z0-9-]{0,47}$")
HM = re.compile(r"([01]?\d|2[0-3]):([0-5]\d)$")
DAY_NAMES = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
DAY_WORDS = {"daily": "0123456", "every-day": "0123456", "every day": "0123456", "weekdays": "01234",
             "weekends": "56"}
ERRORS = r"(?i)\b(error|errors|failed|failure|fatal|panic|traceback|exception|segmentation fault|killed|denied)\b"
WARNINGS = re.compile(r"(?i)\b(warn|warning|deprecated)\b")
SECRET_LINE = [
    (re.compile(r"(?i)\b(password|passwd|pwd|token|secret|api[_-]?key|access[_-]?key|auth)\b(\s*[:=]\s*)(\S+)"),
     r"\1\2…"),
    (re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}"), r"\1 …"),
    (re.compile(r"\b(gh[pousr]_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9_-]{20,}|AKIA[A-Z0-9]{16})\b"), "…"),
    (re.compile(r"(https?://[^/\s:@]+:)[^@\s/]+@"), r"\1…@"),
]
PARTIAL = (".part", ".crdownload", ".download", ".tmp", ".partial", ".!qb", ".opdownload")

DEFAULTS = {"enabled": True, "explain": True, "notify_ok": True, "gamemode_pause": True, "web": True,
            "url_min_minutes": 15}
SETTING_KINDS = {"enabled": "bool", "explain": "bool", "notify_ok": "bool", "gamemode_pause": "bool",
                 "web": "bool", "url_min_minutes": (5, 1440)}

CATEGORIES = {
    "Images": "jpg jpeg png gif webp svg heic heif bmp tif tiff avif raw cr2 nef arw dng ico",
    "Documents": "pdf doc docx odt rtf txt md xls xlsx ods csv ppt pptx odp epub djvu",
    "Archives": "zip tar gz tgz bz2 xz 7z rar zst lz4",
    "Audio": "mp3 flac wav ogg opus m4a aac wma",
    "Video": "mp4 mkv webm mov avi m4v wmv flv",
    "Installers": "rpm deb appimage flatpakref flatpak exe msi dmg iso img",
    "Code": "py js ts json html css c cpp h hpp rs go java ipynb lua sql yaml yml toml xml",
    "DICOM": "dcm dicom",
    "Fonts": "ttf otf woff woff2",
}
EXT_CATEGORY = {ext: cat for cat, exts in CATEGORIES.items() for ext in exts.split()}

# type -> {"params": {name: (kind, required, default, hint)}, "schedules": the
# kinds it may have, "schedule": its default, "heavy": waits for gamemode to end,
# "words": what it does}. Kinds: command, dir, readdir, file, tidydir, unit, url,
# text, regex, glob, choice:a|b, int:lo:hi, number, bool, pid.
TYPES = {
    "watch-command": {
        "params": {"command": ("command", True, None, "the command, exactly as you would type it"),
                   "cwd": ("dir", False, "~", "the folder it runs in (in your home)"),
                   "lines": ("int:10:200", False, TAIL_LINES, "how many last lines the cause is read from")},
        "schedules": ("once", "every", "at", "event", "manual"), "schedule": "once", "heavy": True,
        "words": "run `{command}` in {cwd} and tell you if it fails, with the cause"},
    "watch-file": {
        "params": {"path": ("file", True, None, "the log file to follow"),
                   "pattern": ("regex", False, ERRORS, "a line matching this is a problem"),
                   "lines": ("int:10:200", False, TAIL_LINES, "how many lines before it the cause is read from")},
        "schedules": ("watch",), "schedule": "watch", "heavy": False,
        "words": "follow {path} and tell you when a line looks like a problem, with the cause"},
    "watch-unit": {
        "params": {"unit": ("unit", True, None, "a systemd unit, e.g. backup.service"),
                   "scope": ("choice:user|system", False, "user", "your units or the system's"),
                   "lines": ("int:10:200", False, TAIL_LINES, "how many journal lines the cause is read from")},
        "schedules": ("watch",), "schedule": "watch", "heavy": False,
        "words": "watch the {scope} unit {unit} and tell you when it fails, with the cause"},
    "watch-process": {
        "params": {"pid": ("pid", True, None, "the process id"),
                   "started": ("int:0:999999999999", False, 0, "its start time (guards against a reused id)"),
                   "label": ("text", False, "", "what it is, in words")},
        "schedules": ("watch",), "schedule": "watch", "heavy": False,
        "words": "tell you when {label} ends"},
    "watch-url": {
        "params": {"url": ("url", True, None, "the page, http:// or https://"),
                   "selector": ("text", False, "", "CSS-ish: .price, #total, span.amount, meta[itemprop=price]"),
                   "pattern": ("regex", False, "", "or a pattern; its first group is the value"),
                   "find": ("text", False, "", "or, in words, what the worker model should read off the page"),
                   "when": ("choice:changes|drops|rises|below|above", False, "changes", "when to tell you"),
                   "threshold": ("number", False, None, "for below / above")},
        "schedules": ("every", "at", "event", "manual"), "schedule": "every 1h", "heavy": False,
        "words": "check {host}{what} and tell you when it {when}"},
    "organise-folder": {
        "params": {"folder": ("tidydir", True, None, "the folder to tidy, e.g. ~/Downloads"),
                   "by": ("choice:type|month", False, "type", "sub-folders by file type or by month"),
                   "older_than_days": ("int:0:365", False, 1, "leave newer files where they are")},
        "schedules": ("at", "every", "event", "manual"), "schedule": "daily 03:00", "heavy": True,
        "words": "plan a tidy of {folder} into sub-folders by {by}, for you to approve"},
    "summarise-folder": {
        "params": {"folder": ("readdir", True, None, "the folder, e.g. ~/logs"),
                   "pattern": ("glob", False, "*.log", "which files, e.g. *.log"),
                   "max_files": ("int:1:50", False, 20, "at most this many files a run")},
        "schedules": ("at", "every", "event", "manual"), "schedule": "daily 08:00", "heavy": True,
        "words": "sum up what changed in {folder}/{pattern}"},
    # Built in: health.py makes the one task of this type ("health-checkup")
    # and Settings > Desktop health edits it; not offered in BY HAND (catalog()).
    "nightly-checkup": {
        "params": {},
        "schedules": ("at", "every", "event", "manual"), "schedule": "daily 03:30", "heavy": True,
        "words": "check the desktop's health (journals, failed units, crashes, disk, caches) and fix or "
                 "explain what it finds"},
}
WATCHERS = ("watch-file", "watch-unit", "watch-process")
BUILTIN_TYPES = ("nightly-checkup",)

DOC = [
    "Background tasks: tasks.py's docstring has everything; `tasks.py catalog` lists the types and",
    "their options, `tasks.py check` validates this file. A task: {id, name, type, params, schedule, enabled}.",
    "Schedules: watch | once | every 30m|2h|1d | daily HH:MM | weekdays HH:MM | mon,thu HH:MM | on-event | manual.",
    "Keys starting with _ are ignored. Settings > Background tasks edits this file too.",
]


def log(text):
    print(f"tasks: {redact(str(text))}", flush=True)


def _module(name, filename):
    mod = sys.modules.get(name)
    if mod is None:
        spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, filename))
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
    return mod


def worker():
    return _module("llm_worker", "llm-worker.py")


def run(*cmd, timeout=10):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def redact(text):
    for pattern, repl in SECRET_LINE:
        text = pattern.sub(repl, text)
    return text


def expand(path):
    """~ -> HOME (this module's, which the tests point elsewhere)."""
    path = str(path)
    return HOME + path[1:] if path == "~" or path.startswith("~/") else path


def tilde(path):
    path = str(path)
    return "~" + path[len(HOME):] if path == HOME or path.startswith(HOME + os.sep) else path


def inside(path, root):
    path, root = os.path.realpath(path), os.path.realpath(root)
    return path == root or path.startswith(root.rstrip(os.sep) + os.sep)


def looks_secret(path):
    try:
        return worker().looks_secret(path)
    except Exception:       # llm-worker.py missing: be careful by name alone
        return bool(re.search(r"secret|credential|password|token|\.ssh|\.gnupg|\.env|\.pem$|\.key$",
                              path, re.I))


def in_git_tree(path):
    path = os.path.realpath(path)
    while True:
        if os.path.exists(os.path.join(path, ".git")):
            return True
        parent = os.path.dirname(path)
        if parent == path:
            return False
        path = parent


# -- schedules ----------------------------------------------------------------------------
def parse_days(text):
    """"weekdays" / "mon,wed" -> "024"-style digits; ValueError says why not."""
    text = text.strip().lower()
    if text in DAY_WORDS:
        return DAY_WORDS[text]
    out = []
    for word in re.split(r"[,\s]+", text):
        if word[:3] not in DAY_NAMES:
            raise ValueError(f"{word!r} is not a day")
        out.append(str(DAY_NAMES.index(word[:3])))
    return "".join(sorted(set(out)))


def parse_schedule(text):
    """The schedule string -> {"kind": watch|once|every|at|event|manual, ...};
    ValueError says why not."""
    if not isinstance(text, str) or not text.strip():
        raise ValueError("needs a schedule")
    t = " ".join(text.strip().lower().split())
    if t in ("watch", "once", "manual"):
        return {"kind": t}
    if t in ("on-event", "event", "on event"):
        return {"kind": "event"}
    m = re.fullmatch(r"every (\d+) ?(m|min|mins|minutes?|h|hours?|d|days?)", t)
    if m:
        unit = {"m": 60, "h": 3600, "d": 86400}[m.group(2)[0]]
        seconds = int(m.group(1)) * unit
        if seconds < MIN_EVERY_S:
            raise ValueError(f"every {MIN_EVERY_S // 60} minutes at the most often")
        if seconds > 30 * 86400:
            raise ValueError("every 30 days at the least often")
        return {"kind": "every", "seconds": seconds}
    m = re.fullmatch(r"(?:at )?(.*?)\s*(?:at )?(\d{1,2}:\d{2})", t)
    if m:
        hm = HM.match(m.group(2))
        if not hm:
            raise ValueError("the time is HH:MM (24 h)")
        days = parse_days(m.group(1) or "daily")
        if not days:
            raise ValueError("needs at least one day")
        return {"kind": "at", "at": f"{int(hm.group(1)):02d}:{hm.group(2)}", "days": days}
    raise ValueError("is watch, once, every 30m|2h|1d, daily HH:MM, weekdays HH:MM, mon,thu HH:MM, "
                     "on-event or manual")


def schedule_text(s):
    """The tidy string for a parsed schedule (what tasks.json keeps)."""
    if s["kind"] == "event":
        return "on-event"
    if s["kind"] == "every":
        n = s["seconds"]
        return f"every {n // 86400}d" if n % 86400 == 0 else f"every {n // 3600}h" if n % 3600 == 0 \
            else f"every {n // 60}m"
    if s["kind"] == "at":
        word = next((w for w, d in DAY_WORDS.items() if d == s["days"] and "-" not in w and " " not in w), None)
        return f"{word or ','.join(DAY_NAMES[int(d)] for d in s['days'])} {s['at']}"
    return s["kind"]


def schedule_words(s):
    k = s["kind"]
    if k == "every":
        n = s["seconds"]
        if n % 86400 == 0:
            return "every day" if n == 86400 else f"every {n // 86400} days"
        if n % 3600 == 0:
            return "every hour" if n == 3600 else f"every {n // 3600} hours"
        return f"every {n // 60} minutes"
    if k == "at":
        days = {"0123456": "every day", "01234": "on weekdays", "56": "at weekends"}.get(
            s["days"], "on " + ", ".join(DAY_NAMES[int(d)] for d in s["days"]))
        return f"{days} at {s['at']}"
    return {"watch": "all the time", "once": "once, when switched on", "event": "when an automation runs it",
            "manual": "only when you run it"}[k]


def last_moment(s, now):
    """The latest scheduled moment at or before `now` (epoch), for an "at"
    schedule; None when the last week had none."""
    when = datetime.datetime.fromtimestamp(now)
    hh, mm = map(int, s["at"].split(":"))
    for back in range(0, 8):
        day = when - datetime.timedelta(days=back)
        moment = day.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if str(moment.weekday()) in s["days"] and moment <= when:
            return moment.timestamp()
    return None


def due(task, st, now):
    """Should a scheduled task run now? (Watchers, event and manual ones: never.)"""
    try:
        s = parse_schedule(task["schedule"])
    except ValueError:
        return False
    last = st.get("last_run") or 0
    if s["kind"] == "every":
        return not last or now - last >= s["seconds"]
    if s["kind"] == "at":
        moment = last_moment(s, now)
        return moment is not None and moment > max(last, task.get("created") or 0)
    if s["kind"] == "once":     # again after a pause and resume
        return not last or (st.get("resumed") or 0) > last
    return False


# -- checking a task ------------------------------------------------------------------------
def settings(path=None):
    data = read_config(path)
    out = dict(DEFAULTS)
    raw = data.get("settings") if isinstance(data.get("settings"), dict) else {}
    for key, value in raw.items():
        if key in DEFAULTS:
            try:
                out[key] = check_setting(key, value)
            except ValueError:
                pass
    return out


def check_setting(key, value):
    kind = SETTING_KINDS.get(key)
    if kind is None:
        raise ValueError(f"no setting {key!r}: {', '.join(SETTING_KINDS)}")
    if kind == "bool":
        if isinstance(value, bool):
            return value
        if str(value).lower() in ("on", "true", "yes", "1"):
            return True
        if str(value).lower() in ("off", "false", "no", "0"):
            return False
        raise ValueError(f"{key} is on or off")
    lo, hi = kind
    try:
        n = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{key} is a whole number") from None
    if not lo <= n <= hi:
        raise ValueError(f"{key} is {lo}..{hi}")
    return n


def check_path(kind, value):
    path = os.path.realpath(expand(value))
    if kind in ("dir", "readdir", "tidydir"):
        if not os.path.isdir(path):
            raise ValueError(f"{tilde(path)} is not a folder")
    if kind in ("dir", "tidydir") and not inside(path, HOME):
        raise ValueError("must be inside your home folder")
    if kind in ("readdir", "file") and not any(inside(path, r) for r in (HOME, "/var/log", "/tmp")):
        raise ValueError("must be inside your home folder, /var/log or /tmp")
    if kind == "tidydir":
        rel = os.path.relpath(path, HOME)
        if path == os.path.realpath(HOME):
            raise ValueError("is your whole home folder: name one folder in it, like ~/Downloads")
        if any(part.startswith(".") for part in rel.split(os.sep)):
            raise ValueError("is a hidden folder (settings live there): not tidied")
        if in_git_tree(path):
            raise ValueError("is inside a git work tree: moving files would break it")
    if looks_secret(path):
        raise ValueError("looks secret: not touched")
    if kind == "file" and os.path.isdir(path):
        raise ValueError(f"{tilde(path)} is a folder, not a file")
    return tilde(path)


def check_param(kind, value):
    """The param's value, tidied; ValueError says why not."""
    if kind == "bool":
        return check_setting("enabled", value)
    if kind.startswith("int:") or kind == "pid":
        lo, hi = (2, 4194304) if kind == "pid" else map(int, kind.split(":")[1:])
        try:
            n = int(value)
        except (TypeError, ValueError):
            raise ValueError("is a whole number") from None
        if not lo <= n <= hi:
            raise ValueError(f"is {lo}..{hi}")
        return n
    if kind == "number":
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
        n = parse_number(str(value))
        if n is None:
            raise ValueError("is a number")
        return n
    if not isinstance(value, str):
        raise ValueError("must be text")
    value = value.strip()
    if kind.startswith("choice:"):
        choices = kind.split(":", 1)[1].split("|")
        if value.lower() not in choices:
            raise ValueError(f"is one of {', '.join(choices)}")
        return value.lower()
    if kind in ("text", "regex", "glob") and not value:
        return ""
    if not value:
        raise ValueError("must not be empty")
    if "\n" in value or "\0" in value:
        raise ValueError("is one line")
    if len(value) > 500:
        raise ValueError("is longer than 500 characters")
    if kind == "regex":
        try:
            re.compile(value)
        except re.error as err:
            raise ValueError(f"is not a valid pattern ({err})") from None
    elif kind == "glob":
        if "/" in value or ".." in value:
            raise ValueError("is a file pattern like *.log (no folders)")
    elif kind == "unit":
        # The first character is never "-": systemctl / journalctl would read
        # the "unit" as an option ("-Hhost.service": ssh to a host).
        if not re.fullmatch(r"[A-Za-z0-9@_.:\\][A-Za-z0-9@_.:\\-]{0,119}", value):
            raise ValueError("is a unit name like backup.service")
        if not re.search(r"\.(service|timer|socket|mount|path|target|scope)$", value):
            value += ".service"
    elif kind == "url":
        parts = urllib.parse.urlsplit(value)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise ValueError("is an http:// or https:// address")
    elif kind in ("dir", "readdir", "tidydir", "file"):
        value = check_path(kind, value)
    return value


def validate(task):
    """(tidied task, []) or (None, [problems]). Strict: unknown keys, types and
    params are problems."""
    problems = []
    if not isinstance(task, dict):
        return None, ["a task is a JSON object"]
    allowed = {"id", "name", "type", "params", "schedule", "enabled", "created", "source"}
    for key in task:
        if key not in allowed and not str(key).startswith("_"):
            problems.append(f"unknown key {key!r}")
    kind = task.get("type")
    spec = TYPES.get(kind)
    if spec is None:
        return None, problems + [f"type is one of {', '.join(TYPES)}"]
    tid = task.get("id") or ""
    if tid and not ID.match(str(tid)):
        problems.append("id is lowercase letters, digits and -")
    name = task.get("name")
    if not isinstance(name, str) or not name.strip():
        name = kind.replace("-", " ").capitalize()
    params = task.get("params") or {}
    if not isinstance(params, dict):
        return None, problems + ["params is an object"]
    tidy_params = {}
    for key in params:
        if key not in spec["params"] and not str(key).startswith("_"):
            problems.append(f"{kind} has no param {key!r} (it has {', '.join(spec['params'])})")
    for key, (pkind, required, default, _hint) in spec["params"].items():
        value = params.get(key)
        if value is None or value == "":
            if required:
                problems.append(f"{kind} needs params.{key}")
            elif default not in (None, ""):
                tidy_params[key] = check_param(pkind, default) if pkind in ("dir",) else default
            continue
        try:
            tidy_params[key] = check_param(pkind, value)
        except ValueError as err:
            problems.append(f"params.{key} {err}")
    if kind == "watch-url":
        when = tidy_params.get("when", "changes")
        if when in ("below", "above") and tidy_params.get("threshold") is None:
            problems.append(f"watch-url when={when} needs params.threshold")
        if when != "changes" and not any(tidy_params.get(k) for k in ("selector", "pattern", "find")):
            problems.append(f"watch-url when={when} needs a selector, pattern or find to read a number")
    sched = task.get("schedule") or spec["schedule"]
    try:
        s = parse_schedule(sched)
        if s["kind"] not in spec["schedules"]:
            problems.append(f"{kind} runs " + ", ".join({"every": "every N", "at": "at a time",
                                                         "event": "on-event"}.get(k, k)
                                                        for k in spec["schedules"]))
        sched = schedule_text(s)
    except ValueError as err:
        problems.append(f"schedule {err}")
    enabled = task.get("enabled", True)
    if not isinstance(enabled, bool):
        problems.append("enabled is true or false")
    if problems:
        return None, problems
    out = {"id": tid, "name": name.strip()[:80], "type": kind, "params": tidy_params, "schedule": sched,
           "enabled": enabled, "created": task.get("created") or int(time.time())}
    if task.get("source") in ("text", "json", "settings", "window"):
        out["source"] = task["source"]
    return out, []


def url_min_check(task, conf):
    """A watch-url "every" faster than url_min_minutes: the problem, or None."""
    if task["type"] != "watch-url":
        return None
    s = parse_schedule(task["schedule"])
    if s["kind"] == "every" and s["seconds"] < conf["url_min_minutes"] * 60:
        return f"web checks run every {conf['url_min_minutes']} minutes at the most often (Settings)"
    return None


def host(url):
    return urllib.parse.urlsplit(url).hostname or url


def describe(task):
    """The task in words."""
    p = dict(task["params"])
    if task["type"] == "watch-url":
        what = (f" for “{p['find']}”" if p.get("find") else f" ({p['selector']})" if p.get("selector")
                else " (a pattern)" if p.get("pattern") else "")
        when = p.get("when", "changes")
        when = {"changes": "changes", "drops": "drops", "rises": "rises",
                "below": f"goes below {fmt_number(p.get('threshold'))}",
                "above": f"goes above {fmt_number(p.get('threshold'))}"}[when]
        p.update(host=host(p["url"]), what=what, when=when)
    if task["type"] == "watch-process" and not p.get("label"):
        p["label"] = f"process {p.get('pid')}"
    if task["type"] == "watch-command":
        p["command"] = redact(p["command"])
    words = TYPES[task["type"]]["words"]
    for key, value in p.items():
        words = words.replace("{" + key + "}", str(value))
    try:
        when = schedule_words(parse_schedule(task["schedule"]))
    except ValueError:
        when = task["schedule"]
    return f"{words[0].upper()}{words[1:]} -- {when}"


def permissions(task):
    """What the task may touch, in words: the params, read as permissions."""
    p, kind = task["params"], task["type"]
    out = []
    if kind == "watch-command":
        out += [f"runs the command you typed: {redact(p['command'])}", f"in {p.get('cwd', '~')}",
                f"writes its output to {tilde(path_for(task['id'] or 'ID', 'out'))}"]
    elif kind == "watch-file":
        out.append(f"reads {p['path']}")
    elif kind == "watch-unit":
        out.append(f"reads the state and journal of {p.get('scope', 'user')} unit {p['unit']}")
    elif kind == "watch-process":
        out.append(f"looks at whether process {p['pid']} still runs")
    elif kind == "watch-url":
        out.append(f"fetches {p['url']} (only that site, redirects elsewhere refused; "
                   f"{MAX_FETCH // 1_000_000} MB at most)")
    elif kind == "organise-folder":
        out += [f"lists {p['folder']}", f"moves files only within {p['folder']}, after you approve the plan",
                "never deletes, never overwrites; every move can be undone"]
    elif kind == "summarise-folder":
        out.append(f"reads {p['folder']}/{p.get('pattern', '*.log')} (not what looks secret)")
    elif kind == "nightly-checkup":
        out += ["reads your journal and the system's, failed units, crash reports, disk and cache sizes",
                "fixes only from health.py's fixed catalog (restart a failed desktop service, a big cache or "
                "log to the trash / rotated, a generated theme file again), and only the ones switched on "
                "in Settings > Desktop health; the rest it proposes",
                "sends what it does not know to the local worker model (never off this computer)"]
    if kind in ("watch-command", "watch-file", "watch-unit", "summarise-folder") or \
            (kind == "watch-url" and p.get("find")):
        out.append("sends what it read to the local worker model (never off this computer)")
    out.append("notifies you")
    return out


# -- tasks.json ------------------------------------------------------------------------------
def _lock():
    os.makedirs(STATE_DIR, exist_ok=True)
    handle = open(os.path.join(STATE_DIR, ".lock"), "w")
    fcntl.flock(handle, fcntl.LOCK_EX)
    return handle


def read_config(path=None):
    try:
        with open(path or CONFIG) as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def write_config(data, path=None):
    path = path or CONFIG
    data = {"_doc": DOC, "settings": data.get("settings") or {}, "tasks": data.get("tasks") or []}
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    os.replace(tmp, path)


def load(path=None):
    """(good tasks, [(label, problems)])."""
    raw = read_config(path).get("tasks") or []
    good, bad, seen = [], [], set()
    for n, item in enumerate(raw if isinstance(raw, list) else []):
        tidy, problems = validate(item)
        label = (item.get("name") or item.get("id") or f"#{n + 1}") if isinstance(item, dict) else f"#{n + 1}"
        if tidy and (not tidy["id"] or tidy["id"] in seen):
            problems, tidy = ["needs an id of its own"], None
        if problems:
            bad.append((label, problems))
            continue
        seen.add(tidy["id"])
        good.append(tidy)
    return good, bad


def change_config(fn, path=None):
    """fn(data) under the lock, then written (unless it returns False)."""
    with _lock():
        data = read_config(path)
        data.setdefault("tasks", [])
        data.setdefault("settings", {})
        result = fn(data)
        if result is not False:
            write_config(data, path)
        return result


def slug(text, taken):
    base = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "task"
    out, n = base, 2
    while out in taken:
        out, n = f"{base}-{n}", n + 1
    return out


def find(tasks, word):
    word = (word or "").strip()
    return next((t for t in tasks if t["id"] == word), None) or \
        next((t for t in tasks if t["name"].lower() == word.lower()), None)


def add(task, source="json"):
    """Validate and append; returns the saved task (with its id)."""
    task = dict(task, source=task.get("source") or source)
    task.pop("created", None)
    if task.get("type") in BUILTIN_TYPES:
        raise ValueError(f"{task['type']} is built in (Settings > Desktop health), not added")
    tidy, problems = validate(task)
    if problems:
        raise ValueError("; ".join(problems))
    problem = url_min_check(tidy, settings())

    if problem:
        raise ValueError(problem)

    def put(data):
        tasks = [t for t in data["tasks"] if isinstance(t, dict)]
        if len(tasks) >= MAX_TASKS:
            raise ValueError(f"{MAX_TASKS} tasks at most: delete one first")
        taken = {t.get("id") for t in tasks}
        if not tidy["id"] or tidy["id"] in taken:
            tidy["id"] = slug(tidy["name"], taken)
        data["tasks"].append(tidy)
    change_config(put)
    append_log(tidy["id"], f"added ({tidy.get('source', 'json')}): {describe(tidy)}")
    return tidy


def set_enabled(tid, on):
    def flip(data):
        for t in data["tasks"]:
            if isinstance(t, dict) and t.get("id") == tid:
                t["enabled"] = bool(on)
                return True
        return False
    return change_config(flip)


def remove(tid):
    def drop(data):
        before = len(data["tasks"])
        data["tasks"] = [t for t in data["tasks"] if not (isinstance(t, dict) and t.get("id") == tid)]
        return len(data["tasks"]) != before or False
    if change_config(drop) is False:
        return False
    for ext in ("json", "log", "out", "plan.json", "report.txt"):
        try:
            os.remove(path_for(tid, ext))
        except OSError:
            pass
    # The undo log stays: moves already made can still be put back by hand.
    signal_bar()
    return True


def set_setting(key, value):
    value = check_setting(key, value)

    def put(data):
        data["settings"][key] = value
    change_config(put)
    signal_bar()
    return value


# -- per-task state and log ------------------------------------------------------------------
def path_for(tid, ext):
    os.makedirs(STATE_DIR, exist_ok=True)
    return os.path.join(STATE_DIR, f"{tid}.{ext}")


def get_state(tid):
    try:
        with open(path_for(tid, "json")) as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def update_state(tid, **changes):
    """Merge changes into the task's state (None removes a key); returns it."""
    with _lock():
        st = get_state(tid)
        for key, value in changes.items():
            if value is None:
                st.pop(key, None)
            else:
                st[key] = value
        tmp = path_for(tid, f"json.{os.getpid()}.tmp")
        with open(tmp, "w") as handle:
            json.dump(st, handle)
        os.replace(tmp, path_for(tid, "json"))
    return st


def append_log(tid, text, now=None):
    os.makedirs(STATE_DIR, exist_ok=True)
    stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now or time.time()))
    path = path_for(tid, "log")
    with open(path, "a") as handle:
        for n, line in enumerate(redact(text).splitlines() or [""]):
            handle.write(f"{stamp}  {line}\n" if n == 0 else f"{' ' * len(stamp)}  {line}\n")
    try:
        if os.path.getsize(path) > LOG_KEEP * 200:
            with open(path) as handle:
                lines = handle.readlines()[-LOG_KEEP:]
            with open(path, "w") as handle:
                handle.writelines(lines)
    except OSError:
        pass


def read_log(tid, n=40):
    try:
        with open(path_for(tid, "log")) as handle:
            return handle.readlines()[-n:]
    except OSError:
        return []


def tail(text, n):
    lines = [l.rstrip() for l in text.splitlines()]
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines[-n:])


def read_tail(path, n, max_bytes=256_000):
    try:
        with open(path, "rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - max_bytes))
            raw = handle.read()
    except OSError:
        return ""
    return tail(re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", raw.decode("utf-8", errors="replace")), n)


def attention_count():
    good, _ = load()
    return sum(1 for t in good if get_state(t["id"]).get("attention"))


def signal_bar():
    run("pkill", f"-RTMIN+{SIGNAL}", "-x", "waybar", timeout=3)


def set_attention(tid, text):
    text = redact(text or "")
    if len(text) > 400:
        text = text[:400].rsplit(" ", 1)[0] + "…"
    update_state(tid, attention={"text": text, "since": int(time.time())} if text else None)
    signal_bar()


# -- notifications ---------------------------------------------------------------------------
def notify(summary, body, actions=None, urgency="normal"):
    """A notification; with actions ({key: label}) it waits for a click in a
    thread and runs open_action(key)."""
    argv = ["notify-send", "-a", APP, "-i", ICON, "-u", urgency]
    if actions:
        argv.append("--wait")
        for key, label in actions.items():
            argv += ["-A", f"{key}={label}"]
    argv += [redact(summary), redact(body)[:900]]
    if not actions:
        run(*argv, timeout=5)
        return

    def wait():
        try:
            picked = subprocess.run(argv, capture_output=True, text=True, timeout=3600).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return
        if picked:
            open_action(picked)
    threading.Thread(target=wait, daemon=True).start()


def open_action(key):
    if key in ("review", "settings", "default"):
        subprocess.Popen([sys.executable, SETTINGS_PY, "tasks"], start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    elif key.startswith("open:"):
        subprocess.Popen(["xdg-open", key[5:]], start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# -- the model (local only) --------------------------------------------------------------------
EXPLAIN = ("You read the end of a failed program's output or a log and explain the failure to a developer. "
           "Answer in at most three short sentences: the cause, then the likely fix. Quote the decisive "
           "error line. Say plainly when the lines do not show the cause. No preamble.")
SUMMARY = ("You sum up log files for a developer's morning: what happened, what failed, what needs a look. "
           "Short bullet points per file, most important first; say 'nothing notable' when that is so. "
           "No preamble.")
EXTRACT = ("You read one value off a web page's text. Answer with the value only, exactly as written on "
           "the page (a number with its currency or unit, or a short phrase), or NONE when it is not there.")


def gamemode_on():
    try:
        return _module("llm_models", "llm_models.py")._gamemode_on()
    except Exception:
        return False


def ai_may_read(path, folder=None):
    """(ok, why): may a file's text go to the model (folder_access.py)? The
    task's own `folder` (default: the file's) counts as granted."""
    try:
        fa = _module("folder_access", "folder_access.py")
        folder = folder or fa.folder_of(path)
        verdict, why = fa.decide(path, "tasks", implied=[folder])
    except Exception as err:        # noqa: BLE001 -- unsure is a no
        return False, f"folder access could not be checked ({err})"
    if verdict == "allow":
        return True, why
    return False, f"{fa.tilde(fa.folder_of(path))} is not open to AI ({why}; Settings > Privacy > Folder access)"


def model_answer(prompt, system, conf=None):
    """(answer, by) from the worker model, or (None, why it could not)."""
    conf = conf or settings()
    if not conf["explain"]:
        return None, "the model is off (Settings > Background tasks)"
    try:
        w = worker()
        model, why = w.ready("worker")
        if model is None:
            return None, why.removesuffix(": do the job yourself")
        return w.ask(model, prompt, system=system), model.name
    except Exception as err:        # the server, a timeout
        return None, f"the local model did not answer ({err})"


def plain_cause(text, pattern=ERRORS):
    """The fallback "cause": the last lines that look like errors."""
    rx = re.compile(pattern)
    hits = [l.strip() for l in text.splitlines() if rx.search(l)]
    lines = hits[-3:] or [l.strip() for l in text.splitlines() if l.strip()][-3:]
    return "\n".join(lines) or "(no output)"


def headline(cause, by):
    """The one line of a cause for the bar: the model's first, the plain lines' last (newest)."""
    lines = [l for l in cause.splitlines() if l.strip()] or [""]
    return (lines[-1] if by.startswith("plain") else lines[0])[:200]


def explain(what, text, conf=None, pattern=ERRORS, read_from=None):
    """(cause in words, by whom): the worker model's, or the plain lines.
    `read_from`: the file the text came from (watch-file), whose folder must
    be open to AI (ai_may_read) before the model sees it."""
    ok, why = ai_may_read(read_from) if read_from else (True, "")
    if not ok:
        return plain_cause(text, pattern), f"plain lines -- {why}"
    answer, by = model_answer(f"{redact(what)}\n\n=== last lines ===\n{redact(text)[-MAX_PROMPT:]}", EXPLAIN, conf)
    if answer:
        return answer.strip(), by
    return plain_cause(text, pattern), f"plain lines -- {by}"


# -- web pages ---------------------------------------------------------------------------------
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source",
        "track", "wbr"}


class Node:
    __slots__ = ("tag", "attrs", "children", "parent", "text")

    def __init__(self, tag, attrs, parent):
        self.tag, self.attrs, self.parent, self.children, self.text = tag, attrs, parent, [], []

    def all_text(self):
        parts = list(self.text)
        for c in self.children:
            parts.append(c.all_text())
        return " ".join(p for p in parts if p)


class Tree(html.parser.HTMLParser):
    """A forgiving DOM: enough for a selector, nothing runs."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("#root", {}, None)
        self.cur = self.root
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript", "template"):
            self.skip += 1
            return
        node = Node(tag, {k: (v or "") for k, v in attrs}, self.cur)
        self.cur.children.append(node)
        if tag not in VOID:
            self.cur = node

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript", "template"):
            self.skip = max(0, self.skip - 1)
            return
        node = self.cur
        while node is not self.root and node.tag != tag:
            node = node.parent
        if node is not self.root:
            self.cur = node.parent

    def handle_data(self, data):
        if not self.skip and data.strip():
            self.cur.text.append(" ".join(data.split()))


SIMPLE = re.compile(r"([a-zA-Z][a-zA-Z0-9-]*)?((?:[.#][\w-]+)*)((?:\[[\w:-]+(?:[~*^$]?=[^\]]*)?\])*)$")


def parse_selector(text):
    """"div.price span[itemprop=price]" -> [(tag, ids, classes, attrs)]; ValueError."""
    out = []
    for part in text.split():
        m = SIMPLE.match(part)
        if not m:
            raise ValueError(f"cannot read {part!r} (tag, .class, #id, [attr=value])")
        tag, rest, attrs = m.groups()
        ids = re.findall(r"#([\w-]+)", rest)
        classes = re.findall(r"\.([\w-]+)", rest)
        pairs = []
        for a in re.findall(r"\[([^\]]+)\]", attrs or ""):
            key, op, value = re.match(r"([\w:-]+)(?:([~*^$]?=)(.*))?$", a).groups()
            pairs.append((key, op, (value or "").strip("\"'")))
        out.append(((tag or "").lower(), ids, classes, pairs))
    if not out:
        raise ValueError("is empty")
    return out


def _matches(node, simple):
    tag, ids, classes, pairs = simple
    if tag and node.tag != tag:
        return False
    if ids and node.attrs.get("id") not in ids:
        return False
    have = node.attrs.get("class", "").split()
    if any(c not in have for c in classes):
        return False
    for key, op, value in pairs:
        if key not in node.attrs:
            return False
        got = node.attrs[key]
        if op == "=" and got != value or op == "~=" and value not in got.split() or \
                op == "*=" and value not in got or op == "^=" and not got.startswith(value) or \
                op == "$=" and not got.endswith(value):
            return False
    return True


def _walk(node):
    for c in node.children:
        yield c
        yield from _walk(c)


def select(html_text, selector):
    """The text of the first element the selector matches (its content=/value=
    when it has no text: meta, input), or None."""
    tree = Tree()
    tree.feed(html_text)
    chain = parse_selector(selector)
    found = [tree.root]
    for simple in chain:
        nxt = []
        for base in found:
            for node in _walk(base):
                if _matches(node, simple) and node not in nxt:
                    nxt.append(node)
        found = nxt
        if not found:
            return None
    node = found[0]
    text = node.all_text().strip()
    return text or node.attrs.get("content") or node.attrs.get("value") or None


def page_text(html_text):
    tree = Tree()
    tree.feed(html_text)
    return " ".join(tree.root.all_text().split())


def parse_number(text):
    """The first number in text, reading 1,299.00 / 1.299,00 / 1 299 / 12,5; None."""
    if text is None:
        return None
    m = re.search(r"-?\d[\d.,   ]*\d|-?\d", str(text))
    if not m:
        return None
    s = re.sub(r"[   ]", "", m.group(0))
    if "," in s and "." in s:
        dec = "," if s.rfind(",") > s.rfind(".") else "."
        s = s.replace("." if dec == "," else ",", "").replace(",", ".")
    elif "," in s:
        head, _, last = s.rpartition(",")
        s = s.replace(",", "") if len(last) == 3 and s.count(",") >= 1 and head else s.replace(",", ".")
    elif s.count(".") > 1:
        s = s.replace(".", "")
    try:
        return float(s)
    except ValueError:
        return None


def fmt_number(n):
    if n is None:
        return "?"
    return f"{n:,.2f}".rstrip("0").rstrip(".") if n != int(n) else f"{int(n):,}"


def same_site(a, b):
    """Two host names, read as one site ("www." aside)."""
    strip = lambda h: (h or "").lower().removeprefix("www.")
    return strip(a) == strip(b)


class SameSiteRedirects(urllib.request.HTTPRedirectHandler):
    """Follow a redirect only within the task's site, over http/https: its
    permission is that address, not wherever the page sends it."""

    def __init__(self, url):
        super().__init__()
        self.host = urllib.parse.urlsplit(url).hostname

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        newurl = urllib.parse.urljoin(req.full_url, newurl)
        parts = urllib.parse.urlsplit(newurl)
        if parts.scheme not in ("http", "https") or not same_site(parts.hostname, self.host):
            raise urllib.error.URLError(f"it redirects to another site ({parts.hostname}): not followed")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) tasks.py",
                                               "Accept": "text/html,application/xhtml+xml,*/*;q=0.5"})
    opener = urllib.request.build_opener(SameSiteRedirects(url))
    with opener.open(req, timeout=FETCH_TIMEOUT) as resp:
        raw = resp.read(MAX_FETCH + 1)
        charset = resp.headers.get_content_charset() or "utf-8"
    if len(raw) > MAX_FETCH:
        raw = raw[:MAX_FETCH]
    return raw.decode(charset, errors="replace")


def read_value(p, html_text, conf=None):
    """(value text, None) or (None, why)."""
    if p.get("selector"):
        try:
            value = select(html_text, p["selector"])
        except ValueError as err:
            return None, f"selector {err}"
        return (value, None) if value else (None, f"nothing on the page matches {p['selector']!r}")
    if p.get("pattern"):
        m = re.search(p["pattern"], html_text, re.S)
        if not m:
            m = re.search(p["pattern"], page_text(html_text), re.S)
        if not m:
            return None, "the pattern finds nothing on the page"
        return (m.group(1) if m.groups() else m.group(0)).strip(), None
    if p.get("find"):
        answer, by = model_answer(f"Read off: {p['find']}\n\n=== page text ===\n{page_text(html_text)[:MAX_PROMPT]}",
                                  EXTRACT, conf)
        if not answer:
            return None, f"the model could not read it: {by}"
        answer = answer.strip().splitlines()[0][:200]
        return (None, "the model did not find it on the page") if answer.upper() == "NONE" else (answer, None)
    text = page_text(html_text)
    return hashlib.sha256(text.encode()).hexdigest()[:16] + " " + text[:160], None


def compare(when, old, new, threshold=None):
    """(tell?, words) for a watch-url value going from old to new."""
    if when == "changes":
        if old is None or old == new:
            return False, ""
        return True, "changed"
    a, b = parse_number(old), parse_number(new)
    if b is None:
        return False, ""
    if when in ("below", "above"):
        crossed_now = b < threshold if when == "below" else b > threshold
        crossed_before = a is not None and (a < threshold if when == "below" else a > threshold)
        return (crossed_now and not crossed_before), f"is {when} {fmt_number(threshold)}: {fmt_number(b)}"
    if a is None:
        return False, ""
    if when == "drops" and b < a:
        return True, f"dropped from {fmt_number(a)} to {fmt_number(b)}"
    if when == "rises" and b > a:
        return True, f"rose from {fmt_number(a)} to {fmt_number(b)}"
    return False, ""


# -- tidying a folder ---------------------------------------------------------------------------
def unique(path, taken=()):
    if not os.path.lexists(path) and path not in taken:
        return path
    base, ext = os.path.splitext(path)
    n = 2
    while os.path.lexists(f"{base} ({n}){ext}") or f"{base} ({n}){ext}" in taken:
        n += 1
    return f"{base} ({n}){ext}"


def make_plan(p, now=None):
    """The moves a tidy would make: [{"from", "to"}] (absolute paths). Only
    plain files directly in the folder, not hidden, not half-downloaded,
    older than older_than_days; files of no known type stay where they are."""
    folder = os.path.realpath(expand(p["folder"]))
    now = now or time.time()
    age = p.get("older_than_days", 1) * 86400
    moves, taken = [], set()
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        return []
    for name in names:
        src = os.path.join(folder, name)
        low = name.lower()
        if name.startswith(".") or low.endswith(PARTIAL) or os.path.islink(src) or not os.path.isfile(src):
            continue
        try:
            mtime = os.path.getmtime(src)
        except OSError:
            continue
        if now - mtime < age:
            continue
        if p.get("by", "type") == "month":
            sub = time.strftime("%Y-%m", time.localtime(mtime))
        else:
            ext = low.rsplit(".", 1)[-1] if "." in low else ""
            if low.endswith((".tar.gz", ".tar.xz", ".tar.zst", ".tar.bz2")):
                ext = "tar"
            sub = EXT_CATEGORY.get(ext)
            if not sub:
                continue
        dest_dir = os.path.join(folder, sub)
        if os.path.exists(dest_dir) and not os.path.isdir(dest_dir):
            continue
        dest = unique(os.path.join(dest_dir, name), taken)
        taken.add(dest)
        moves.append({"from": src, "to": dest})
    return moves


def safe_move(src, dest, folder):
    """Move one file within `folder` (never across it, never over a file);
    the path it landed at, or raise OSError / ValueError."""
    if not (inside(src, folder) and inside(os.path.dirname(dest), folder) and inside(folder, HOME)):
        raise ValueError("outside the folder")
    if not os.path.isfile(src) or os.path.islink(src):
        raise ValueError("no longer there")
    dest = unique(dest)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    os.rename(src, dest)        # same folder tree: a rename, never a copy-and-delete
    return dest


def approve(task):
    """Make the planned moves; (moved, [problems])."""
    plan = read_plan(task["id"])
    if not plan:
        return 0, ["no plan waiting"]
    folder = os.path.realpath(expand(task["params"]["folder"]))
    batch, moved, problems = int(time.time()), 0, []
    with open(path_for(task["id"], "undo.jsonl"), "a") as undo:
        for mv in plan["moves"]:
            try:
                landed = safe_move(mv["from"], mv["to"], folder)
            except (OSError, ValueError) as err:
                problems.append(f"{os.path.basename(mv['from'])}: {getattr(err, 'strerror', None) or err}")
                continue
            undo.write(json.dumps({"batch": batch, "from": mv["from"], "to": landed}) + "\n")
            moved += 1
    discard_plan(task["id"])
    append_log(task["id"], f"approved: moved {moved} file{'s' if moved != 1 else ''}"
               + (f"; skipped {len(problems)}: " + "; ".join(problems[:5]) if problems else ""))
    return moved, problems


def undo(task):
    """Put the last approved batch back; (moved back, [problems])."""
    path = path_for(task["id"], "undo.jsonl")
    try:
        with open(path) as handle:
            entries = [json.loads(l) for l in handle if l.strip()]
    except (OSError, ValueError):
        return 0, ["nothing to undo"]
    if not entries:
        return 0, ["nothing to undo"]
    batch = entries[-1]["batch"]
    folder = os.path.realpath(expand(task["params"]["folder"]))
    back, problems = 0, []
    for e in reversed([e for e in entries if e["batch"] == batch]):
        try:
            if os.path.lexists(e["from"]):
                raise ValueError("a file has its old name now")
            safe_move(e["to"], e["from"], folder)
            back += 1
        except (OSError, ValueError) as err:
            problems.append(f"{os.path.basename(e['to'])}: {getattr(err, 'strerror', None) or err}")
    with open(path, "w") as handle:
        for e in entries:
            if e["batch"] != batch:
                handle.write(json.dumps(e) + "\n")
    append_log(task["id"], f"undo: put back {back}" + (f"; could not: {'; '.join(problems[:5])}" if problems else ""))
    return back, problems


def read_plan(tid):
    try:
        with open(path_for(tid, "plan.json")) as handle:
            plan = json.load(handle)
        return plan if isinstance(plan, dict) and plan.get("moves") else None
    except (OSError, ValueError):
        return None


def discard_plan(tid):
    try:
        os.remove(path_for(tid, "plan.json"))
    except OSError:
        pass
    st = get_state(tid)
    if (st.get("attention") or {}).get("plan"):
        update_state(tid, attention=None)
        signal_bar()


def has_undo(tid):
    try:
        return os.path.getsize(path_for(tid, "undo.jsonl")) > 0
    except OSError:
        return False


# -- the jobs ----------------------------------------------------------------------------------
def finish(task, ok, summary, body="", attention=None, conf=None, actions=None, quiet=False):
    """Log, state, notification and the bar's attention for one outcome."""
    tid = task["id"]
    append_log(tid, f"{summary}" + (f"\n{body}" if body else ""))
    update_state(tid, last_run=int(time.time()), last_result="ok" if ok else "failed",
                 last_summary=redact(summary)[:300])
    if attention:
        set_attention(tid, attention)
    if not quiet:
        notify(f"{task['name']}: {summary}", body, actions=actions or ({"review": "Open tasks"} if not ok else None),
               urgency="normal" if ok else "critical" if attention else "normal")


def job_url(task, conf):
    if not conf["web"]:
        append_log(task["id"], "skipped: web checks are off (Settings > Background tasks)")
        update_state(task["id"], last_run=int(time.time()), last_result="skipped")
        return
    p, tid = task["params"], task["id"]
    try:
        page = fetch(p["url"])
    except (OSError, urllib.error.URLError, ValueError) as err:
        reason = getattr(err, "reason", None) or err
        append_log(tid, f"could not fetch {host(p['url'])}: {reason}")
        update_state(tid, last_run=int(time.time()), last_result="failed",
                     last_summary=f"could not fetch: {reason}"[:300])
        return
    value, why = read_value(p, page, conf)
    if value is None:
        finish(task, False, "could not read the value", why, attention=f"could not read the value: {why}")
        return
    st = get_state(tid)
    old = st.get("last_value")
    tell, words = compare(p.get("when", "changes"), old, value, p.get("threshold"))
    shown = value if p.get("when") != "changes" or p.get("selector") or p.get("pattern") or p.get("find") \
        else "the page"
    update_state(tid, last_value=value, last_run=int(time.time()), last_result="ok",
                 last_summary=f"{shown[:120]}" + (f" ({words})" if tell else ""))
    append_log(tid, f"{host(p['url'])}: {value[:200]}" + (f" -- {words}" if tell else
                                                          " (first reading)" if old is None else ""))
    if tell:
        notify(f"{task['name']}: {words}", f"{host(p['url'])}: {value[:200]}",
               actions={f"open:{p['url']}": "Open the page"})


def job_organise(task, conf):
    moves = make_plan(task["params"])
    tid = task["id"]
    if not moves:
        discard_plan(tid)
        update_state(tid, last_run=int(time.time()), last_result="ok", last_summary="nothing to tidy")
        append_log(tid, "nothing to tidy")
        return
    plan = {"made": int(time.time()), "folder": task["params"]["folder"], "moves": moves}
    tmp = path_for(tid, "plan.json.tmp")
    with open(tmp, "w") as handle:
        json.dump(plan, handle, indent=1)
    os.replace(tmp, path_for(tid, "plan.json"))
    counts = collections.Counter(os.path.basename(os.path.dirname(m["to"])) for m in moves)
    body = ", ".join(f"{n} → {sub}" for sub, n in counts.most_common(6))
    summary = f"{len(moves)} move{'s' if len(moves) != 1 else ''} planned, waiting for your OK"
    append_log(tid, f"{summary}: {body}")
    update_state(tid, last_run=int(time.time()), last_result="plan", last_summary=summary,
                 attention={"text": f"{summary} ({body})", "since": int(time.time()), "plan": True})
    signal_bar()
    notify(f"{task['name']}: {summary}", body + "\nNothing moves until you approve it.",
           actions={"review": "Review the plan"})


def read_recent(path, max_bytes=60_000):
    """(the file's last max_bytes as text, None) or (None, why not)."""
    if looks_secret(path):
        return None, "looks secret: not read"
    try:
        with open(path, "rb") as handle:
            head = handle.read(4096)
            if b"\0" in head:
                return None, "binary: not read"
            handle.seek(0, os.SEEK_END)
            handle.seek(max(0, handle.tell() - max_bytes))
            raw = handle.read()
    except OSError as err:
        return None, err.strerror or str(err)
    return raw.decode("utf-8", errors="replace"), None


def job_summarise(task, conf):
    p, tid = task["params"], task["id"]
    folder = os.path.realpath(expand(p["folder"]))
    st = get_state(tid)
    since = st.get("until") or (time.time() - 86400)
    started = time.time()      # what changes while this runs is next time's
    files = []
    for path in glob.glob(os.path.join(glob.escape(folder), p.get("pattern") or "*.log")):
        try:
            if os.path.isfile(path) and os.path.getmtime(path) > since and not looks_secret(path):
                files.append((os.path.getmtime(path), path))
        except OSError:
            continue
    files = [f for _, f in sorted(files, reverse=True)[:p.get("max_files", 20)]]
    update_state(tid, until=started)
    if not files:
        update_state(tid, last_run=int(time.time()), last_result="ok", last_summary="nothing changed")
        append_log(tid, "nothing changed since the last run")
        return
    parts, plain = [], []
    rx = re.compile(ERRORS)
    for path in files:
        new, why = read_recent(path)
        if why:
            plain.append(f"{os.path.basename(path)}: {why}")
            continue
        errs = [l.strip() for l in new.splitlines() if rx.search(l)]
        warns = sum(1 for l in new.splitlines() if WARNINGS.search(l))
        plain.append(f"{os.path.basename(path)}: {len(errs)} error lines, {warns} warnings"
                     + ("".join(f"\n    {e[:160]}" for e in errs[-3:])))
        parts.append(f"=== {os.path.basename(path)} ===\n{tail(new, 150)}")
    share = MAX_PROMPT // max(1, len(parts))
    may, why = ai_may_read(folder, folder)
    if not may:
        answer, by = None, why
    else:
        answer, by = model_answer("\n\n".join(redact(x[-share:]) for x in parts), SUMMARY, conf) if parts \
            else (None, "nothing readable")
    report = (answer.strip() + f"\n\n(by {by}, local)") if answer else \
        ("\n".join(plain) + f"\n\n(plain counts: {by})")
    head = f"{len(files)} file{'s' if len(files) != 1 else ''} in {p['folder']} -- " + time.strftime("%Y-%m-%d %H:%M")
    with open(path_for(tid, "report.txt"), "w") as handle:
        handle.write(redact(head + "\n\n" + report + "\n"))
    finish(task, True, f"summed up {len(files)} file{'s' if len(files) != 1 else ''}", report[:600], conf=conf,
           actions={f"open:{path_for(tid, 'report.txt')}": "Open the summary"})


def command_failed(task, rc, elapsed, conf):
    p = task["params"]
    text = read_tail(path_for(task["id"], "out"), p.get("lines", TAIL_LINES))
    cause, by = explain(f"The command `{p['command']}` exited with status {rc} after {dur(elapsed)}.", text, conf)
    finish(task, False, f"failed (exit {rc}) after {dur(elapsed)}", f"{cause}\n\n({by})",
           attention=f"failed (exit {rc}): {headline(cause, by)}", conf=conf)


def dur(seconds):
    seconds = int(seconds)
    if seconds < 90:
        return f"{seconds} s"
    if seconds < 5400:
        return f"{seconds // 60} min"
    return f"{seconds // 3600} h {seconds % 3600 // 60:02d} min"


def job_checkup(task, conf):
    """health.py's checkup, in its own process (it notifies by itself)."""
    try:
        done = subprocess.run([sys.executable, os.path.join(HERE, "health.py"), "run", "--by", "tasks",
                               "--summary"], capture_output=True, text=True, timeout=1800)
        info = json.loads((done.stdout.strip().splitlines() or ["{}"])[-1])
    except (OSError, subprocess.SubprocessError, ValueError) as err:
        finish(task, False, "the checkup went wrong", str(err), attention=f"the checkup went wrong: {err}")
        return
    if done.returncode != 0 or "headline" not in info:
        why = (done.stderr.strip().splitlines() or ["no answer"])[-1]
        finish(task, False, "the checkup went wrong", why, attention=f"the checkup went wrong: {why}")
        return
    finish(task, True, info["headline"], quiet=True)


JOBS = {"watch-url": job_url, "organise-folder": job_organise, "summarise-folder": job_summarise,
        "nightly-checkup": job_checkup}


# -- watchers (cheap: called every tick by the daemon) ----------------------------------------
def unit_status(p):
    scope = ["--user"] if p.get("scope", "user") == "user" else []
    out = run("systemctl", *scope, "show", "-p", "ActiveState,Result,NRestarts,LoadState", "--", p["unit"],
              timeout=5)
    return dict(l.split("=", 1) for l in out.splitlines() if "=" in l)


def unit_failed(old, new):
    """(failed?, words) from two `systemctl show` readings."""
    if not old or not new:
        return False, ""
    if new.get("ActiveState") == "failed" and old.get("ActiveState") != "failed":
        return True, f"failed ({new.get('Result', '?')})"
    try:
        if int(new.get("NRestarts", 0)) > int(old.get("NRestarts", 0)):
            return True, f"crashed and was restarted ({new.get('Result', '?')})"
    except ValueError:
        pass
    return False, ""


def journal(p):
    scope = ["--user"] if p.get("scope", "user") == "user" else []
    return run("journalctl", *scope, f"--unit={p['unit']}", "-n", str(p.get("lines", TAIL_LINES)), "--no-pager",
               "-o", "short", timeout=10)


def proc_start(pid):
    """A process's start time (clock ticks since boot), or None when gone."""
    try:
        with open(f"/proc/{pid}/stat") as handle:
            stat = handle.read()
        return int(stat[stat.rfind(")") + 2:].split()[19])
    except (OSError, ValueError, IndexError):
        return None


def proc_name(pid):
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as handle:
            argv = [a.decode(errors="replace") for a in handle.read().split(b"\0") if a]
        return " ".join(argv)[:120] or None
    except OSError:
        return None


def children(pid):
    out = []
    for task in glob.glob(f"/proc/{pid}/task/*/children"):
        try:
            with open(task) as handle:
                out += [int(x) for x in handle.read().split()]
        except (OSError, ValueError):
            pass
    return out


SHELLS = {"bash", "zsh", "fish", "sh", "dash", "nu", "xonsh", "tmux: server", "tmux"}


def comm(pid):
    try:
        with open(f"/proc/{pid}/comm") as handle:
            return handle.read().strip()
    except OSError:
        return ""


def foreground_job(window_pid):
    """The newest job a shell under the terminal's process runs, or None."""
    jobs = []
    stack = [window_pid]
    seen = set()
    while stack:
        pid = stack.pop()
        if pid in seen:
            continue
        seen.add(pid)
        for child in children(pid):
            if comm(pid) in SHELLS and comm(child) not in SHELLS:
                jobs.append(child)
            else:
                stack.append(child)
    jobs = [(proc_start(j) or 0, j) for j in jobs]
    return max(jobs)[1] if jobs else None


# -- the daemon --------------------------------------------------------------------------------
class Daemon:
    def __init__(self):
        self.jobs = queue.Queue()
        self.queued = set()
        self.running = {}           # task id -> (Popen, started, out handle)  (watch-command)
        self.busy = None            # the task the worker thread is on
        self.watch = {}             # task id -> watcher memory (offsets, unit readings...)
        self.mtime = None
        self.tasks, self.conf = [], dict(DEFAULTS)
        self.game = (0, False)
        self.written = None
        self.stop = False

    # -- reading
    def reload(self):
        try:
            mtime = os.path.getmtime(CONFIG)
        except OSError:
            mtime = 0
        if mtime == self.mtime:
            return
        self.mtime = mtime
        self.tasks, bad = load()
        self.conf = settings()
        for label, problems in bad:
            log(f"skipped {label}: {'; '.join(problems)}")
        alive = {t["id"] for t in self.tasks}
        for tid in list(self.watch):
            if tid not in alive:
                self.watch.pop(tid)
        for tid in list(self.running):      # deleted while its command runs: stop it
            if tid not in alive:
                self.kill(tid, quiet=True)
        log(f"{len(self.tasks)} task(s), " + ("on" if self.conf["enabled"] else "switched off"))

    def gamemode(self, now):
        if now - self.game[0] > GAMEMODE_S:
            self.game = (now, gamemode_on())
        return self.game[1]

    def write_state(self):
        data = {"pid": os.getpid(), "running": sorted(self.running), "busy": self.busy,
                "queued": sorted(self.queued), "gamemode": self.game[1], "enabled": self.conf["enabled"]}
        if data == self.written and os.path.exists(DAEMON_STATE):
            return
        self.written = data
        tmp = f"{DAEMON_STATE}.tmp"
        try:
            with open(tmp, "w") as handle:
                json.dump(data, handle)
            os.replace(tmp, DAEMON_STATE)
        except OSError:
            pass

    # -- the loop
    def run(self):
        signal.signal(signal.SIGTERM, lambda *_: setattr(self, "stop", True))
        os.makedirs(POKES, exist_ok=True)
        self.reload()
        self.recover()
        threading.Thread(target=self.work, daemon=True).start()
        log("started")
        while not self.stop:
            now = time.time()
            try:
                self.reload()
                self.pokes()
                self.reap(now)
                if self.conf["enabled"]:
                    self.tick(now)
                else:
                    self.watch.clear()
                self.write_state()
            except Exception as err:        # one bad tick must not end the daemon
                log(f"tick: {err!r}")
            time.sleep(TICK_S)
        for tid, (proc, _, _) in list(self.running.items()):
            log(f"{tid}: its command (pid {proc.pid}) ends with the service")
        try:
            os.remove(DAEMON_STATE)
        except OSError:
            pass

    def pokes(self):
        try:
            names = os.listdir(POKES)
        except OSError:
            return
        for name in names:
            try:
                os.remove(os.path.join(POKES, name))
            except OSError:
                continue
            tid, _, verb = name.rpartition(".")
            if verb == "stop":      # by id, even when the task is already deleted
                self.kill(tid, quiet=find(self.tasks, tid) is None)
                continue
            task = find(self.tasks, tid)
            if task is not None and verb == "run":
                self.start(task, by="asked")

    def tick(self, now):
        game = self.gamemode(now) and self.conf["gamemode_pause"]
        for task in self.tasks:
            if not task["enabled"]:
                self.watch.pop(task["id"], None)    # back on: only what is new from then
                continue
            tid, kind = task["id"], task["type"]
            try:
                if kind == "watch-file":
                    self.check_file(task, now)
                elif kind == "watch-unit":
                    self.check_unit(task, now)
                elif kind == "watch-process":
                    self.check_process(task)
                else:
                    st = get_state(tid)
                    if tid in self.running or tid in self.queued or self.busy == tid or not due(task, st, now):
                        continue
                    if game and TYPES[kind]["heavy"]:
                        if st.get("status") != "waiting: gamemode":
                            update_state(tid, status="waiting: gamemode")
                            append_log(tid, "due, waiting for gamemode to end")
                        continue
                    self.start(task, by="schedule")
            except Exception as err:
                log(f"{tid}: {err!r}")

    def start(self, task, by):
        tid = task["id"]
        if tid in self.running or tid in self.queued or self.busy == tid:
            return
        update_state(tid, status=None)
        if task["type"] == "watch-command":
            self.spawn(task, by)
        elif task["type"] in JOBS:
            self.queued.add(tid)
            self.jobs.put((tid, JOBS[task["type"]], (task, self.conf)))
        else:
            append_log(tid, "a watcher: it watches all the time, there is nothing to run")

    def spawn(self, task, by):
        p, tid = task["params"], task["id"]
        os.makedirs(STATE_DIR, exist_ok=True)
        out = open(path_for(tid, "out"), "wb")
        try:
            proc = subprocess.Popen(["sh", "-c", p["command"]], cwd=expand(p.get("cwd", "~")),
                                    stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT,
                                    start_new_session=True)
        except OSError as err:
            out.close()
            finish(task, False, f"could not start: {err.strerror or err}", attention=f"could not start: {err}")
            return
        self.running[tid] = (proc, time.time(), out)
        update_state(tid, status="running", started=int(time.time()), pid=proc.pid)
        append_log(tid, f"started ({by}): {p['command']}")

    def kill(self, tid, quiet=False):
        """SIGTERM a running command's group; quiet: the task is deleted, so
        no log or state is written back for it (reap drops it silently)."""
        entry = self.running.get(tid)
        if entry:
            try:
                os.killpg(entry[0].pid, signal.SIGTERM)
            except OSError:
                pass
            if quiet:
                log(f"{tid}: deleted, its command stopped")
                return
            append_log(tid, "stopped by you")
            update_state(tid, stopped=True)

    def known(self, tid):
        return any(t["id"] == tid for t in self.tasks)

    def recover(self):
        """At start: a command or job a previous daemon left mid-way died with
        it (the service's cgroup). Say so, rather than "running" forever --
        and do not run it again by itself (a "once" command would)."""
        for task in self.tasks:
            st = get_state(task["id"])
            if st.get("status") in ("running", "working"):
                update_state(task["id"], status=None, pid=None, last_run=int(time.time()),
                             last_result="stopped", last_summary="interrupted: the service restarted")
                append_log(task["id"], "interrupted: tasks.service restarted while it ran (Run starts it again)")

    def reap(self, now):
        for tid, (proc, started, out) in list(self.running.items()):
            rc = proc.poll()
            if rc is None:
                try:
                    if os.path.getsize(path_for(tid, "out")) > MAX_OUT:
                        out.seek(0)
                        out.truncate()      # a runaway: keep the latest lines only
                except OSError:
                    pass
                continue
            out.close()
            self.running.pop(tid)
            task = find(self.tasks, tid)
            if task is None:        # deleted meanwhile: no state, log or notification comes back
                for ext in ("json", "out"):
                    try:
                        os.remove(path_for(tid, ext))
                    except OSError:
                        pass
                continue
            st = update_state(tid, status=None, pid=None)
            elapsed = now - started
            if st.pop("stopped", None):
                update_state(tid, stopped=None, last_run=int(now), last_result="stopped",
                             last_summary=f"stopped after {dur(elapsed)}")
            elif rc == 0:
                finish(task, True, f"finished OK after {dur(elapsed)}", quiet=not self.conf["notify_ok"])
            else:
                self.queued.add(tid)
                self.jobs.put((tid, lambda t, c, rc=rc, el=elapsed: command_failed(t, rc, el, c), (task, self.conf)))

    def work(self):
        while True:
            tid, fn, (task, conf) = self.jobs.get()
            self.queued.discard(tid)
            if not self.known(tid):     # deleted while it waited
                continue
            self.busy = tid
            try:
                update_state(tid, status="working")
                fn(task, conf)
            except Exception as err:
                log(f"{tid}: {err!r}")
                append_log(tid, f"went wrong: {err}")
                # A last run, or due() would start it again on the next tick, forever.
                update_state(tid, last_run=int(time.time()), last_result="failed",
                             last_summary=f"went wrong: {err}"[:300])
            finally:
                if self.known(tid):
                    update_state(tid, status=None)
                self.busy = None

    # -- watchers
    def alert(self, task, now, what, text, pattern=ERRORS, read_from=None):
        mem = self.watch.setdefault(task["id"], {})
        if now - mem.get("alerted", 0) < ALERT_GAP_S:
            return
        mem["alerted"] = now
        self.queued.add(task["id"])

        def job(t, c):
            cause, by = explain(what, text, c, pattern, read_from)
            finish(t, False, what, f"{cause}\n\n({by})", attention=f"{what}: {headline(cause, by)}", conf=c)
        self.jobs.put((task["id"], job, (task, self.conf)))

    def check_file(self, task, now):
        p, mem = task["params"], self.watch.setdefault(task["id"], {})
        path = expand(p["path"])
        try:
            size = os.path.getsize(path)
        except OSError:
            if mem.get("status") != "waiting":
                update_state(task["id"], status=f"waiting for {p['path']}")
                mem["status"] = "waiting"
            mem["offset"] = 0
            return
        if "offset" not in mem or mem.get("path") != path:
            mem.update(offset=size, path=path, pending=0)      # only lines from now on
            mem["status"] = "watching"
            update_state(task["id"], status="watching")
            return
        if size < mem["offset"]:
            mem["offset"] = 0                                   # truncated or rotated
        if size > mem["offset"]:
            with open(path, "rb") as handle:
                handle.seek(mem["offset"])
                new = handle.read(min(size - mem["offset"], 1_000_000)).decode("utf-8", errors="replace")
            mem["offset"] = size
            if re.search(p.get("pattern") or ERRORS, new):
                mem["pending"] = mem.get("pending") or now
        if mem.get("pending") and now - mem["pending"] >= SETTLE_S:
            mem["pending"] = 0
            text = read_tail(path, p.get("lines", TAIL_LINES))
            self.alert(task, now, f"a problem in {os.path.basename(path)}", text, p.get("pattern") or ERRORS,
                       read_from=path)

    def check_unit(self, task, now):
        mem = self.watch.setdefault(task["id"], {})
        if now - mem.get("polled", 0) < UNIT_POLL_S:
            return
        mem["polled"] = now
        new = unit_status(task["params"])
        if new.get("LoadState") == "not-found":
            update_state(task["id"], status=f"no unit {task['params']['unit']}")
            return
        failed, what = unit_failed(mem.get("last"), new)
        mem["last"] = new
        words = f"watching ({new.get('ActiveState', '?')})"
        if mem.get("status") != words:
            mem["status"] = words
            update_state(task["id"], status=words)
        if failed:
            self.alert(task, now, f"{task['params']['unit']} {what}", journal(task["params"]))

    def check_process(self, task):
        p = task["params"]
        started = proc_start(p["pid"])
        if started is not None and (not p.get("started") or started == p["started"]):
            return
        st = get_state(task["id"])
        if st.get("status") == "done":
            return
        elapsed = time.time() - (task.get("created") or time.time())
        label = p.get("label") or f"process {p['pid']}"
        update_state(task["id"], status="done")
        finish(task, True, f"{label} ended", f"(watched for {dur(elapsed)})",
               conf=self.conf, actions={"review": "Open tasks"})
        set_enabled(task["id"], False)


# -- plain words -> a task (the local "quick" model) --------------------------------------------
SYSTEM = ("You turn a sentence about a background job into ONE task, as JSON. Use only the task types and "
          "params listed; never invent others. Copy commands, addresses and paths exactly as the sentence "
          "writes them; never write a command or address the sentence does not contain. If the sentence "
          "asks for something the list cannot do, answer {\"error\": \"why\"}.")
SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "type": {"type": "string"},
        "params": {"type": "object"},
        "schedule": {"type": "string"},
        "error": {"type": "string"},
    },
}


def catalog():
    return {"types": [{"type": k, "words": v["words"], "schedule": v["schedule"],
                       "schedules": list(v["schedules"]), "heavy": v["heavy"],
                       "params": [{"name": n, "kind": kind, "required": req, "default": d, "hint": h}
                                  for n, (kind, req, d, h) in v["params"].items()]}
                      for k, v in TYPES.items() if k != "watch-process" and k not in BUILTIN_TYPES],
            "settings": DEFAULTS}


def model_prompt(text):
    lines = []
    for t in catalog()["types"]:
        params = "; ".join(f"{p['name']} ({'required' if p['required'] else 'optional'}: {p['hint']})"
                           for p in t["params"])
        lines.append(f"  {t['type']}: {t['words']}. params: {params}. schedule default: {t['schedule']}")
    return ("Task types:\n" + "\n".join(lines) + "\n\n"
            "Schedules: watch | once | every 30m | every 2h | every 1d | daily HH:MM | weekdays HH:MM | "
            "mon,thu HH:MM | on-event | manual. Watchers (watch-file, watch-unit) use watch. "
            "Paths start with ~/ for the home folder (my Downloads = ~/Downloads).\n"
            "Answer with {\"name\": a short title, \"type\": ..., \"params\": {...}, \"schedule\": ...}.\n"
            "Example: \"check https://shop.example/item every hour and tell me if the price drops\" -> "
            "{\"name\": \"Item price\", \"type\": \"watch-url\", \"params\": {\"url\": "
            "\"https://shop.example/item\", \"find\": \"the price of the item\", \"when\": \"drops\"}, "
            "\"schedule\": \"every 1h\"}\n\n"
            f"Sentence: {text}")


def squash(text):
    return " ".join(str(text).split())


def from_text(text, ask=None):
    """(task, None) or (None, why): the quick model's task for `text`,
    validated strictly; a command or address must be word for word in `text`.
    Local only: no cloud model is ever asked."""
    if ask is None:
        w = worker()
        model, why = w.ready("quick")
        if model is None:
            return None, f"the local model cannot run now: {why.removesuffix(': do the job yourself')}"

        def ask(prompt):
            return w.ask(model, prompt, system=SYSTEM, extra={
                "response_format": {"type": "json_schema", "json_schema": {"name": "task", "schema": SCHEMA}}})
    try:
        answer = ask(model_prompt(text))
    except Exception as err:
        return None, f"the local model did not answer ({err})"
    m = re.search(r"\{.*\}", answer or "", re.S)
    try:
        data = json.loads(m.group(0)) if m else None
    except ValueError:
        data = None
    if not isinstance(data, dict):
        return None, "the model's answer was not a task"
    if data.get("error"):
        return None, f"the model says it cannot: {data['error']}"
    if data.get("type") == "watch-process":
        return None, "watching a running program: use watch-window (SUPER+ALT+W in a terminal)"
    params = data.get("params") if isinstance(data.get("params"), dict) else {}
    params = {str(k).strip(" ?*"): v for k, v in params.items()}      # "by?" from a small model
    said = squash(text)
    if data.get("type") == "watch-command":
        cmd = squash(params.get("command") or "").strip("`'\"")
        if not cmd or cmd not in said:
            return None, ("a command is run only when you typed it: put it in your sentence exactly, "
                          "e.g. watch `make -j24` in ~/src/thing")
        params["command"] = cmd
    if data.get("type") == "watch-url":
        url = str(params.get("url") or "")
        if not url or url.rstrip("/") not in said:
            return None, "the address must be in your sentence, exactly (https://…)"
    task = {"name": data.get("name"), "type": data.get("type"), "params": params,
            "schedule": data.get("schedule") or None, "enabled": True, "source": "text"}
    try:        # a schedule the type cannot have (a small model's "watch" for a command): its default
        if parse_schedule(task["schedule"])["kind"] not in TYPES[task["type"]]["schedules"]:
            task["schedule"] = None
    except (ValueError, KeyError, TypeError):
        pass
    if task["schedule"] is None:
        task.pop("schedule")
    tidy, problems = validate(task)
    if problems:
        return None, "the model's task does not check out: " + "; ".join(problems)
    problem = url_min_check(tidy, settings())
    if problem:
        return None, problem
    return tidy, None


# -- the command line ---------------------------------------------------------------------------
def daemon_state():
    try:
        with open(DAEMON_STATE) as handle:
            data = json.load(handle)
        os.kill(data.get("pid", 0), 0)
        return data
    except (OSError, ValueError, TypeError):
        return {}


def poke(tid, verb):
    """Ask the running daemon; False when there is none."""
    if not daemon_state():
        return False
    os.makedirs(POKES, exist_ok=True)
    with open(os.path.join(POKES, f"{tid}.{verb}"), "w"):
        pass
    return True


def status_of(task, st, d):
    if not task["enabled"]:
        return "done" if st.get("status") == "done" else "paused"
    if task["id"] in (d.get("running") or []):
        return "running"
    if d.get("busy") == task["id"]:
        return "working"
    if task["id"] in (d.get("queued") or []):
        return "queued"
    if not d:
        return "the service is not running"
    if not d.get("enabled", True):
        return "all tasks are switched off"
    return st.get("status") or ("watching" if task["type"] in WATCHERS else "idle")


def rows():
    good, bad = load()
    d = daemon_state()
    out = []
    for t in good:
        st = get_state(t["id"])
        plan = read_plan(t["id"])
        out.append({**t, "words": describe(t), "permissions": permissions(t), "status": status_of(t, st, d),
                    "last_run": st.get("last_run"), "last_result": st.get("last_result"),
                    "last_summary": st.get("last_summary"), "last_value": st.get("last_value"),
                    "attention": st.get("attention"),
                    "plan": plan and {"made": plan["made"], "moves": [{"from": tilde(m["from"]), "to": tilde(m["to"])}
                                                                       for m in plan["moves"]]},
                    "undo": has_undo(t["id"]), "report": path_for(t["id"], "report.txt") if os.path.exists(path_for(t["id"], "report.txt")) else None,
                    "runnable": t["type"] not in WATCHERS})
    return {"tasks": out, "broken": [{"task": l, "problems": p} for l, p in bad], "running": bool(d),
            "settings": settings(), "gamemode": bool(d.get("gamemode")), "file": CONFIG}


def bar_json():
    if not settings()["enabled"]:
        return {"text": "", "tooltip": "", "class": "none"}
    good, _ = load()
    need = [(t, get_state(t["id"]).get("attention")) for t in good]
    need = [(t, a) for t, a in need if a]
    if not need:
        return {"text": "", "tooltip": "", "class": "none"}
    tip = "\n".join(f"{t['name']}: {a['text'][:120]}" for t, a in need[:8])
    return {"text": f"{BAR_ICON} {len(need)}", "class": "attention",
            "tooltip": f"Background tasks need you\n{tip}\nClick: open them  ·  right-click: mark seen"}


def run_now(task):
    """`tasks.py run`: through the daemon when it runs, else here and now."""
    if poke(task["id"], "run"):
        return f"asked the daemon to run {task['id']} (tasks.py logs {task['id']})"
    conf = settings()
    if task["type"] in WATCHERS:
        return "a watcher: it watches while tasks.service runs"
    if task["type"] == "watch-command":
        p = task["params"]
        start = time.time()
        os.makedirs(STATE_DIR, exist_ok=True)
        with open(path_for(task["id"], "out"), "wb") as out:
            rc = subprocess.call(["sh", "-c", p["command"]], cwd=expand(p.get("cwd", "~")),
                                 stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT)
        if rc:
            command_failed(task, rc, time.time() - start, conf)
        else:
            finish(task, True, f"finished OK after {dur(time.time() - start)}", quiet=not conf["notify_ok"])
        return get_state(task["id"]).get("last_summary", "done")
    JOBS[task["type"]](task, conf)
    return get_state(task["id"]).get("last_summary", "done")


def watch_window(address=None):
    """A watch-process task for the job running in the focused (or given)
    terminal window."""
    try:
        clients = json.loads(run("hyprctl", "clients", "-j", timeout=5) or "[]")
        active = json.loads(run("hyprctl", "activewindow", "-j", timeout=5) or "{}")
    except ValueError:
        clients, active = [], {}
    win = next((c for c in clients if c.get("address") == address), None) if address else active
    if not win or not win.get("pid"):
        return None, "no window to watch"
    job = foreground_job(win["pid"])
    if not job:
        return None, f"nothing is running in “{win.get('title', '')[:40]}” (only its shell)"
    label = proc_name(job) or comm(job)
    task = add({"name": f"Job: {label[:50]}", "type": "watch-process",
                "params": {"pid": job, "started": proc_start(job) or 0, "label": f"“{label[:60]}”"},
                "schedule": "watch"}, source="window")
    return task, None


def show_task(task):
    print(f"{task['name']}  [{task['type']}, {task['schedule']}]")
    print(f"  {describe(task)}")
    print("  It may:")
    for line in permissions(task):
        print(f"    - {line}")


def main(argv):
    if not argv:
        print(__doc__)
        return 0
    cmd, rest = argv[0], argv[1:]
    if cmd == "run-daemon":
        Daemon().run()
        return 0
    if cmd == "bar":
        print(json.dumps(bar_json()))
        return 0
    if cmd == "catalog":
        print(json.dumps(catalog(), indent=1))
        return 0
    if cmd == "list":
        data = rows()
        if "--json" in rest:
            print(json.dumps(data))
            return 0
        print(f"Background tasks: {'on' if data['settings']['enabled'] else 'OFF'}, "
              f"service {'running' if data['running'] else 'NOT running'}")
        for t in data["tasks"]:
            last = time.strftime("%a %H:%M", time.localtime(t["last_run"])) if t["last_run"] else "never"
            print(f"{t['id']:<24} {t['status']:<20} last: {last}  {t.get('last_summary') or ''}")
            print(f"  {t['words']}")
            if t["attention"]:
                print(f"  ! {t['attention']['text']}")
        for b in data["broken"]:
            print(f"BROKEN {b['task']}: {'; '.join(b['problems'])}")
        return 0
    if cmd == "status":
        data = {"settings": settings(), "daemon": daemon_state(), "attention": attention_count(), "file": CONFIG}
        if "--json" in rest:
            print(json.dumps(data))
        else:
            for k, v in data["settings"].items():
                print(f"{k} = {v}")
            print(f"daemon: {'running' if data['daemon'] else 'not running'}; need attention: {data['attention']}")
        return 0
    if cmd in ("on", "off"):
        set_setting("enabled", cmd)
        print(f"background tasks {cmd}")
        return 0
    if cmd == "set" and len(rest) == 2:
        try:
            print(f"{rest[0]} = {set_setting(rest[0], rest[1])}")
        except ValueError as err:
            print(f"tasks: {err}", file=sys.stderr)
            return 1
        return 0
    if cmd == "check":
        good, bad = load()
        for label, problems in bad:
            print(f"{label}: {'; '.join(problems)}")
        print(f"{len(good)} good, {len(bad)} broken")
        return 1 if bad else 0
    if cmd == "add" and rest:
        try:
            task = add(json.loads(rest[0]), source="settings" if "--settings" in rest else "json")
        except (ValueError, TypeError) as err:
            print(f"tasks: {err}", file=sys.stderr)
            return 1
        print(f"added {task['id']}: {describe(task)}")
        return 0
    if cmd == "add-from-text" and rest:
        words = " ".join(a for a in rest if a not in ("--yes", "--json"))
        task, why = from_text(words)
        if "--json" in rest:
            print(json.dumps({"task": task, "error": why, "words": task and describe(task),
                              "permissions": task and permissions(task)}))
            return 0 if task else 1
        if task is None:
            print(f"tasks: {why}", file=sys.stderr)
            return 1
        show_task(task)
        print(json.dumps({k: v for k, v in task.items() if k not in ("id", "created")}, indent=2, ensure_ascii=False))
        if "--yes" not in rest:
            if input("Save it? [y/N] ").strip().lower() not in ("y", "yes", "s", "si", "sí"):
                print("not saved")
                return 1
        saved = add(task, source="text")
        print(f"added {saved['id']}")
        return 0
    if cmd == "watch-window":
        task, why = watch_window(rest[0] if rest else None)
        if task is None:
            notify("Nothing to watch", why)
            print(f"tasks: {why}", file=sys.stderr)
            return 1
        notify("Watching", f"{task['params']['label']}: you'll be told when it ends")
        print(f"added {task['id']}")
        return 0
    if cmd == "seen":
        good, _ = load()
        for t in good if not rest else [find(good, rest[0])]:
            if t and get_state(t["id"]).get("attention") and not (get_state(t["id"])["attention"].get("plan")):
                update_state(t["id"], attention=None)
        signal_bar()
        return 0

    good, _ = load()
    task = find(good, rest[0]) if rest else None
    if task is None:
        print(f"tasks: no task {rest[0] if rest else ''!r} (tasks.py list)", file=sys.stderr)
        return 1
    tid = task["id"]
    if cmd == "run":
        print(run_now(task))
    elif cmd == "stop":
        print("asked the daemon to stop it" if poke(tid, "stop") else "the daemon is not running: nothing to stop")
    elif cmd in ("pause", "resume"):
        set_enabled(tid, cmd == "resume")
        if cmd == "resume":
            update_state(tid, status=None, resumed=int(time.time()))
        append_log(tid, "resumed" if cmd == "resume" else "paused")
        print(f"{tid} {'on' if cmd == 'resume' else 'paused'}")
    elif cmd == "delete":
        poke(tid, "stop")
        remove(tid)
        print(f"deleted {tid}")
    elif cmd == "logs":
        n = int(rest[rest.index("-n") + 1]) if "-n" in rest else 40
        sys.stdout.write("".join(read_log(tid, n)) or "(no log yet)\n")
    elif cmd == "plan":
        plan = read_plan(tid)
        if "--json" in rest:
            print(json.dumps(plan))
        elif not plan:
            print("no plan waiting")
        else:
            for m in plan["moves"]:
                print(f"{tilde(m['from'])}  ->  {tilde(m['to'])}")
    elif cmd == "approve":
        moved, problems = approve(task)
        print(f"moved {moved}" + ("".join(f"\n  skipped {p}" for p in problems) if problems else ""))
        return 0 if moved or not problems else 1
    elif cmd == "discard":
        discard_plan(tid)
        append_log(tid, "plan discarded: nothing moved")
        print("plan discarded")
    elif cmd == "undo":
        back, problems = undo(task)
        print(f"put back {back}" + ("".join(f"\n  {p}" for p in problems) if problems else ""))
        return 0 if back or not problems else 1
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
