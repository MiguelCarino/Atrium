#!/usr/bin/env python3
"""Settings > Battery's backend: everything the page shows, in one JSON, and
the battery settings it changes.

    battery-settings.py status                 JSON (below)
    battery-settings.py set warn_at 20,10,5    the low-battery warnings, percent
                                               ("none": no warnings at all)
    battery-settings.py set saver_auto_at 15   the saver turns itself on at 15 %
                                               (0: never)
    battery-settings.py set saver_on_unplug on|off
                                               ...or as soon as the charger is out

`set` prints the status JSON after (exit 2 for a key or value it does not
take, with why on stderr; nothing is written then). The charge limit and the
saver's own switch are not here: the page runs charge-limit.py and
battery-saver.py for those, the same commands the launcher and the keys run,
so there is one way each thing is ever changed.

Why one more script. Every Settings page holds no settings of its own and
redraws from what a command reports (settings_pages/common.py); the battery
settings live in $XDG_STATE_HOME/hypr/battery.json, which power_state.py
reads and writes but which had no command -- power-watch.py and
battery-saver.py only read it. The three keys above are the ones this page
owns; charge_limit in the same file is charge-limit.py's mirror and is not
settable here (writing it would not move the firmware's limit).

After a saver setting changes, `battery-saver.py auto` runs once (only on a
machine with a battery). Without it a new "turn on at 30 %" while the
battery already reads 25 % would wait for the next percent's uevent to
take effect, a minute or more; auto also respects an "off" you gave by hand
during this discharge (battery-saver.py's "declined"), so picking a value
never overrides that. warn_at needs nothing of the kind: power-watch.py
reads the settings at every check.

The status JSON (cheap: sysfs reads and small files, nothing started --
the saver's and the charge limit's status are those scripts' own status()
functions, imported, not run; the saver's asks Hyprland's socket whether
gamemode is on, which costs one socket round trip):

    {"has_battery": bool, "on_battery": bool, "plugged": bool|null,
     "battery": power_state.battery() or null,
     "settings": {"warn_at": [...], "saver_auto_at": N, "saver_on_unplug": bool, "charge_limit": N},
     "choices": {"warn_at": [...], "saver_auto_at": [...]},
     "warned": [percent, ...]   (warnings already given this discharge, from power-watch),
     "watcher": bool            (power-watch.py has written its state this login),
     "saver": battery-saver.py's status or null (the script missing or failing),
     "charge": charge-limit.py's status or null,
     "early_warnings": null, or {"battery_poll": bool, "fast": [source names]}
                       (emergency-alerts.py: the sources it polls every few
                       seconds, which keep that pace on battery unless
                       battery_poll is on; null when none is enabled)}

On a desktop has_battery is false and battery null; `set` still works (the
file is plain settings) but nothing reads it there.
"""
import importlib.util
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import power_state  # noqa: E402  (sysfs reads, battery.json)
import desk_common  # noqa: E402  (read_json, run)

SAVER = os.path.join(HERE, "battery-saver.py")
CHARGE = os.path.join(HERE, "charge-limit.py")
EMERGENCY = os.path.join(HERE, "emergency-alerts.py")
EMERGENCY_CONF = os.path.expanduser("~/.config/hypr/emergency.conf")
# What the page offers. A value in the file that is none of these (a hand
# edit, a CLI `set`) is shown as well, so the page never lies about it.
WARN_CHOICES = [30, 25, 20, 15, 10, 5]
SAVER_AUTO_CHOICES = [0, 10, 15, 20, 30]
KEYS = ("warn_at", "saver_auto_at", "saver_on_unplug")
ON, OFF = ("on", "true", "yes", "1"), ("off", "false", "no", "0")


# -- the other scripts, imported (their names have dashes) --------------------------
_modules = {}


def _module(path, name):
    """PATH imported as NAME, once; None when it is missing or does not
    import (an older checkout without it: the page then says so instead of
    failing whole)."""
    if name not in _modules:
        try:
            spec = importlib.util.spec_from_file_location(name, path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        except (OSError, ImportError, SyntaxError, AttributeError):
            module = None
        _modules[name] = module
    return _modules[name]


def saver_status():
    mod = _module(SAVER, "battery_saver")
    try:
        return mod.status() if mod else None
    except Exception as exc:        # noqa: BLE001 -- one part failing must not take the page with it
        print(f"battery-settings: battery-saver status failed: {exc}", file=sys.stderr)
        return None


def charge_status():
    mod = _module(CHARGE, "charge_limit")
    try:
        return mod.status() if mod else None
    except Exception as exc:        # noqa: BLE001
        print(f"battery-settings: charge-limit status failed: {exc}", file=sys.stderr)
        return None


def early_warnings(conf_path=None):
    """The emergency alerts' sources that poll every few seconds, and
    whether battery_poll slows them on battery; None when none is enabled
    or emergency alerts were never set up. The conf is read only when it
    exists: emergency-alerts.py's config() writes a fresh one otherwise,
    and a status must never write."""
    conf_path = conf_path or EMERGENCY_CONF
    if not os.path.exists(conf_path):
        return None
    mod = _module(EMERGENCY, "emergency_alerts")
    if mod is None:
        return None
    try:
        mod.CONF = conf_path
        conf = mod.config()
        fast = [mod.SOURCES[s][0] for s in mod.enabled(conf)
                if s in mod.SOURCES and mod.SOURCES[s][3] < mod.BATTERY_POLL_S]
    except Exception:               # noqa: BLE001 -- a broken conf: no row, the Alerts page says why
        return None
    if not fast:
        return None
    return {"battery_poll": mod.battery_poll_on(conf), "fast": fast, "battery_s": mod.BATTERY_POLL_S}


# -- status --------------------------------------------------------------------------
def watcher_state():
    """power-watch.py's state file: (written at all, warnings given)."""
    data = desk_common.read_json(power_state.POWER_STATE, None, typed=False)
    if not isinstance(data, dict):
        return False, []
    warned = data.get("warned") if data.get("on_battery") else []
    return True, [p for p in (warned or []) if isinstance(p, int)]


def choices(settings):
    return {"warn_at": sorted(set(WARN_CHOICES) | set(settings["warn_at"]), reverse=True),
            "saver_auto_at": sorted(set(SAVER_AUTO_CHOICES) | {settings["saver_auto_at"]})}


def status():
    settings = power_state.load_settings()
    has = power_state.has_battery()
    watching, warned = watcher_state()
    return {"has_battery": has, "on_battery": power_state.on_battery(),
            "plugged": power_state.plugged() if has else None,
            "battery": power_state.battery(), "settings": settings, "choices": choices(settings),
            "warned": warned, "watcher": watching,
            "saver": saver_status(), "charge": charge_status(), "early_warnings": early_warnings()}


# -- set -----------------------------------------------------------------------------
def parse(key, text):
    """The value of `set KEY TEXT`, or raise ValueError saying why."""
    text = str(text).strip().lower()
    if key == "warn_at":
        if text in ("none", "off", "never", ""):
            return []
        try:
            values = [int(part.strip().rstrip("%")) for part in text.replace(" ", ",").split(",") if part.strip()]
        except ValueError:
            raise ValueError(f"warn_at takes percentages, e.g. 20,10,5 (or none), not {text!r}") from None
        if not all(1 <= v <= 99 for v in values):
            raise ValueError("warn_at percentages are 1-99")
        return sorted(set(values), reverse=True)
    if key == "saver_auto_at":
        try:
            value = int(text.rstrip("%"))
        except ValueError:
            raise ValueError(f"saver_auto_at takes a percentage (0 = never), not {text!r}") from None
        if not 0 <= value <= 99:
            raise ValueError("saver_auto_at is 0-99 (0 = never)")
        return value
    if key == "saver_on_unplug":
        if text in ON:
            return True
        if text in OFF:
            return False
        raise ValueError(f"saver_on_unplug is on or off, not {text!r}")
    raise ValueError(f"unknown setting {key!r} (one of: {', '.join(KEYS)})")


def saver_auto(run=desk_common.run):
    """battery-saver.py auto, so a new threshold takes effect now; only with
    a battery (a desktop has nothing to switch) and only when the script is
    there. Its failure is reported, not raised: the setting is saved."""
    if not power_state.has_battery() or not os.path.exists(SAVER):
        return None
    done = run([sys.executable, SAVER, "auto"], timeout=30)
    if done is None or done.returncode != 0:
        return "battery-saver.py auto failed" + (f": {done.stderr.strip()}" if done is not None and
                                                 (done.stderr or "").strip() else "")
    return None


def set_value(key, text, run=desk_common.run):
    """(exit code, message or None)."""
    try:
        value = parse(key, text)
    except ValueError as err:
        return 2, str(err)
    power_state.save_settings({key: value})
    if key.startswith("saver_"):
        problem = saver_auto(run)
        if problem:
            return 0, problem           # saved; the switch itself will catch up at the next change
    return 0, None


def main(argv):
    cmd = argv[0] if argv else "status"
    if cmd == "status" and len(argv) == 1 or not argv:
        print(json.dumps(status(), indent=1))
        return 0
    if cmd == "set" and len(argv) >= 3:
        code, message = set_value(argv[1], " ".join(argv[2:]))
        if message:
            print(f"battery-settings: {message}", file=sys.stderr)
        if code == 0:
            print(json.dumps(status(), indent=1))
        return code
    print(__doc__.strip().split("\n\n")[1], file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
