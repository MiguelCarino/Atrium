#!/usr/bin/env python3
"""Everything that starts with the session, in one place: the desktop's own
background services, its timers, the XDG autostart apps and Hyprland's own
login commands -- what each is for, whether it runs, and the switch.

    startup.py [list] [--json]       all of it (the Settings page's
                                     "Startup & background" reads --json)
    startup.py services [--json]     the desktop's user services
    startup.py timers [--json]       the desktop's timers, with the next run
    startup.py autostart [--json]    XDG autostart apps (/etc/xdg/autostart
                                     and ~/.config/autostart)
    startup.py exec [--json]         what Hyprland itself starts (lua/)

    startup.py enable <unit>         start it at every login, and now
    startup.py disable <unit> [--force]
                                     not at login any more, and stop it now;
                                     an essential one (ESSENTIAL below) needs
                                     --force, so no click turns the bar off
    startup.py restart <unit>        restart a service
    startup.py run <timer>           run a timer's job now, not at its time
    startup.py autostart on|off <id> an XDG autostart app on / off for
                                     Hyprland (<id> = the .desktop file name,
                                     with or without .desktop)

Services and timers
    "The desktop's own" are the units ~/.config/systemd/user/*.wants/ pulls
    in -- the same rule doctor.py uses, so a unit added later shows up with
    no list to keep -- plus the ones that could be there but are switched
    off: unit files in that folder with an [Install] section, KNOWN below
    (Fedora's units this desktop enables, the cliphist@ instances), and
    every unit this script disabled (remembered in
    $XDG_STATE_HOME/hypr/startup-disabled, so a switched-off Fedora unit
    keeps its row). enable / disable are `systemctl --user enable|disable
    --now`, which is what survives a reload and a re-login: the *.wants
    links ARE the setting. Two timers have their own owner script, and the
    switch goes through it so the script's own state stays right:
        theme-schedule.timer   theme-schedule.py on|off
        timers-calendar.timer  timers.py calendar on|off (the timer keeps
                               ticking; the script stops arming alarms)

XDG autostart
    Under uwsm, systemd's xdg-autostart generator turns each .desktop file in
    the autostart folders into an app-<id>@autostart.service at login. Its
    rules, which judge() follows: Hidden=true, X-systemd-skip=true or a
    missing TryExec= program means never; OnlyShowIn= / NotShowIn= are
    checked against XDG_CURRENT_DESKTOP (Hyprland). A file in
    ~/.config/autostart replaces the system one of the same name. "off" here
    is the repo's own convention: a copy in ~/.config/autostart with
    Hyprland added to NotShowIn=, so a COSMIC login still starts it; "on"
    takes Hyprland back out (and turns a Hidden=true into false). Either one
    reloads the user manager so the generated unit follows, then starts or
    stops the app now. Entries that are not for this desktop at all
    (OnlyShowIn=GNOME, X-systemd-skip) are listed with the reason and no
    switch.

Hyprland's own (read-only)
    lua/autostart.lua's exec lines on hyprland.start (and its fallback list,
    used only in a plain non-uwsm Hyprland session, where the services above
    do not exist), plus hl.timer exec lines anywhere in lua/ (the night
    light's). Changing those is editing the config, not a switch.

Logs every change through desklog (journal tag "startup").
"""
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import desklog  # noqa: E402

HOME = os.path.expanduser("~")
CONFIG = os.environ.get("XDG_CONFIG_HOME") or os.path.join(HOME, ".config")
UNIT_DIR = os.path.join(CONFIG, "systemd", "user")
LUA_DIR = os.path.join(HOME, ".config", "hypr", "lua")
STATE_DIR = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.join(HOME, ".local", "state"), "hypr")
DISABLED = os.path.join(STATE_DIR, "startup-disabled")
USER_AUTOSTART = os.path.join(CONFIG, "autostart")
SYSTEM_AUTOSTART = [os.path.join(d, "autostart") for d in
                    (os.environ.get("XDG_CONFIG_DIRS") or "/etc/xdg").split(":") if d]
DESKTOP = "Hyprland"
THEME_SCHEDULE = os.path.join(HERE, "theme-schedule.py")
TIMERS = os.path.join(HERE, "timers.py")

# Units that keep their row even while switched off: Fedora's own units this
# desktop enables (they live in /usr/lib, so the folder scan cannot find them
# once their link is gone) and the template's instances.
KNOWN = ["waybar.service", "mako.service", "hypridle.service", "hyprpaper.service",
         "hyprpolkitagent.service", "cliphist@text.service", "cliphist@image.service"]

# The pieces the desktop does not work without. The page shows a lock
# instead of a switch; the CLI wants --force. The text says what goes
# missing, so the lock explains itself.
ESSENTIAL = {
    "waybar.service": "the bar: clock, workspaces, tray, and the toolbox's way in",
    "waybar-toolbox.service": "the toolbox, where Settings and the quick switches live",
    "launcher.service": "ALT+E and the search bar",
    "mako.service": "notifications; without it apps draw them as windows",
    "hypridle.service": "locks the computer and turns the screens off when you are away",
    "screen-color.service": "brightness and the night light on every screen",
    "hypr-guard.service": "safe mode: brings back a working config after a broken edit",
    "hyprpolkitagent.service": "the password prompt apps need for admin actions",
    "hyprpaper.service": "the wallpapers",
    "timers.service": "puts your timers and alarms back after a restart",
    "emergency-alerts.service": "earthquake and severe-weather alerts (single sources go off on the "
                                "Alerts page)",
}

# Fedora's units describe themselves for every compositor ("Highly
# customizable Wayland bar for Sway and Wlroots..."); these say what they do
# here. The desktop's own units have good Descriptions of their own.
TITLES = {
    "waybar.service": "The bar",
    "mako.service": "Notifications",
    "hypridle.service": "Idle: lock and screens off",
    "hyprpaper.service": "Wallpapers",
    "hyprpolkitagent.service": "Password prompts for admin actions",
}

# Timers whose switch belongs to another script (see the top).
ROUTES = {
    "theme-schedule.timer": ([THEME_SCHEDULE, "on"], [THEME_SCHEDULE, "off"]),
    "timers-calendar.timer": ([TIMERS, "calendar", "on"], [TIMERS, "calendar", "off"]),
}

PROPS = ("Id,Description,LoadState,ActiveState,SubState,Result,Type,UnitFileState,"
         "ActiveEnterTimestampMonotonic,MemoryCurrent,NRestarts,FragmentPath,DropInPaths,"
         "Triggers,TimersCalendar,TimersMonotonic,ConsistsOf")


def systemctl(*args, timeout=15):
    try:
        out = subprocess.run(["systemctl", "--user", *args], capture_output=True, text=True, timeout=timeout)
        return out.returncode, out.stdout, out.stderr
    except (OSError, subprocess.SubprocessError) as exc:
        return 127, "", str(exc)


# -- pure helpers (tests/test_settings_startup.py) ----------------------------------------
def parse_show(text):
    """`systemctl show` output for several units -> {Id: {prop: value}}. A
    property that appears more than once (TimersCalendar= with two
    OnCalendar= lines) keeps every value, joined by a newline."""
    units, cur = {}, {}
    for line in text.splitlines() + [""]:
        if not line.strip():
            if cur.get("Id"):
                units[cur["Id"]] = cur
            cur = {}
            continue
        key, _, value = line.partition("=")
        cur[key] = cur[key] + "\n" + value if key in cur else value
    return units


def has_install(text):
    """A unit file with WantedBy= / RequiredBy= under [Install], i.e. one
    `systemctl enable` can switch on."""
    section = ""
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("["):
            section = line
        elif section == "[Install]" and re.match(r"(WantedBy|RequiredBy|UpheldBy)\s*=\s*\S", line):
            return True
    return False


def wanted(unit_dir):
    """Units the user's *.wants/ folders link, in order."""
    out = []
    try:
        for entry in sorted(os.listdir(unit_dir)):
            path = os.path.join(unit_dir, entry)
            if entry.endswith(".wants") and os.path.isdir(path):
                out += [u for u in sorted(os.listdir(path)) if u not in out]
    except OSError:
        pass
    return out


def installable(unit_dir):
    """Unit files in the folder that could be enabled (templates left out:
    their instances come from the links and KNOWN)."""
    out = []
    try:
        names = sorted(os.listdir(unit_dir))
    except OSError:
        return out
    for name in names:
        if not name.endswith((".service", ".timer")) or "@." in name:
            continue
        try:
            with open(os.path.join(unit_dir, name)) as handle:
                if has_install(handle.read()):
                    out.append(name)
        except OSError:
            pass
    return out


def remembered():
    try:
        with open(DISABLED) as handle:
            return [line.strip() for line in handle if line.strip()]
    except OSError:
        return []


def remember(unit, off):
    units = [u for u in remembered() if u != unit] + ([unit] if off else [])
    os.makedirs(STATE_DIR, exist_ok=True)
    tmp = DISABLED + ".tmp"
    with open(tmp, "w") as handle:
        handle.write("".join(u + "\n" for u in units))
    os.replace(tmp, DISABLED)


def desktop_units(unit_dir=UNIT_DIR):
    """Every unit the page lists: linked, installable here, KNOWN, or
    switched off by this script -- once each."""
    out = []
    for unit in wanted(unit_dir) + installable(unit_dir) + KNOWN + remembered():
        if unit not in out:
            out.append(unit)
    return out


SPANS = {"us": 1e-6, "ms": 1e-3, "s": 1, "sec": 1, "min": 60, "m": 60, "h": 3600, "hr": 3600,
         "d": 86400, "day": 86400, "w": 604800}


def span_text(text):
    """systemd's "1h 30min" / "5min" / "20s" in plain words."""
    secs = 0.0
    for num, unit in re.findall(r"([\d.]+)\s*([a-z]+)", text):
        secs += float(num) * SPANS.get(unit, 0)
    if secs <= 0:
        return text
    if secs < 90:
        return f"{secs:g} s"
    if secs < 5400:
        return f"{secs / 60:g} min"
    if secs < 172800:
        return f"{secs / 3600:g} h"
    return f"{secs / 86400:g} days"


MONO = {"OnActiveUSec": "{} after login", "OnStartupUSec": "{} after login", "OnBootUSec": "{} after boot",
        "OnUnitActiveUSec": "every {}", "OnUnitInactiveUSec": "{} after each run ends"}


def calendar_text(spec):
    """A normalized OnCalendar= in plain words, for the common shapes; the
    spec itself for anything else."""
    m = re.fullmatch(r"\*-\*-\* (\d\d):(\d\d):00", spec)
    if m:
        return f"every day at {m[1]}:{m[2]}"
    m = re.fullmatch(r"\*-\*-\* \*:(\d\d)/(\d+):00", spec)
    if m:
        return f"every {int(m[2])} min"
    if re.fullmatch(r"\*-\*-\* \*:00:00", spec):
        return "every hour"
    m = re.fullmatch(r"(\S+) \*-\*-\* (\d\d):(\d\d):00", spec)
    if m:
        return f"{m[1]} at {m[2]}:{m[3]}"
    return spec


def schedule_text(calendar, monotonic):
    """TimersCalendar= / TimersMonotonic= (systemctl show) in plain words,
    e.g. "every 15 min, 20 s after login"."""
    parts = []
    for line in (calendar or "").splitlines():
        m = re.search(r"OnCalendar=([^;]+?)\s*;", line)
        if m:
            parts.append(calendar_text(m[1].strip()))
    for line in (monotonic or "").splitlines():
        m = re.search(r"(On\w+USec)=([^;]+?)\s*;", line)
        if m:
            parts.append(MONO.get(m[1], m[1] + " {}").format(span_text(m[2])))
    # "every 5 min" first, the one-time "after login" after it
    parts.sort(key=lambda p: "after login" in p or "after boot" in p)
    return ", ".join(parts) or "?"


def service_state(p):
    """(word, ok): what a service is doing, in plain words."""
    active, sub = p.get("ActiveState", ""), p.get("SubState", "")
    if p.get("LoadState") == "not-found":
        return "its unit file is gone", False
    if active == "active":
        return ("done" if sub == "exited" else "running"), True
    if active == "failed":
        return f"failed ({p.get('Result') or '?'})", False
    if active in ("activating", "reloading"):
        return "starting", True
    if active == "deactivating":
        return "stopping", True
    if p.get("Type") == "oneshot" and p.get("Result") == "success":
        return "done", True
    return "stopped", p.get("Type") == "oneshot"


def is_enabled(file_state):
    return file_state in ("enabled", "enabled-runtime", "linked", "linked-runtime", "alias")


# -- XDG autostart -----------------------------------------------------------------------
def read_entry(text):
    """The [Desktop Entry] group's unlocalized keys."""
    out, group = {}, ""
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("["):
            group = s
        elif group == "[Desktop Entry]" and "=" in s and not s.startswith("#"):
            key, _, value = s.partition("=")
            if "[" not in key:
                out[key.strip()] = value.strip()
    return out


def listed(value):
    return [v for v in (value or "").split(";") if v]


def truthy(value):
    return (value or "").strip().lower() == "true"


def judge(entry, desktop=DESKTOP, which=None):
    """(on, switchable, reason) for one entry under `desktop`, by the
    generator's rules (see the top). `which` finds a program (shutil.which)."""
    if which is None:
        import shutil
        which = shutil.which
    if truthy(entry.get("X-systemd-skip")):
        return False, False, "started by GNOME's own session, never by systemd"
    only = listed(entry.get("OnlyShowIn"))
    if only and desktop not in only:
        return False, False, "only for " + ", ".join(only)
    tryexec = entry.get("TryExec")
    if tryexec and not which(os.path.expanduser(tryexec)):
        return False, False, f"not installed ({os.path.basename(tryexec)} is missing)"
    if truthy(entry.get("Hidden")):
        return False, True, "off in every desktop (Hidden=true)"
    if desktop in listed(entry.get("NotShowIn")):
        return False, True, f"off for {desktop}"
    return True, True, ""


def rewrite(text, on, desktop=DESKTOP):
    """The .desktop text with `desktop` taken out of (on) or added to (off)
    NotShowIn=, everything else kept as it was (translations, comments,
    other groups). On also turns Hidden=true into Hidden=false."""
    lines = text.splitlines()
    out, group, seen, entry_end = [], "", False, None
    for line in lines:
        s = line.strip()
        if s.startswith("["):
            if group == "[Desktop Entry]" and entry_end is None:
                entry_end = len(out)
            group = s
            out.append(line)
            continue
        if group == "[Desktop Entry]":
            key = s.partition("=")[0].strip()
            if key == "NotShowIn":
                seen = True
                names = [n for n in listed(s.partition("=")[2]) if n != desktop]
                if not on:
                    names.append(desktop)
                if names:
                    out.append("NotShowIn=" + ";".join(names) + ";")
                continue
            if key == "Hidden" and on and truthy(s.partition("=")[2]):
                out.append("Hidden=false")
                continue
        out.append(line)
    if group == "[Desktop Entry]" and entry_end is None:
        entry_end = len(out)
    if not seen and not on:
        at = entry_end if entry_end is not None else len(out)
        while at > 0 and not out[at - 1].strip():      # before the blank line ending the group
            at -= 1
        out.insert(at, f"NotShowIn={desktop};")
    return "\n".join(out) + "\n"


def escape_unit(name):
    """systemd-escape for one name (what the generator does to the .desktop
    file's base name): '-' and anything outside [A-Za-z0-9:_.] become \\xNN,
    a leading '.' too."""
    out = []
    for i, ch in enumerate(name):
        if (ch.isascii() and (ch.isalnum() or ch in ":_.")) and not (i == 0 and ch == "."):
            out.append(ch)
        else:
            out += [f"\\x{b:02x}" for b in ch.encode()]
    return "".join(out)


def app_unit(desktop_id):
    return f"app-{escape_unit(desktop_id.removesuffix('.desktop'))}@autostart.service"


def autostart_entries(user_dir=None, system_dirs=None, which=None):
    """Every autostart entry: the user's file wins over the system one of the
    same name (as the generator does). Sorted: on first, then by name."""
    user_dir = user_dir or USER_AUTOSTART
    system_dirs = SYSTEM_AUTOSTART if system_dirs is None else system_dirs
    files = {}
    for d in list(reversed(system_dirs)) + [user_dir]:
        try:
            names = os.listdir(d)
        except OSError:
            continue
        for name in names:
            if name.endswith(".desktop"):
                files.setdefault(name, []).append(os.path.join(d, name))
    out = []
    for name, paths in files.items():
        path = paths[-1]
        try:
            with open(path, errors="replace") as handle:
                entry = read_entry(handle.read())
        except OSError:
            continue
        on, switchable, reason = judge(entry, which=which)
        mine = path.startswith(user_dir + os.sep)
        where = ("system, changed by you" if mine and len(paths) > 1 else
                 "yours" if mine else "system")
        out.append({"id": name, "name": entry.get("Name") or name, "comment": entry.get("Comment", ""),
                    "exec": entry.get("Exec", ""), "on": on, "switchable": switchable, "reason": reason,
                    "where": where, "file": path, "unit": app_unit(name)})
    out.sort(key=lambda e: (not e["on"], not e["switchable"], e["name"].lower()))
    return out


def autostart_switch(desktop_id, on):
    name = desktop_id if desktop_id.endswith(".desktop") else desktop_id + ".desktop"
    entry = next((e for e in autostart_entries() if e["id"] == name), None)
    if entry is None:
        sys.exit(f"startup.py: no autostart entry {name}")
    if not entry["switchable"]:
        sys.exit(f"startup.py: {entry['name']} cannot be switched here: {entry['reason']}")
    with open(entry["file"], errors="replace") as handle:
        text = rewrite(handle.read(), on)
    os.makedirs(USER_AUTOSTART, exist_ok=True)
    target = os.path.join(USER_AUTOSTART, name)
    tmp = target + ".tmp"
    with open(tmp, "w") as handle:
        handle.write(text)
    os.replace(tmp, target)
    # The generator runs at daemon-reload; only then does the app's unit
    # carry the new NotShowIn= in its ExecCondition.
    systemctl("daemon-reload", timeout=30)
    systemctl("start" if on else "stop", "--no-block", entry["unit"])
    desklog.log("startup", f"autostart {name} {'on' if on else 'off'} for {DESKTOP}")


# -- Hyprland's own ----------------------------------------------------------------------
def comment_above(lines, index):
    """The -- comment block right above lines[index], as one paragraph."""
    out = []
    i = index - 1
    while i >= 0 and lines[i].strip().startswith("--"):
        out.insert(0, lines[i].strip()[2:].strip())
        i -= 1
    return " ".join(t for t in out if t)


def lua_execs(lua_dir=LUA_DIR):
    """[{cmd, when, why, file}] from lua/autostart.lua (exec lines and the
    fallback list) and hl.timer exec lines in every lua/*.lua."""
    out = []
    path = os.path.join(lua_dir, "autostart.lua")
    try:
        with open(path) as handle:
            text = handle.read()
    except OSError:
        text = ""
    lines = text.splitlines()
    m = re.search(r"local fallback_daemons\s*=\s*\{(.*?)\n\}", text, re.S)
    for cmd in re.findall(r'"([^"]+)"', m[1] if m else ""):
        out.append({"cmd": cmd, "when": "at login, plain Hyprland session only", "fallback": True,
                    "why": "the same program as a service above; used only when uwsm (and so systemd's "
                           "session) is not there", "file": "lua/autostart.lua"})
    for i, line in enumerate(lines):
        m = re.search(r'hl\.exec_cmd\("([^"]+)"\)', line)
        if m and not line.strip().startswith("--"):
            out.append({"cmd": m[1], "when": "once at login", "fallback": False,
                        "why": comment_above(lines, i), "file": "lua/autostart.lua"})
    try:
        names = sorted(os.listdir(lua_dir))
    except OSError:
        names = []
    timer = re.compile(r'hl\.timer\(function\(\)\s*hl\.exec_cmd\("([^"]+)"\)\s*end,\s*\{\s*timeout\s*=\s*(\d+)'
                       r'\s*,\s*type\s*=\s*"(\w+)"', re.S)
    for name in names:
        if not name.endswith(".lua"):
            continue
        try:
            with open(os.path.join(lua_dir, name)) as handle:
                body = handle.read()
        except OSError:
            continue
        for m in timer.finditer(body):
            secs = int(m[2]) / 1000
            when = (f"{span_text(f'{secs:g}s')} after every config load" if m[3] == "oneshot"
                    else f"every {span_text(f'{secs:g}s')}")
            out.append({"cmd": m[1], "when": when, "fallback": False,
                        "why": f"an hl.timer in lua/{name}", "file": f"lua/{name}"})
    return out


def process_running(cmd):
    """Is the command's program running now (by its executable's name)?"""
    words = cmd.split()
    if words and words[0] in ("python3", "python", "bash", "sh") and len(words) > 1:
        words = words[1:]
    if not words:
        return False
    prog = os.path.basename(os.path.expanduser(words[0]))
    try:
        return subprocess.run(["pgrep", "-f", "-u", str(os.getuid()), "--", prog],
                              capture_output=True, timeout=5).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


# -- gathering ---------------------------------------------------------------------------
def unit_props(units):
    if not units:
        return {}
    _, out, _ = systemctl("show", "--timestamp=unix", "-p", PROPS, *units)
    return parse_show(out)


def uptime():
    try:
        with open("/proc/uptime") as handle:
            return float(handle.read().split()[0])
    except (OSError, ValueError, IndexError):
        return None


def last_log(unit, lines=2):
    try:
        out = subprocess.run(["journalctl", "--user", "-u", unit, "-n", str(lines), "-o", "cat", "--no-pager"],
                             capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return ""
    return " / ".join(line.strip() for line in out.splitlines() if line.strip())[-200:]


def owner(p):
    frag = p.get("FragmentPath", "")
    if frag.startswith(UNIT_DIR + os.sep):
        return "this desktop's unit"
    return "Fedora's unit, with this desktop's changes" if p.get("DropInPaths") else "Fedora's unit"


def services(props=None):
    units = [u for u in desktop_units() if u.endswith(".service")]
    props = props if props is not None else unit_props(units)
    up = uptime()
    out = []
    for unit in units:
        p = props.get(unit, {"Id": unit, "LoadState": "not-found"})
        state, ok = service_state(p)
        since = None
        try:
            mono = int(p.get("ActiveEnterTimestampMonotonic") or 0) / 1e6
            if mono and up and p.get("ActiveState") == "active":
                since = max(0, int(up - mono))
        except ValueError:
            pass
        try:
            mem = int(p.get("MemoryCurrent", ""))
        except ValueError:
            mem = None
        out.append({"unit": unit, "title": TITLES.get(unit) or p.get("Description") or unit,
                    "description": p.get("Description", ""), "state": state, "ok": ok,
                    "enabled": is_enabled(p.get("UnitFileState", "")), "file_state": p.get("UnitFileState", ""),
                    "essential": ESSENTIAL.get(unit, ""), "oneshot": p.get("Type") == "oneshot",
                    "since_s": since, "memory": mem if mem and mem < 1 << 60 else None,
                    "restarts": int(p.get("NRestarts") or 0), "owner": owner(p),
                    # units a restart of this one takes along (their PartOf=
                    # names it): restarting waybar also restarts the toolbox
                    "parts": (p.get("ConsistsOf") or "").split(),
                    "log": "" if ok else last_log(unit)})
    return out


def list_timers():
    """{unit: {next, last}} in seconds since the epoch, from list-timers."""
    rc, out, _ = systemctl("list-timers", "--all", "-o", "json")
    try:
        rows = json.loads(out) if rc == 0 else []
    except ValueError:
        rows = []
    return {r["unit"]: {"next": (r.get("next") or 0) / 1e6 or None, "last": (r.get("last") or 0) / 1e6 or None}
            for r in rows if isinstance(r, dict) and r.get("unit")}


def timer_rows():
    units = [u for u in desktop_units() if u.endswith(".timer")]
    props = unit_props(units)
    jobs = [j for u in units for j in props.get(u, {}).get("Triggers", "").split()]
    job_props = unit_props(jobs)
    times = list_timers()
    calendar_on = None
    if "timers-calendar.timer" in units:
        try:
            import timers
            calendar_on = timers.calendar_on()
        except Exception:      # a broken timers.py must not take this page down
            calendar_on = None
    out = []
    for unit in units:
        p = props.get(unit, {})
        job = (p.get("Triggers") or "").split()
        jp = job_props.get(job[0], {}) if job else {}
        on = is_enabled(p.get("UnitFileState", ""))
        note = ""
        if unit == "timers-calendar.timer" and calendar_on is not None:
            on = on and calendar_on
            note = "" if calendar_on else "calendar alarms are off (timers.py calendar off)"
        t = times.get(unit, {})
        out.append({"unit": unit, "title": p.get("Description") or unit, "on": on,
                    "waiting": p.get("ActiveState") == "active", "schedule": schedule_text(
                        p.get("TimersCalendar"), p.get("TimersMonotonic")),
                    "next": t.get("next") if on else None, "last": t.get("last"),
                    "job": job[0] if job else "", "job_title": jp.get("Description", ""),
                    "job_result": jp.get("Result", ""), "job_running": jp.get("ActiveState") == "activating",
                    "route": " ".join(os.path.basename(a) for a in ROUTES[unit][0][:-1]) if unit in ROUTES else "",
                    "note": note})
    return out


def other_rows():
    """The rest of the user session, read-only: Fedora's own user services
    that run (sound, portals, ...; not the dbus-:* ones D-Bus starts on
    demand, nor the app-* autostart units listed on their own) and the user timers that are not the
    desktop's (systemd's housekeeping; timers.py's alarms only as a count)."""
    ours = set(desktop_units())
    _, out, _ = systemctl("list-units", "--type=service", "--state=running", "--plain", "--no-legend")
    rows = []
    for line in out.splitlines():
        parts = line.split(None, 4)
        if len(parts) >= 4 and parts[0] not in ours and not parts[0].startswith(("app-", "dbus-:")):
            rows.append({"unit": parts[0], "description": parts[4] if len(parts) > 4 else ""})
    times = list_timers()
    alarms = sum(1 for u in times if u.startswith("hypr-timer-"))
    system_timers = sorted(u for u in times if u not in ours and not u.startswith("hypr-timer-"))
    return {"services": rows, "alarms": alarms, "timers": system_timers}


def autostart_rows():
    entries = autostart_entries()
    props = unit_props([e["unit"] for e in entries])
    for e in entries:
        p = props.get(e["unit"], {})
        e["running"] = p.get("ActiveState") == "active" and p.get("SubState") == "running"
    return entries


def exec_rows():
    rows = lua_execs()
    for r in rows:
        r["running"] = False if r["fallback"] else process_running(r["cmd"])
    return rows


def session_managed():
    """True when uwsm runs the session (graphical-session.target is up), so
    the services above are what start the daemons."""
    return systemctl("is-active", "graphical-session.target")[1].strip() == "active"


def everything():
    return {"services": services(), "timers": timer_rows(), "autostart": autostart_rows(),
            "exec": exec_rows(), "other": other_rows(), "uwsm": session_managed()}


# -- changing ----------------------------------------------------------------------------
def known(unit):
    if unit not in desktop_units():
        sys.exit(f"startup.py: {unit} is not one of the desktop's units (startup.py services / timers)")


def full(unit):
    return unit if unit.endswith((".service", ".timer")) else unit + ".service"


def switch(unit, on, force=False):
    unit = full(unit)
    known(unit)
    if not on and unit in ESSENTIAL and not force:
        sys.exit(f"startup.py: {unit} is essential ({ESSENTIAL[unit]}); "
                 f"`startup.py disable {unit} --force` if you really mean it")
    if unit in ROUTES:
        cmd = ROUTES[unit][0 if on else 1]
        try:
            done = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            rc, err = done.returncode, done.stderr
        except (OSError, subprocess.SubprocessError) as exc:
            rc, err = 127, str(exc)
        if rc:
            sys.exit(f"startup.py: {os.path.basename(cmd[0])} failed: {err.strip() or rc}")
        if on and unit == "timers-calendar.timer":    # the flag alone does not bring back a disabled timer
            rc, _, err = systemctl("enable", "--now", unit, timeout=30)
            if rc:
                sys.exit(f"startup.py: {err.strip()}")
    else:
        rc, _, err = systemctl("enable" if on else "disable", "--now", unit, timeout=30)
        if rc:
            sys.exit(f"startup.py: {err.strip()}")
    remember(unit, not on)
    desklog.log("startup", f"{unit} {'enabled' if on else 'disabled'}" + (" (forced)" if force else ""))
    return rc


def main(argv):
    as_json = "--json" in argv
    args = [a for a in argv if a not in ("--json", "--force")]
    cmd = args[0] if args else "list"
    show = (lambda data: print(json.dumps(data, ensure_ascii=False))) if as_json else None
    if cmd == "list":
        data = everything()
        if show:
            show(data)
        else:
            print_all(data)
    elif cmd == "services":
        (show or print_services)(services())
    elif cmd == "timers":
        (show or print_timers)(timer_rows())
    elif cmd == "exec":
        (show or print_exec)(exec_rows())
    elif cmd == "autostart" and len(args) == 3 and args[1] in ("on", "off"):
        autostart_switch(args[2], args[1] == "on")
    elif cmd == "autostart":
        (show or print_autostart)(autostart_rows())
    elif cmd in ("enable", "disable") and len(args) == 2:
        switch(args[1], cmd == "enable", "--force" in argv)
    elif cmd == "restart" and len(args) == 2:
        unit = full(args[1])
        known(unit)
        rc, _, err = systemctl("restart", "--no-block", unit)
        desklog.log("startup", f"restarted {unit}" + (f": {err.strip()}" if rc else ""))
        sys.exit(f"startup.py: {err.strip()}" if rc else 0)
    elif cmd == "run" and len(args) == 2:
        unit = full(args[1]) if args[1].endswith(".timer") else args[1] + ".timer"
        known(unit)
        job = unit_props([unit]).get(unit, {}).get("Triggers", "").split()
        if not job:
            sys.exit(f"startup.py: {unit} has no job")
        rc, _, err = systemctl("start", "--no-block", job[0])
        desklog.log("startup", f"ran {job[0]} by hand" + (f": {err.strip()}" if rc else ""))
        sys.exit(f"startup.py: {err.strip()}" if rc else 0)
    else:
        sys.exit(__doc__)


# -- plain-text output -------------------------------------------------------------------
def print_services(rows):
    for s in rows:
        flag = "on " if s["enabled"] else "off"
        lock = "  [essential]" if s["essential"] else ""
        print(f"{flag}  {s['state']:<14} {s['unit']:<30} {s['title']}{lock}")


def print_timers(rows):
    for t in rows:
        nxt = time.strftime("%a %H:%M", time.localtime(t["next"])) if t["next"] else "-"
        print(f"{'on ' if t['on'] else 'off'}  next {nxt:<10} {t['unit']:<26} {t['schedule']}")


def print_autostart(rows):
    for e in rows:
        state = "on " if e["on"] else "off"
        print(f"{state}  {e['id']:<48} {e['name']}" + (f"  ({e['reason']})" if e["reason"] else ""))


def print_exec(rows):
    for r in rows:
        print(f"{r['when']:<40} {r['cmd']}")


def print_all(data):
    for title, fn, key in (("Services", print_services, "services"), ("Timers", print_timers, "timers"),
                           ("XDG autostart", print_autostart, "autostart"), ("Hyprland", print_exec, "exec")):
        print(f"== {title}")
        fn(data[key])


if __name__ == "__main__":
    main(sys.argv[1:])
