#!/usr/bin/env python3
"""The battery saver: one switch that makes the desktop cheaper to run, by
hand or by itself when the battery runs low.

    battery-saver.py on        switch it on (why=manual)
    battery-saver.py off       switch it off, putting back what was there
    battery-saver.py on|off --why rule
                               the same for an automation rule
                               (automations.py's battery-saver action)
    battery-saver.py toggle    on when off, off when on (for a key bind)
    battery-saver.py auto      what power-watch.py runs after every power
                               change: on / off by the battery settings
    battery-saver.py status    JSON: the saver's state, the battery, the
                               settings, and what `auto` would do now

on, off and toggle print the same JSON as status afterwards (plus "errors"
when a part of the switch failed, each also on stderr, with exit status 1).

What "on" does
--------------
  * the power profile goes to power-saver, through `idle-settings.py profile`
    (net.hadess.PowerProfiles, tuned-ppd on Fedora) -- the same path the
    Power page uses, so there is one way the profile is ever switched. The
    profile it was on before is remembered (previous_profile). When the
    current profile cannot be read (tuned-ppd slow on the bus just after a
    resume -- asked twice), the profile is left alone and that is reported:
    the saver never makes a change it would not know how to undo.
  * the compositor draws less: blur and shadows off, every animation leaf
    disabled, direct scanout on for fullscreen windows. That is Lua
    (lua/batterysaver.lua, which says why each one and why NOT
    animations.enabled = false, gamemode's switch): this writes the state
    file and runs `hyprctl eval 'require("lua.batterysaver").apply()'`.
    lua/display.lua and lua/gamemode.lua read the same file at every config
    load, so a reload, a theme switch or gamemode OFF keep the saver's look
    while it is on -- nothing here has to re-apply it after them.
  * the moving wallpaper stops moving: wallpaper-slideshow.py pauses its
    players (a still frame stays on screen) whenever power_state.frugal()
    -- on battery OR the saver on -- and does not start new ones then.
  * everything that backs off on battery (power_state.period()) backs off
    with the saver on too: frugal() is on_battery() or saver_active().

What "off" puts back
--------------------
The look is not restored from a list of remembered values: off writes the
file saying inactive and runs the same Lua apply, which lays the THEME's look
(lua/display.lua: your theme, your hyprlook overrides, your animation preset,
the ambient calm level if one is set) down again. A value written down when
the saver went on could be stale by the time it goes off -- you may have
switched theme in between -- the config cannot be. Gamemode is respected the
same way: while it is on, display.lua leaves the options it strips alone
and the scanout value is gamemode's, so switching the saver off mid-game
neither brings blur back into the game nor turns tearing / scanout off;
gamemode OFF later reloads into the full look.

The profile goes back to previous_profile -- but only when it is still
power-saver: a profile you picked yourself while the saver was on is your
decision and stays.

Automatic ("auto")
------------------
power-watch.py runs `battery-saver.py auto` after every power change (the
charger, the status, each percent). The settings are Settings > Battery's
($XDG_STATE_HOME/hypr/battery.json, power_state.load_settings()):
  * on battery and capacity <= saver_auto_at (0 = never)  -> on, why=auto
  * on battery and saver_on_unplug                        -> on, why=unplug
  * plugged in, and why is auto / unplug / rule           -> off
A saver you switched on yourself (why=manual) is never switched off by this:
plugging in does not undo a decision. Switching on automatically sends one
notification saying why, so the slower desktop is never a mystery.

"Plugged in" is asked positively (plugged() below): the charger's own
online when the firmware lists one, else the battery's status (Charging,
Full, Not charging). It is NOT "not on_battery()": that one says False
whenever it is unsure -- this ASUS reports Unknown or Not charging with the
charger already out for a moment around an unplug or a resume -- and one
such reading would switch an automatic saver off (and back on a uevent
later, with a second notification) and forget what you had declined. When
neither side is sure, auto does nothing.

An automation rule (automations.py, `on|off --why rule`) is not you: its
"on" is undone by plugging in like saver_auto_at's and never turns an
automatic saver into a manual one; its "off" is not a "no" that holds off
saver_auto_at (nothing is declined). A rule's "on" sends no notification:
you wrote the rule, and a rule can notify of its own.

Switching it OFF yourself while on battery is a decision too: the reasons
that held at that moment are written down (declined) and `auto` does not
switch the saver back on for them until the charger is plugged in -- else
the next percent's uevent would undo your "off" a minute later. A NEW reason
still counts: off at 50 % with saver_on_unplug declines "unplug", and
reaching saver_auto_at later still switches it on, with why=auto.

State
-----
$XDG_RUNTIME_DIR/battery-saver.json (power_state.SAVER_STATE), written whole:
    {"active": bool, "why": "manual"|"auto"|"unplug"|"rule"|"", "since": epoch (0 when off),
     "previous_profile": "balanced"|...|null, "declined": ["auto", "unplug"]}
In the runtime dir on purpose: the compositor's look and the paused
wallpaper belong to the login, so the saver's state does too. It lasts as
long as the runtime dir -- until your LAST session ends: with lingering, an
ssh login or a second session open, a Hyprland restarted from the greeter
finds the file still saying active and starts in the saver's look (its
config load reads the file), and `off` -- or plugging in, for an automatic
one -- undoes it as usual. That is consistent, just not "a re-login is a
clean slate".

The power profile is the one thing that outlives the runtime dir: tuned-ppd
keeps it across reboots, so a shutdown at low battery with the saver on
would leave power-saver behind with previous_profile gone. So the profile
the saver still owes is ALSO written to $XDG_STATE_HOME/hypr/
battery-saver-profile.json ({"previous_profile": ...}) while the saver
holds it, and deleted when the saver gives it back. Finding that file with
the runtime state saying inactive means a session ended under the saver:
the next command (power-watch's first `auto` at login is one) puts the
profile back -- only when it is still power-saver, as `off` does -- and
deletes the file; `auto` may then switch the saver on again, fresh.

One command at a time: a lock beside the state file, so power-watch's
`auto` and a key press arriving together cannot both read the old state.

A desktop PC never sees any of this happen by itself: with no battery,
`auto` returns before it takes the lock and writes nothing (unless a
profile is still owed from an `on` by hand before a reboot).
`on` still works there by hand (a quieter, cheaper desktop is not only a
battery thing).
"""
import fcntl
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import power_state  # noqa: E402  (sysfs reads, the settings, the state file's path)
import desk_common  # noqa: E402  (atomic JSON, notifications, Hyprland's socket)

IDLE_SETTINGS = os.path.join(HERE, "idle-settings.py")     # `profile [NAME]`: the one profile switch
SAVER_PROFILE = "power-saver"
PROFILES = ("power-saver", "balanced", "performance")
LUA_APPLY = 'require("lua.batterysaver").apply()'
REASONS = ("manual", "auto", "unplug", "rule")    # automations.py reads this line: "rule" = takes --why rule
AUTO_REASONS = ("auto", "unplug", "rule")         # the ones plugging in undoes
DECLINABLE = ("auto", "unplug")                   # the ones an `off` by hand can decline
PLUGGED_STATUSES = power_state.PLUGGED_STATUSES          # the "charger connected" statuses
RETRY_S = 1.0                                     # before asking for the profile a second time
APP = "Battery"                          # the notification's app: power-watch.py's warnings use it too


def state_path():
    """power_state's path, read at call time (the tests point
    $XDG_RUNTIME_DIR at a scratch folder before importing either)."""
    return power_state.SAVER_STATE


def lock_path():
    return os.path.splitext(state_path())[0] + ".lock"


def owed_path():
    """The profile the saver still owes, beside Settings > Battery's
    battery.json: in $XDG_STATE_HOME, so it outlives a reboot (see the
    module's docstring)."""
    return os.path.join(os.path.dirname(power_state.SETTINGS_FILE), "battery-saver-profile.json")


def read_owed():
    raw = desk_common.read_json(owed_path(), {}, typed=True)
    return raw.get("previous_profile") if raw.get("previous_profile") in PROFILES else None


def write_owed(profile):
    desk_common.atomic_write_json(owed_path(), {"previous_profile": profile})


def drop_owed():
    try:
        os.remove(owed_path())
    except FileNotFoundError:
        pass


# -- the state file ------------------------------------------------------------------
def read_state():
    """The saver's state with every key checked: a missing, broken or
    hand-edited file reads as "off", which is the side nothing has to be
    undone from."""
    raw = desk_common.read_json(state_path(), {}, typed=True)
    active = raw.get("active") is True
    why = raw.get("why") if raw.get("why") in REASONS else ""
    since = raw.get("since") if isinstance(raw.get("since"), (int, float)) else 0
    prev = raw.get("previous_profile") if raw.get("previous_profile") in PROFILES else None
    declined = [r for r in DECLINABLE if r in (raw.get("declined") or [])]
    return {"active": active, "why": why if active else "", "since": int(since) if active else 0,
            "previous_profile": prev if active else None, "declined": declined}


def write_state(st):
    """Written with plain json.dump spacing: lua/batterysaver.lua finds
    "active": true with a pattern."""
    desk_common.atomic_write_json(state_path(), st)


# -- the world outside (each one stubbed in the tests) ------------------------------
def run(argv, timeout=15):
    return desk_common.run(argv, timeout=timeout)


def get_profile():
    """The active power profile, or None when it cannot be told (no
    tuned-ppd / power-profiles-daemon on the bus)."""
    done = run([sys.executable, IDLE_SETTINGS, "profile"])
    name = (done.stdout or "").strip() if done is not None and done.returncode == 0 else ""
    return name if name in PROFILES else None


def read_profile():
    """get_profile(), asked a second time when the first answer is none:
    idle-settings.py's busctl gives up after 5 s, and tuned-ppd can be that
    slow just after a resume."""
    name = get_profile()
    if name is None:
        time.sleep(RETRY_S)
        name = get_profile()
    return name


def set_profile(name):
    """Switch the profile; None when it worked, else what went wrong."""
    done = run([sys.executable, IDLE_SETTINGS, "profile", name])
    if done is None:
        return "idle-settings.py did not run"
    if done.returncode != 0:
        return (done.stderr or done.stdout or "").strip() or f"idle-settings.py exited {done.returncode}"
    return None


def hypr_eval(code):
    """`hyprctl eval CODE`; None when Hyprland said ok, else its answer.
    Without a running Hyprland (a tty, the tests) that is an error to
    report, not a crash: the state file is written either way, and the next
    config load picks it up."""
    done = run(["hyprctl", "eval", code], timeout=5)
    if done is None:
        return "hyprctl did not run"
    text = ((done.stdout or "") + (done.stderr or "")).strip()
    return None if done.returncode == 0 and text in ("", "ok") else (text or f"hyprctl exited {done.returncode}")


def notify(title, body):
    desk_common.notify(title, body, app=APP, icon="power-profile-power-saver-symbolic", background=True)


def gamemode():
    """lua/gamemode.lua's own test (animations off == gamemode on), over
    Hyprland's socket -- no hyprctl started. None when Hyprland does not
    answer."""
    got = desk_common.hypr_request("getoption animations:enabled", json=True)
    if not isinstance(got, dict) or "int" not in got:
        return None
    return got["int"] == 0


# -- what `auto` wants ---------------------------------------------------------------
def plugged():
    """Is a charger connected: True / False, or None when nothing says for
    sure (the module's docstring says why this is not `not on_battery()`).
    The charger's own online first (ACAD here); only without one, what the
    battery's status implies -- power_state.plugged_from(), the rule
    power-watch.py uses too. The battery is read only when it is needed."""
    ac = power_state.ac_online()
    if ac is not None:
        return ac
    return power_state.plugged_from(None, (power_state.battery() or {}).get("status"))


def wanted(on_battery, bat, settings):
    """The reasons that say "saver on" right now, the stronger first: a low
    battery is a more useful thing to be told than "unplugged"."""
    if not on_battery:
        return []
    out = []
    cap = (bat or {}).get("capacity")
    limit = settings.get("saver_auto_at", 0)
    if limit and cap is not None and cap <= limit:
        out.append("auto")
    if settings.get("saver_on_unplug"):
        out.append("unplug")
    return out


def _message(why, bat):
    cap = (bat or {}).get("capacity")
    lead = f"Battery at {cap}%" if why == "auto" and cap is not None else "On battery"
    return (f"{lead}: blur, shadows, animations and the moving wallpaper are off and the power "
            "profile is power-saver until the charger is plugged in. battery-saver.py off undoes it.")


# -- the switch ----------------------------------------------------------------------
def switch_on(why="manual", bat=None):
    """Saver on. Already on: only the reason can change, and only towards
    manual (switching it on by hand over an automatic saver means plugging
    in must not switch it off any more; a rule's "on" over it changes
    nothing). Returns the errors, [] when none."""
    st = read_state()
    errors = []
    if st["active"]:
        if why == "manual" and st["why"] != "manual":
            st["why"] = "manual"
            write_state(st)
        # Re-applied either way: a hand `on` is also the way to repair a
        # look something else changed under the saver.
        err = hypr_eval(LUA_APPLY)
        return [f"compositor: {err}"] if err else []
    prev = read_profile()
    if prev is None:
        errors.append("power profile: could not read the current one, left alone")
    elif prev != SAVER_PROFILE:
        # Owed first: a crash right after the switch must still find it.
        write_owed(prev)
        err = set_profile(SAVER_PROFILE)
        if err:
            errors.append(f"power profile: {err}")
            drop_owed()                     # nothing was changed, nothing is owed
    # The file first: the Lua apply below reads it.
    write_state({"active": True, "why": why, "since": int(time.time()), "previous_profile": prev,
                 "declined": st["declined"]})
    err = hypr_eval(LUA_APPLY)
    if err:
        errors.append(f"compositor: {err}")
    if why in DECLINABLE:                   # auto / unplug: a rule is yours, and can notify itself
        notify("Battery saver on", _message(why, bat))
    return errors


def switch_off(declined=()):
    """Saver off: the look back through the same Lua apply (the theme's,
    or gamemode's while that is on), the profile back to what it was if it
    is still power-saver. DECLINED: the reasons `auto` must leave alone
    until the charger is plugged in; None keeps what was declined before (a
    rule's "off", which declines nothing of its own). Returns the errors."""
    st = read_state()
    keep = declined is None
    declined = () if keep else declined
    if not st["active"]:
        # Already off: `off` on battery still says "not for these reasons".
        if set(declined) - set(st["declined"]):
            st["declined"] = sorted(set(st["declined"]) | set(declined))
            write_state(st)
        return []
    errors = []
    prev = st["previous_profile"]
    write_state({"active": False, "why": "", "since": 0, "previous_profile": None,
                 "declined": st["declined"] if keep else sorted(set(declined))})
    err = hypr_eval(LUA_APPLY)
    if err:
        errors.append(f"compositor: {err}")
    if prev and prev != SAVER_PROFILE:
        err = give_back(prev)
        if err:
            errors.append(f"power profile: {err}")
    # Given back or not, it is no longer owed: a failure is reported now,
    # and a later retry could undo a power-saver you picked yourself.
    drop_owed()
    return errors


def give_back(prev):
    """The profile back to PREV if it is still the saver's (yours
    otherwise, and it stays). None when done or nothing to do, else what
    went wrong."""
    now = read_profile()
    if now is None:
        return f"could not read the current one, {prev} not put back"
    if now != SAVER_PROFILE:
        return None
    return set_profile(prev)


def recover():
    """A session that ended under the saver (the runtime state is gone or
    says off, the owed profile is still written down): the profile back,
    as `off` would have. Kept for the next command when the profile cannot
    be read yet (tuned-ppd not up at login). Returns the errors."""
    prev = read_owed()
    if prev is None:
        if os.path.exists(owed_path()):
            drop_owed()                     # a broken file owes nothing
        return []
    if read_state()["active"]:
        return []                           # still held: `off` gives it back
    now = read_profile()
    if now is None:
        return []
    drop_owed()
    if now == SAVER_PROFILE:
        err = set_profile(prev)
        if err:
            return [f"power profile: {err}"]
    return []


def manual_off():
    """`off` by hand: on battery, the reasons that hold now are declined
    (see the module's docstring), so the next uevent does not undo it.
    A rule's "off" is switch_off(None) instead."""
    on_bat = power_state.on_battery()
    reasons = wanted(on_bat, power_state.battery(), power_state.load_settings()) if on_bat else []
    return switch_off(declined=reasons)


def auto():
    """power-watch.py's call after a power change. Returns (what it did,
    errors); what it did is "on:auto", "on:unplug", "off" or ""."""
    if not power_state.has_battery():
        return "", []
    st = read_state()
    plug = plugged()
    if plug is True:
        if st["active"] and st["why"] in AUTO_REASONS:
            return "off", switch_off()
        if st["declined"]:                  # plugged in: the next discharge starts fresh
            st["declined"] = []
            write_state(st)
        return "", []
    if plug is None or not power_state.on_battery():
        return "", []                       # not sure either way: leave everything as it is
    if st["active"]:
        return "", []
    bat = power_state.battery()
    reasons = [r for r in wanted(True, bat, power_state.load_settings()) if r not in st["declined"]]
    if not reasons:
        return "", []
    return f"on:{reasons[0]}", switch_on(reasons[0], bat)


# -- status --------------------------------------------------------------------------
def status():
    st = read_state()
    on_bat = power_state.on_battery()
    bat = power_state.battery()
    settings = power_state.load_settings()
    would = ""
    plug = plugged() if power_state.has_battery() else None
    if plug is True:
        would = "off" if st["active"] and st["why"] in AUTO_REASONS else ""
    elif plug is False and on_bat and not st["active"]:
        reasons = [r for r in wanted(True, bat, settings) if r not in st["declined"]]
        would = f"on:{reasons[0]}" if reasons else ""
    return {**st,
            "has_battery": power_state.has_battery(), "on_battery": on_bat,
            "capacity": (bat or {}).get("capacity"),
            "settings": {k: settings[k] for k in ("saver_auto_at", "saver_on_unplug")},
            "plugged": plug, "profile_owed": read_owed(),
            "auto_would": would, "gamemode": gamemode(), "state_file": state_path()}


def _locked():
    """The lock beside the state file (an open file: the lock goes with it,
    at the end of the with block or when the process dies)."""
    path = lock_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    handle = open(path, "w")
    fcntl.flock(handle, fcntl.LOCK_EX)
    return handle


def main(argv):
    cmd = argv[0] if argv else "status"
    if cmd == "status" and len(argv) <= 1:
        print(json.dumps(status(), indent=1))
        return 0
    why = "manual"
    if cmd in ("on", "off") and len(argv) == 3 and argv[1] == "--why" and argv[2] in ("manual", "rule"):
        why = argv[2]
    elif cmd not in ("on", "off", "toggle", "auto") or len(argv) > 1:
        print(__doc__.strip().split("\n\n")[1], file=sys.stderr)
        return 2
    if cmd == "auto" and not power_state.has_battery() and not os.path.exists(owed_path()):
        return 0                            # a desktop: nothing to do, not even the lock file
    with _locked():
        return _switch(cmd, why)


def _switch(cmd, why="manual"):
    errors = recover()
    if cmd == "toggle":
        cmd = "off" if read_state()["active"] else "on"
    if cmd == "on":
        errors += switch_on(why, power_state.battery())
    elif cmd == "off":
        errors += switch_off(None) if why == "rule" else manual_off()
    else:
        did, more = auto()
        errors += more
        if did or errors:
            print(json.dumps({"did": did, "errors": errors}))
        return 1 if errors else 0
    out = status()
    if errors:
        out["errors"] = errors
        # Also on stderr, one line each: the launcher's notification and the
        # Settings page show a failed switch's last stderr line.
        for problem in errors:
            print(f"battery-saver: {problem}", file=sys.stderr)
    print(json.dumps(out, indent=1))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
