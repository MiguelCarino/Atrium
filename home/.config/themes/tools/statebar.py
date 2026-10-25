#!/usr/bin/env python3
"""Test bar: every pill state the real bar can show, side by side, for
screenshots. A theme is mostly judged on states you rarely see (a full disk,
a muted mic, a failed update check), so this puts them all on screen at once
instead of waiting for them to happen.

    statebar.py show            start it (overlay at the bottom of the primary
                                screen)
    statebar.py hide            stop it
    statebar.py shot FILE.png   start, wait for it to draw, screenshot, stop

STATEBAR_OUTPUT=<name> draws it on that screen instead. Without it the bar
goes to the primary (Settings > Screens) when that screen is connected, else
to the first connected one: with the main screen unplugged or powered off the
bar named an output waybar could not find (no bar, and `shot` died in
geometry() with StopIteration).

It is a second waybar with the REAL style.css (and therefore the live
generated/accent.css and generated/theme.css), fed static JSON by
custom modules whose names match the real ones -- custom/disk#crit is drawn
as #custom-disk with the class from the JSON, exactly like the real pill. The
bar's own surface is painted solid black (statebar.css, next to this file's
output in $XDG_RUNTIME_DIR) so the screenshot does not depend on what window
happens to be under it: two shots of the same theme are pixel-identical, and
`magick compare -metric AE a.png b.png null:` is a real test.

Layer "overlay", exclusive zone off: it covers the bottom 80 px of the primary screen for a
few seconds and moves no window. Namespace "themetest", outside waybar-*, so
the compositor's glass blur (lua/rules.lua) leaves it alone -- another reason
the shot is deterministic.

Animated states (critical CPU blink, REC pulse, capture pulse) are on the
second row and will differ between shots by animation phase; compare those
by eye.

Glyphs are built with chr() at runtime and reach waybar as JSON \\u escapes,
so this file holds no private-use characters.
"""

import json
import os
import shlex
import signal
import subprocess
import sys
import time

RUNTIME = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
WORK = os.path.join(RUNTIME, "themetest-bar")
PIDFILE = os.path.join(WORK, "pid")
# STATEBAR_STYLE: another style.css to render instead (an A/B against a saved
# copy of the old one; give the copy a generated/ symlink so its imports resolve).
STYLE = os.environ.get("STATEBAR_STYLE") or os.path.expanduser("~/.config/waybar/style.css")
sys.path.insert(0, os.path.expanduser("~/.config/hypr/scripts"))
import screens  # noqa: E402  (hypr/scripts/screens.py)


def pick_output(override, primary, connected):
    """The screen to draw on: the override, else the primary if it is
    connected, else the first connected screen (hyprctl's order), else the
    primary anyway (nothing is connected: waybar says so in its log)."""
    if override:
        return override
    if primary in connected or not connected:
        return primary
    return connected[0]


def connected_outputs():
    try:
        mons = json.loads(subprocess.run(["hyprctl", "monitors", "-j"], capture_output=True,
                                         text=True, timeout=2).stdout)
        return [m["name"] for m in mons]
    except (OSError, ValueError, subprocess.SubprocessError, KeyError, TypeError):
        return []


# Settings > Screens' choice, else the host file's first -- if it is connected.
OUTPUT = pick_output(os.environ.get("STATEBAR_OUTPUT", ""), screens.primary(),
                     connected_outputs())
ROW_H = 36


def g(cp):
    return chr(cp)


# The label colours come from the current theme (theme.conf color.* keys, via
# waybar/generated/colors.conf -- the same lookup cpu_usage.sh, gpu_usage.sh
# and updates.sh make), so a theme's shot shows ITS labels. The fallbacks are
# cyberpunk's, which is also what this file used to hardcode: a cyberpunk shot
# is unchanged.
sys.path.insert(0, os.path.expanduser("~/.config/waybar/scripts"))
try:
    import themecolors
    _hex = themecolors.hex
except ImportError:
    def _hex(name, fallback):
        return fallback
CPU = _hex("cpu", "#ff2a6d")
GPU = _hex("gpu", "#39ff14")
CPU_HOT = _hex("cpu_hot", CPU)     # the label on the filled critical pill
PENDING = _hex("pending", "#ff2a6d")


# (module, text, class). Text may hold Pango markup; the colours in it are the
# ones the real scripts print (cpu_usage.sh, gpu_usage.sh, updates.sh).
ROW1 = [
    ("custom/day", "Sat 17 Oct", ""),
    ("custom/clock", "21:45:07", "local"),
    ("custom/weather", f"{g(0xf185)} 21°", ""),
    ("custom/updates", f"<span color='{PENDING}'>{g(0xf49e)}</span> 12", "pending"),
    ("custom/repos", g(0xf1d3), "unpushed"),
    ("custom/notifications", g(0xf0f3), ""),
    ("custom/clock#utc", "03:45 UTC", "utc"),
    ("custom/clock#epoch", "1792302307", "epoch"),
    ("custom/updates#many", f"{g(0xf49e)} 64", "many"),
    ("custom/updates#ok", g(0xf49e), "updated"),
    ("custom/repos#dirty", g(0xf1d3), "dirty"),
    ("custom/repos#clean", g(0xf1d3), "clean"),
    ("custom/notifications#dnd", g(0xf1f6), "dnd"),
    ("custom/workhours", f"{g(0xf0b1)} 3:15", "work"),
    ("custom/recording#replay", f"{g(0xf03d)} replay", "replay"),
    ("custom/player", f"{g(0xf04b)} Artist - Track", "playing"),
    ("custom/player#paused", f"{g(0xf04c)} Paused", "paused"),
    ("custom/player#error", f"{g(0xf071)} player", "error"),
    ("custom/mic", g(0xf130), "active"),
    ("custom/camera", g(0xf030), "active"),
    ("custom/location", g(0xf3c5), "active"),
    ("custom/disk", f"{g(0xf0a0)} 41%", ""),
    ("custom/disk#warn", f"{g(0xf0a0)} 88%", "warning"),
    ("custom/disk#crit", f"{g(0xf0a0)} 97%", "critical"),
    ("custom/network", f"{g(0xf6ff)} 1.2M", ""),
    ("custom/network#off", f"{g(0xf127)} offline", "disconnected"),
    ("custom/toolbox", g(0xf1de), "open"),
    ("custom/power", g(0xf011), ""),
]

ROW2 = [
    ("custom/cpu", f"<span color='{CPU}'>CPU</span>  7%  48° 16.2G", "normal"),
    ("custom/gpu", f"<span color='{GPU}'>GPU</span>  3%  41° 1.1G", "normal"),
    ("custom/gpu#na", "GPU N/A", "unavailable"),
    ("custom/fsstate", g(0xf065), "idle"),
    ("custom/fsstate#a", g(0xf065) + " A", "mode-a"),
    ("custom/fsstate#b", g(0xf065) + " B", "mode-b"),
    ("custom/fsstate#other", g(0xf065) + " ?", "other"),
    ("custom/fsstate#error", g(0xf065) + " !", "error"),
    ("custom/nightlight", g(0xf186), "on"),
    ("custom/nightlight#off", g(0xf186), "off"),
    ("custom/display", g(0xf26c), "on"),
    ("custom/display#off", g(0xf26c), "off"),
    ("custom/keybinds", g(0xf11c), ""),
    ("custom/weather#stale", f"{g(0xf0c2)} --", "stale"),
    ("custom/updates#err", g(0xf49e), "error"),
    # The clock with a world clock pinned (clock_panel.py's pin: "· TYO" after
    # the time, the widest the clock pill gets) and the timers pill's states
    # (timers.py bar: a countdown, the stopwatch paused, one ringing) -- none
    # of them were here, so no theme shot showed them.
    ("custom/clock#pin", "21:45:07 \u00b7 TYO 12:45", "local"),
    ("custom/timers", f"{g(0xf252)} 4:59", "timer"),
    ("custom/timers#paused", f"{g(0xf2f2)} 0:03", "paused"),
    ("custom/timers#ringing", f"{g(0xf0f3)} tea", "ringing"),
    # Animated: compare by eye.
    ("custom/cpu#crit", f"<span color='{CPU_HOT}'>CPU</span> 99%  91° 16.2G", "critical"),
    ("custom/recording", f"{g(0xf111)} 0:42", "recording"),
    ("custom/capture", g(0xf030), "recording"),
]


def module_conf(text, cls):
    line = json.dumps({"text": text, "class": cls, "tooltip": ""})
    return {"exec": "printf '%s\\n' " + shlex.quote(line), "return-type": "json",
            "format": "{}", "tooltip": False}


def bar(name, mods, bottom):
    conf = {
        "name": "themetest", "layer": "overlay", "position": "bottom",
        "output": OUTPUT, "exclusive": False, "height": ROW_H,
        "margin": f"0 0 {bottom} 0", "passthrough": True,
        "modules-left": [m for m, _, _ in mods],
    }
    for m, text, cls in mods:
        conf[m] = module_conf(text, cls)
    return conf


def write_files():
    os.makedirs(WORK, exist_ok=True)
    cfg = os.path.join(WORK, "config.json")
    css = os.path.join(WORK, "statebar.css")
    with open(cfg, "w") as f:
        json.dump([bar("themetest", ROW2, 0), bar("themetest", ROW1, ROW_H)], f, indent=1)
    with open(css, "w") as f:
        # Absolute import: the real file, so its own relative imports
        # (generated/...) resolve next to it. Then a solid floor.
        f.write(f'@import url("file://{STYLE}");\n'
                "window#waybar.themetest { background: #000000; }\n")
    return cfg, css


def running():
    try:
        with open(PIDFILE) as f:
            pid = int(f.read())
        os.kill(pid, 0)
        return pid
    except (OSError, ValueError):
        return None


def show():
    if running():
        return
    cfg, css = write_files()
    proc = subprocess.Popen(["waybar", "-c", cfg, "-s", css], stdout=subprocess.DEVNULL,
                            stderr=open(os.path.join(WORK, "log"), "w"),
                            start_new_session=True)
    with open(PIDFILE, "w") as f:
        f.write(str(proc.pid))


def hide():
    pid = running()
    if pid:
        os.kill(pid, signal.SIGTERM)    # SIGTERM, never SIGUSR2/SIGINT: see bar-restart.sh
    try:
        os.remove(PIDFILE)
    except OSError:
        pass


def geometry():
    mons = json.loads(subprocess.run(["hyprctl", "monitors", "-j"], capture_output=True,
                                     text=True).stdout)
    m = next(m for m in mons if m["name"] == OUTPUT)
    w, h = int(m["width"] / m["scale"]), int(m["height"] / m["scale"])
    return m["x"], m["y"] + h - 2 * ROW_H, w, 2 * ROW_H


def shot(path):
    show()
    time.sleep(4)
    x, y, w, h = geometry()
    subprocess.run(["grim", "-g", f"{x},{y} {w}x{h}", path], check=True)
    hide()


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "show":
        show()
    elif cmd == "hide":
        hide()
    elif cmd == "shot" and len(sys.argv) == 3:
        shot(sys.argv[2])
    else:
        print(__doc__.strip(), file=sys.stderr)
        sys.exit(2)
