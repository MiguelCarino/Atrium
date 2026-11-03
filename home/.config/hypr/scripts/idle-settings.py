#!/usr/bin/env python3
"""Idle timings, screen lock, Keep awake and the power profile -- the backend
of Settings > Power & screen lock, usable from a terminal or a key as well.

    idle-settings.py status                  JSON: everything below, as it is now
    idle-settings.py set <key> <value> [<key> <value> ...]
        dim | lock | screens_off | suspend   after how long idle: "never", minutes
                                             ("10"), or with a unit ("90s", "1h")
        off_after_lock    screens off this long after ANY lock ("30s", "never")
        grace             seconds after an idle lock in which input unlocks
                          without the password (0 = ask at once)
        dim_level         how dark the dim is, percent of your brightness (10-90)
        lock_before_sleep  on|off   lock the screen before the computer sleeps
        password_on_wake   on|off   screens going off on idle lock first
        battery_dim | battery_screens_off | battery_suspend
                          a shorter time for the same thing while the laptop
                          runs on its battery ("never" = as on the charger)
    idle-settings.py preview                 the hypridle.conf `set` would write now
    idle-settings.py laptop-defaults         dim 2 min, lock 5 min, screens off
                                             10 min, suspend 30 min, lock before
                                             sleep on (Settings: "Use laptop defaults")
    idle-settings.py init                    first run (install.sh): the laptop
                                             defaults on a laptop nobody has set
                                             up yet; prints what it did as JSON
    idle-settings.py battery-idle <dim|screens_off|suspend> [...]
                                             hypridle's battery listeners (below)
    idle-settings.py awake on [minutes] | off | status
                                             Keep awake: nothing dims, locks,
                                             turns off or sleeps on idle
    idle-settings.py profile [power-saver|balanced|performance]
                                             print or switch the power profile

hypridle.conf is the source of truth: there is no settings file of its own.
`status` reads the timings back out of ~/.config/hypr/hypridle.conf, `set`
writes the whole file again from the template below with the new values and
restarts hypridle.service (hypridle reads its config only at start). Hand
edits to the numbers in hypridle.conf therefore show up on the page as they
are.

What `set` keeps: every listener it does not manage -- one whose on-timeout is
not a dim, a lock, a screens-off or a suspend -- is copied back verbatim,
with the comment lines right above it, at the end of the file. So are the
general { } keys (lock_cmd, after_sleep_cmd, ignore_dbus_inhibit, ...);
before_sleep_cmd is the "lock before sleep" switch, and is kept as written
when it locks. While the screens go off exactly off_after_lock after the idle
lock (10 min + 30 s), changing either moves screens_off along (apply_changes
says why). A managed listener carries a "# idle-settings:
<kind>" line, so the next read knows it for certain; listeners written by
hand before this script existed are recognised by their commands (see
kind_of). The file before each write is kept in
$XDG_STATE_HOME/hypr/hypridle.conf.prev.

Dim uses screen-color.py's `dim` (every screen, gone at the next input): on
a laptop's built-in panel that lowers the real backlight (backlight.py), and
only falls back to the software colour matrix when the backlight cannot be
written; every other screen is dimmed in software.

Laptops. hypridle with no listener does nothing, which is what the shipped
hypridle.conf says (dim, lock, screens off and suspend all "never"): right for
a desktop on a desk, wrong for a laptop, which then never locks when left in
a cafe and runs its battery flat with the screen on. So a laptop
(power_state.has_battery(): its own battery, not a wireless mouse's) gets
LAPTOP below on its first run, and Settings has a "Use laptop defaults" button
for one set up before that. The first run is `init`, which install.sh runs
right after copying the files in. It is careful never to undo a choice. It
changes nothing unless all of these hold: this machine has a battery; the
file's timings are all "never" (the shipped ones); no `set` has ever been
recorded in $XDG_STATE_HOME/hypr/idle-settings.json; and the first login
has not happened yet (welcome.py's welcome-done marker is absent, and the page
has never written the file: no hypridle.conf.prev). That last check is why
init is not the same as "the timings are never". On a machine that has been
used, "never" may be what its owner wants, even if `set` never wrote it.
What init decides is recorded, so it decides only once -- except "desktop",
which it decides again each time (cheap, and a battery can be invisible for
a moment: a VM, a driver not bound yet). One more case: install.sh copies the
shipped file over hypridle.conf on every run, so after an update init puts
back the timings this script last wrote ($XDG_STATE_HOME/hypr/
hypridle.conf.written) when the file is the untouched shipped "never" one
(replaced_by_shipped says how it tells). It restarts hypridle only when it
is already running (try-restart). install.sh may run from another desktop's
session, where starting hypridle would lock GNOME's screen.

On battery. hypridle has one set of timeouts and no idea of power: it cannot
switch to shorter ones when the charger comes out. Restarting it with another
file on every plug or unplug would reset every idle clock, and something
would have to watch the charger to do it. Instead each battery timing is one
more listener at the shorter timeout whose on-timeout is
`idle-settings.py battery-idle <what>`. That reads power_state.on_battery()
(a few sysfs files, no process started) and acts only on battery: it dims,
turns the screens off (locking first when "ask for the password" is on) or
suspends, using the same commands as the listeners for the charger. On the
charger it exits. Cost: one Python start (about 30 ms) when an idle stretch
reaches that timeout, and one when input ends it. That happens a few times
an hour at most, never per tick. Unplugging after the battery timeout has
passed in the same idle stretch does nothing until the next stretch:
hypridle fires a listener once per stretch, and the charger timings still
apply. The screens-off one leaves a flag in $XDG_RUNTIME_DIR/idle-battery/,
so its on-resume turns the screens back on only when it turned them off. An
unguarded DPMS on is a full modeset on some cards (see the off_after_lock
template). For the same reason the charger's screens-off listener goes
through battery-idle too ("screens_off always") while a battery one exists:
an idle stretch on battery past both would otherwise end in two dpms-ons.
The flag is taken under a lock, against hypridle's on-timeout and on-resume
racing each other (_screens says how). A battery screens-off sooner than the
idle lock locks first ("prelock"): the lock was coming anyway, and blanking
an unlocked desktop is one mouse move from showing it.

Keep awake is a transient user unit, keep-awake.service, holding a systemd
"idle" inhibitor lock (systemd-inhibit --what=idle). hypridle honours those
(ignore_systemd_inhibit is false unless set), so while it runs no listener
fires. It is not a sleep lock: Suspend from the power menu still works. It
lasts until turned off, for the minutes given, or until you log out --
deliberately not across a login, like any "keep awake" switch. The toolbox's
Keep awake row is the same switch: it runs `idle-settings.py awake on|off`
and shows `awake status` (waybar/scripts/toolbox_awake.py), so the toolbox,
this page and the search bar always agree.

The power profile goes through net.hadess.PowerProfiles on the system bus,
which on Fedora is tuned-ppd (tuned's power-profiles-daemon stand-in;
powerprofilesctl is not installed). polkit lets the active session switch it
without a password, and tuned-ppd remembers it across reboots. The CPU's
power draw comes from cpu-power.service (a system service, when installed),
which publishes a 5-second average in /run/cpu-power/watts.
"""
import fcntl
import json
import os
import re
import subprocess
import sys
import time

CONF = os.path.expanduser("~/.config/hypr/hypridle.conf")
STATE = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"), "hypr")
PREV = os.path.join(STATE, "hypridle.conf.prev")
RUNTIME = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
AWAKE_FILE = os.path.join(RUNTIME, "keep-awake.json")
AWAKE_UNIT = "keep-awake.service"
# Run by systemd when keep-awake.service ends -- its minutes are up, or it is
# stopped -- so the toolbox's Keep awake pill (custom/awake) redraws then,
# not at its next poll.
AWAKE_REDRAW = f"/usr/bin/python3 {os.path.join(os.path.dirname(os.path.abspath(__file__)), 'bar_signals.py')} poke awake"
SCREEN_COLOR = "~/.config/hypr/scripts/screen-color.py"     # the shell in hypridle expands ~
CPU_WATTS = "/run/cpu-power/watts"

# The Lua dispatch: this machine configures Hyprland in Lua, where the classic
# `hyprctl dispatch dpms off` is a syntax error.
DPMS_OFF = "hyprctl dispatch 'hl.dsp.dpms({ on = false })'"
DPMS_ON = "hyprctl dispatch 'hl.dsp.dpms({ on = true })'"

PP_BUS = ["busctl", "--system", "--json=short"]
PP_ARGS = ["net.hadess.PowerProfiles", "/net/hadess/PowerProfiles", "net.hadess.PowerProfiles"]
PROFILES = ["power-saver", "balanced", "performance"]

# What the file says when a value is missing, i.e. hypridle's own behaviour
# with no listener: nothing happens. Seconds; 0 = never.
DEFAULTS = {"dim": 0, "dim_level": 40, "lock": 0, "grace": 0, "off_after_lock": 0, "screens_off": 0,
            "suspend": 0, "lock_before_sleep": False, "password_on_wake": False,
            "battery_dim": 0, "battery_screens_off": 0, "battery_suspend": 0}
# The shorter timings for the battery (0 = as on the charger) -> what they do.
BATTERY = {"battery_dim": "dim", "battery_screens_off": "screens_off", "battery_suspend": "suspend"}
TIMEOUTS = ("dim", "lock", "screens_off", "suspend", "off_after_lock") + tuple(BATTERY)
SWITCHES = ("lock_before_sleep", "password_on_wake")
# A laptop's first run and the "Use laptop defaults" button. These are the
# usual laptop timings (GNOME and macOS ship close to them): dim before the
# lock, so you get a warning and can nudge the mouse; the screen off a little
# after the lock; and sleep long enough after that not to interrupt a download
# left running over lunch. Locking before sleep is on because the lid and the
# power menu suspend too. Grace, the dim level and the rest are left as they
# are.
LAPTOP = {"dim": 120, "lock": 300, "screens_off": 600, "suspend": 1800, "lock_before_sleep": True}
# What `set` and `init` remember. hypridle.conf still holds every timing;
# this file only says whether anyone ever chose them.
RECORD = os.path.join(STATE, "idle-settings.json")
WELCOME_DONE = os.path.join(STATE, "welcome-done")       # welcome.py: the first login has happened
BATTERY_FLAGS = os.path.join(RUNTIME, "idle-battery")    # battery-idle: "I turned the screens off"
# battery-idle's tombstone window, seconds: an on-resume that found nothing
# to undo less than this long before an on-timeout ran means the two raced
# (input as the timeout fired), and the timeout must not turn the screens
# off. Far below any idle timeout (a minute or more), far above a Python
# start.
RACE = 5
SELF = "python3 ~/.config/hypr/scripts/idle-settings.py"  # the shell in hypridle expands ~


# ------------------------------- reading the file -------------------------------

def parse(text):
    """hypridle.conf -> {"general": [(key, value)], "listeners": [...], "other": [raw blocks]}.

    Each listener is {"keys": {key: value}, "raw": [lines], "kind": ...}, where
    raw is the block itself with the comment lines directly above it (no blank
    line between), so a listener that is kept goes back exactly as it was.
    Comments inside blocks belong to the block; the file's header and the
    comments of managed listeners are the template's to write."""
    out = {"general": [], "listeners": [], "other": []}
    lines = text.splitlines()
    pending = []                     # comment lines waiting for the block below them
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        m = re.match(r"^([\w-]+)\s*\{\s*$", stripped)
        if m:
            name = m.group(1)
            raw = pending + [line]
            pending = []
            keys = {}
            i += 1
            while i < len(lines) and lines[i].strip() != "}":
                raw.append(lines[i])
                kv = re.match(r"^\s*([\w:-]+)\s*=\s*(.*?)\s*$", lines[i])
                if kv and not lines[i].strip().startswith("#"):
                    keys[kv.group(1)] = kv.group(2)
                i += 1
            if i < len(lines):
                raw.append(lines[i])
            if name == "general":
                out["general"] = list(keys.items())
            elif name == "listener":
                out["listeners"].append({"keys": keys, "raw": raw, "kind": kind_of(keys, raw)})
            else:
                out["other"].append(raw)
        elif stripped.startswith("#"):
            pending.append(line)
        else:
            pending = []
        i += 1
    return out


def kind_of(keys, raw):
    """Which of our timeouts a listener is, or None for one we leave alone.
    The marker line first; then the commands, for files written by hand."""
    for line in raw:
        m = re.match(r"^\s*#\s*idle-settings:\s*([\w_]+)", line)
        if m and m.group(1) in TIMEOUTS:
            return m.group(1)
    cmd = keys.get("on-timeout", "")
    # First: "battery-idle dim 40" would otherwise pass for a dim below.
    # "screens_off always" is the charger's own screens-off, routed through
    # the same flag when a battery one exists too (see render).
    if re.search(r"idle-settings\.py\s+battery-idle\s+screens_off\s+always\b", cmd):
        return "screens_off"
    m = re.search(r"idle-settings\.py\s+battery-idle\s+(dim|screens_off|suspend)\b", cmd)
    if m:
        return f"battery_{m.group(1)}"
    if "screen-color.py dim" in cmd:
        return "dim"
    if "systemctl suspend" in cmd or "loginctl suspend" in cmd:
        return "suspend"
    if "dpms" in cmd and "on = false" in cmd.replace('"', "'") or re.search(r"dpms\W+off", cmd):
        return "off_after_lock" if re.match(r"^\s*pidof hyprlock\s*&&", cmd) else "screens_off"
    if "hyprlock" in cmd or "lock-session" in cmd:
        return "lock"
    return None


def seconds(value):
    try:
        return max(0, int(float(value)))
    except (TypeError, ValueError):
        return 0


def values_from(parsed):
    """The page's values, read back out of a parsed file."""
    v = dict(DEFAULTS)
    general = dict(parsed["general"])
    v["lock_before_sleep"] = "lock" in general.get("before_sleep_cmd", "")
    # The battery listeners carry the dim level and "lock first" too, which
    # count only when there is no charger listener to read them from (a
    # laptop that dims on battery only).
    from_battery = {}
    for lst in parsed["listeners"]:
        kind, keys = lst["kind"], lst["keys"]
        if not kind:
            continue
        v[kind] = seconds(keys.get("timeout"))
        cmd = keys.get("on-timeout", "")
        if kind == "battery_dim":
            m = re.search(r"battery-idle\s+dim\s+(\d+)", cmd)
            if m:
                from_battery["dim_level"] = int(m.group(1))
        elif kind == "battery_screens_off":
            # "lock" is "ask for the password"; "prelock" is render's own
            # lock-first for a battery screens-off sooner than the idle lock,
            # which says nothing about that switch.
            from_battery["password_on_wake"] = bool(re.search(r"battery-idle\s+screens_off\s+lock\b", cmd))
        elif kind == "lock":
            m = re.search(r"--grace\s+(\d+)", cmd)
            v["grace"] = int(m.group(1)) if m else 0
        elif kind == "dim":
            m = re.search(r"dim\s+(\d+)", cmd)
            v["dim_level"] = int(m.group(1)) if m else DEFAULTS["dim_level"]
        elif kind == "screens_off":
            v["password_on_wake"] = ("lock-session" in cmd or "hyprlock" in cmd
                                     or bool(re.search(r"battery-idle\s+screens_off\s+always\s+lock\b", cmd)))
    if not v["dim"] and "dim_level" in from_battery:
        v["dim_level"] = from_battery["dim_level"]
    if not v["screens_off"] and "password_on_wake" in from_battery:
        v["password_on_wake"] = from_battery["password_on_wake"]
    return v


def read_conf(path=None):
    try:
        with open(path or CONF) as handle:     # CONF looked up now, so tests can point it elsewhere
            return handle.read()
    except OSError:
        return ""


# ------------------------------- writing the file -------------------------------

def minutes_text(s):
    if not s:
        return "never"
    if s % 3600 == 0:
        return f"{s // 3600} h"
    if s % 60 == 0:
        return f"{s // 60} min"
    if s > 60:
        return f"{s // 60} min {s % 60} s"
    return f"{s} s"


def parse_duration(text):
    """"never"/"off"/"0" -> 0; "10" -> 600 (minutes); "90s", "15m", "1h",
    "1.5h" -> seconds. ValueError for anything else."""
    t = str(text).strip().lower()
    if t in ("never", "off", "0", "none", ""):
        return 0
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(s|sec|secs|m|min|mins|h|hr|hrs)?", t)
    if not m:
        raise ValueError(f"not a duration: {text!r} (minutes, or 90s / 15m / 1h, or never)")
    n, unit = float(m.group(1)), (m.group(2) or "m")[0]
    return int(round(n * {"s": 1, "m": 60, "h": 3600}[unit]))


def on_battery_times(v):
    """What happens when on battery: each battery timing, or the charger's
    where it is 0. A battery timing longer than the charger's changes
    nothing, because the charger's listener fires first either way."""
    out = {}
    for key, what in BATTERY.items():
        own, ac = v.get(key, 0), v[what]
        out[what] = min(own, ac) if own and ac else (own or ac)
    return out


def problems(v, has_battery=True):
    """Plain-English warnings about a combination that will not do what it
    looks like; the page shows them, `set` still writes what was asked.
    HAS_BATTERY is False only for a machine without one (status says),
    where any battery timing is dead weight."""
    out = []
    order = [(k, v[k]) for k in ("dim", "lock", "screens_off", "suspend") + tuple(BATTERY) if v.get(k)]
    if v["dim"] and v["lock"] and v["dim"] >= v["lock"]:
        out.append("the dim comes after the lock, so you will only see it on the lock screen")
    if v["dim"] and v["screens_off"] and v["dim"] >= v["screens_off"]:
        out.append("the screens turn off before they would dim, so the dim never shows")
    if v["suspend"] and not (v["lock_before_sleep"] or (v["lock"] and v["lock"] < v["suspend"])):
        out.append("the computer sleeps on idle without locking: anyone can use it when it wakes")
    if v["screens_off"] and not v["password_on_wake"] and not (v["lock"] and v["lock"] <= v["screens_off"]):
        out.append("the screens go off without a lock: moving the mouse brings back the open desktop")
    if any(t < 60 for k, t in order):
        out.append("a timeout under a minute can fire while you are reading")
    if v["password_on_wake"] and not (v["screens_off"] or v.get("battery_screens_off")):
        out.append("asking for the password when the screens wake needs \"Turn the screens off\" set to a time")
    if not any(v.get(k) for k in BATTERY):
        return out
    if not has_battery:
        out.append("this computer has no battery, so the battery timings never apply")
        return out
    names = {"dim": "dimming", "screens_off": "turning the screens off", "suspend": "sleeping"}
    for key, what in BATTERY.items():
        if v.get(key) and v[what] and v[key] >= v[what]:
            out.append(f"on battery, {names[what]} is not sooner than on the charger, so it changes nothing")
    bat = on_battery_times(v)
    # The same two checks as above, for the battery's own timings. Each is
    # said only once: when the charger check above already said it, the
    # battery one would only repeat it.
    said = " ".join(out)
    if (v.get("battery_suspend") and "sleeps on idle without locking" not in said
            and not (v["lock_before_sleep"] or (v["lock"] and v["lock"] < bat["suspend"]))):
        out.append("on battery the computer sleeps on idle without locking: anyone can use it when it wakes")
    # Any idle lock is enough here: a battery screens-off sooner than the lock
    # locks first (render's "prelock"), and a later one finds it locked.
    if (v.get("battery_screens_off") and "brings back the open desktop" not in said and not v["password_on_wake"]
            and not v["lock"]):
        out.append("on battery the screens go off without a lock: moving the mouse brings back the open desktop")
    if v.get("battery_dim") and bat["screens_off"] and bat["dim"] >= bat["screens_off"]:
        out.append("on battery the screens turn off before they would dim, so the dim never shows")
    return out


HEADER = """\
# hypridle -- idle timings. Runs as hypridle.service (see lua/autostart.lua).
#
# WRITTEN BY ~/.config/hypr/scripts/idle-settings.py (Settings > Power &
# screen lock, SUPER+I). Change the timings there or with
#     idle-settings.py set lock 10 screens_off never ...
# Hand edits to the numbers below are fine too -- the page reads them back from
# this file, which is the only place they are kept -- but the comments and the
# order are rewritten on the next change from the page. Your own listeners
# (anything that is not a dim, lock, screens-off or suspend) are kept as they
# are, at the end of the file. The previous version is in
# ~/.local/state/hypr/hypridle.conf.prev.
#
# Now:  {summary}
#
# Nothing sleeps on its own unless "suspend" below has a listener: logind's own
# IdleAction is "ignore" on this machine (checked 2026-10), so suspend only
# happens from the power menu or from that listener, and before_sleep_cmd locks
# first in both cases (when "lock before sleep" is on).
#
# lock_cmd uses pidof as a guard so a second trigger cannot stack a second
# hyprlock on top of the first -- without it, an idle event arriving while the
# screen is already locked leaves you with two lockers to dismiss.
#
# before_sleep_cmd locks *before* suspend rather than after, so the machine is
# never briefly unlocked while it wakes.
#
# after_sleep_cmd turns the displays back on. Waking does not implicitly undo
# a DPMS off, and without this the monitors can stay dark until you move the
# mouse.
#
# Every dispatch is Lua because this machine configures Hyprland in Lua -- the
# classic `hyprctl dispatch dpms off` form is a syntax error here. Same trap
# that broke the waybar workspace clicks; see the workspaces notes in
# ~/.config/waybar/config.
#
# Things that hold all of this off: a fullscreen window and Steam games
# (idle_inhibit rules in lua/rules.lua), browsers and mpv while they play, the
# toolbox's Keep awake, and Keep awake in Settings (idle-settings.py awake).
#
# On a laptop the first run (idle-settings.py init) writes the laptop
# timings, unless you have already chosen your own. The "on battery" listeners
# are shorter timings that act only while running on the battery: each one
# checks the power supply when it fires, and exits on the charger.
"""

GENERAL = """\
general {{
    # No --grace here. lock_cmd is what `loginctl lock-session` runs, and
    # before_sleep_cmd goes through it too: with a grace period on this line,
    # the lock taken just before suspend could still be inside its grace
    # window on wake, so touching the mouse would unlock with no password.
    # The grace period is for idle locks only -- see the lock listener.
{body}}}
"""

BLOCKS = {
    "dim": """\
# {when}: dim every screen to {level} % of its brightness (screen-color.py
# dim). Any input undoes it.
listener {{
    # idle-settings: dim
    timeout = {timeout}
    on-timeout = {sc} dim {level}
    on-resume = {sc} dim off
}}
""",
    "lock": """\
# {when}: lock.{grace_note}
{how}
listener {{
    # idle-settings: lock
    timeout = {timeout}
    on-timeout = {lock}
}}
""",
    "off_after_lock": """\
# Screens off {when} after ANY lock -- by hand (SUPER+ALT+L, the power menu) or
# the idle lock. hypridle timeouts count idle time from the last input and each
# fires once per idle stretch: the key press that locked resets the clock, so
# {when} later the screens go dark, but only if hyprlock is actually up
# (pidof); unlocked, {when} idle does nothing. The idle lock gets a listener of
# its own below ("screens off"), because this one has already fired by then.
listener {{
    # idle-settings: off_after_lock
    timeout = {timeout}
    on-timeout = pidof hyprlock && {off}
    # Guarded like on-timeout. Unguarded, every short idle stretch while
    # UNLOCKED ended with a dpms-on to screens that were already on, which on
    # this NVIDIA card is a full modeset: all three went black for a moment on
    # the first mouse move. Input wakes the screens anyway (*_enables_dpms).
    on-resume = pidof hyprlock && {on}
}}
""",
    "screens_off": """\
# {when}: screens off.{after_lock}{pw_note}
# Any input brings them back (on-resume here, plus misc.mouse_move_enables_dpms
# and key_press_enables_dpms in lua/settings.lua){where}.
listener {{
    # idle-settings: screens_off
    timeout = {timeout}
    on-timeout = {lock_first}{off}
    on-resume = {on}
}}
""",
    # The charger's screens-off when a battery one exists too: on battery,
    # an idle stretch past both fires both, and two dpms-on dispatches at the
    # next input is the modeset flash the off_after_lock template is about.
    # Both go through battery-idle's one flag instead, so exactly one of the
    # two on-resumes turns the screens back on.
    "screens_off_shared": """\
# {when}: screens off.{after_lock}{pw_note}
# Through battery-idle ("always": on the charger too) because there is a
# battery screens-off as well: they share one "the screens are off" flag, so
# at the next input exactly one dpms-on is sent, not two. Any input also wakes
# the screens by itself (misc.mouse_move_enables_dpms and key_press_enables_dpms
# in lua/settings.lua){where}.
listener {{
    # idle-settings: screens_off
    timeout = {timeout}
    on-timeout = {self} battery-idle screens_off always{lock_arg}
    on-resume = {self} battery-idle screens_off resume
}}
""",
    "suspend": """\
# {when}: suspend.
# before_sleep_cmd {sleep_note}.
# after_sleep_cmd turns the screens back on.
listener {{
    # idle-settings: suspend
    timeout = {timeout}
    on-timeout = systemctl suspend
}}
""",
    "battery_dim": """\
# {when}, on battery only: dim every screen to {level} %.{battery_note}
listener {{
    # idle-settings: battery_dim
    timeout = {timeout}
    on-timeout = {self} battery-idle dim {level}
    on-resume = {sc} dim off
}}
""",
    "battery_screens_off": """\
# {when}, on battery only: screens off.{pw_note}{battery_note}
# Its on-resume turns them back on only if battery-idle turned them off.
listener {{
    # idle-settings: battery_screens_off
    timeout = {timeout}
    on-timeout = {self} battery-idle screens_off{lock_arg}
    on-resume = {self} battery-idle screens_off resume
}}
""",
    "battery_suspend": """\
# {when}, on battery only: suspend.{battery_note}
# before_sleep_cmd {sleep_note}.
listener {{
    # idle-settings: battery_suspend
    timeout = {timeout}
    on-timeout = {self} battery-idle suspend
}}
""",
}

# Under each battery listener: why it fires on the charger too.
BATTERY_NOTE = ("\n# hypridle cannot switch timings when the charger comes out, so this fires\n"
                "# on the charger too; battery-idle checks power_state.on_battery() (a few\n"
                "# sysfs reads) and does nothing while plugged in.")


# Why the idle lock is written the way it is: the usual way (loginctl
# lock-session, the same lock as SUPER+ALT+L, presence.py and sleep), or, only
# with a grace period, hyprlock itself -- lock_cmd is shared with sleep and
# must never carry a grace.
LOCK_HOW = {False: "# The usual way: loginctl lock-session, which runs lock_cmd above (the same\n"
                   "# lock as SUPER+ALT+L, the power menu and sleep; pidof keeps it to one).",
            True: "# Calls hyprlock directly rather than going through loginctl, so that only this\n"
                  "# path gets the grace period (lock_cmd above is shared with sleep). SUPER+ALT+L\n"
                  "# goes through loginctl lock-session (lock_cmd) and locks at once."}


def lock_command(grace):
    """The idle lock listener's on-timeout: `loginctl lock-session` (logind
    knows the session is locked, lock_cmd's pidof guard stops a second
    hyprlock), or hyprlock itself when there is a grace period, which only
    hyprlock's own --grace can give."""
    grace = seconds(grace)
    return f"pidof hyprlock || hyprlock --grace {grace}" if grace else "loginctl lock-session"


# Listeners other scripts need: written when the file has none calling that
# script yet, and from then on kept like any listener of your own (a hand
# edit to one stays). Each costs one `test` while its service is off.
# The command it calls -> the block.
COMPANIONS = {
    "screentime-idle": """\
# 60 s: "no keyboard or mouse" for screentime.py (Settings > Screen time), so
# the minutes away from the computer do not count as screen time. Only a word
# to its socket (scripts/screentime-idle, sh + ncat); with the service off
# there is no socket and nothing runs past one test. Not managed by
# idle-settings.py.
listener {
    timeout = 60
    on-timeout = ~/.config/hypr/scripts/screentime-idle on
    on-resume = ~/.config/hypr/scripts/screentime-idle off
}""",
}


def missing_companions(parsed):
    """The COMPANIONS blocks no listener of the file calls yet, as kept
    listeners ({"raw": lines})."""
    have = "\n".join("\n".join(lst["raw"]) for lst in parsed["listeners"])
    return [{"raw": block.splitlines()} for marker, block in COMPANIONS.items() if marker not in have]


def summary(v):
    parts = []
    for key, name in (("dim", "dim"), ("lock", "lock"), ("screens_off", "screens off"), ("suspend", "suspend")):
        parts.append(f"{name} {minutes_text(v[key]) if v[key] else 'never'}")
    if v["off_after_lock"]:
        parts.append(f"screens off {minutes_text(v['off_after_lock'])} after a lock")
    bat = [f"{name} {minutes_text(v[key])}" for key, name in
           (("battery_dim", "dim"), ("battery_screens_off", "screens off"), ("battery_suspend", "suspend"))
           if v.get(key)]
    if bat:
        parts.append("on battery " + ", ".join(bat))
    return ", ".join(parts)


def render(v, parsed):
    """The whole new hypridle.conf for values v, keeping from parsed what is
    not ours. Pure: no file is read or written here."""
    out = [HEADER.format(summary=summary(v))]
    body = []
    general = [(k, val) for k, val in parsed["general"] if k != "before_sleep_cmd"]
    keys = dict(general)
    keys.setdefault("lock_cmd", "pidof hyprlock || hyprlock")
    keys.setdefault("after_sleep_cmd", DPMS_ON)
    order = ["lock_cmd"] + (["before_sleep_cmd"] if v["lock_before_sleep"] else []) + ["after_sleep_cmd"]
    if v["lock_before_sleep"]:
        # A hand-written one that already locks ("loginctl lock-session;
        # playerctl pause") is what values_from read as "on": keep it.
        own = dict(parsed["general"]).get("before_sleep_cmd", "")
        keys["before_sleep_cmd"] = own if "lock" in own else "loginctl lock-session"
    else:
        body.append("    # Lock before sleep is off: waking from suspend lands on the open desktop.")
    for k in order + [k for k in keys if k not in order]:
        body.append(f"    {k} = {keys[k]}")
    out.append(GENERAL.format(body="\n".join(body) + "\n"))

    blocks = []
    if v["dim"]:
        blocks.append((v["dim"], BLOCKS["dim"].format(when=minutes_text(v["dim"]), level=v["dim_level"],
                                                     timeout=v["dim"], sc=SCREEN_COLOR)))
    if v["lock"]:
        g = v["grace"]
        note = (f"\n# --grace {g}: any input in the first {g} seconds after an idle lock unlocks\n"
                f"# without a password, so nudging the mouse as the lock fades in does not\n"
                f"# cost you a login." if g else " No grace period: the password is asked at once.")
        blocks.append((v["lock"], BLOCKS["lock"].format(when=minutes_text(v["lock"]), grace_note=note,
                                                       timeout=v["lock"], how=LOCK_HOW[bool(g)],
                                                       lock=lock_command(g))))
    if v["off_after_lock"]:
        blocks.append((v["off_after_lock"], BLOCKS["off_after_lock"].format(
            when=minutes_text(v["off_after_lock"]), timeout=v["off_after_lock"], off=DPMS_OFF, on=DPMS_ON)))
    if v["screens_off"]:
        locked = v["lock"] and v["lock"] <= v["screens_off"]
        lock_first = "loginctl lock-session; sleep 1; " if v["password_on_wake"] else ""
        pw = ("\n# Locks first (loginctl lock-session, which runs lock_cmd), so waking them\n"
              "# asks for the password."
              if v["password_on_wake"] else "")
        shared = bool(v.get("battery_screens_off"))
        blocks.append((v["screens_off"], BLOCKS["screens_off_shared" if shared else "screens_off"].format(
            when=minutes_text(v["screens_off"]), timeout=v["screens_off"], pw_note=pw, lock_first=lock_first,
            self=SELF, lock_arg=" lock" if v["password_on_wake"] else "",
            after_lock=(f" That is {minutes_text(v['off_after_lock'])} after the idle lock: the listener\n"
                        "# for locks by hand has already fired by then and will not fire again until\n"
                        "# there is input, so the idle lock needs this one."
                        if v["lock"] and v["off_after_lock"] and v["screens_off"] == v["lock"] + v["off_after_lock"]
                        else ""),
            off=DPMS_OFF, on=DPMS_ON,
            where=", straight onto the lock screen" if locked or v["password_on_wake"] else "")))
    if v["suspend"]:
        blocks.append((v["suspend"], BLOCKS["suspend"].format(
            when=minutes_text(v["suspend"]), timeout=v["suspend"],
            sleep_note="locks first" if v["lock_before_sleep"] else "is off, so it does NOT lock first")))
    if v.get("battery_dim"):
        blocks.append((v["battery_dim"], BLOCKS["battery_dim"].format(
            when=minutes_text(v["battery_dim"]), timeout=v["battery_dim"], level=v["dim_level"],
            self=SELF, sc=SCREEN_COLOR, battery_note=BATTERY_NOTE)))
    if v.get("battery_screens_off"):
        # Sooner than the idle lock, it locks first anyway ("prelock"): the
        # lock was coming at v["lock"] regardless, and blanking an unlocked
        # desktop on battery is the "save battery" click that leaves it open
        # to the next mouse move. With no idle lock at all, it does not lock
        # (problems() says so).
        early = not v["password_on_wake"] and v["lock"] and v["battery_screens_off"] < v["lock"]
        blocks.append((v["battery_screens_off"], BLOCKS["battery_screens_off"].format(
            when=minutes_text(v["battery_screens_off"]), timeout=v["battery_screens_off"], self=SELF,
            lock_arg=" lock" if v["password_on_wake"] else " prelock" if early else "",
            battery_note=BATTERY_NOTE,
            pw_note=(" Locks first, so waking them asks for the password." if v["password_on_wake"] else
                     ("\n# Locks first: this comes before the idle lock, which would lock by then"
                                         "\n# anyway.") if early else ""))))
    if v.get("battery_suspend"):
        blocks.append((v["battery_suspend"], BLOCKS["battery_suspend"].format(
            when=minutes_text(v["battery_suspend"]), timeout=v["battery_suspend"], self=SELF,
            battery_note=BATTERY_NOTE,
            sleep_note="locks first" if v["lock_before_sleep"] else "is off, so it does NOT lock first")))
    # Shortest first, the way they happen; at equal times the order above.
    for _t, text in sorted(blocks, key=lambda b: b[0]):
        out.append(with_extras(text, parsed))
    kept = [lst for lst in parsed["listeners"] if not lst["kind"]] + [{"raw": r} for r in parsed["other"]]
    kept += missing_companions(parsed)
    if kept:
        out.append("# ---- kept as they were (not managed by idle-settings.py) ----\n")
        for lst in kept:
            out.append("\n".join(lst["raw"]) + "\n")
    return "\n".join(out)


OURS = ("timeout", "on-timeout", "on-resume")


def with_extras(block, parsed):
    """A managed listener keeps the keys the template does not write
    (ignore_inhibit, condition_cmd, ...) from the listener it replaces."""
    kind = re.search(r"# idle-settings: (\w+)", block).group(1)
    for lst in parsed["listeners"]:
        if lst["kind"] == kind:
            extra = [f"    {k} = {val}" for k, val in lst["keys"].items() if k not in OURS]
            if extra:
                block = block[:block.rindex("}")] + "\n".join(extra) + "\n}\n"
            break
    return block


def linked(v):
    """True when screens_off is "off_after_lock after the idle lock" -- the
    630 = 600 + 30 pair this machine started with. See apply_changes."""
    return bool(v["lock"] and v["off_after_lock"] and v["screens_off"] == v["lock"] + v["off_after_lock"])


def apply_changes(v, pairs):
    """New values from <key> <value> pairs; ValueError with a readable message.

    The screens-off listener follows the lock: while it sits exactly
    off_after_lock after the idle lock (linked), changing "lock" or
    "off_after_lock" moves it along unless the same call also sets
    screens_off. Otherwise "lock 15" would leave the screens going off at
    10½ min onto an unlocked desktop, and "Screens off after locking: 1 min"
    would still turn them off 30 s after an idle lock -- the 30 s listener
    has already fired by then (see the off_after_lock template)."""
    was_linked = linked(v)
    v = dict(v)
    if len(pairs) % 2:
        raise ValueError("give <key> <value> pairs")
    keys = [k.replace("-", "_").lower() for k in pairs[::2]]
    for key, value in zip(pairs[::2], pairs[1::2]):
        key = key.replace("-", "_").lower()
        if key in ("dim", "lock", "screens_off", "suspend") + tuple(BATTERY):
            v[key] = parse_duration(value)
        elif key == "off_after_lock":
            v[key] = parse_duration(value if re.search(r"[a-z]", str(value)) else f"{value}s")
        elif key == "grace":
            v[key] = max(0, min(60, seconds(value)))
        elif key == "dim_level":
            v[key] = max(10, min(90, seconds(value)))
        elif key in SWITCHES:
            if str(value).lower() not in ("on", "off", "true", "false", "1", "0", "yes", "no"):
                raise ValueError(f"{key} is on or off, not {value!r}")
            v[key] = str(value).lower() in ("on", "true", "1", "yes")
        else:
            raise ValueError(f"unknown setting {key!r} ({', '.join(TIMEOUTS + SWITCHES + ('grace', 'dim_level'))})")
    if was_linked and "screens_off" not in keys and v["lock"] and v["off_after_lock"]:
        v["screens_off"] = v["lock"] + v["off_after_lock"]
    return v


def write_conf(text, restart="restart"):
    """Write hypridle.conf whole and make hypridle read it. RESTART is
    systemctl's verb: "restart" for a change from the page (it starts a
    stopped hypridle too), "try-restart" for init (see the docstring)."""
    old = read_conf()
    os.makedirs(STATE, exist_ok=True)
    if old:
        with open(PREV, "w") as handle:
            handle.write(old)
    os.makedirs(os.path.dirname(CONF), exist_ok=True)
    for path in (written_path(), CONF):
        tmp = path + ".tmp"
        with open(tmp, "w") as handle:
            handle.write(text)
        os.replace(tmp, path)
    run("systemctl", "--user", restart, "hypridle.service")


def written_path():
    """$XDG_STATE_HOME/hypr/hypridle.conf.written: the file exactly as this
    script last wrote it (PREV is the one before). init uses it to put the
    timings back after install.sh copied the shipped file over them; see
    replaced_by_shipped. Looked up at call time, like CONF, for the tests."""
    return os.path.join(STATE, "hypridle.conf.written")


def replaced_by_shipped(text):
    """The values to put back when TEXT (hypridle.conf now) is the shipped
    all-"never" file copied over timings this script wrote, else None.

    install.sh copies the repo's home/ over $HOME on every run, which is how
    people update. Until it excludes an existing hypridle.conf (it should:
    the file is user state, like desktop.conf), each update replaces the
    laptop timings init wrote, or the ones chosen on the page, with the
    shipped never/never/never/never, and the record would then make init
    answer "already" for good: a laptop that silently stops locking after its
    first update. So it is put back, but only when all of this holds, which
    a choice of the user's cannot look like:
      - this script wrote timings before (the .written copy has some);
      - the file now has none at all, battery ones included;
      - the file is an untouched render: its "# Now:" line still describes
        its own listeners. A hand edit to "never" removes listeners and
        leaves the old summary (or no header at all), so it is kept, and a
        "never" chosen on the page was written by us, so .written says never
        too.
    The listeners that are not ours come from the file now (the shipped one
    may bring new companions), the timings from .written."""
    try:
        with open(written_path()) as handle:
            ours = handle.read()
    except OSError:
        return None
    if ours == text:
        return None
    managed = ("dim", "lock", "screens_off", "suspend", "off_after_lock") + tuple(BATTERY)
    before = values_from(parse(ours))
    now = values_from(parse(text))
    if not any(before[k] for k in managed) or any(now[k] for k in managed):
        return None
    if f"# Now:  {summary(now)}\n" not in text:
        return None
    return before


def read_record():
    """$XDG_STATE_HOME/hypr/idle-settings.json: {"chosen_at": epoch of the
    last `set`, "init_at": epoch, "init": what init decided}, or {}."""
    try:
        with open(RECORD) as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def write_record(**changes):
    data = read_record()
    data.update(changes)
    os.makedirs(os.path.dirname(RECORD), exist_ok=True)
    tmp = f"{RECORD}.{os.getpid()}.tmp"
    with open(tmp, "w") as handle:
        json.dump(data, handle)
    os.replace(tmp, RECORD)
    return data


def change(pairs, restart="restart"):
    """`set`: read, change, write, under the lock. One `set` at a time: each
    reads the file, changes it and writes it whole, so two quick clicks on
    the page (two processes) would otherwise both read the old file and the
    second would undo the first. The lock is held until hypridle has
    restarted. Returns the new values; ValueError for bad pairs."""
    os.makedirs(STATE, exist_ok=True)
    with open(os.path.join(STATE, "idle-settings.lock"), "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        parsed = parse(read_conf())
        v = apply_changes(values_from(parsed), pairs)
        write_conf(render(v, parsed), restart)
    return v


def laptop_pairs():
    """LAPTOP as `set` pairs ("dim", "120s", ...)."""
    out = []
    for key, value in LAPTOP.items():
        out += [key, ("on" if value else "off") if isinstance(value, bool) else f"{value}s"]
    return out


def _power_state():
    """power_state.py, from this folder (the name has no dash: importable)."""
    here = os.path.dirname(os.path.abspath(__file__))
    if here not in sys.path:
        sys.path.insert(0, here)
    import power_state
    return power_state


def init():
    """The first run on this machine (install.sh): LAPTOP when it is a
    laptop that nobody has set up yet, else nothing. Returns what it decided
    as {"init": word, "why": text}. It runs once: the decision is recorded,
    and a recorded decision or `set` is final. See the module docstring for
    why each condition is there."""
    record = read_record()
    text = read_conf()
    back = replaced_by_shipped(text) if record.get("init") == "laptop" or record.get("chosen_at") else None
    if back:
        os.makedirs(STATE, exist_ok=True)
        with open(os.path.join(STATE, "idle-settings.lock"), "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            write_conf(render(back, parse(read_conf())), restart="try-restart")
        write_record(restored_at=int(time.time()))
        return {"init": "restored", "why": "install.sh copied the shipped file over your timings: put back "
                                           + summary(back)}
    # "desktop" is not final: a battery can be missing for a moment (a VM, a
    # toolbox, the ACPI driver not bound yet), and deciding again costs one
    # sysfs read.
    if record.get("init") in ("laptop", "kept") or record.get("chosen_at"):
        return {"init": "already", "why": "decided before" if record.get("init") else "you set the timings",
                "record": record}
    if not _power_state().has_battery():
        decided = ("desktop", "no battery: the timings stay as shipped")
    elif any(values_from(parse(text))[k] for k in ("dim", "lock", "screens_off", "suspend")):
        decided = ("kept", "the timings in hypridle.conf are already someone's choice")
    elif os.path.exists(WELCOME_DONE):
        decided = ("kept", "this desktop has been used already (first login done): \"never\" may be meant")
    elif os.path.exists(PREV) or os.path.exists(written_path()):
        # Every write from the page leaves these: the page has been used, so
        # "never" may be meant even without welcome.py's marker (a machine
        # installed before welcome.py, or one that never wrote it).
        decided = ("kept", "Settings has written hypridle.conf before: \"never\" may be meant")
    else:
        change(laptop_pairs(), restart="try-restart")
        decided = ("laptop", "laptop: dim 2 min, lock 5 min, screens off 10 min, suspend 30 min")
    write_record(init=decided[0], init_at=int(time.time()))
    return {"init": decided[0], "why": decided[1]}


def battery_idle(args, on_battery=None, execute=None):
    """The battery listeners' commands (see the module docstring):

        battery-idle dim <level>             dim, on battery only
        battery-idle screens_off [lock|prelock]
                                             screens off (lock first), on battery only
        battery-idle screens_off always [lock]
                                             the same on the charger too: the charger's
                                             own screens-off when a battery one exists
        battery-idle screens_off resume      screens on, if one of the lines above
                                             turned them off
        battery-idle suspend                 suspend, on battery only

    Returns the shell command it runs (None: nothing to do), so the tests
    can see the decision; EXECUTE (default: exec sh -c, which replaces this
    process, so no second one is started) runs it. ON_BATTERY defaults to
    power_state.on_battery."""
    what = args[0] if args else ""
    rest = args[1:]
    if what not in ("dim", "screens_off", "suspend"):
        raise ValueError(f"battery-idle takes dim, screens_off or suspend, not {what!r}")
    execute = execute or (lambda c: os.execvp("sh", ["sh", "-c", c]))
    if what == "screens_off":
        return _screens(rest, on_battery, execute)
    if not (on_battery or _power_state().on_battery)():
        return None
    if what == "dim":
        level = max(10, min(90, seconds(rest[0]) if rest else DEFAULTS["dim_level"]))
        cmd = f"{SCREEN_COLOR} dim {level}"
    else:
        cmd = "systemctl suspend"
    execute(cmd)
    return cmd


def _screens(rest, on_battery, execute):
    """battery-idle screens_off: the flag, under a lock.

    hypridle starts on-timeout and on-resume without waiting for either, so
    input arriving just as the timeout fires can run the resume (nothing to
    undo yet) before the timeout's Python has even started -- which would
    then turn the screens off under an active user and leave a flag for a
    later, unguarded dpms-on. Hence, in $XDG_RUNTIME_DIR/idle-battery/:
      lock         flock()ed by both sides around the flag. The timeout keeps
                   it through the exec, until its dpms-off (and the second of
                   "lock first") is done, so a resume racing it waits and then
                   turns the screens back on, in that order.
      screens_off  "the screens are off because of us": hypridle's pid, so a
                   flag left by an hypridle that has since been restarted
                   (Settings restarts it on every change) or killed is stale
                   and sends no dpms-on.
      resumed      a resume that found no flag: a timeout that runs less than
                   RACE seconds later lost the race and does nothing.
    All of it is a few small files in a tmpfs; no process is started."""
    flag = os.path.join(BATTERY_FLAGS, "screens_off")
    tomb = os.path.join(BATTERY_FLAGS, "resumed")
    start = time.time()
    resume = rest[:1] == ["resume"]
    always = rest[:1] == ["always"]
    if always:
        rest = rest[1:]
    if not (resume or always or (on_battery or _power_state().on_battery)()):
        return None
    os.makedirs(BATTERY_FLAGS, exist_ok=True)
    lock = open(os.path.join(BATTERY_FLAGS, "lock"), "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX)
        me = str(hypridle_pid() or "")
        try:
            with open(flag) as handle:
                owner = handle.read().strip()
        except OSError:
            owner = None
        if resume:
            # No battery check here: if the charger went in while the screens
            # were off, they still need to come back on.
            if owner is None:
                with open(tomb, "w") as handle:
                    handle.write(f"{start}\n")
                return None
            os.remove(flag)
            if owner and me and owner != me:
                return None                       # an earlier hypridle's flag
            cmd = DPMS_ON
        else:
            try:
                raced = os.path.getmtime(tomb) >= start - RACE
                os.remove(tomb)
            except OSError:
                raced = False
            if raced:
                return None
            lock_first = rest[:1] in (["lock"], ["prelock"])
            if owner is not None and (not owner or not me or owner == me):
                # Already off: the battery one fired first in this stretch.
                if not lock_first:
                    return None
                cmd = "loginctl lock-session"
            else:
                with open(flag, "w") as handle:
                    handle.write(me)
                cmd = ("loginctl lock-session; sleep 1; " if lock_first else "") + DPMS_OFF
        # Through the exec: sh and hyprctl inherit the lock (see above).
        os.set_inheritable(lock.fileno(), True)
        execute(cmd)
        return cmd
    finally:
        lock.close()


def hypridle_pid():
    """The pid of the hypridle that runs us: up our parents (sh -c, maybe a
    second sh) in /proc, or None when hypridle is not among them (a
    terminal, the tests)."""
    pid = os.getppid()
    for _ in range(4):
        try:
            with open(f"/proc/{pid}/stat") as handle:
                stat = handle.read()
        except OSError:
            return None
        if stat[stat.index("(") + 1:stat.rindex(")")] == "hypridle":
            return pid
        pid = int(stat[stat.rindex(")") + 2:].split()[1])
        if pid <= 1:
            return None
    return None


# --------------------------------- the rest ---------------------------------

def run(*cmd, timeout=5):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def unit_props(unit, *props, system=False):
    out = run("systemctl", *([] if system else ["--user"]), "show", unit, *[f"-p{p}" for p in props])
    return dict(line.split("=", 1) for line in out.splitlines() if "=" in line)


def awake_status():
    on = unit_props(AWAKE_UNIT, "ActiveState").get("ActiveState") == "active"
    until = minutes = None
    if on:
        try:
            with open(AWAKE_FILE) as handle:
                saved = json.load(handle)
            until, minutes = saved.get("until"), saved.get("minutes")
        except (OSError, ValueError, AttributeError):
            pass
    return {"on": on, "until": until, "minutes": minutes}


def awake(state, minutes=None):
    run("systemctl", "--user", "stop", AWAKE_UNIT)
    run("systemctl", "--user", "reset-failed", AWAKE_UNIT)
    if state == "off":
        try:
            os.remove(AWAKE_FILE)
        except OSError:
            pass
        return
    mins = seconds(minutes) if minutes else 0
    until = time.time() + mins * 60 if mins else None
    why = (f"Keep awake until {time.strftime('%H:%M', time.localtime(until))}" if until
           else "Keep awake is on (Settings > Power)")
    subprocess.run(["systemd-run", "--user", "--quiet", "--collect", f"--unit={AWAKE_UNIT}",
                    "--description=Keep awake (idle-settings.py)",
                    f"--property=ExecStopPost={AWAKE_REDRAW}",
                    "systemd-inhibit", "--what=idle", "--who=Keep awake", f"--why={why}", "--mode=block",
                    "sleep", str(mins * 60) if mins else "infinity"],
                   capture_output=True, timeout=10)
    os.makedirs(RUNTIME, exist_ok=True)
    with open(AWAKE_FILE, "w") as handle:
        json.dump({"until": until, "minutes": mins or None}, handle)
    redraw_awake()


def redraw_awake():
    """The toolbox's Keep awake pill, now (bar_signals "awake"). Turning it
    off needs no call here: the unit's ExecStopPost does it."""
    try:
        here = os.path.dirname(os.path.abspath(__file__))
        if here not in sys.path:
            sys.path.insert(0, here)
        import bar_signals
        bar_signals.poke("awake")
    except Exception:       # noqa: BLE001 - no bar, nothing to redraw
        pass


def holders():
    """Who is keeping the screens awake right now, as far as hypridle can see:
    systemd idle locks, and the org.freedesktop.ScreenSaver inhibits that the
    running hypridle has logged (browsers, mpv); the toolbox's Keep awake is
    the keep-awake.service lock, so it is here. Wayland inhibitors -- the
    fullscreen / Steam rules -- are Hyprland's own and
    never reach hypridle's log, so they are not in this list."""
    out = []
    try:
        data = json.loads(run(*PP_BUS[:3], "call", "org.freedesktop.login1", "/org/freedesktop/login1",
                              "org.freedesktop.login1.Manager", "ListInhibitors") or "{}")
        for what, who, why, mode, _uid, _pid in data.get("data", [[]])[0]:
            if "idle" in what.split(":") and mode == "block":
                out.append({"who": who, "why": why})
    except (ValueError, TypeError, IndexError):
        pass
    pid = unit_props("hypridle.service", "MainPID").get("MainPID", "0")
    if pid != "0":
        held = {}
        for line in run("journalctl", "--user", f"_PID={pid}", "-o", "cat", "--no-pager", "-n", "2000").splitlines():
            m = re.search(r"ScreenSaver inhibit: (true|false) dbus message from (\S+) \(owner: (\S+)\) "
                          r"with content (.*)$", line)
            if re.search(r"Inhibit locks: 0\b", line):
                held = {}           # hypridle's own count: nothing at all held
            if m:
                key = (m.group(3), m.group(4))
                if m.group(1) == "true":
                    held[key] = m.group(2)
                else:
                    held.pop(key, None)
        out += [{"who": who, "why": why} for (_owner, why), who in held.items()]
    return out


def profile_status():
    data = {"active": None, "profiles": [], "degraded": ""}
    try:
        got = json.loads(run(*PP_BUS, "get-property", *PP_ARGS, "ActiveProfile") or "null")
        data["active"] = got and got.get("data")
        got = json.loads(run(*PP_BUS, "get-property", *PP_ARGS, "Profiles") or "null")
        data["profiles"] = [p["Profile"]["data"] for p in (got or {}).get("data", [])]
        got = json.loads(run(*PP_BUS, "get-property", *PP_ARGS, "PerformanceDegraded") or "null")
        data["degraded"] = (got or {}).get("data", "")
    except (ValueError, TypeError, KeyError):
        pass
    try:
        with open(CPU_WATTS) as handle:
            data["cpu_watts"] = float(handle.read().strip())
    except (OSError, ValueError):
        data["cpu_watts"] = None
    try:
        with open("/sys/devices/system/cpu/cpu0/cpufreq/energy_performance_preference") as handle:
            data["epp"] = handle.read().strip()
    except OSError:
        data["epp"] = None
    return data


def set_profile(name):
    if name not in PROFILES:
        sys.exit(f"idle-settings: profile is one of {', '.join(PROFILES)}")
    r = subprocess.run(["busctl", "--system", "set-property", *PP_ARGS, "ActiveProfile", "s", name],
                       capture_output=True, text=True, timeout=10)
    if r.returncode:
        sys.exit(f"idle-settings: could not switch the profile: {r.stderr.strip()}")


def logind():
    out = {}
    for prop in ("HandlePowerKey", "HandleSuspendKey", "IdleAction"):
        try:
            got = json.loads(run("busctl", "--system", "--json=short", "get-property", "org.freedesktop.login1",
                                 "/org/freedesktop/login1", "org.freedesktop.login1.Manager", prop) or "null")
            out[prop] = got["data"]
        except (ValueError, TypeError, KeyError):
            out[prop] = None
    try:
        with open("/sys/power/mem_sleep") as handle:
            m = re.search(r"\[(\w+)\]", handle.read())
            out["mem_sleep"] = m.group(1) if m else None
    except OSError:
        out["mem_sleep"] = None
    out["nvidia_suspend"] = nvidia_suspend_state(run("systemctl", "is-enabled", "nvidia-suspend.service"))
    return out


def nvidia_suspend_state(text):
    """`systemctl is-enabled nvidia-suspend.service` -> "enabled" / "disabled"
    / ... or None when there is no such unit (an AMD or Intel machine, or
    NVIDIA without its suspend helpers packaged): systemd answers
    "not-found", or nothing at all on stdout, and neither means "off"."""
    word = (text or "").strip().splitlines()[0].strip() if (text or "").strip() else ""
    return None if word in ("", "not-found") else word


def status():
    parsed = parse(read_conf())
    v = values_from(parsed)
    hyp = unit_props("hypridle.service", "ActiveState", "ActiveEnterTimestamp")
    general = dict(parsed["general"])
    sc = unit_props("screen-color.service", "ActiveState", "ActiveEnterTimestampMonotonic")
    try:
        sc_script = os.path.getmtime(os.path.expanduser(SCREEN_COLOR))
        started = time.time() - (time.monotonic() - int(sc.get("ActiveEnterTimestampMonotonic", "0")) / 1e6)
        dim_ready = sc.get("ActiveState") == "active" and started > sc_script
    except (OSError, ValueError):
        dim_ready = False
    ps = _power_state()
    battery = ps.has_battery()
    power = {"has_battery": battery, "on_battery": ps.on_battery(),
             # What happens on battery right now, each timing or the charger's.
             "on_battery_times": on_battery_times(v) if battery else None}
    return {"values": v, "problems": problems(v, battery), "power": power,
            "laptop_defaults": LAPTOP, "record": read_record(),
            "kept": [lst["raw"] for lst in parsed["listeners"] if not lst["kind"]],
            "hypridle": {"state": hyp.get("ActiveState"), "since": hyp.get("ActiveEnterTimestamp"),
                         "ignores_systemd_inhibit": general.get("ignore_systemd_inhibit", "false") == "true"},
            "dim_ready": dim_ready, "awake": awake_status(), "holders": holders(),
            "profile": profile_status(), "logind": logind(), "conf": CONF}


def main():
    args = sys.argv[1:]
    cmd = args[0] if args else "status"
    if cmd == "status":
        print(json.dumps(status(), indent=1))
    elif cmd == "battery-idle":
        # First of all, and before anything slow: hypridle runs this.
        try:
            battery_idle(args[1:])
        except ValueError as exc:
            sys.exit(f"idle-settings: {exc}")
    elif cmd == "preview":
        parsed = parse(read_conf())
        try:
            v = apply_changes(values_from(parsed), args[1:])
        except ValueError as exc:
            sys.exit(f"idle-settings: {exc}")
        print(render(v, parsed), end="")
    elif cmd in ("set", "laptop-defaults"):
        try:
            v = change(args[1:] if cmd == "set" else laptop_pairs())
        except ValueError as exc:
            sys.exit(f"idle-settings: {exc}")
        # From now on these are someone's choice: init never touches them.
        # A bare `set` (Settings > Screen time adding its listener) changes
        # no timing, so it is not a choice.
        if cmd == "laptop-defaults" or args[1:]:
            write_record(chosen_at=int(time.time()))
        for p in problems(v, _power_state().has_battery()):
            print(f"note: {p}")
    elif cmd == "init":
        print(json.dumps(init()))
    elif cmd == "awake" and len(args) >= 2 and args[1] in ("on", "off"):
        awake(args[1], args[2] if len(args) > 2 else None)
    elif cmd == "awake":
        print(json.dumps(awake_status()))
    elif cmd == "profile" and len(args) == 2:
        set_profile(args[1])
    elif cmd == "profile":
        print(profile_status()["active"] or "unknown")
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
