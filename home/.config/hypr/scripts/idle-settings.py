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
    idle-settings.py preview                 the hypridle.conf `set` would write now
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

Dim uses screen-color.py's `dim` (software, every screen, gone at the next
input); it has no backlight to turn down on these monitors.

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
            "suspend": 0, "lock_before_sleep": False, "password_on_wake": False}
TIMEOUTS = ("dim", "lock", "screens_off", "suspend", "off_after_lock")
SWITCHES = ("lock_before_sleep", "password_on_wake")


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
    for lst in parsed["listeners"]:
        kind, keys = lst["kind"], lst["keys"]
        if not kind:
            continue
        v[kind] = seconds(keys.get("timeout"))
        cmd = keys.get("on-timeout", "")
        if kind == "lock":
            m = re.search(r"--grace\s+(\d+)", cmd)
            v["grace"] = int(m.group(1)) if m else 0
        elif kind == "dim":
            m = re.search(r"dim\s+(\d+)", cmd)
            v["dim_level"] = int(m.group(1)) if m else DEFAULTS["dim_level"]
        elif kind == "screens_off":
            v["password_on_wake"] = "lock-session" in cmd or "hyprlock" in cmd
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


def problems(v):
    """Plain-English warnings about a combination that will not do what it
    looks like; the page shows them, `set` still writes what was asked."""
    out = []
    order = [(k, v[k]) for k in ("dim", "lock", "screens_off", "suspend") if v[k]]
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
    if v["password_on_wake"] and not v["screens_off"]:
        out.append("asking for the password when the screens wake needs \"Turn the screens off\" set to a time")
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
# {when}: dim every screen to {level} % of its brightness (screen-color.py dim,
# in software; there is no backlight on these monitors). Any input undoes it.
listener {{
    # idle-settings: dim
    timeout = {timeout}
    on-timeout = {sc} dim {level}
    on-resume = {sc} dim off
}}
""",
    "lock": """\
# {when}: lock.{grace_note}
# Calls hyprlock directly rather than going through loginctl, so that only this
# path gets the grace period (lock_cmd above is shared with sleep). SUPER+ALT+L
# runs plain hyprlock and locks at once.
listener {{
    # idle-settings: lock
    timeout = {timeout}
    on-timeout = pidof hyprlock || hyprlock{grace}
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
}


def summary(v):
    parts = []
    for key, name in (("dim", "dim"), ("lock", "lock"), ("screens_off", "screens off"), ("suspend", "suspend")):
        parts.append(f"{name} {minutes_text(v[key]) if v[key] else 'never'}")
    if v["off_after_lock"]:
        parts.append(f"screens off {minutes_text(v['off_after_lock'])} after a lock")
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
                                                       timeout=v["lock"], grace=f" --grace {g}" if g else "")))
    if v["off_after_lock"]:
        blocks.append((v["off_after_lock"], BLOCKS["off_after_lock"].format(
            when=minutes_text(v["off_after_lock"]), timeout=v["off_after_lock"], off=DPMS_OFF, on=DPMS_ON)))
    if v["screens_off"]:
        locked = v["lock"] and v["lock"] <= v["screens_off"]
        lock_first = "loginctl lock-session; sleep 1; " if v["password_on_wake"] else ""
        pw = ("\n# Locks first (loginctl lock-session, which runs lock_cmd), so waking them\n"
              "# asks for the password."
              if v["password_on_wake"] else "")
        blocks.append((v["screens_off"], BLOCKS["screens_off"].format(
            when=minutes_text(v["screens_off"]), timeout=v["screens_off"], pw_note=pw, lock_first=lock_first,
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
    # Shortest first, the way they happen; at equal times the order above.
    for _t, text in sorted(blocks, key=lambda b: b[0]):
        out.append(with_extras(text, parsed))
    kept = [lst for lst in parsed["listeners"] if not lst["kind"]] + [{"raw": r} for r in parsed["other"]]
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
        if key in ("dim", "lock", "screens_off", "suspend"):
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


def write_conf(text):
    old = read_conf()
    os.makedirs(STATE, exist_ok=True)
    if old:
        with open(PREV, "w") as handle:
            handle.write(old)
    tmp = CONF + ".tmp"
    with open(tmp, "w") as handle:
        handle.write(text)
    os.replace(tmp, CONF)
    run("systemctl", "--user", "restart", "hypridle.service")


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
                    "systemd-inhibit", "--what=idle", "--who=Keep awake", f"--why={why}", "--mode=block",
                    "sleep", str(mins * 60) if mins else "infinity"],
                   capture_output=True, timeout=10)
    os.makedirs(RUNTIME, exist_ok=True)
    with open(AWAKE_FILE, "w") as handle:
        json.dump({"until": until, "minutes": mins or None}, handle)


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
    out["nvidia_suspend"] = run("systemctl", "is-enabled", "nvidia-suspend.service").strip() or None
    return out


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
    return {"values": v, "problems": problems(v),
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
    elif cmd in ("set", "preview"):
        # One `set` at a time: each reads the file, changes it and writes it
        # whole, so two quick clicks on the page (two processes) would
        # otherwise both read the old file and the second would undo the
        # first. The lock is held until hypridle has restarted.
        if cmd == "set":
            os.makedirs(STATE, exist_ok=True)
            lock = open(os.path.join(STATE, "idle-settings.lock"), "w")
            fcntl.flock(lock, fcntl.LOCK_EX)
        parsed = parse(read_conf())
        try:
            v = apply_changes(values_from(parsed), args[1:])
        except ValueError as exc:
            sys.exit(f"idle-settings: {exc}")
        text = render(v, parsed)
        if cmd == "preview":
            print(text, end="")
        else:
            write_conf(text)
            for p in problems(v):
                print(f"note: {p}")
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
