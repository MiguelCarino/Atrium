#!/usr/bin/env python3
"""Is this machine running on its battery, and should the desktop go easy?
The one place every Atrium script asks.

Imported as a plain module (the name has no dash on purpose) after a script
puts its own folder on sys.path, like desk_common.py. Standard library only,
nothing happens at import time, and nothing here ever starts a process: the
answers come from reading a handful of small sysfs files, so a daemon's 1 s
loop can ask every tick. frugal() is the question those loops ask, and it
is cached for FRUGAL_TTL_S on top of that.

    POWER_SUPPLY                  /sys/class/power_supply, or $ATRIUM_POWER_SUPPLY
    POWER_STATE / SAVER_STATE / SETTINGS_FILE
                                  the files below
    has_battery(root=None)        -> bool
    on_battery(root=None)         -> bool  (False on a desktop, always)
    ac_online(root=None)          -> bool or None (None: no charger is reported at all)
    plugged(root=None)            -> bool or None: is a charger connected, asked positively
    plugged_from(ac, status)      the same rule on values already read (power-watch's snapshot)
    system_batteries(root=None)   -> [(name, folder)]: the machine's own batteries
    battery(root=None)            -> dict or None (no battery)
    saver_active()                -> bool  (battery-saver.py's state file)
    frugal(fresh=False)           -> bool  on_battery() or saver_active(), cached
    period(normal_s, battery_s)   -> battery_s when frugal() else normal_s
    load_settings() / save_settings(d)
    reset_cache()                 forget frugal()'s cached answer (tests, a CLI that just switched)

Which supplies count. The kernel lists every power supply it knows in
/sys/class/power_supply: the laptop's battery (type Battery), its charger
(type Mains: ACAD on this ASUS, AC / ADP1 elsewhere), the USB-C ports
(type USB, the UCSI "source" supplies) -- and also the batteries of a
wireless mouse, keyboard or game pad (type Battery, scope Device). Those last
ones are why "is there a battery" cannot be "is there a Battery entry": a
desktop PC with a wireless mouse has one, and it must see no change at all.
So a battery counts only when its scope is not Device (the system batteries
have scope System or no scope file at all) and it says it is present.

"On battery" is the strict version: a system battery says Discharging AND no
Mains supply is online. Both, because neither alone is reliable -- a full
battery on the charger reads "Not charging" or "Full" (so "not Charging" is
not "unplugged"), and some firmware leaves a battery reading Discharging for
a moment after the charger is plugged in, or under a heavy load while
plugged in to a weak USB-C charger (then the desktop is still on mains power
as far as the person is concerned: backing off then would only be a
surprise). ac_online() is the charger alone, for the plugged / unplugged
events: a Mains supply's "online"; on a machine that reports no Mains supply
at all (some USB-C-only laptops), the USB ones (scope not Device) instead.

Units. The kernel reports either charge (charge_now / charge_full, uAh, with
current_now in uA) or energy (energy_now / energy_full, uWh, with power_now
in uW), never a promise of both; this ASUS reports charge. Watts are then
current_now x voltage_now (uA x uV = 1e-12 W) or power_now / 1e6. Some
firmware reports current_now as negative while discharging: abs() it.

The battery saver's state ($XDG_RUNTIME_DIR/battery-saver.json, written by
battery-saver.py) is {"active": bool, "why": "manual"|"auto"|"unplug"|"rule"|"",
"since": epoch}; only its "active" matters here. The battery settings
($XDG_STATE_HOME/hypr/battery.json, Settings > Battery) are read with every
key checked and a bad one replaced by its default, so a hand-edited file can
never stop the warnings.
"""
import json
import os
import threading
import time

POWER_SUPPLY = os.environ.get("ATRIUM_POWER_SUPPLY") or "/sys/class/power_supply"
_RUNTIME = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
_STATE = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
POWER_STATE = os.path.join(_RUNTIME, "power-state.json")       # power-watch.py writes it
SAVER_STATE = os.path.join(_RUNTIME, "battery-saver.json")     # battery-saver.py writes it
SETTINGS_FILE = os.path.join(_STATE, "hypr", "battery.json")   # Settings > Battery writes it

FRUGAL_TTL_S = 10       # frugal() reads sysfs at most this often (a 1 s loop asks every tick)
DEFAULTS = {
    "warn_at": [20, 10, 5],     # percent; one warning each per discharge, the lowest one critical
    "saver_auto_at": 20,        # battery-saver.py turns itself on at this percent (0: never)
    "saver_on_unplug": False,   # ...or as soon as the charger is unplugged
    "charge_limit": 100,        # charge-limit.py: stop charging here (50-100)
}
# The statuses a battery reports while a charger is connected (Not charging:
# held at the charge limit, or full on some firmware).
PLUGGED_STATUSES = ("Charging", "Full", "Not charging")
# A wireless mouse's battery, a game pad's: not this machine's power.
_DEVICE_SCOPE = "Device"
_USB_TYPES = ("USB", "USB_C", "USB_PD", "USB_PD_DRP", "USB_DCP", "USB_CDP", "USB_ACA", "USB_TYPE_C")


# -- sysfs ---------------------------------------------------------------------------
def _root(root=None):
    """The power_supply folder: ROOT, else $ATRIUM_POWER_SUPPLY as it is now
    (tests point it at a fake tree), else POWER_SUPPLY."""
    return root or os.environ.get("ATRIUM_POWER_SUPPLY") or POWER_SUPPLY


def _read(folder, name):
    """One sysfs attribute, stripped; None when missing or unreadable (a
    battery being removed, an attribute this firmware does not have)."""
    try:
        with open(os.path.join(folder, name)) as handle:
            return handle.read().strip()
    except (OSError, UnicodeDecodeError):
        return None


def _int(folder, name):
    text = _read(folder, name)
    try:
        return int(text) if text is not None else None
    except ValueError:
        return None


def _supplies(root=None):
    """[(name, folder, type)] for every supply, sorted by name (so "the
    battery" is the same one every time)."""
    base = _root(root)
    try:
        names = sorted(os.listdir(base))
    except OSError:
        return []
    out = []
    for name in names:
        folder = os.path.join(base, name)
        out.append((name, folder, _read(folder, "type") or ""))
    return out


def system_batteries(root=None):
    """The machine's own batteries: [(name, folder)], by name. Public:
    charge-limit.py walks them to find the one with the switch."""
    found = []
    for name, folder, kind in _supplies(root):
        if kind != "Battery" or _read(folder, "scope") == _DEVICE_SCOPE:
            continue
        if _read(folder, "present") == "0":     # an empty bay (two-battery ThinkPads)
            continue
        found.append((name, folder))
    return found


_system_batteries = system_batteries     # the old private name, kept for anything still using it


def _online(folder):
    return _read(folder, "online") == "1"


def has_battery(root=None):
    """True when this machine has a battery of its own (not a mouse's)."""
    return bool(_system_batteries(root))


def _mains(root=None):
    return [folder for _, folder, kind in _supplies(root) if kind == "Mains"]


def ac_online(root=None):
    """Is a charger plugged in: True / False, or None when nothing here
    reports one (a desktop; or a laptop whose firmware lists no Mains and
    no USB supply). Mains supplies first; only when there is none, the USB
    ones that are the machine's own (scope not Device)."""
    mains = _mains(root)
    if mains:
        return any(_online(f) for f in mains)
    usb = [f for _, f, kind in _supplies(root)
           if kind in _USB_TYPES and _read(f, "scope") != _DEVICE_SCOPE and _read(f, "online") is not None]
    if usb:
        return any(_online(f) for f in usb)
    return None


def plugged_from(ac, status):
    """The "is a charger connected" rule on values already read: AC (what
    ac_online() said) when it is not None, else what the battery's STATUS
    implies -- Discharging is no; Charging, Full and Not charging (held at
    the charge limit) are yes; anything else (Unknown, no battery) is None.
    One rule for power-watch.py's events and battery-saver.py's `auto`,
    which used to carry a copy each."""
    if ac is not None:
        return ac
    if status == "Discharging":
        return False
    if status in PLUGGED_STATUSES:
        return True
    return None


def plugged(root=None):
    """Is a charger connected: True / False, or None when nothing says for
    sure. Asked POSITIVELY, unlike `not on_battery()`, which says "plugged"
    whenever it is unsure: this ASUS reads Unknown or Not charging for a
    moment around an unplug or a resume, and a "plugged in" read then would
    switch an automatic saver off and forget what had been declined."""
    return plugged_from(ac_online(root), (battery(root) or {}).get("status"))


def on_battery(root=None):
    """True when a system battery says Discharging and no Mains supply is
    online. False on a desktop, and False whenever in doubt."""
    batteries = _system_batteries(root)
    if not batteries:
        return False
    if not any((_read(f, "status") or "") == "Discharging" for _, f in batteries):
        return False
    return not any(_online(f) for f in _mains(root))


def _watts(folder):
    """The battery's draw (or charge rate) in watts; None when the firmware
    gives neither power_now nor current_now with voltage_now."""
    power = _int(folder, "power_now")
    if power is not None:
        return round(abs(power) / 1e6, 2)
    current, voltage = _int(folder, "current_now"), _int(folder, "voltage_now")
    if current is not None and voltage is not None:
        return round(abs(current) * voltage / 1e12, 2)
    return None


def _minutes(folder, status):
    """Minutes to empty (Discharging) or to full (Charging), from the
    battery's own now / full / rate; None when it cannot be worked out (the
    rate is 0 or missing, or the status is neither)."""
    for now_key, full_key, rate_key in (("charge_now", "charge_full", "current_now"),
                                        ("energy_now", "energy_full", "power_now")):
        now, full, rate = _int(folder, now_key), _int(folder, full_key), _int(folder, rate_key)
        if now is None or not rate:
            continue
        rate = abs(rate)
        if status == "Discharging":
            return int(now / rate * 60)
        if status == "Charging" and full is not None:
            return int(max(0, full - now) / rate * 60)
        return None
    return None


def battery(root=None):
    """The laptop's battery (the first system battery, by name), or None:

        {"name": "BATT", "capacity": 83, "status": "Discharging",
         "watts": 10.78, "health_pct": 57, "cycles": 255,
         "charge_limit": 100, "charge_limit_supported": True,
         "minutes_left": 165, "minutes_to_full": None}

    watts / health_pct / cycles / charge_limit are None when the firmware
    does not say; capacity is None only when the firmware gives no way at
    all to tell (no capacity, no now / full). minutes_left is time to empty while discharging,
    minutes_to_full time to full while charging (None otherwise). A
    capacity the battery does not report is worked out from now / full."""
    batteries = _system_batteries(root)
    if not batteries:
        return None
    name, folder = batteries[0]
    status = _read(folder, "status") or "Unknown"
    capacity = _int(folder, "capacity")
    if capacity is None:
        for now_key, full_key in (("charge_now", "charge_full"), ("energy_now", "energy_full")):
            now, full = _int(folder, now_key), _int(folder, full_key)
            if now is not None and full:
                capacity = round(100 * now / full)
                break
    health = None
    for full_key, design_key in (("charge_full", "charge_full_design"), ("energy_full", "energy_full_design")):
        full, design = _int(folder, full_key), _int(folder, design_key)
        if full is not None and design:
            health = round(100 * full / design)
            break
    minutes = _minutes(folder, status)
    return {
        "name": name,
        "capacity": max(0, min(100, capacity)) if capacity is not None else None,
        "status": status,
        "watts": _watts(folder),
        "health_pct": health,
        "cycles": _int(folder, "cycle_count"),
        "charge_limit": _int(folder, "charge_control_end_threshold"),
        "charge_limit_supported": os.path.exists(os.path.join(folder, "charge_control_end_threshold")),
        "minutes_left": minutes if status == "Discharging" else None,
        "minutes_to_full": minutes if status == "Charging" else None,
    }


# -- the battery saver and the back-off ----------------------------------------------
def saver_active():
    """True while battery-saver.py says the saver is on (its state file in
    $XDG_RUNTIME_DIR: gone at logout, as the saver's effects are)."""
    try:
        with open(SAVER_STATE) as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return False
    return isinstance(data, dict) and data.get("active") is True


_cache_lock = threading.Lock()
_cache = {"value": False, "at": None}


def reset_cache():
    """Forget frugal()'s cached answer: the next call reads again."""
    with _cache_lock:
        _cache["at"] = None


def frugal(fresh=False):
    """Should the desktop go easy right now: on_battery() or saver_active().
    Cached for FRUGAL_TTL_S (fresh=True reads now), so asking every tick of
    a 1 s loop costs a clock read, and a change shows within 10 s -- far
    quicker than any loop that backs off notices the difference."""
    now = time.monotonic()
    with _cache_lock:
        if not fresh and _cache["at"] is not None and now - _cache["at"] < FRUGAL_TTL_S:
            return _cache["value"]
    value = on_battery() or saver_active()
    with _cache_lock:
        _cache["value"], _cache["at"] = value, now
    return value


def period(normal_s, battery_s):
    """The one helper a daemon backs off with: BATTERY_S while frugal(),
    NORMAL_S otherwise. A desktop always gets NORMAL_S."""
    return battery_s if frugal() else normal_s


# -- settings ------------------------------------------------------------------------
def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _valid(key, value):
    """VALUE tidied when it is a well-formed KEY setting, else None."""
    if key == "warn_at":
        if isinstance(value, list) and all(_is_int(p) and 1 <= p <= 99 for p in value):
            return sorted(set(value), reverse=True)     # [] is allowed: no warnings at all
    elif key == "saver_auto_at":
        if _is_int(value) and 0 <= value <= 99:
            return value
    elif key == "saver_on_unplug":
        if isinstance(value, bool):
            return value
    elif key == "charge_limit":
        if _is_int(value) and 50 <= value <= 100:
            return value
    return None


def _over(base, data):
    """BASE with each well-formed key of DATA laid over it (unknown keys
    and malformed values are dropped)."""
    out = {key: (list(value) if isinstance(value, list) else value) for key, value in base.items()}
    if isinstance(data, dict):
        for key in DEFAULTS:
            if key in data:
                value = _valid(key, data[key])
                if value is not None:
                    out[key] = value
    return out


def load_settings():
    """The battery settings: DEFAULTS where the file is missing, unreadable
    or a key in it is malformed."""
    try:
        with open(SETTINGS_FILE) as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        data = {}
    return _over(DEFAULTS, data)


def save_settings(d):
    """Lay the keys of D over the current settings and write the file whole
    (a temporary file renamed over it). Returns what was saved. A malformed
    value in D is dropped -- the current one stays -- rather than raised:
    the Settings page only sends what its controls can produce, and a bad
    value from a CLI is reported by what comes back."""
    merged = _over(load_settings(), d)
    os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
    tmp = f"{SETTINGS_FILE}.{os.getpid()}.{threading.get_ident()}.tmp"
    try:
        with open(tmp, "w") as handle:
            json.dump(merged, handle, indent=2)
        os.replace(tmp, SETTINGS_FILE)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
    return merged


if __name__ == "__main__":
    print(json.dumps({"has_battery": has_battery(), "on_battery": on_battery(), "ac_online": ac_online(),
                      "plugged": plugged(),
                      "battery": battery(), "saver_active": saver_active(), "frugal": frugal(fresh=True),
                      "settings": load_settings()}, indent=2))
