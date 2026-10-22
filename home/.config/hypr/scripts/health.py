#!/usr/bin/env python3
"""The self-healing desktop: a nightly checkup (and one on demand) that reads
what went wrong since the last one, fixes the KNOWN problems from a fixed
catalog of safe, reversible remedies -- only those Settings allows to run on
their own; the others are proposed -- and explains everything else in plain
words with the local worker model. The result goes to the morning brief
(brief.py's "health" section), doctor.py's report and Settings > Desktop
health.

    health.py run [--by schedule|tasks|asked] [--since 24h] [--dry-run] [--json]
                              the checkup now (tasks.py's "nightly-checkup" task
                              runs it with --by tasks); --dry-run fixes nothing,
                              asks no model and keeps no report
    health.py report [--json]  the last report, in words (or as saved)
    health.py status [--json]  the settings, the schedule, the last report's
                              summary (Settings > Desktop health)
    health.py set KEY VALUE    one setting (SETTINGS below); "enabled" and
                              "schedule" are the checkup task's (tasks.json)
    health.py fix ID           apply the remedy the last report proposed for
                              finding ID (Settings' Apply button)
    health.py undo             put back what the last batch of fixes moved to
                              the trash or rotated away
    health.py dismiss          "seen": doctor and the bar stop pointing at it
    health.py ensure-task      create / repair the checkup task in tasks.json
    health.py catalog          JSON: the remedies, the known problems

WHAT IT READS (nothing else; read only):

    journals    your journal at warning and worse (journalctl --user -p
                warning) and the system's at error and worse (journalctl
                --system -p err, as far as you may read it without sudo --
                when you may not, the report says how to allow it), since the
                last checkup (48 h at most). Lines are grouped by who wrote
                them and what they say (numbers and ids masked), so a message
                repeated 300 times is one finding
    crashes     coredumpctl list (yours), with each crash's stack from the
                journal's systemd-coredump entry
    doctor      doctor.py's checks (units, Hyprland config errors, the colour
                daemon, the launcher, disks, snapshots, dotfiles, LM Studio)
    caches      the sizes of a FIXED list of caches (CACHES: pip, uv, npm,
                yarn, go, thumbnails, the NVIDIA and Mesa shader caches) --
                du at idle priority
    logs        the desktop's own log files (LOG_GLOBS, under
                ~/.local/state/hypr and ~/.cache/hypr) and Hyprland's own log
    generated   theme.py's generated files (waybar/generated/*, mako's theme,
                gtk-4.0/gtk.css): missing or emptied
    broken-*    ~/.config/hypr/broken-*/, the edits hypr-guard put aside when
                it restored a config that did not load
    waybar      how often the bar crashed (its coredumps, systemd's "Main
                process exited, code=dumped" lines)

THE REMEDIES (REMEDIES; each one auto-applied only with its auto_* setting
on, else proposed with an Apply button; the target is always re-derived from
the fixed catalog when it runs -- a report file can never name something
else to touch):

    restart-unit   a failed user service of the desktop's (pulled in by your
                   targets, or with its unit file / a drop-in in
                   ~/.config/systemd/user): reset-failed + restart; waybar
                   through waybar/scripts/bar-restart.sh. Never a system unit,
                   never twice in a day for the same unit (failing again after
                   a restart is a problem to look at, not to loop on)
    trash-cache    a cache from CACHES bigger than cache_gb, not in use by a
                   running program: moved to the trash with `gio trash` (the
                   program makes a new one). The space comes back when the
                   trash is emptied (Settings > Storage); `undo` restores it
    rotate-log     a desktop log over log_mb: the old .1 to the trash, the log
                   copied to NAME.1, then emptied -- nothing is lost
    regen-config   a generated theme file missing or empty: an empty one to
                   the trash, then `theme.py ensure` (writes only what is
                   missing, no other side effect)

Never: sudo, a system file, a delete (everything goes to the trash), user
data (the activity history and such are not "logs"), a command a model
wrote. Everything it does is logged (journal tag "health" and
$XDG_STATE_HOME/hypr/health/fixes.jsonl, which `undo` reads).

EXPLANATIONS: a KNOWN problem (KNOWN) has its words here, and known noise
(harmless lines every desktop has) is counted, not shown. The rest, worst
first, go to the local worker model with their raw lines attached
(llm-worker.py's ready()/ask(): local only, never a cloud model, refused in
gamemode or when the GPU is full) -- at most explain_max a run; an answer is
kept for EXPLAIN_KEEP_S per kind of problem, so the same message is not
asked about every night. Without the model, the plain lines say it. Secrets
in lines (token=..., Bearer ...) are masked (tasks.py's redact) before
anything is kept, shown or sent.

SETTINGS (~/.config/hypr/health.json, "settings"; a missing key is its
default):

    explain            the worker model explains what is not known (on)
    explain_max        at most this many explanations a run (6)
    system_journal     read the system journal too (on)
    notify             a notification when a checkup finds something that
                       needs you, or fixed something (on)
    auto_restart_unit  restart failed desktop services by itself (off)
    auto_trash_cache   move big caches to the trash by itself (off)
    auto_rotate_log    rotate huge desktop logs by itself (off)
    auto_regen_config  write missing generated files again by itself (off)
    cache_gb           a cache bigger than this is a finding (2)
    log_mb             a log bigger than this is a finding (200)

The schedule: tasks.py's built-in task "health-checkup" (type
nightly-checkup, "daily 03:30" by default; heavy, so it waits for gamemode
to end; a time missed while the computer was off runs once when it is back).
`health.py set enabled|schedule` and Settings change that task.

Where things are: $XDG_STATE_HOME/hypr/health/{last.json, report.txt,
fixes.jsonl, explained.json, run.lock}.
"""
import datetime
import fcntl
import glob
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
HOME = os.path.expanduser("~")
CONFIG = os.path.join(HOME, ".config", "hypr", "health.json")
STATE_DIR = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.join(HOME, ".local", "state"),
                         "hypr", "health")
RUNTIME = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
UNIT_DIR = os.path.join(HOME, ".config", "systemd", "user")
HYPR_DIR = os.path.join(HOME, ".config", "hypr")
BAR_RESTART = os.path.join(HOME, ".config", "waybar", "scripts", "bar-restart.sh")
SETTINGS_PY = os.path.join(HERE, "settings.py")
APP, ICON = "Desktop health", "preferences-system"
TAG = "health"
TASK_ID, TASK_TYPE, TASK_SCHEDULE = "health-checkup", "nightly-checkup", "daily 03:30"

MAX_WINDOW_S = 48 * 3600    # the journals are read since the last checkup, this far back at most
FIRST_WINDOW_S = 24 * 3600  # ... and this far back the first time
MAX_ENTRIES = 6000          # journal entries read per journal
STACK_LINES = 20            # lines of a crash's stack kept
MAX_STACKS = 8              # crashes whose stack is read (the newest per program)
RAW_KEEP = 12               # raw lines kept per finding (the newest)
RAW_PROMPT = 40             # raw lines sent to the model per finding
BURST_S = 1.0               # lines of one program this close together are one event
EXPLAIN_KEEP_S = 14 * 86400
RESTART_GAP_S = 86400       # one automatic restart per unit per day
HYPR_LOG_WARN = 1_000_000_000
STALE_S = 3 * 86400         # the brief says the last checkup is old

DEFAULTS = {"explain": True, "explain_max": 6, "system_journal": True, "notify": True,
            "auto_restart_unit": False, "auto_trash_cache": False, "auto_rotate_log": False,
            "auto_regen_config": False, "cache_gb": 2, "log_mb": 200}
SETTING_KINDS = {"explain": "bool", "explain_max": (0, 20), "system_journal": "bool", "notify": "bool",
                 "auto_restart_unit": "bool", "auto_trash_cache": "bool", "auto_rotate_log": "bool",
                 "auto_regen_config": "bool", "cache_gb": (1, 100), "log_mb": (10, 5000)}

# The remedies: what each does, in words, and the setting that lets it run by itself.
REMEDIES = {
    "restart-unit": {"setting": "auto_restart_unit", "title": "Restart failed desktop services",
                     "words": "reset-failed + restart a failed user service of the desktop's (waybar through "
                              "bar-restart.sh); never a system unit, never twice a day for the same one"},
    "trash-cache": {"setting": "auto_trash_cache", "title": "Move big caches to the trash",
                    "words": "a cache from the fixed list over the size limit, not in use: to the trash "
                             "(gio trash), where it can be restored; programs make a new one"},
    "rotate-log": {"setting": "auto_rotate_log", "title": "Rotate huge desktop logs",
                   "words": "a desktop log over the size limit: copied to NAME.1 (the old .1 to the trash), "
                            "then emptied -- nothing is lost"},
    "regen-config": {"setting": "auto_regen_config", "title": "Write missing generated files again",
                     "words": "a theme file theme.py generates, missing or empty: written again with "
                              "`theme.py ensure` (only what is missing)"},
}

# The caches a remedy may move to the trash: (id, path under HOME, words). A
# fixed list -- programs rebuild every one of these by themselves; browsers'
# caches, model downloads (huggingface, playwright's browsers) are not here.
CACHES = [
    ("pip", ".cache/pip", "pip's downloaded packages"),
    ("uv", ".cache/uv", "uv's downloaded packages"),
    ("npm", ".npm/_cacache", "npm's downloaded packages"),
    ("yarn", ".cache/yarn", "yarn's downloaded packages"),
    ("go-build", ".cache/go-build", "Go's build cache"),
    ("thumbnails", ".cache/thumbnails", "file thumbnails (Files draws them again)"),
    ("nvidia-gl", ".cache/nvidia/GLCache", "NVIDIA's compiled OpenGL shaders"),
    ("nvidia-compute", ".cache/nvidia/ComputeCache", "NVIDIA's compiled CUDA kernels"),
    ("mesa", ".cache/mesa_shader_cache", "Mesa's compiled shaders"),
    ("mesa-db", ".cache/mesa_shader_cache_db", "Mesa's compiled shaders"),
]
# The desktop's own logs (rotate-log may touch these and nothing else).
LOG_GLOBS = [".local/state/hypr/**/*.log", ".cache/hypr/**/*.log"]
# Units a restart is never automatic for (proposed, with why): restarting them
# does something you see or opens a sensor.
ASK_FIRST = {"presence.service": "it may open the webcam: only when you say so",
             "voice.service": "it listens to the microphone: only when you say so",
             "sessions-offer.service": "it offers to restore your windows: only when you say so",
             "sessions-autosave.service": "it saves your windows' layout: only when you say so"}

# Programs whose crash is the desktop's (a warning, not just a note).
DESKTOP_EXES = {"Hyprland", "waybar", "mako", "hypridle", "hyprlock", "hyprpaper", "hyprpolkitagent",
                "xdg-desktop-portal-hyprland", "cliphist", "wl-paste", "kitty", "python3"}

# Known lines: (who regex or None, message regex, what). what = "noise" (a
# harmless line every desktop like this one has: counted, not shown) or
# {"title", "words", "level"} -- {0}, {1}... are the message pattern's groups.
NOISE = "noise"
KNOWN = [
    (r"xdg-desktop-portal$", r"Inhibiting other than idle not supported", NOISE),
    (r"xdg-desktop-portal-gtk", r"Unhandled parent window type|Failed to associate portal window|"
                                r"Could not init tracker3 search engine", NOISE),
    (r"dbus-broker", r"is not named after the D-Bus name", NOISE),
    (r"abrt-server", r"Not saving repeating crash", NOISE),
    (r"abrt-notification|abrt-applet", r".", NOISE),        # abrt's copy of a crash the coredumps list has
    (r"rsyslogd", r"get tty for session", NOISE),
    (r"sudo|su|polkitd", r"pam_systemd\(.*Failed to check if /run/user/0/bus", NOISE),
    (None, r"has no capability of surrounding-text feature", NOISE),
    (None, r"gtk_disable_setlocale\(\) must be called before gtk_init", NOISE),
    (r"systemd", r"(ptyxis|vte)-spawn-\S+\.scope", NOISE),
    (r"systemd-udevd", r"^(\S+):\d+ Failed to resolve group '([^']+)'",
     {"title": "A device rule names a group this system does not have", "level": "info",
      "words": "The device rule {0} (installed by another program) gives a device to the group "
               "'{1}', which Fedora does not have. That line of the rule is ignored and the device "
               "still works for you, so it is harmless. To quiet it, the program that installed the "
               "rule would need fixing (or create the group: sudo groupadd {1})."}),
    (r"systemd", r"^(repo-preview-\S+\.service): (Service reached runtime time limit|Failed with result)",
     {"title": "A repo preview server timed out", "level": "info",
      "words": "{0} is a short-lived preview server (systemd-run with a time limit). It was stopped when "
               "its time was up, as designed. Nothing to do."}),
    (r"waybar", r"Status Notifier Item with bus name .* (already registered|already exists|not found)", NOISE),
]
SIGNALS = {4: "SIGILL: an illegal instruction", 6: "SIGABRT: it stopped itself on an internal error",
           7: "SIGBUS: a bad memory access", 8: "SIGFPE: an arithmetic error",
           11: "SIGSEGV: a bad memory access", 5: "SIGTRAP: a debug trap / assertion"}
WAYBAR_EXIT = re.compile(r"^(waybar(?:-toolbox)?\.service): Main process exited, code=(dumped|killed)")
SECRET_FILE = re.compile(r"(?i)secret|credential|password|token|\.ssh|\.gnupg")

EXPLAIN = ("You explain Linux desktop log lines (Fedora, Hyprland) to the person who uses this computer, "
           "who is technical but not reading logs all day. In at most three short sentences: what it "
           "means in plain words, whether it is harmless or needs a look, and the likely fix. Quote the "
           "decisive line. Say plainly when the lines do not show the cause. Never suggest deleting "
           "files or running anything as root unless the lines leave no other way. No preamble.")


def log(text, level="info"):
    try:
        _module("desklog", "desklog.py").log(TAG, redact(str(text)), level)
    except Exception:       # logging never breaks the checkup
        pass


def _module(name, filename, folder=HERE):
    mod = sys.modules.get(name)
    if mod is None:
        spec = importlib.util.spec_from_file_location(name, os.path.join(folder, filename))
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
    return mod


def tasks():
    return _module("tasks", "tasks.py")


def doctor():
    return _module("doctor", "doctor.py")


def storage():
    return _module("storage", "storage.py")


def sh(*cmd, timeout=30, env=None):
    """(returncode, stdout, stderr); 127 when it could not run."""
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)
        return out.returncode, out.stdout, out.stderr
    except (OSError, subprocess.SubprocessError) as exc:
        return 127, "", str(exc)


def redact(text):
    try:
        return tasks().redact(text)
    except Exception:       # tasks.py missing: mask the obvious by hand
        return re.sub(r"(?i)\b(password|token|secret|api[_-]?key)(\s*[:=]\s*)\S+", r"\1\2…", text)


def tilde(path):
    path = str(path)
    return "~" + path[len(HOME):] if path == HOME or path.startswith(HOME + os.sep) else path


def human(size):
    size = float(size or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1000 or unit == "TB":
            return f"{size:.0f} {unit}" if unit in ("B", "KB", "MB") else f"{size:.1f} {unit}"
        size /= 1000
    return ""


def when_words(epoch, now=None):
    if not epoch:
        return "never"
    now = now if now is not None else time.time()
    same_day = time.localtime(epoch).tm_yday == time.localtime(now).tm_yday and now - epoch < 86400
    return time.strftime("today %H:%M" if same_day else "%a %d %b %H:%M", time.localtime(epoch))


# -- settings ---------------------------------------------------------------------------------
def read_config(path=None):
    try:
        with open(path or CONFIG) as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def check_setting(key, value):
    kind = SETTING_KINDS.get(key)
    if kind is None:
        raise ValueError(f"no setting {key!r}: {', '.join(list(SETTING_KINDS) + ['enabled', 'schedule'])}")
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


def settings(path=None):
    out = dict(DEFAULTS)
    raw = read_config(path).get("settings")
    for key, value in (raw if isinstance(raw, dict) else {}).items():
        if key in DEFAULTS:
            try:
                out[key] = check_setting(key, value)
            except ValueError:
                pass
    return out


def set_setting(key, value, path=None):
    if key in ("enabled", "schedule"):
        return set_task(key, value)
    value = check_setting(key, value)
    path = path or CONFIG
    data = read_config(path)
    data["_doc"] = "Desktop health (scripts/health.py; its docstring explains). Settings > Desktop health edits this."
    data.setdefault("settings", {})[key] = value
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w") as handle:
        json.dump(data, handle, indent=2)
        handle.write("\n")
    os.replace(tmp, path)
    return value


# -- the checkup task (tasks.json) ------------------------------------------------------------
def task_entry():
    """The checkup task as tasks.json has it (validated), or None."""
    try:
        good, _bad = tasks().load()
    except Exception:
        return None
    return next((t for t in good if t["id"] == TASK_ID), None)


def ensure_task():
    """Create the checkup task if it is missing (on, TASK_SCHEDULE); repair
    one that lost its type. Returns the task."""
    t = tasks()

    def put(data):
        items = [x for x in data["tasks"] if isinstance(x, dict)]
        mine = next((x for x in items if x.get("id") == TASK_ID), None)
        if mine and mine.get("type") == TASK_TYPE and t.validate(mine)[0]:
            return False
        sched = (mine or {}).get("schedule") or TASK_SCHEDULE
        try:
            if t.parse_schedule(sched)["kind"] not in t.TYPES[TASK_TYPE]["schedules"]:
                sched = TASK_SCHEDULE
        except ValueError:
            sched = TASK_SCHEDULE
        tidy, problems = t.validate({"id": TASK_ID, "name": "Nightly health checkup", "type": TASK_TYPE,
                                     "params": {}, "schedule": sched, "source": "settings",
                                     "enabled": (mine or {}).get("enabled", True) is not False})
        if problems:
            raise ValueError("; ".join(problems))
        data["tasks"] = [x for x in data["tasks"] if not (isinstance(x, dict) and x.get("id") == TASK_ID)]
        data["tasks"].append(tidy)
    t.change_config(put)
    return task_entry()


def set_task(key, value):
    t = tasks()
    ensure_task()
    if key == "enabled":
        on = check_setting("explain", value)       # the same on/off reading
        t.set_enabled(TASK_ID, on)
        return on
    s = t.parse_schedule(str(value))               # ValueError says why not
    if s["kind"] not in t.TYPES[TASK_TYPE]["schedules"]:
        raise ValueError("the checkup runs at a time (daily 03:30), every N hours/days, on-event or manual")
    text = t.schedule_text(s)

    def put(data):
        for x in data["tasks"]:
            if isinstance(x, dict) and x.get("id") == TASK_ID:
                x["schedule"] = text
                return True
        return False
    t.change_config(put)
    return text


# -- state ------------------------------------------------------------------------------------
def path_for(name):
    os.makedirs(STATE_DIR, exist_ok=True)
    return os.path.join(STATE_DIR, name)


def read_json(name, default):
    try:
        with open(path_for(name)) as handle:
            data = json.load(handle)
        return data if isinstance(data, type(default)) else default
    except (OSError, ValueError):
        return default


def write_json(name, data):
    tmp = path_for(f"{name}.{os.getpid()}.tmp")
    with open(tmp, "w") as handle:
        json.dump(data, handle, indent=1, ensure_ascii=False)
    os.replace(tmp, path_for(name))


def last_report():
    return read_json("last.json", {})


def read_fixes():
    out = []
    try:
        with open(path_for("fixes.jsonl")) as handle:
            for line in handle:
                try:
                    out.append(json.loads(line))
                except ValueError:
                    continue
    except OSError:
        pass
    return out


def record_fix(entry):
    with open(path_for("fixes.jsonl"), "a") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")


# -- reading: the journals --------------------------------------------------------------------
def text_of(value):
    """A journal field: a string, or bytes as a list of ints (not UTF-8)."""
    if isinstance(value, list):
        try:
            return bytes(value).decode("utf-8", errors="replace")
        except (TypeError, ValueError):
            return str(value)
    return "" if value is None else str(value)


def parse_journal(text):
    """journalctl -o json lines -> entries (dicts)."""
    out = []
    for line in (text or "").splitlines():
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if isinstance(entry, dict):
            out.append(entry)
    return out


def read_journal(scope, since):
    """(entries, None) or ([], why not). scope: user (warning and worse) or
    system (error and worse)."""
    prio = "warning" if scope == "user" else "err"
    rc, out, err = sh("journalctl", f"--{scope}", "-p", prio, "--since", f"@{int(since)}", "-o", "json",
                      "--no-pager", "-n", str(MAX_ENTRIES), timeout=60)
    entries = parse_journal(out)
    if rc != 0 and not entries:
        return [], (err.strip().splitlines() or ["journalctl failed"])[0][:200]
    if scope == "system" and not entries and "not seeing messages from other users" in err:
        return [], ("you may not read the system journal (add yourself to the systemd-journal group: "
                    "sudo usermod -aG systemd-journal $USER, then log in again)")
    return entries, None


def who_of(entry):
    return (text_of(entry.get("SYSLOG_IDENTIFIER")) or text_of(entry.get("_COMM"))
            or text_of(entry.get("_SYSTEMD_USER_UNIT")) or text_of(entry.get("_SYSTEMD_UNIT")) or "?")


def unit_of(entry):
    return text_of(entry.get("_SYSTEMD_USER_UNIT")) or text_of(entry.get("_SYSTEMD_UNIT"))


def raw_line(entry):
    try:
        stamp = time.strftime("%b %d %H:%M:%S", time.localtime(int(entry.get("__REALTIME_TIMESTAMP")) / 1e6))
    except (TypeError, ValueError):
        stamp = "?"
    pid = text_of(entry.get("_PID"))
    msg = text_of(entry.get("MESSAGE")).strip()
    return redact(f"{stamp} {who_of(entry)}{f'[{pid}]' if pid else ''}: {msg}")


MASKS = [
    (re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I), "<uuid>"),
    (re.compile(r"0x[0-9a-f]+", re.I), "<hex>"),
    (re.compile(r"\b[0-9a-f]{12,}\b", re.I), "<hex>"),
    (re.compile(r":1\.\d+"), ":<bus>"),
    (re.compile(r"\d+"), "#"),
]


def signature(who, message):
    """What makes two lines "the same problem": who, and the message's first
    line with numbers, ids and addresses masked."""
    first = (message.strip().splitlines() or [""])[0]
    for rx, repl in MASKS:
        first = rx.sub(repl, first)
    return f"{who}|{first[:120]}"


def short_id(sig):
    return hashlib.sha1(sig.encode()).hexdigest()[:10]


def match_known(who, message):
    """(what, match) for a KNOWN line, else (None, None)."""
    for who_rx, msg_rx, what in KNOWN:
        if who_rx and not re.search(who_rx, who):
            continue
        m = re.search(msg_rx, message)
        if m:
            return what, m
    return None, None


def group_journal(entries, source, ours=()):
    """Entries -> {"groups": [group], "noise": {who: count}, "waybar": [raw
    lines], "coredump_stacks": {pid: text}}. A group: {sig, who, unit, source,
    prio, count, first, last, raw, message, ours, known (the KNOWN what or None),
    known_args}."""
    groups, noise, waybar, stacks = {}, {}, [], {}
    burst = None
    for entry in entries:
        who, message = who_of(entry), text_of(entry.get("MESSAGE"))
        if who == TAG or not message.strip():
            continue                            # our own lines
        if who == "systemd-coredump" or entry.get("COREDUMP_PID"):
            pid = text_of(entry.get("COREDUMP_PID"))
            if pid:
                stacks[pid] = stack_part(redact(message))
            continue                            # crashes: the coredumps finding has them
        if WAYBAR_EXIT.search(message):
            waybar.append(raw_line(entry))
            continue
        what, m = match_known(who, message)
        if what == NOISE:
            noise[who] = noise.get(who, 0) + 1
            continue
        unit = unit_of(entry)
        try:
            prio = int(text_of(entry.get("PRIORITY")) or 6)
        except ValueError:
            prio = 6
        try:
            at = int(entry.get("__REALTIME_TIMESTAMP")) / 1e6
        except (TypeError, ValueError):
            at = 0
        pid = text_of(entry.get("_PID"))
        if what is None and burst and burst[0] == (who, pid) and 0 <= at - burst[1] <= BURST_S:
            # The next line of one event (a traceback, a machine check's
            # dozen lines): it belongs to the event's first line.
            g = burst[2]
            g["prio"] = min(g["prio"], prio)
            g["raw"].append(raw_line(entry))
            if len(g["raw"]) > RAW_PROMPT:
                del g["raw"][0]
            burst[1] = at
            continue
        if what is not None:        # a known problem: one finding per what and its first group
            sig = f"known|{who}|{what['title']}|{m.group(1) if m.groups() else ''}"
        else:
            sig = signature(who, redact(message))
        g = groups.get(sig)
        if g is None:
            g = groups[sig] = {"sig": sig, "who": who, "unit": unit, "source": source, "prio": prio,
                               "count": 0, "first": at, "last": at, "raw": [],
                               "message": redact(message.strip().splitlines()[0])[:300],
                               "ours": bool(unit and unit in ours) or who in ours,
                               "known": what, "known_args": list(m.groups()) if m else []}
        g["count"] += 1
        g["prio"] = min(g["prio"], prio)
        g["first"], g["last"] = min(g["first"] or at, at), max(g["last"], at)
        g["raw"].append(raw_line(entry))
        if len(g["raw"]) > RAW_PROMPT:
            del g["raw"][0]
        burst = [(who, pid), at, g] if what is None else None
    return {"groups": list(groups.values()), "noise": noise, "waybar": waybar, "coredump_stacks": stacks}


# -- reading: the rest ------------------------------------------------------------------------
def read_coredumps(since):
    """[{pid, exe, sig, time}] of your crashes since then ([] when none)."""
    stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(since))
    rc, out, _ = sh("coredumpctl", "list", "--json=short", "--no-pager", "--since", stamp, timeout=30)
    try:
        rows = json.loads(out) if out.strip() else []
    except ValueError:
        return []
    uid = os.getuid()
    return [{"pid": str(r.get("pid")), "exe": str(r.get("exe") or "?"), "sig": r.get("sig"),
             "time": (r.get("time") or 0) / 1e6}
            for r in rows if isinstance(r, dict) and r.get("uid", uid) == uid]


def stack_part(text):
    """From a crash report's text: its first stack (STACK_LINES lines), or
    its start when it has none."""
    lines = text.splitlines()
    start = next((n for n, l in enumerate(lines) if "Stack trace of thread" in l), None)
    if start is None:
        return "\n".join(lines[:STACK_LINES])
    return "\n".join(l.strip() for l in lines[start:start + 1 + STACK_LINES])


def coredump_stack(pid):
    """The first thread's stack of one of your crashes (coredumpctl info; no
    debuginfod download -- nothing goes on the network)."""
    env = {k: v for k, v in os.environ.items() if k != "DEBUGINFOD_URLS"}
    _, out, _ = sh("coredumpctl", "info", "--no-pager", str(pid), timeout=30, env=env)
    return redact(stack_part(out)) if "Stack trace of thread" in out else ""


def du_size(path):
    try:
        return storage().du(path).get(path, 0)
    except Exception:
        return 0


def read_caches():
    out = []
    for cid, rel, words in CACHES:
        path = os.path.join(HOME, rel)
        if os.path.islink(path) or not os.path.isdir(path):
            continue
        out.append({"id": cid, "path": path, "words": words, "size": du_size(path)})
    return out


def cache_holders(path):
    try:
        return storage().holders(path)
    except Exception:
        return []


def desktop_logs():
    paths = set()
    for pattern in LOG_GLOBS:
        for path in glob.glob(os.path.join(HOME, pattern), recursive=True):
            if os.path.isfile(path) and not os.path.islink(path):
                paths.add(path)
    return sorted(paths)


def read_logs():
    out = []
    for path in desktop_logs():
        try:
            out.append({"path": path, "size": os.path.getsize(path)})
        except OSError:
            continue
    for path in glob.glob(os.path.join(RUNTIME, "hypr", "*", "hyprland.log")):
        try:
            out.append({"path": path, "size": os.path.getsize(path), "hyprland": True})
        except OSError:
            continue
    return out


def generated_files():
    """theme.py's generated files (every one `theme.py ensure` writes when missing)."""
    try:
        th = _module("theme", "theme.py")
        return [p for p, _, _ in th.TARGETS.values()] + [th.COLORS, th.LANG_FILE, th.MODULES]
    except Exception:
        return []


def read_generated():
    out = []
    for path in generated_files():
        if not os.path.exists(path):
            out.append({"path": path, "state": "missing"})
        elif os.path.isfile(path) and os.path.getsize(path) == 0:
            out.append({"path": path, "state": "empty"})
    return out


def read_broken():
    out = []
    for path in sorted(glob.glob(os.path.join(HYPR_DIR, "broken-*"))):
        if os.path.isdir(path):
            n = sum(len(files) for _, _, files in os.walk(path))
            out.append({"path": path, "mtime": os.path.getmtime(path), "files": n})
    return out


def read_doctor():
    """doctor.py's checks (light: its own journal check is ours, done better)."""
    try:
        d = doctor()
        return [c for c in d.run_checks(health=False) if c["name"] not in ("health", "journal")], d.wanted_units()
    except Exception as err:
        return [{"name": "doctor", "level": "warn", "text": f"doctor.py did not run: {err}"}], []


def unit_info(unit):
    """{FragmentPath, DropInPaths, ActiveState, Result} of a user unit."""
    _, out, _ = sh("systemctl", "--user", "show", "-p", "FragmentPath,DropInPaths,ActiveState,Result,Transient",
                   unit, timeout=10)
    info = {}
    for line in out.splitlines():
        key, _, value = line.partition("=")
        info[key] = value
    return info


def unit_journal(unit, n=25):
    # json, so the lines look exactly like the journal groups' (raw_line) and
    # the same line from both is kept once when they are joined (analyse)
    _, out, _ = sh("journalctl", "--user", "-u", unit, "-n", str(n), "--no-pager", "-o", "json", timeout=15)
    return [raw_line(e) for e in parse_journal(out) if text_of(e.get("MESSAGE")).strip()]


def collect(since, conf):
    """Everything the checkup reads, as plain data (analyse() is pure on it)."""
    facts = {"since": since, "until": time.time(), "notes": []}
    checks, wanted = read_doctor()
    facts["doctor"], facts["wanted"] = checks, wanted
    user, why = read_journal("user", since)
    if why:
        facts["notes"].append(f"your journal: {why}")
    facts["journal_user"] = user
    facts["journal_system"] = []
    if conf["system_journal"]:
        system, why = read_journal("system", since)
        if why:
            facts["notes"].append(f"the system journal: {why}")
        facts["journal_system"] = system
    facts["coredumps"] = read_coredumps(since)
    newest = {}
    for d in facts["coredumps"]:
        newest[os.path.basename(d["exe"])] = d["pid"]
    facts["coredump_info"] = {pid: coredump_stack(pid) for pid in list(newest.values())[-MAX_STACKS:]}
    facts["caches"] = read_caches()
    facts["logs"] = read_logs()
    facts["generated"] = read_generated()
    facts["broken"] = read_broken()
    facts["units"] = {}
    for c in checks:
        if c["name"] == "units" and c["level"] == "fail" and c.get("unit"):
            info = unit_info(c["unit"])
            info["journal"] = unit_journal(c["unit"])
            facts["units"][c["unit"]] = info
    return facts


# -- analysing (pure) ---------------------------------------------------------------------------
def finding(kind, level, title, words="", raw=(), key=None, count=1, remedy=None, by="catalog", **extra):
    sig = key or f"{kind}|{title}"
    return {"id": short_id(sig), "sig": sig, "kind": kind, "level": level, "title": title, "words": words,
            "raw": list(raw)[:2 * RAW_KEEP] if kind == "crash" else list(raw)[-RAW_KEEP:], "count": count, "remedy": remedy, "by": by if words else "", **extra}


def owned_unit(unit, info, wanted):
    """Is this a user unit the desktop owns (a remedy may restart it)?"""
    if not unit or info.get("Transient") == "yes" or "/" in unit:
        return False
    if unit in wanted:
        return True
    paths = [info.get("FragmentPath") or ""] + (info.get("DropInPaths") or "").split()
    return any(p.startswith(UNIT_DIR + os.sep) for p in paths)


def recently_restarted(unit, fixes, now):
    return any(f.get("remedy") == "restart-unit" and f.get("target") == unit and f.get("ok")
               and now - f.get("at", 0) < RESTART_GAP_S for f in fixes)


def known_words(what, args):
    try:
        return what["words"].format(*args)
    except (IndexError, KeyError):
        return what["words"]


def analyse(facts, conf, fixes=(), now=None):
    """facts -> (findings, noise counts). Each finding needing words that the
    catalog does not have keeps words "" (explain() fills them)."""
    now = now if now is not None else time.time()
    out, noise = [], {}
    wanted = set(facts.get("wanted") or [])
    stacks = dict(facts.get("coredump_info") or {})
    groups = []
    for source in ("user", "system"):
        g = group_journal(facts.get(f"journal_{source}") or [], source, wanted | {"hyprland", "Hyprland"})
        groups += g["groups"]
        stacks.update({pid: text for pid, text in g["coredump_stacks"].items() if "#0" in text or pid not in stacks})
        for who, n in g["noise"].items():
            noise[who] = noise.get(who, 0) + n
        if g["waybar"]:
            facts.setdefault("waybar_exits", []).extend(g["waybar"])

    # doctor's checks: units first (they have a remedy)
    for c in facts.get("doctor") or []:
        if c["level"] not in ("warn", "fail"):
            continue
        name = c["name"]
        if name == "units" and c.get("unit"):
            unit = c["unit"]
            info = (facts.get("units") or {}).get(unit, {})
            raw = info.get("journal") or []
            if info.get("ActiveState") == "inactive" and info.get("Result") == "success":
                # A run-once service (an offer after login) that ended well:
                # doctor counts it as "not running", but nothing is wrong.
                out.append(finding("unit", "info", c["text"],
                                   f"{unit} ran and ended normally (exit status 0): it is meant to run once "
                                   "and stop, so there is nothing to restart.", raw=raw[-4:],
                                   key=f"unit|{unit}", unit=unit))
                continue
            remedy = None
            if c["level"] == "fail" and owned_unit(unit, info, wanted):
                remedy = {"type": "restart-unit", "target": unit, "label": f"Restart {unit}"}
                if unit in ASK_FIRST:
                    remedy["note"] = ASK_FIRST[unit]
                elif recently_restarted(unit, fixes, now):
                    remedy["note"] = "failed again after a restart in the last day: look at why first"
            out.append(finding("unit", c["level"], c["text"], raw=raw, key=f"unit|{unit}", remedy=remedy,
                               unit=unit))
        elif name == "hyprland":
            out.append(finding("hyprland", c["level"], "Hyprland's config has errors",
                               "Hyprland loaded its config with errors, so some settings are not in effect. "
                               "hypr-guard can restore the last working config, keeping your edit aside "
                               "(Settings > Maintenance, or the launcher: \"Restore the last working Hyprland "
                               "config\").", raw=[c["text"]], key="hyprland|configerrors"))
        elif name == "disk":
            out.append(finding("disk", c["level"], f"Disk space: {c['text']}",
                               "This disk is getting full. Settings > Storage shows the biggest folders and "
                               "can empty the trash; any big caches below can go to the trash too.",
                               key=f"disk|{c['text'].split(':')[0]}"))
        elif name not in ("lm studio",):
            out.append(finding("doctor", c["level"], f"{name}: {c['text']}", c["text"], key=f"doctor|{name}"))

    # crashes
    by_exe = {}
    for d in facts.get("coredumps") or []:
        by_exe.setdefault(os.path.basename(d["exe"]), []).append(d)
    for exe, dumps in sorted(by_exe.items(), key=lambda kv: -len(kv[1])):
        sigs = sorted({str(d.get("sig")) for d in dumps})
        raw = []
        for d in dumps[-3:]:
            raw += [f"crash of {d['exe']} (pid {d['pid']}, signal {d.get('sig')} {SIGNALS.get(d.get('sig'), '')}) at "
                    f"{time.strftime('%b %d %H:%M', time.localtime(d['time']))}"]
            raw += (stacks.get(d["pid"]) or "").splitlines()[:STACK_LINES + 1]
        level = "warn" if exe in DESKTOP_EXES else "info"
        title = f"{exe} crashed" + (f" {len(dumps)} times" if len(dumps) > 1 else "") + \
            f" ({', '.join(SIGNALS.get(int(x), 'signal ' + x).split(':')[0] if x.isdigit() else x for x in sigs)})"
        out.append(finding("crash", level, title, raw=raw, key=f"crash|{exe}", count=len(dumps), exe=exe))

    # the bar
    exits = facts.get("waybar_exits") or []
    bar_dumps = len(by_exe.get("waybar", []))
    if exits or bar_dumps:
        n = max(len(exits), bar_dumps)
        out.append(finding("waybar", "warn", f"The bar (waybar) crashed {n} time{'s' if n != 1 else ''}",
                           "systemd started it again each time. Bar reloads by signal (SIGUSR2 or SIGINT) are "
                           "the usual cause on waybar 0.15 -- restart it only with ALT+G (bar-restart.sh). "
                           "If it keeps happening with no reload, the crash's stack below says which module.",
                           raw=exits[-6:], key="waybar|crashes", count=n))

    # the journal groups (systemd's lines about a unit that has its own finding join it)
    by_unit = {f["unit"]: f for f in out if f["kind"] == "unit"}
    for g in groups:
        m = re.match(r"(\S+\.(?:service|timer|socket)): ", g["message"]) if g["who"] == "systemd" else None
        if m and m.group(1) in by_unit:
            # The group's signature masks numbers, so run-p1-... and run-p2-...
            # share one: each line joins the finding of the unit it names.
            for line in g["raw"]:
                name = re.search(r"\]?: (\S+\.(?:service|timer|socket)): ", line)
                f = by_unit.get(name.group(1) if name else m.group(1))
                if f is not None and line not in f["raw"]:
                    f["raw"] = (f["raw"] + [line])[-RAW_KEEP:]
            continue
        if g["known"]:
            what = g["known"]
            out.append(finding("journal", what.get("level", "info"), what["title"],
                               known_words(what, g["known_args"]), raw=g["raw"], key=g["sig"], count=g["count"],
                               who=g["who"], source=g["source"], prio=g["prio"], ours=g["ours"]))
            continue
        level = "warn" if g["prio"] <= 3 and (g["ours"] or g["source"] == "system" or g["count"] >= 5) else \
            "info"
        title = f"{g['who']}: {g['message'][:140]}"
        out.append(finding("journal", level, title, raw=g["raw"], key=g["sig"], count=g["count"],
                           who=g["who"], source=g["source"], prio=g["prio"], ours=g["ours"], unit=g["unit"]))

    # caches
    limit = conf["cache_gb"] * 1_000_000_000
    for c in facts.get("caches") or []:
        if c["size"] <= limit:
            continue
        busy = c.get("busy") or []
        remedy = None if busy else {"type": "trash-cache", "target": c["id"],
                                    "label": f"Move {tilde(c['path'])} ({human(c['size'])}) to the trash"}
        words = (f"{c['words'][0].upper()}{c['words'][1:]}: {human(c['size'])}, over your {conf['cache_gb']} GB "
                 "limit. It is only a cache -- the program makes a new one as needed.")
        if busy:
            words += f" In use by {', '.join(busy[:3])} right now, so it is left alone."
        out.append(finding("cache", "info", f"{tilde(c['path'])} is {human(c['size'])}", words,
                           key=f"cache|{c['id']}", remedy=remedy, size=c["size"]))

    # logs
    log_limit = conf["log_mb"] * 1_000_000
    for item in facts.get("logs") or []:
        if item.get("hyprland"):
            if item["size"] > HYPR_LOG_WARN:
                out.append(finding("log", "info", f"Hyprland's own log is {human(item['size'])}",
                                   "Hyprland writes it in memory (/run/user) and it goes away when you log out; "
                                   "it only grows this big when something repeats an error -- the journal "
                                   "findings may say what.", key="log|hyprland"))
            continue
        if item["size"] > log_limit:
            out.append(finding("log", "info", f"{tilde(item['path'])} is {human(item['size'])}",
                               f"A desktop log over your {conf['log_mb']} MB limit. Rotating keeps every line "
                               "(in NAME.1) and starts it empty.", key=f"log|{item['path']}",
                               remedy={"type": "rotate-log", "target": item["path"],
                                       "label": f"Rotate {os.path.basename(item['path'])}"}))

    # generated files
    for item in facts.get("generated") or []:
        out.append(finding("generated", "warn", f"{tilde(item['path'])} is {item['state']}",
                           "A file theme.py generates from the current theme is "
                           f"{item['state']}, so whatever imports it falls back to the plain look. "
                           "Writing the missing files again is safe: nothing else changes.",
                           key=f"generated|{item['path']}",
                           remedy={"type": "regen-config", "target": item["path"],
                                   "label": f"Write {os.path.basename(item['path'])} again"}))

    # broken-* folders
    for item in facts.get("broken") or []:
        new = item["mtime"] >= (facts.get("since") or 0)
        stamp = time.strftime("%a %d %b %H:%M", time.localtime(item["mtime"]))
        out.append(finding("broken", "warn" if new else "info",
                           f"Hyprland's config was restored ({os.path.basename(item['path'])})",
                           f"On {stamp} the Hyprland config did not load and hypr-guard restored the last "
                           f"working one. Your edited files ({item['files']}) are kept in "
                           f"{tilde(item['path'])}: compare them with the live config (diff -r), take what "
                           "you want back, then delete the folder.", key=f"broken|{item['path']}"))

    for n in facts.get("notes") or []:
        out.append(finding("note", "info", n, n, key=f"note|{n[:60]}"))
    rank = {"fail": 0, "warn": 1, "info": 2}
    out.sort(key=lambda f: (rank[f["level"]], f["remedy"] is None, not f.get("ours"), -f["count"]))
    return out, noise


# -- explaining ---------------------------------------------------------------------------------
def explain_budget(findings, conf):
    """The findings without words, worst first, up to explain_max."""
    todo = [f for f in findings if not f["words"]]
    return todo[:conf["explain_max"]], todo[conf["explain_max"]:]


def plain_words(f):
    lines = [l for l in f["raw"] if l.strip()]
    if f["kind"] == "crash":        # its first line says what crashed; the stack ends in noise
        lines = lines[:1]
    tail = lines[-1] if lines else f["title"]
    return (f"{f['count']} time{'s' if f['count'] != 1 else ''} since the last checkup; the latest: "
            if f["count"] > 1 else "") + tail[:300]


def model_prompt(f):
    head = f"{f['title']}\nSeen {f['count']} time(s)"
    if f.get("source"):
        head += f" in the {f['source']} journal"
    if f.get("ours"):
        head += " (a part of this desktop)"
    return head + "\n\n=== raw lines ===\n" + redact("\n".join(f["raw"][-RAW_PROMPT:]))[-8000:]


def ask_model(prompts):
    """[(answer or None)], by: the worker model's answers, or Nones and why not."""
    try:
        w = _module("llm_worker", "llm-worker.py")
        model, why = w.ready("worker")
        if model is None:
            return [None] * len(prompts), (why or "no model").removesuffix(": do the job yourself")
        out = []
        for prompt in prompts:
            try:
                out.append(w.ask(model, prompt, system=EXPLAIN))
            except Exception as err:        # one timeout: the rest still get theirs
                log(f"the model did not answer: {err}", "warning")
                out.append(None)
        return out, model.name
    except Exception as err:
        return [None] * len(prompts), f"the local model did not answer ({err})"


def plain_markdown(text):
    """The model's **bold** and leading blank lines out: the answer is shown in labels."""
    return re.sub(r"\*\*([^*]+)\*\*", r"\1", text or "").strip()


def explain(findings, conf, dry_run=False, now=None):
    """Fill in the words the catalog does not have: the kept answer, the
    model's, or the plain lines."""
    now = now if now is not None else time.time()
    cache = read_json("explained.json", {})
    cache = {k: v for k, v in cache.items() if isinstance(v, dict) and now - v.get("at", 0) < EXPLAIN_KEEP_S}
    for f in findings:
        kept = cache.get(f["sig"])
        if not f["words"] and kept and f["kind"] != "crash":     # a crash's stack differs each time
            f["words"], f["by"] = plain_markdown(kept["words"]), kept["by"] + " (kept)"
    ask, rest = explain_budget(findings, conf)
    why = "the model is off (Settings > Desktop health)" if not conf["explain"] else \
        "a dry run asks no model" if dry_run else None
    if ask and why is None:
        answers, by = ask_model([model_prompt(f) for f in ask])
        for f, answer in zip(ask, answers):
            if answer:
                answer = plain_markdown(answer)
                f["words"], f["by"] = answer, f"{by}, local"
                cache[f["sig"]] = {"words": f["words"], "by": f"{by}, local", "at": int(now)}
            else:
                f["words"], f["by"] = plain_words(f), f"plain lines -- {by}"
    else:
        rest = ask + rest
    for f in rest:
        if not f["words"]:
            f["words"], f["by"] = plain_words(f), "plain lines" + (f" -- {why}" if why else " (over explain_max)")
    if not dry_run:
        write_json("explained.json", cache)
    return findings


# -- the remedies ---------------------------------------------------------------------------------
def gio_trash(path):
    rc, _, err = sh("gio", "trash", "--", path, timeout=120)
    return rc == 0, err.strip()[:200]


def is_active(unit):
    _, out, _ = sh("systemctl", "--user", "is-active", unit, timeout=10)
    return out.strip()


def cache_target(cid):
    """The CACHES entry's real path for a cache id, or None (the only way a
    remedy finds what to trash)."""
    for c, rel, _words in CACHES:
        if c == cid:
            path = os.path.join(HOME, rel)
            if os.path.islink(path) or not os.path.isdir(path):
                return None
            real = os.path.realpath(path)
            return real if real.startswith(os.path.realpath(HOME) + os.sep) else None
    return None


UNIT_NAME = re.compile(r"[A-Za-z0-9_][A-Za-z0-9@_.:\\-]*\.(?:service|timer|socket|path)")


def remedy_restart(unit, dry_run, wanted=None):
    if not UNIT_NAME.fullmatch(unit):       # never an option (--host=...) or a path for systemctl
        return False, f"{unit[:80]!r} is not a unit name: not touched", {}
    info = unit_info(unit)
    wanted = set(doctor().wanted_units()) if wanted is None else wanted
    if not owned_unit(unit, info, wanted):
        return False, f"{unit} is not one of the desktop's own user units: not touched", {}
    if info.get("ActiveState") == "active":
        return True, f"{unit} is running again already", {}
    if dry_run:
        return True, f"would restart {unit}", {}
    sh("systemctl", "--user", "reset-failed", unit)
    if unit.split(".")[0] in ("waybar", "waybar-toolbox"):
        rc, _, err = sh(BAR_RESTART, timeout=60)
    else:
        rc, _, err = sh("systemctl", "--user", "restart", unit, timeout=60)
    time.sleep(2)
    state = is_active(unit)
    if rc == 0 and state == "active":
        return True, f"restarted {unit}: running again", {}
    return False, f"restarted {unit}, but it is {state or 'not running'}" + (f" ({err.strip()[:120]})" if err else ""), {}


def remedy_trash_cache(cid, dry_run, conf):
    path = cache_target(cid)
    if path is None:
        return False, f"no cache {cid!r} in the list (or it is gone already)", {}
    size = du_size(path)
    if size <= conf["cache_gb"] * 1_000_000_000:
        return True, f"{tilde(path)} is {human(size)} now, under the limit: left alone", {}
    busy = cache_holders(path)
    if busy:
        return False, f"{', '.join(busy[:3])} {'is' if len(busy) == 1 else 'are'} using {tilde(path)}: left alone", {}
    if dry_run:
        return True, f"would move {tilde(path)} ({human(size)}) to the trash", {}
    ok, err = gio_trash(path)
    if not ok:
        return False, f"could not move {tilde(path)} to the trash: {err}", {}
    return True, (f"moved {tilde(path)} ({human(size)}) to the trash -- the space comes back when the "
                  "trash is emptied (Settings > Storage)"), {"trashed": path}


def remedy_rotate(path, dry_run, conf):
    real = os.path.realpath(path)
    if real not in [os.path.realpath(p) for p in desktop_logs()] or os.path.islink(path):
        return False, f"{tilde(path)} is not one of the desktop's own logs: not touched", {}
    size = os.path.getsize(real)
    if size <= conf["log_mb"] * 1_000_000:
        return True, f"{tilde(real)} is {human(size)} now, under the limit: left alone", {}
    kept = real + ".1"
    if dry_run:
        return True, f"would rotate {tilde(real)} ({human(size)}) to {os.path.basename(kept)}", {}
    if os.path.exists(kept):
        ok, err = gio_trash(kept)
        if not ok:
            return False, f"could not move the old {os.path.basename(kept)} to the trash: {err}", {}
    shutil.copyfile(real, kept)
    with open(real, "r+b") as handle:
        handle.truncate(0)
    return True, f"rotated {tilde(real)} ({human(size)}): the old lines are in {os.path.basename(kept)}", \
        {"rotated": real, "kept": kept}


def remedy_regen(path, dry_run):
    if path not in generated_files():
        return False, f"{tilde(path)} is not a file theme.py generates: not touched", {}
    undo = {}
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return True, f"{tilde(path)} is there again", {}
    if dry_run:
        return True, f"would write {tilde(path)} again (theme.py ensure)", {}
    if os.path.exists(path):
        ok, err = gio_trash(path)
        if not ok:
            return False, f"could not move the empty {tilde(path)} to the trash: {err}", {}
    rc, _, err = sh(sys.executable, os.path.join(HERE, "theme.py"), "ensure", timeout=60)
    if rc == 0 and os.path.exists(path) and os.path.getsize(path) > 0:
        return True, f"wrote {tilde(path)} again", undo
    return False, f"theme.py ensure did not write {tilde(path)}: {err.strip()[:160]}", undo


def apply_remedy(remedy, conf, dry_run=False, wanted=None):
    """(ok, result in words, undo info) -- the target re-checked against its
    fixed catalog first."""
    kind, target = remedy.get("type"), str(remedy.get("target") or "")
    try:
        if kind == "restart-unit":
            return remedy_restart(target, dry_run, wanted)
        if kind == "trash-cache":
            return remedy_trash_cache(target, dry_run, conf)
        if kind == "rotate-log":
            return remedy_rotate(target, dry_run, conf)
        if kind == "regen-config":
            return remedy_regen(target, dry_run)
    except OSError as err:
        return False, f"went wrong: {err.strerror or err}", {}
    return False, f"no remedy {kind!r}", {}


def fix_all(findings, conf, dry_run=False, now=None, run_id=None, wanted=None):
    """Apply the remedies the settings allow; mark the rest proposed."""
    now = now if now is not None else time.time()
    for f in findings:
        rem = f.get("remedy")
        if not rem:
            continue
        setting = REMEDIES[rem["type"]]["setting"]
        if not conf[setting] or rem.get("note"):
            rem["status"] = "proposed"
            continue
        ok, result, undo = apply_remedy(rem, conf, dry_run, wanted)
        rem["status"] = ("would apply" if dry_run else "applied") if ok else "failed"
        rem["result"] = result
        if not dry_run:
            record_fix({"at": int(now), "run": run_id, "remedy": rem["type"], "target": rem["target"],
                        "ok": ok, "result": result, "by": "auto", **undo})
            log(f"{'fixed' if ok else 'could not fix'}: {result}", "notice" if ok else "warning")
    return findings


# -- the report ---------------------------------------------------------------------------------
def summary_of(findings, noise=None):
    applied = [f for f in findings if (f.get("remedy") or {}).get("status") == "applied"]
    proposed = [f for f in findings if (f.get("remedy") or {}).get("status") == "proposed"]
    problems = [f for f in findings if f["level"] in ("warn", "fail")]
    return {"findings": len(findings), "problems": len(problems), "fixed": len(applied),
            "proposed": len(proposed), "worst": "fail" if any(f["level"] == "fail" for f in findings) else
            "warn" if problems else "ok", "noise": sum((noise or {}).values())}


def headline(s):
    if not s["findings"]:
        return "all good"
    bits = []
    if s["problems"]:
        bits.append(f"{s['problems']} problem{'s' if s['problems'] != 1 else ''}")
    if s["fixed"]:
        bits.append(f"{s['fixed']} fixed")
    if s["proposed"]:
        bits.append(f"{s['proposed']} fix{'es' if s['proposed'] != 1 else ''} to approve")
    notes = s["findings"] - s["problems"]
    if notes:
        bits.append(f"{notes} note{'s' if notes != 1 else ''}")
    return ", ".join(bits)


def report_text(rep):
    if not rep:
        return "No checkup yet: health.py run"
    s = rep["summary"]
    lines = [f"Desktop health -- {when_words(rep['at'])} ({rep.get('by', '?')}): {headline(s)}",
             f"Read: the journals since {time.strftime('%a %d %b %H:%M', time.localtime(rep['since']))}"
             + (f"; {s['noise']} harmless known lines not shown" if s.get("noise") else ""), ""]
    mark = {"fail": "FAIL", "warn": "WARN", "info": "  --"}
    for f in rep["findings"]:
        lines.append(f"{mark[f['level']]}  {f['title']}" + (f"  (x{f['count']})" if f["count"] > 1 else ""))
        for w in (f["words"] or "").splitlines():
            lines.append(f"      {w}")
        if f["by"] and f["by"] != "catalog":
            lines.append(f"      ({f['by']})")
        rem = f.get("remedy")
        if rem:
            state = {"applied": "done", "proposed": f"proposed -- health.py fix {f['id']}",
                     "failed": "failed", "would apply": "would apply"}.get(rem.get("status"), rem.get("status"))
            lines.append(f"      fix: {rem['label']} [{state}]" + (f": {rem['result']}" if rem.get("result") else "")
                         + (f" ({rem['note']})" if rem.get("note") else ""))
        for raw in f["raw"][-4:]:
            lines.append(f"        | {raw[:200]}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def notify(summary, body, open_page=True):
    argv = ["notify-send", "-a", APP, "-i", ICON]
    if open_page:
        argv += ["--wait", "-A", "open=Open"]
    argv += [redact(summary), redact(body)[:900]]
    if not open_page:
        sh(*argv, timeout=5)
        return
    try:
        subprocess.Popen(["sh", "-c", '[ "$("$@")" = open ] && exec python3 "$0" health', SETTINGS_PY] + argv,
                         start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        pass


def window_start(prev, now, since_arg=None):
    if since_arg:
        return now - since_arg
    start = (prev or {}).get("until") or (now - FIRST_WINDOW_S)
    return max(now - MAX_WINDOW_S, min(start, now - 3600))


def parse_span(text):
    m = re.fullmatch(r"(\d+)\s*([hd])", (text or "").strip().lower())
    if not m:
        raise ValueError("--since is like 24h or 2d")
    return int(m.group(1)) * (3600 if m.group(2) == "h" else 86400)


def run_checkup(by="asked", since_arg=None, dry_run=False, now=None, facts=None):
    """The checkup: read, analyse, fix what is allowed, explain the rest,
    keep the report, tell you when something needs you. Returns the report."""
    now = now if now is not None else time.time()
    conf = settings()
    lock = run_lock()
    try:
        prev = last_report()
        since = window_start(prev, now, since_arg)
        facts = facts if facts is not None else collect(since, conf)
        for c in facts.get("caches") or []:
            if c["size"] > conf["cache_gb"] * 1_000_000_000:
                c["busy"] = cache_holders(c["path"])
        findings, noise = analyse(facts, conf, read_fixes(), now)
        run_id = f"{int(now)}"
        fix_all(findings, conf, dry_run, now, run_id, set(facts.get("wanted") or []))
        explain(findings, conf, dry_run, now)
        rep = {"at": int(now), "by": by, "since": int(since), "until": int(facts.get("until") or now),
               "run": run_id, "dry_run": dry_run, "findings": findings, "noise": noise,
               "summary": summary_of(findings, noise), "seen": False}
        if not dry_run:
            old = {f["sig"] for f in prev.get("findings") or []}
            rep["new"] = [f["id"] for f in findings if f["sig"] not in old and f["level"] in ("warn", "fail")]
            # A fix you left waiting (a big cache you keep) is told once, not
            # every night: only a proposal the last report did not have counts,
            # and "seen" carries over while nothing new turned up.
            was_proposed = {f["sig"] for f in prev.get("findings") or []
                            if (f.get("remedy") or {}).get("status") == "proposed"}
            fresh = [f["id"] for f in findings if (f.get("remedy") or {}).get("status") == "proposed"
                     and f["sig"] not in was_proposed]
            rep["seen"] = bool(prev.get("seen")) and not rep["new"] and not fresh
            write_json("last.json", rep)
            with open(path_for("report.txt"), "w") as handle:
                handle.write(report_text(rep))
            s = rep["summary"]
            log(f"checkup ({by}): {headline(s)}")
            if conf["notify"] and by != "asked" and (s["fixed"] or fresh or rep["new"]):
                tops = [f["title"] for f in findings if f["id"] in rep["new"] or
                        (f.get("remedy") or {}).get("status") in ("applied", "proposed")][:4]
                notify(f"Nightly checkup: {headline(s)}", "\n".join(tops))
        return rep
    finally:
        lock.close()


# -- fixing one, undo, dismiss --------------------------------------------------------------------
def run_lock():
    """run.lock, held: one checkup / fix / undo at a time (each rewrites
    last.json or fixes.jsonl); RuntimeError when another one has it."""
    lock = open(path_for("run.lock"), "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        lock.close()
        raise RuntimeError("a checkup is running already: try again when it is done") from None
    return lock


def fix_one(fid):
    with run_lock():
        return _fix_one(fid)


def _fix_one(fid):
    rep = last_report()
    f = next((x for x in rep.get("findings") or [] if x["id"] == fid), None)
    if f is None or not f.get("remedy"):
        raise ValueError(f"no finding {fid!r} with a fix in the last report")
    rem = f["remedy"]
    if rem.get("status") == "applied":
        return True, "done already"
    ok, result, undo = apply_remedy({"type": rem["type"], "target": rem["target"]}, settings())
    record_fix({"at": int(time.time()), "run": f"manual-{int(time.time())}", "remedy": rem["type"],
                "target": rem["target"], "ok": ok, "result": result, "by": "you", **undo})
    log(f"{'fixed' if ok else 'could not fix'} (asked): {result}", "notice" if ok else "warning")
    rem.update(status="applied" if ok else "failed", result=result)
    rep["summary"] = summary_of(rep["findings"], rep.get("noise"))
    write_json("last.json", rep)
    with open(path_for("report.txt"), "w") as handle:
        handle.write(report_text(rep))
    return ok, result


def trash_uri(path):
    """The trash:// URI of the newest trashed item that came from path."""
    _, out, _ = sh("gio", "trash", "--list", timeout=30)
    found = None
    for line in out.splitlines():
        uri, _, orig = line.partition("\t")
        if orig.strip() == path:
            found = uri.strip()
    return found


def undo_last():
    """Put back the last batch of fixes that moved or rotated something."""
    with run_lock():
        return _undo_last()


def _undo_last():
    fixes = [f for f in read_fixes() if f.get("ok") and (f.get("trashed") or f.get("rotated"))
             and not f.get("undone")]
    if not fixes:
        return ["nothing to undo"]
    batch = fixes[-1]["run"]
    out = []
    for f in [x for x in fixes if x["run"] == batch]:
        if f.get("trashed"):
            path = f["trashed"]
            if os.path.exists(path):
                out.append(f"{tilde(path)}: a new one was made since -- restore the old one from the trash by hand")
                continue
            uri = trash_uri(path)
            rc, _, err = sh("gio", "trash", "--restore", uri, timeout=120) if uri else (1, "", "not in the trash")
            out.append(f"{tilde(path)}: " + ("restored" if rc == 0 else f"not restored ({err.strip()[:120]})"))
        elif f.get("rotated"):
            path, kept = f["rotated"], f["kept"]
            try:
                with open(kept, "rb") as old, open(path, "rb") as new:
                    joined = old.read() + new.read()
                with open(path, "wb") as handle:
                    handle.write(joined)
                ok, _ = gio_trash(kept)
                out.append(f"{tilde(path)}: its old lines are back" + ("" if ok else f" ({os.path.basename(kept)} kept)"))
            except OSError as err:
                out.append(f"{tilde(path)}: not undone ({err.strerror})")
        record_fix({"at": int(time.time()), "run": f"undo-{batch}", "remedy": "undo", "target":
                    f.get("trashed") or f.get("rotated"), "ok": True, "result": out[-1]})
    rewritten = []
    for f in read_fixes():
        if f.get("run") == batch and (f.get("trashed") or f.get("rotated")):
            f["undone"] = True
        rewritten.append(json.dumps(f, ensure_ascii=False))
    with open(path_for("fixes.jsonl"), "w") as handle:
        handle.write("\n".join(rewritten) + "\n")
    log("undo: " + "; ".join(out))
    return out


def dismiss():
    rep = last_report()
    if rep:
        rep["seen"] = True
        write_json("last.json", rep)
    return bool(rep)


# -- for doctor, the brief, the page ----------------------------------------------------------------
def doctor_checks(light=True, now=None):
    """doctor.py's "health" lines from the last report (no checkup is run)."""
    now = now if now is not None else time.time()
    rep = last_report()
    if not rep:
        return [{"name": "health", "level": "info", "text": "no nightly checkup yet (health.py run)"}]
    s = rep["summary"]
    when = when_words(rep["at"], now)
    level = "ok"
    if not rep.get("seen") and (s["proposed"] or s["worst"] == "fail"):
        level = "warn"
    elif s["problems"]:
        level = "info"
    text = f"checkup {when}: {headline(s)}" + (" (Settings > Desktop health)" if level == "warn" else "")
    if now - rep["at"] > STALE_S:
        level, text = "info", f"the last checkup was {when} (health.py run)"
    out = [{"name": "health", "level": level, "text": text}]
    if not light:
        for f in [f for f in rep["findings"] if f["level"] in ("warn", "fail")][:5]:
            words = (f["words"] or "").replace("\n", " ")
            out.append({"name": "health", "level": "info",
                        "text": f"{f['title'][:90]} -- {words[:220]}"})
    return out


def brief_lines(now=None):
    """The morning brief's "health" section (brief.py): [] when all is well."""
    now = now if now is not None else time.time()
    rep = last_report()
    if not rep:
        return []
    if now - rep["at"] > STALE_S:
        return [f"The last nightly checkup was {when_words(rep['at'], now)} -- is tasks.service running? "
                "(Settings > Desktop health)"]
    s = rep["summary"]
    if not (s["problems"] or s["fixed"] or s["proposed"]):
        return []
    lines = [f"Checkup {when_words(rep['at'], now)}: {headline(s)} (Settings > Desktop health)"]
    shown = [f for f in rep["findings"] if f["level"] in ("warn", "fail")
             or (f.get("remedy") or {}).get("status") in ("applied", "proposed")]
    for f in shown[:4]:
        first = re.split(r"(?<=[.!?])\s", (f["words"] or "").strip(), maxsplit=1)[0]
        rem = f.get("remedy") or {}
        tag = " [fixed]" if rem.get("status") == "applied" else " [fix waiting]" if rem.get("status") == "proposed" \
            else ""
        lines.append(f"{f['title'][:100]}{tag}" + (f" -- {first[:160]}" if first else ""))
    if len(shown) > 4:
        lines.append(f"... and {len(shown) - 4} more")
    return lines


def status():
    t = task_entry()
    st = {}
    daemon = {}
    try:
        st = tasks().get_state(TASK_ID) if t else {}
        daemon = {"enabled": tasks().settings().get("enabled", True),
                  "running": sh("systemctl", "--user", "is-active", "tasks.service")[1].strip() == "active"}
    except Exception:
        pass
    rep = last_report()
    fixes = read_fixes()
    undoable = [f for f in fixes if f.get("ok") and (f.get("trashed") or f.get("rotated")) and not f.get("undone")]
    return {"settings": settings(), "remedies": REMEDIES,
            "task": {"exists": bool(t), "enabled": bool(t and t["enabled"]), "schedule": (t or {}).get("schedule"),
                     "status": st.get("status"), "last_run": st.get("last_run"), "last_result": st.get("last_result")},
            "tasks": daemon, "report": rep, "undo": len(undoable),
            "report_file": path_for("report.txt")}


def catalog():
    return {"remedies": REMEDIES, "caches": [{"id": c, "path": f"~/{r}", "words": w} for c, r, w in CACHES],
            "logs": [f"~/{g}" for g in LOG_GLOBS],
            "known": [{"who": w, "pattern": p, "noise": x == NOISE, **({} if x == NOISE else x)} for w, p, x in KNOWN],
            "settings": DEFAULTS}


def main(argv):
    cmd, args = (argv[0], argv[1:]) if argv else ("report", [])
    if cmd == "run":
        by = args[args.index("--by") + 1] if "--by" in args and args.index("--by") + 1 < len(args) else "asked"
        since = parse_span(args[args.index("--since") + 1]) if "--since" in args else None
        try:
            rep = run_checkup(by, since, dry_run="--dry-run" in args)
        except RuntimeError as err:
            sys.exit(str(err))
        if "--json" in args:
            print(json.dumps(rep, indent=1, ensure_ascii=False))
        elif "--summary" in args:
            print(json.dumps({"headline": headline(rep["summary"]), **rep["summary"]}))
        else:
            print(report_text(rep), end="")
    elif cmd == "report":
        rep = last_report()
        print(json.dumps(rep, indent=1, ensure_ascii=False) if "--json" in args else report_text(rep), end="\n"
              if "--json" in args else "")
    elif cmd == "status":
        print(json.dumps(status(), indent=1, ensure_ascii=False))
    elif cmd == "set" and len(args) == 2:
        try:
            print(f"{args[0]} = {set_setting(args[0], args[1])}")
        except ValueError as err:
            sys.exit(str(err))
    elif cmd == "fix" and len(args) == 1:
        try:
            ok, result = fix_one(args[0])
        except (ValueError, RuntimeError) as err:
            sys.exit(str(err))
        print(result)
        sys.exit(0 if ok else 1)
    elif cmd == "undo":
        try:
            print("\n".join(undo_last()))
        except RuntimeError as err:
            sys.exit(str(err))
    elif cmd == "dismiss":
        print("marked seen" if dismiss() else "no report yet")
    elif cmd == "ensure-task":
        t = ensure_task()
        print(f"{t['id']}: {t['schedule']}, {'on' if t['enabled'] else 'off'}" if t else "could not create it")
    elif cmd == "catalog":
        print(json.dumps(catalog(), indent=1))
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
