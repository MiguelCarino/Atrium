#!/usr/bin/env python3
"""The screens, for the scripts: which ones there are, how big they are,
which one is the primary and which can do HDR. The same answers
lua/monitors.lua gives the config, so no script has to name a connector
(DP-1, HDMI-A-1 ...) of its own -- the desktop then works on any set of
screens, and on this machine exactly as the host file lays it out.

    screens.py              JSON: the outputs, the primary, the HDR screens
    screens.py primary      just the primary's name ("" when nothing knows one)
    screens.py check        the config files that name a screen this machine
                            does not have, with the command that moves each
                            to the primary (read-only; exit 1 if any)

Imported by its siblings (display.py, the wallpaper makers, the slideshow ...)
as a plain module -- the name has no dash on purpose -- after they put their
own folder on sys.path, the same way they import theme.py.

Where the answers come from, first match wins
---------------------------------------------
The machine's host file, lua/hosts/<hostname>.lua (what lua/monitors.lua
loads; scripts/monitors-capture.py writes one from the live layout):

    M.screens     = { "DP-1", "DP-2", "HDMI-A-1" }   the screens in order: the
                                                     first is the primary,
                                                     the second and third get
                                                     workspaces 4 and 6
                                                     (lua/rules.lua)
    M.hdr_capable = { ["DP-1"] = true }              the screens with HDR

are read here with a pattern, not run: keep each on one line as above.

  primary()      display.conf's primary=<o> (Settings > Screens, display.py
                 primary) -> the host file's first screen -> the live screen
                 at 0x0 -> the first one Hyprland lists -> "" (no Hyprland,
                 no host file: a test, or a script run from a TTY).
  order()        the host file's screens -> the live ones, 0x0 first.
  hdr_capable()  the host file's list -> none. Hyprland does not report what
                 a panel can do, only what it is doing, so with no host file
                 there is no HDR switch (lua/monitors.lua agrees).
  outputs()      the live screens (hyprctl monitors -j) in order(), each with
                 its sizes worked out (see there).
  sizes()        {name: (W, H)} for rendering one picture per screen, with
                 FALLBACK_SIZE for the primary when Hyprland is not there;
                 primary_size() just the primary's (a renderer's -W / -H).

The live parts ask hyprctl once per call (a ~5 ms round trip); nothing here
caches them, so a long-running caller sees a screen plugged in later.
"""
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import desk_common  # noqa: E402  (hypr_request: hyprctl over the socket)
# The host files sit next to the scripts in the config (../lua/hosts), so a
# copy of the desktop elsewhere reads its own.
HOSTS = os.path.join(os.path.dirname(HERE), "lua", "hosts")
# One host file to read instead of HOSTS/<hostname>.lua: the tests point it at
# a fixture (tests/helpers.py), so they give the same answers on any machine.
# Set but missing = no host file.
HOST_FILE_ENV = "HYPR_HOST_FILE"
STATE = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"),
                     "hypr", "display.conf")
# A picture for "a screen" when nothing says which: the commonest desktop size.
FALLBACK_SIZE = (1920, 1080)
FALLBACK_NAME = "default"      # the folder sizes() names when no screen has one


# -- the host file -------------------------------------------------------------
def hostname():
    """The same name lua/monitors.lua's hostname() makes: /etc/hostname (or
    `hostname -s`) up to the first dot, anything but letters, digits and _
    turned into _."""
    name = ""
    try:
        with open("/etc/hostname", encoding="utf-8") as handle:
            name = handle.readline().strip()
    except OSError:
        pass
    if not name:
        try:
            name = subprocess.run(["hostname", "-s"], capture_output=True, text=True,
                                  timeout=2).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            name = ""
    return re.sub(r"[^A-Za-z0-9_]", "_", name.split(".")[0])


def host_text():
    """This machine's host file, or "" when it has none."""
    path = os.environ.get(HOST_FILE_ENV) or os.path.join(HOSTS, hostname() + ".lua")
    try:
        with open(path, encoding="utf-8") as handle:
            return handle.read()
    except OSError:
        return ""


def parse_host(text):
    """{"screens": [...], "hdr_capable": [...]} out of a host file's text.
    Pure, for the tests. Lines that are Lua comments do not count."""
    code = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("--"))
    out = {"screens": [], "hdr_capable": []}
    m = re.search(r"^\s*M\.screens\s*=\s*\{([^}]*)\}", code, re.M)
    if m:
        out["screens"] = re.findall(r'"([^"]+)"', m.group(1))
    m = re.search(r"^\s*M\.hdr_capable\s*=\s*\{([^}]*)\}", code, re.M)
    if m:
        out["hdr_capable"] = re.findall(r'\[\s*"([^"]+)"\s*\]\s*=\s*true', m.group(1))
    return out


def host():
    return parse_host(host_text())


# -- live --------------------------------------------------------------------
def hyprctl_monitors(include_disabled=False):
    """hyprctl monitors -j as a list ([] without Hyprland)."""
    mons = desk_common.hypr_request("monitors all" if include_disabled else "monitors",
                                    json=True, timeout=3)      # over the socket: no process
    return mons if isinstance(mons, list) else []


def live_order(mons):
    """Names of the live screens: the one at 0x0 first (where Hyprland puts
    the first screen when positions are "auto", as the no-host-file layout
    has them), then the rest in the order Hyprland lists them (by id).
    lua/monitors.lua's live_order() is the same rule."""
    mons = sorted(mons, key=lambda m: m.get("id", 0))
    first = [m for m in mons if m.get("x", 0) == 0 and m.get("y", 0) == 0][:1]
    return [m["name"] for m in first + [m for m in mons if m not in first]]


# -- the answers ---------------------------------------------------------------
def read_state():
    state = {}
    try:
        with open(STATE, encoding="utf-8") as handle:
            for line in handle:
                key, sep, value = line.partition("=")
                if sep:
                    state[key.strip()] = value.strip()
    except OSError:
        pass
    return state


def order(mons=None, profile=None):
    """The screens in order, primary-by-default first (see the top)."""
    profile = host() if profile is None else profile
    if profile["screens"]:
        return list(profile["screens"])
    return live_order(hyprctl_monitors() if mons is None else mons)


def default_primary(mons=None, profile=None):
    """The primary when display.conf names none: order()'s first, or ""."""
    names = order(mons, profile)
    return names[0] if names else ""


def primary(state=None, mons=None, profile=None):
    """The main screen: workspace 1, the bar, the wallpaper the accent is
    taken from, the lock screen's password field."""
    state = read_state() if state is None else state
    return state.get("primary") or default_primary(mons, profile)


def hdr_capable(profile=None):
    return list((host() if profile is None else profile)["hdr_capable"])


def logical_size(width, height, scale, transform):
    """What Hyprland lays out: the mode / scale, swapped when rotated
    (transform 1, 3, 5, 7)."""
    scale = scale or 1
    w, h = round(width / scale), round(height / scale)
    return (h, w) if transform % 2 else (w, h)


def describe(m):
    """One hyprctl monitor as the scripts want it. width / height are the
    mode as the panel is driven (a portrait screen still says 1920x1080);
    pixels is that turned the way it is seen (1080x1920 for that screen) --
    the size for a picture shown one pixel per pixel, e.g. a hyprpaper still;
    logical is what Hyprland lays out (pixels / scale) -- the size a window
    is drawn at, e.g. a video wallpaper's player."""
    w, h, t = m.get("width", 0), m.get("height", 0), m.get("transform", 0)
    pixels = (h, w) if t % 2 else (w, h)
    return {
        "name": m["name"],
        "description": m.get("description", ""),
        "width": w, "height": h,
        "pixels": pixels,
        "logical": logical_size(w, h, m.get("scale", 1), t),
        "scale": m.get("scale", 1),
        "transform": t,
        "portrait": pixels[1] > pixels[0],
        "x": m.get("x", 0), "y": m.get("y", 0),
        "disabled": bool(m.get("disabled", False)),
    }


def outputs(mons=None, profile=None):
    """The live screens, described, in order(): the host file's order first,
    any screen it does not name after it."""
    mons = hyprctl_monitors() if mons is None else mons
    rank = {name: i for i, name in enumerate(order(mons, profile))}
    mons = sorted(mons, key=lambda m: (rank.get(m["name"], len(rank)), m.get("id", 0)))
    return [describe(m) for m in mons]


def sizes(logical=False, mons=None, profile=None, state=None):
    """{name: (W, H)} for one picture per live screen: pixels (a still), or
    logical=True (a video a player window shows). Without Hyprland:
    FALLBACK_SIZE for the primary (or FALLBACK_NAME when nothing names one),
    so a renderer always has one screen to draw for."""
    found = {o["name"]: (o["logical"] if logical else o["pixels"])
             for o in outputs(mons, profile) if not o["disabled"]}
    if found:
        return found
    return {primary(state, [] if mons is None else mons, profile) or FALLBACK_NAME: FALLBACK_SIZE}


def primary_size(logical=False):
    """(W, H) of the primary as sizes() gives it: the default size of a
    renderer's single picture (-W / -H). Another screen's, or FALLBACK_SIZE,
    when the primary is not up."""
    found = sizes(logical)
    return found.get(primary()) or next(iter(found.values()))


# The config files that hold a screen's NAME, because the program reading them
# takes no other kind of answer -- each is moved by its own settings command,
# so check() only reports. Shipped with the primary of the machine they were
# written on: on another machine they may name a screen that is not there
# (no bar, notifications nowhere, a lock screen with no password field).
# (file(s), pattern whose group 1 is the name, the command that moves it); with
# several files the last one that has a match is in effect (mako includes its
# generated/settings -- notify-settings.py's -- after its own output= line).
CONF = os.path.dirname(os.path.dirname(HERE))         # ~/.config
NAMED_IN = [
    (os.path.join(CONF, "waybar", "config"), r'^\s*"output"\s*:\s*"([^"]+)"',
     "~/.config/hypr/scripts/bar-settings.py screen {p} && ~/.config/hypr/scripts/bar-settings.py apply"),
    (os.path.join(CONF, "waybar", "config-toolbox"), r'^\s*"output"\s*:\s*"([^"]+)"',
     "(moves with the bar: bar-settings.py screen {p})"),
    ((os.path.join(CONF, "mako", "config"), os.path.join(CONF, "mako", "generated", "settings")),
     r"^output=(\S+)",
     "~/.config/hypr/scripts/notify-settings.py set output {p}"),
    (os.path.join(HERE, "..", "hyprlock.conf"), r"^[ \t]*monitor[ \t]*=[ \t]*(\S+)",
     "~/.config/hypr/scripts/lock-screen.py screen {p}"),
]


def check(mons=None):
    """[(file, named screen, fix)] for every file in NAMED_IN that names a
    screen Hyprland does not list (all screens, switched-off ones included);
    the fix moves it to the primary, or the first live screen when even the
    primary is not here.
    [] when Hyprland does not answer -- nothing to compare with."""
    mons = hyprctl_monitors(include_disabled=True) if mons is None else mons
    have = {m.get("name") for m in mons}
    if not have:
        return []
    p = primary(None, mons)
    if p not in have:           # the host file names a screen that is not here
        p = live_order([m for m in mons if not m.get("disabled")] or mons)[0]
    found = []
    for paths, pattern, fix in NAMED_IN:
        path, names = None, set()
        for one in (paths if isinstance(paths, tuple) else (paths,)):
            try:
                with open(one, encoding="utf-8") as handle:
                    got = set(re.findall(pattern, handle.read(), re.M))
            except OSError:
                continue
            if got:
                path, names = one, got
        for name in sorted(names - have):
            found.append((os.path.normpath(path), name, fix.format(p=p)))
    return found


def main(argv):
    if argv[:1] == ["primary"]:
        print(primary())
        return 0
    if argv[:1] == ["check"]:
        found = check()
        for path, name, fix in found:
            print(f"{path}: names {name}, which this machine does not have\n    fix: {fix}")
        return 1 if found else 0
    if argv:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    mons = hyprctl_monitors()
    profile = host()
    print(json.dumps({"outputs": outputs(mons, profile), "primary": primary(None, mons, profile),
                      "order": order(mons, profile), "hdr_capable": hdr_capable(profile)}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
