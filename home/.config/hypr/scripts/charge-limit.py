#!/usr/bin/env python3
"""The battery's charge limit, from the session: how far the laptop charges
on the charger (Settings > Battery and the search bar run this).

    charge-limit.py status     JSON: {"supported", "installed", "limit", "saved",
                               "choices", "fixed", "range", "battery", "setting"}
    charge-limit.py set N      stop charging at N % (50-100; snapped to what the
                               firmware takes); prints the status JSON after

Why a limit at all: a lithium battery kept full on the charger wears out
fastest. This laptop's was at 57 % of its design capacity after 255 cycles,
almost always plugged in and charged to 100 %. Stopping at 80 % costs a
little runtime off the charger and spares the battery most of that wear.

The switch is the firmware's (charge_control_end_threshold on the battery
in /sys/class/power_supply), and writing it needs root, so the work is done
by the root side in system/charge-limit/ (its install.sh puts it in place
on a laptop that has the switch; a desktop never gets it):

  * `set N` runs `systemctl start charge-limit@N.service`. A polkit rule lets
    the active local session start that one template -- with 50-100 as the
    instance, nothing else -- without a password; systemd runs the root
    helper with N as its only input, which writes the threshold and saves N
    in /etc/atrium/charge-limit. Without the rule (an older install) polkit
    asks for the administrator password instead: still the same one unit.
  * charge-limit.service writes the saved limit again at every boot and
    after every resume, because a lot of firmware forgets it.

Firmware with fixed values (several ASUS models take only 60 / 80 / 100;
LG and Toshiba 80 / 100). The same rule as the root helper's, first match
wins: /etc/atrium/charge-limit-choices (learned by the helper when a `set`
showed fixed values, or written by hand; "any" opts out), else 60 / 80 / 100
on an ASUS whose switch is asus-wmi's -- that driver reads back its own
cached value, so whether the firmware honours 70 cannot be seen, while
60 / 80 / 100 always work -- else any value. With fixed values `choices`
lists only those and `set` snaps to the nearest one (the lower on a tie: the
point is sparing the battery) before asking. Firmware that takes any value
gets PRESETS as choices, and any whole number 50-100 is accepted.

"limit" is what the battery's firmware uses now (read from sysfs, which
anyone may read), "saved" what the root side will write at the next boot;
they differ only before the first boot after a limit was chosen by hand, or
when something else wrote the threshold. The saved file is the source of
truth: it is mirrored to the battery settings (power_state.save_settings,
"charge_limit") so the rest of the desktop reads one place -- by `set`, and
by `status` whenever the two disagree (a limit given to install.sh --limit,
a lost battery.json), so "setting" never contradicts "saved". On a machine
without the switch "supported" is false and `set` changes nothing (exit 1).
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import power_state  # noqa: E402  (sysfs reads, the battery settings)
import desk_common  # noqa: E402  (run)

CONF_DIR = "/etc/atrium"                                # the root side's files (readable by all)
SAVED_FILE = os.path.join(CONF_DIR, "charge-limit")
CHOICES_FILE = os.path.join(CONF_DIR, "charge-limit-choices")
DMI_VENDOR = "/sys/class/dmi/id/sys_vendor"
PLATFORM_DRIVERS = "/sys/bus/platform/drivers"
ASUS_DRIVERS = ("asus-nb-wmi", "asus-wmi")
ASUS_CHOICES = [60, 80, 100]
END = "charge_control_end_threshold"
UNIT_FILE = "/etc/systemd/system/charge-limit@.service"    # present once system/charge-limit/install.sh ran
INSTALL_HINT = "sudo system/charge-limit/install.sh (from the Atrium repo)"
LOW, HIGH = 50, 100
PRESETS = [50, 60, 70, 80, 90, 100]     # what a picker offers when the firmware takes any value
START_TIMEOUT_S = 120   # systemctl start: the helper takes well under a second; this leaves time to
                        # type a password if polkit asks (the rule not installed)


def _read(path):
    try:
        with open(path) as handle:
            return handle.read().strip()
    except (OSError, UnicodeDecodeError):
        return None


def parse_limit(value):
    """VALUE (an int, or digits as text) as a limit in LOW..HIGH, or None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, str):
        if not re.fullmatch(r"[0-9]{1,3}", value.strip()):
            return None
        value = int(value.strip())
    if isinstance(value, int) and LOW <= value <= HIGH:
        return value
    return None


def asus_wmi():
    """Is this an ASUS whose battery switch is asus-wmi's (see above)?"""
    vendor = _read(DMI_VENDOR) or ""
    return vendor.startswith("ASUSTeK") and any(
        os.path.isdir(os.path.join(PLATFORM_DRIVERS, name)) for name in ASUS_DRIVERS)


def fixed_choices(path=None):
    """The fixed values this firmware takes ([] when it takes any): the
    choices file ("any": none), else ASUS_CHOICES on an asus-wmi ASUS."""
    text = _read(path or CHOICES_FILE) or ""
    if text.split() == ["any"]:
        return []
    learned = sorted({parse_limit(word) for word in text.split()} - {None})
    return learned or (list(ASUS_CHOICES) if asus_wmi() else [])


def switch_folder(root=None):
    """The first system battery with the switch (the root helper writes
    every one of them; this is the one shown), or None. Not simply the
    first battery: BAT0 may lack it while BAT1 has it."""
    # power_state's own list of system batteries (no mouse, no empty bay):
    # the same rule as the root helper's batteries().
    for _name, folder in power_state.system_batteries(root):
        if os.path.exists(os.path.join(folder, END)):
            return folder
    return None


def snap(value, choices):
    """VALUE when CHOICES allows it (or there are none), else the nearest
    choice -- the lower on a tie. The same rule as the root helper's."""
    if not choices or value in choices:
        return value
    return min(choices, key=lambda c: (abs(c - value), c))


def saved():
    return parse_limit(_read(SAVED_FILE) or "")


def status(root=None):
    """The status JSON (a dict)."""
    bat = power_state.battery(root)
    folder = switch_folder(root)
    supported = folder is not None
    # As the firmware reports it, not range-checked: a 40 set by another
    # tool is shown as 40.
    text = _read(os.path.join(folder, END)) if supported else None
    limit = int(text) if text and text.isdigit() else None
    kept = saved() if supported else None
    setting = power_state.load_settings()["charge_limit"]
    if kept is not None and kept != setting:
        # The root side's file is the truth (install.sh --limit, a lost
        # battery.json): mirrored, so the rest of the desktop agrees.
        power_state.save_settings({"charge_limit": kept})
        setting = power_state.load_settings()["charge_limit"]
    fixed = fixed_choices() if supported else []
    if not supported:
        choices = []
    elif fixed:
        choices = fixed
    else:
        # The presets, plus the limit in use when it is none of them (set
        # to 75 by hand): a picker can then show what is really set.
        choices = sorted(set(PRESETS) | {v for v in (limit, kept) if parse_limit(v) is not None})
    return {
        "supported": supported,
        "installed": os.path.exists(UNIT_FILE),
        "limit": limit,
        "saved": kept,
        "choices": choices,
        "fixed": bool(fixed),
        "range": [LOW, HIGH],
        "battery": bat,
        "setting": setting,
    }


def set_limit(value, root=None, run=desk_common.run):
    """Ask the root side for VALUE. Returns (exit code, result dict): the
    status, plus "ok", "asked", "requested" (after snapping) and "error"
    when it failed."""
    asked = value
    value = parse_limit(value)
    if value is None:
        return 2, {"ok": False, "asked": asked, "error": f"not a limit: {asked!r} (a whole number, {LOW}-{HIGH})"}
    now = status(root)
    if not now["supported"]:
        return 1, dict(now, ok=False, asked=asked, error="this battery cannot stop charging short of full")
    if not now["installed"]:
        return 1, dict(now, ok=False, asked=asked,
                       error=f"the root side is not installed: {INSTALL_HINT}")
    target = snap(value, fixed_choices())
    proc = run(["systemctl", "start", f"charge-limit@{target}.service"], timeout=START_TIMEOUT_S)
    after = status(root)
    if proc is None or proc.returncode != 0:
        why = ((proc.stderr or proc.stdout or "").strip() if proc is not None else "") or "systemctl failed"
        return 1, dict(after, ok=False, asked=asked, requested=target, error=why.splitlines()[-1])
    # What the root side saved (it may have snapped further, learning
    # fixed values or a firmware minimum just now); that, not the request,
    # is mirrored -- the readback only when nothing could be read back
    # from /etc (status() has mirrored "saved" already when there is one).
    effective = parse_limit(after["saved"]) or parse_limit(after["limit"]) or target
    power_state.save_settings({"charge_limit": effective})
    after["setting"] = power_state.load_settings()["charge_limit"]
    return 0, dict(after, ok=True, asked=asked, requested=target)


def main(argv):
    cmd = argv[0] if argv else ""
    if cmd == "status" and len(argv) == 1:
        print(json.dumps(status(), indent=2))
        return 0
    if cmd == "set" and len(argv) == 2:
        code, result = set_limit(argv[1])
        print(json.dumps(result, indent=2))
        if not result.get("ok") and result.get("error"):
            print(f"charge-limit: {result['error']}", file=sys.stderr)
        return code
    print(__doc__.split("\n\n")[1])
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
