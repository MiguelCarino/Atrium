#!/usr/bin/env python3
"""The kernel backlight of the built-in panel: which screen has one, what
level it is at, and how to change it without root.

    backlight.py [status]       JSON: every screen that has a backlight, its
                                device, raw level, maximum and percent

This is a library first (screen-color.py and osd.py import it; standard
library only, no GTK), the CLI is only there to look.

Why it exists: screen-color.py's brightness is a colour matrix. On an
external monitor that is all there is (its own backlight sits behind DDC,
a different story), but on a laptop's eDP panel a matrix at 40 % still has
the backlight burning at 100 % -- the picture is darker and the battery
drains just the same. A panel with a kernel backlight is driven through it
instead, and its matrix brightness stays at 100 %.

Which screen has which backlight. /sys/class/backlight/<dev>/device is a
link; for the GPU's own backlight (amdgpu_bl1, intel_backlight, ...) it
points at the DRM connector (.../drm/card1/card1-eDP-1), so the connector
name falls out of the link: card1-eDP-1 -> eDP-1, the name Hyprland uses.
A firmware (acpi_video0) or platform backlight links to an ACPI or PCI
device instead; that one is given to the built-in panel (eDP / LVDS / DSI)
when there is exactly one and nothing else claimed it, preferring firmware
over platform over raw as GNOME and systemd do. Only connectors that exist
in the DRM folder and say "connected" count, as in screens.drm_screens: a
mini-PC or an APU desktop can have an eDP connector with no panel on it
(and a board may register acpi_video0 anyway), and that phantom must not
make a desktop look like a laptop. A laptop's own panel stays "connected"
with the lid shut (the kernel reports the panel, not whether Hyprland uses
it), so it can still be named then. The tests point HYPR_DRM_DIR
(screens.py's variable) at a folder that is not there, so they never see
this laptop's panel; HYPR_BACKLIGHT_DIR does the same for
/sys/class/backlight.

How it is changed, unprivileged. /sys/class/backlight/*/brightness is
root's (0644), so a plain write only works where a udev rule made it
writable -- tried first, since it costs no process. Otherwise logind's
Session.SetBrightness: systemd-logind writes the attribute for the user of
the active session, no polkit prompt, no setuid helper. It is called with
busctl, which ships with systemd itself, so nothing new has to be
installed; session "auto" is the caller's session, or the user's display
session when the caller is outside one (screen-color.service runs in the
user manager, not in the session). brightnessctl, when installed, is the
last resort -- on Fedora it is built against logind and makes the same
call, so it only helps where busctl is missing. One fork per key press.

When none of them works (no udev rule, logind refusing -- a session that
is not the active one -- and no brightnessctl) the device is written down
in $XDG_RUNTIME_DIR/backlight-unwritable.json, and driven() leaves it out:
screen-color.py then gives that panel software brightness and the matrix
dim again, as before the backlight was used, instead of keys that silently
do nothing. A writer tries such a device again after RETRY_S (one failed
attempt a minute at most), a write that works takes the mark away, and the
runtime folder empties at logout, so every session starts by trying.

Concurrency. A brightness key is input, so the key that wakes a dimmed
panel runs screen-color's `set` at the same moment as hypridle's on-resume
`dim off`; a held key starts overlapping processes too. Each of those is a
read-modify-write of one sysfs value, so locked() -- an flock on
$XDG_RUNTIME_DIR/backlight.lock -- lets one at a time through. It is not
reentrant (flock is per open file): take it once, at the command's top.

The scale. The rest of the desktop speaks screen-color's 20-100 %: 20 is
its floor (below that a matrix leaves an unreadable screen). Here 20 % is
the backlight's lowest useful level, MIN_FRACTION of its maximum and never
0 (on many panels 0 is fully off, which is not "dim"), and 100 % is the
maximum. In between the curve is a square (GAMMA): the eye sees light
roughly as its square root, so a straight line would spend the top half of
the keys on changes nobody notices and jump at the bottom. It also makes a
backlight step look about like a matrix step on an external monitor (a
matrix scales the encoded signal, whose light goes with ~its 2.2nd power),
so the brightness keys feel the same on both and a migrated software
brightness (screen-color.py) looks the same in hardware.

Reading back: `brightness` is the level, as systemd-backlight and
gsd-backlight read it. It is what was last asked of the kernel -- by us,
by logind, by brightnessctl, or by the kernel's own hotkey handling
(acpi_video, asus-wmi: all of them go through the backlight core, which
updates it) -- so it round-trips exactly and a change from elsewhere is
simply what it reads now. `actual_brightness` is NOT trusted for a GPU's
own ("raw") backlight: on amdgpu it is the hardware's report after ABM
(adaptive backlight, panel_power_savings) has taken its cut, and tuned's
balanced-battery and powersave profiles turn ABM on -- so on battery it
reads 10-30 % low, and a brightness-up key stepping from it would land at
or below where `brightness` already is: "up" that dims. Only a "firmware"
backlight (acpi_video's _BQC) has an actual_brightness that means "the
firmware moved it behind the kernel's back", and only there does it win,
when it is more than ACTUAL_SLACK of the range off (small differences are
rounding, and ignored, so a round trip stays exact).
"""
import json
import os
import contextlib
import fcntl
import subprocess
import sys
import time

BACKLIGHT_ENV = "HYPR_BACKLIGHT_DIR"
BACKLIGHT = "/sys/class/backlight"
DRM_ENV = "HYPR_DRM_DIR"                    # the same variable screens.py reads
DRM = "/sys/class/drm"
INTERNAL = ("eDP", "LVDS", "DSI")           # connector kinds that are a built-in panel
TYPE_RANK = {"firmware": 0, "platform": 1, "raw": 2}

FLOOR = 20                  # screen-color.py's lowest brightness, here the backlight's lowest level
MIN_FRACTION = 0.01         # ... which is 1 % of the raw range (and at least 1)
GAMMA = 2.0                 # perceptual curve between FLOOR and 100
ACTUAL_SLACK = 0.03         # a firmware backlight's actual_brightness this far off: the firmware moved it
RETRY_S = 60                # a device no method could write is tried again after this long

LOGIND = ("org.freedesktop.login1", "/org/freedesktop/login1/session/auto",
          "org.freedesktop.login1.Session", "SetBrightness")


def backlight_root(root=None):
    return root or os.environ.get(BACKLIGHT_ENV) or BACKLIGHT


def drm_root(drm=None):
    return drm or os.environ.get(DRM_ENV) or DRM


def runtime():
    """$XDG_RUNTIME_DIR, read when asked (the tests set it before importing)."""
    return os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"


def read_int(path):
    try:
        with open(path) as handle:
            return int(handle.read().strip())
    except (OSError, ValueError):
        return None


def read_text(path):
    try:
        with open(path) as handle:
            return handle.read().strip()
    except OSError:
        return ""


# -- which screen has which backlight -----------------------------------------------
def connectors(drm=None):
    """{connector name: DRM entry} of the connected connectors:
    card1-eDP-1 -> {"eDP-1": "card1-eDP-1"}."""
    found = {}
    try:
        entries = sorted(os.listdir(drm_root(drm)))
    except OSError:
        return found
    for entry in entries:
        card, dash, name = entry.partition("-")
        if dash and card.startswith("card") and card[4:].isdigit() and name \
                and read_text(os.path.join(drm_root(drm), entry, "status")) == "connected":
            found.setdefault(name, entry)
    return found


def devices(root=None):
    """{device: {"max", "type", "link"}} for every backlight with a usable
    range; "link" is the basename its device link resolves to."""
    root = backlight_root(root)
    found = {}
    try:
        entries = sorted(os.listdir(root))
    except OSError:
        return found
    for dev in entries:
        top = read_int(os.path.join(root, dev, "max_brightness"))
        if not top or top <= 0:
            continue
        link = os.path.join(root, dev, "device")
        found[dev] = {"max": top, "type": read_text(os.path.join(root, dev, "type")) or "raw",
                      "link": os.path.basename(os.path.realpath(link)) if os.path.islink(link) else ""}
    return found


def screens(drm=None, root=None):
    """{connector: device} for every screen with a kernel backlight. {} on
    a desktop (and in the tests, unless they build a fake tree)."""
    conns = connectors(drm)
    if not conns:
        return {}
    by_entry = {entry: name for name, entry in conns.items()}
    out, loose = {}, []
    for dev, info in devices(root).items():
        name = by_entry.get(info["link"])
        if name and name not in out:
            out[name] = dev
        else:
            loose.append((TYPE_RANK.get(info["type"], 3), dev))
    panels = [name for name in conns if name.split("-")[0] in INTERNAL and name not in out]
    if loose and len(panels) == 1 and not any(n.split("-")[0] in INTERNAL for n in out):
        out[panels[0]] = min(loose)[1]
    return out


def find(connector, drm=None, root=None):
    """The backlight device of one screen (matched without case), or None."""
    for name, dev in screens(drm, root).items():
        if name.lower() == str(connector).lower():
            return dev
    return None


# -- levels ------------------------------------------------------------------------------
def max_brightness(dev, root=None):
    return read_int(os.path.join(backlight_root(root), dev, "max_brightness"))


def raw(dev, root=None):
    """The level last asked of the kernel (`brightness`), or None."""
    return read_int(os.path.join(backlight_root(root), dev, "brightness"))


def level(dev, root=None):
    """(raw, max) as it is now, or (None, None): `brightness`; for a
    firmware backlight only, actual_brightness when it says the firmware
    moved it (see the docstring for why never for a raw one)."""
    top = max_brightness(dev, root)
    asked = raw(dev, root)
    if not top or asked is None:
        return None, None
    if read_text(os.path.join(backlight_root(root), dev, "type")) == "firmware":
        actual = read_int(os.path.join(backlight_root(root), dev, "actual_brightness"))
        if actual is not None and abs(actual - asked) > top * ACTUAL_SLACK:
            asked = actual
    return max(0, min(top, asked)), top


def min_raw(top):
    """The lowest level ever written: MIN_FRACTION of the range, never 0."""
    return max(1, min(top, round(top * MIN_FRACTION)))


def to_raw(percent, top):
    """screen-color's 20-100 % -> a raw level in [min_raw, top]."""
    percent = max(FLOOR, min(100, percent))
    t = (percent - FLOOR) / (100 - FLOOR)
    value = round(top * (MIN_FRACTION + (1 - MIN_FRACTION) * t ** GAMMA))
    return max(min_raw(top), min(top, value))


def to_percent(value, top):
    """A raw level -> 20-100 %; anything at or below the floor reads 20."""
    if not top:
        return 100
    frac = max(0.0, min(1.0, value / top))
    t = max(0.0, (frac - MIN_FRACTION) / (1 - MIN_FRACTION)) ** (1 / GAMMA)
    return max(FLOOR, min(100, round(FLOOR + (100 - FLOOR) * t)))


def percent(dev, root=None):
    value, top = level(dev, root)
    return None if top is None else to_percent(value, top)


def stepped(current, top, target_percent, step):
    """The raw level for a change to target_percent from raw `current`.
    A relative step (step != 0) always moves at least one raw unit the way
    it was asked: with a coarse backlight (acpi_video's 10 or 15 levels) a
    5 % step can round back to where it started, and the key would do
    nothing. Nor does it ever move the other way: a level below the floor
    (0 or 1, set by the firmware or another tool) stays where it is on a
    down key instead of being lifted to min_raw, and a level the curve
    rounds below on a coarse grid is never lowered by an up key."""
    new = to_raw(target_percent, top)
    if step > 0:
        if new <= current:
            new = current + 1
        return max(current, min(top, new))
    if step < 0:
        if new >= current:
            new = current - 1
        return min(current, max(min_raw(top), new))
    return max(min_raw(top), min(top, new))


# -- who may write, one at a time ------------------------------------------------------
def marks_file():
    return os.path.join(runtime(), "backlight-unwritable.json")


def unwritable():
    """{device: when every write method last failed on it}."""
    try:
        with open(marks_file()) as handle:
            data = json.load(handle)
        return {k: float(v) for k, v in data.items()} if isinstance(data, dict) else {}
    except (OSError, ValueError, TypeError, AttributeError):
        return {}


def mark(dev, failed):
    """Note (failed) or forget a device no method could write. Only touches
    the file when that changes something, so a working write costs a stat."""
    marks = unwritable()
    if failed:
        marks[dev] = time.time()
    elif marks.pop(dev, None) is None:
        return
    try:
        if not marks:
            os.remove(marks_file())
            return
        os.makedirs(runtime(), exist_ok=True)
        tmp = marks_file() + ".tmp"
        with open(tmp, "w") as handle:
            json.dump(marks, handle)
        os.replace(tmp, marks_file())
    except OSError:
        pass


def driven(drm=None, root=None, retry=False):
    """screens() without the devices that could not be written: the screens
    whose brightness is the backlight's. retry=True (a command about to
    write) keeps those that failed more than RETRY_S ago, to try again."""
    lit = screens(drm, root)
    if not lit:
        return lit
    marks = unwritable()
    now = time.time()
    return {name: dev for name, dev in lit.items()
            if dev not in marks or (retry and now - marks[dev] > RETRY_S)}


@contextlib.contextmanager
def locked():
    """One backlight read-modify-write at a time (see the docstring)."""
    os.makedirs(runtime(), exist_ok=True)
    with open(os.path.join(runtime(), "backlight.lock"), "a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


# -- writing -------------------------------------------------------------------------------
def write(dev, value, root=None, run=None):
    """Set the raw level; the method that worked ("sysfs", "logind",
    "brightnessctl") or None, which also marks the device unwritable (and a
    success unmarks it). `run` stands in for subprocess.run (tests)."""
    method = _write(dev, int(value), root, run or subprocess.run)
    mark(dev, method is None)
    return method


def _write(dev, value, root, run):
    path = os.path.join(backlight_root(root), dev, "brightness")
    if os.access(path, os.W_OK):
        try:
            with open(path, "w") as handle:
                handle.write(str(value))
            return "sysfs"
        except OSError:
            pass
    # A missing busctl / brightnessctl is an OSError, and the next one is tried.
    commands = (("logind", ["busctl", "call", *LOGIND, "ssu", "backlight", dev, str(value)]),
                ("brightnessctl", ["brightnessctl", "--quiet", "-d", dev, "set", str(value)]))
    for method, argv in commands:
        try:
            if run(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5).returncode == 0:
                return method
        except (OSError, subprocess.SubprocessError):
            continue
    return None


def set_percent(dev, target_percent, step=0, root=None, run=None, base=None):
    """Set a device to target_percent (stepped() for relative changes);
    the new raw level, or None when it could not be read or written.
    `base` is the raw level a relative step starts from when that is not
    the live one (screen-color: the level before an idle dim)."""
    current, top = level(dev, root)
    if top is None:
        return None
    new = stepped(current if base is None else max(0, min(top, int(base))), top, target_percent, step)
    if new == current:
        return new
    return new if write(dev, new, root, run) else None


def status_data(drm=None, root=None):
    out = {}
    marks = unwritable()
    for name, dev in sorted(screens(drm, root).items()):
        value, top = level(dev, root)
        out[name] = {"device": dev, "raw": value, "max": top,
                     "percent": None if top is None else to_percent(value, top),
                     "type": devices(root).get(dev, {}).get("type", ""),
                     "writable": dev not in marks}
    return out


if __name__ == "__main__":
    if sys.argv[1:] not in ([], ["status"]):
        sys.exit(__doc__)
    print(json.dumps({"screens": status_data(), "floor": FLOOR}, indent=1))
