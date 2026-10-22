#!/usr/bin/env python3
"""mpv's borders: a preset for the window's frame (Hyprland) and one for the
on-screen controls (uosc), each laid over the desktop theme's look. The
backend of Settings > Theme's "Video player" section.

    mpv-style.py status [--json]      both choices and the presets
    mpv-style.py frame NAME           the window frame (see FRAMES)
    mpv-style.py controls NAME        the controls' borders (see CONTROLS)
    mpv-style.py next frame|controls  the next preset, for a key or the launcher

"theme" for either means no override: what the desktop theme says.

Where it lives. Both choices are frame= / controls= in
~/.local/state/hypr/mpv-style.conf.
  frame     lua/mpvframe.lua turns the preset into a window rule for class
            mpv; this script runs `hyprctl eval 'require("lua.mpvframe").apply()'`
            so it takes at once, on mpv windows already open too.
  controls  written as uosc script-opts to ~/.config/mpv/controls.conf, which
            mpv.conf includes right AFTER theme.conf (a later script-opts
            entry for the same key wins, so the preset beats the theme). A
            new mpv reads it at start; mpv windows already open get the same
            options through their IPC sockets (/tmp/mpvSockets/, from
            mpvSockets.lua) and uosc redraws with them straight away.
Works with both skins: the plain uosc and aero's Liquid Glass fork read the
same uosc-* options.
"""

import glob
import json
import os
import re
import socket
import subprocess
import sys

HOME = os.path.expanduser("~")
STATE = os.path.join(os.environ.get("XDG_STATE_HOME", os.path.join(HOME, ".local", "state")),
                     "hypr", "mpv-style.conf")
MPV = os.path.join(HOME, ".config", "mpv")
CONTROLS_CONF = os.path.join(MPV, "controls.conf")
THEME_CONF = os.path.join(MPV, "theme.conf")
SOCKETS = "/tmp/mpvSockets"

# The names and what each looks like; the fields are in lua/mpvframe.lua.
FRAMES = {
    "theme":   "the theme's own (aero: a wide glass pane; cyberpunk: neon; "
               "moe: a pastel ribbon; matrix: a phosphor line; win95: a raised bevel)",
    "cinema":  "no border, square corners, no shadow",
    "thin":    "a 1 px border",
    "bold":    "a 4 px border",
    "accent":  "3 px, a gradient of your accent colour",
    "rainbow": "3 px, a rainbow gradient",
    "soft":    "big rounded corners and a 2 px border",
    "square":  "square corners and a 2 px border",
}

# uosc options per preset. Only border and shape keys: the colours, fonts
# and the rest stay the theme's.
CONTROLS = {
    "theme":    ("the theme's own", {}),
    "flat":     ("square, no outlines", {"border_radius": "0", "timeline_border": "0",
                                         "text_border": "0.8", "window_border_size": "0"}),
    "rounded":  ("soft corners, a thin outline", {"border_radius": "10", "timeline_border": "1"}),
    "pill":     ("fully round bubbles, a thick bar", {"border_radius": "24", "timeline_style": "bar",
                                                       "timeline_size": "26", "timeline_border": "0"}),
    "outlined": ("thick outlines everywhere", {"border_radius": "6", "timeline_border": "3",
                                               "text_border": "2", "window_border_size": "2"}),
    "bold":     ("heavy text outlines, a framed bar", {"border_radius": "8", "timeline_border": "2",
                                                        "text_border": "2.5"}),
    "minimal":  ("a thin line, no outlines", {"timeline_style": "line", "timeline_size": "20",
                                              "timeline_border": "0", "text_border": "0.6",
                                              "border_radius": "2", "window_border_size": "0"}),
}
# uosc's own defaults (its main.lua), for a key the theme does not set: going
# back from a preset to "theme" in a running mpv must undo every key.
UOSC_DEFAULTS = {"border_radius": "4", "timeline_border": "1", "text_border": "1.2",
                 "window_border_size": "1", "timeline_style": "line", "timeline_size": "40"}


def read_state():
    out = {"frame": "theme", "controls": "theme"}
    try:
        with open(STATE) as handle:
            for line in handle:
                key, _, value = line.strip().partition("=")
                if key in out and value:
                    out[key] = value
    except OSError:
        pass
    return out


def write_state(state):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    tmp = STATE + ".tmp"
    with open(tmp, "w") as handle:
        handle.write("# mpv's borders (scripts/mpv-style.py; lua/mpvframe.lua reads frame=)\n")
        for key in ("frame", "controls"):
            handle.write(f"{key}={state[key]}\n")
    os.replace(tmp, STATE)


def theme_uosc():
    """The uosc-* values the current theme sets (its theme.conf)."""
    found = {}
    try:
        with open(THEME_CONF) as handle:
            for line in handle:
                m = re.match(r"\s*script-opts-append\s*=\s*uosc-([\w]+)=(.*?)\s*$", line)
                if m:
                    found[m.group(1)] = m.group(2)
    except OSError:
        pass
    return found


def controls_text(name):
    desc, opts = CONTROLS[name]
    lines = ["# GENERATED by ~/.config/hypr/scripts/mpv-style.py -- do not edit.",
             f"# Controls' borders: {name} ({desc}). Included after theme.conf, so",
             "# these win over the theme's values for the same keys.", ""]
    lines += [f"script-opts-append=uosc-{k}={v}" for k, v in opts.items()]
    return "\n".join(lines) + "\n"


def live_values(name):
    """Every key any preset touches, with the value it should have now:
    the preset's, else the theme's, else uosc's default."""
    theme = theme_uosc()
    keys = sorted({k for _, opts in CONTROLS.values() for k in opts})
    opts = CONTROLS[name][1]
    return {k: opts.get(k, theme.get(k, UOSC_DEFAULTS.get(k, ""))) for k in keys}


def send_live(values):
    """Push uosc options into every running mpv; how many took them."""
    done = 0
    for path in glob.glob(os.path.join(SOCKETS, "*")):
        try:
            with socket.socket(socket.AF_UNIX) as sock:
                sock.settimeout(1)
                sock.connect(path)
                for k, v in values.items():
                    cmd = {"command": ["change-list", "script-opts", "append", f"uosc-{k}={v}"]}
                    sock.sendall((json.dumps(cmd) + "\n").encode())
            done += 1
        except OSError:
            continue        # a socket left by an mpv that crashed
    return done


def set_frame(name):
    if name not in FRAMES:
        raise SystemExit(f"unknown frame '{name}': {', '.join(FRAMES)}")
    state = read_state()
    state["frame"] = name
    write_state(state)
    subprocess.run(["hyprctl", "eval", 'require("lua.mpvframe").apply()'],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return f"mpv frame: {name} ({FRAMES[name]})"


def set_controls(name):
    if name not in CONTROLS:
        raise SystemExit(f"unknown controls '{name}': {', '.join(CONTROLS)}")
    state = read_state()
    state["controls"] = name
    write_state(state)
    tmp = CONTROLS_CONF + ".tmp"
    with open(tmp, "w") as handle:
        handle.write(controls_text(name))
    os.replace(tmp, CONTROLS_CONF)
    live = send_live(live_values(name))
    return (f"mpv controls: {name} ({CONTROLS[name][0]})"
            + (f"; {live} open mpv window{'s' if live != 1 else ''} updated" if live else ""))


def status():
    state = read_state()
    return {"frame": state["frame"], "controls": state["controls"],
            "frames": FRAMES, "controls_presets": {k: v[0] for k, v in CONTROLS.items()}}


def main(argv):
    cmd, args = (argv[0], argv[1:]) if argv else ("status", [])
    if cmd == "status":
        s = status()
        if "--json" in args:
            print(json.dumps(s))
        else:
            print(f"frame={s['frame']}  controls={s['controls']}")
    elif cmd == "frame" and len(args) == 1:
        print(set_frame(args[0]))
    elif cmd == "controls" and len(args) == 1:
        print(set_controls(args[0]))
    elif cmd == "next" and args and args[0] in ("frame", "controls"):
        names = list(FRAMES if args[0] == "frame" else CONTROLS)
        now = read_state()[args[0]]
        nxt = names[(names.index(now) + 1) % len(names)] if now in names else names[0]
        print((set_frame if args[0] == "frame" else set_controls)(nxt))
    else:
        print(__doc__.strip(), file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main(sys.argv[1:])
