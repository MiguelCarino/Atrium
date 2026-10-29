#!/usr/bin/env python3
"""The toolbox's Keep awake row (custom/awake in ../config-toolbox).

    toolbox_awake.py              JSON for the row: lit while Keep awake is on
    toolbox_awake.py toggle       on until turned off / off again
    toolbox_awake.py toggle 60    on for an hour (right-click) / off again

The row used to be waybar's own idle_inhibitor: a Wayland inhibitor held by
the toolbox waybar, which nothing outside waybar can see. Settings > Power
had a Keep awake of its own (~/.config/hypr/scripts/idle-settings.py awake,
a systemd idle lock), so there were two switches with one name that did not
know about each other -- the page could say "off" while the toolbox kept the
screens on. Now both are the same switch: this row runs `idle-settings.py
awake on|off` and shows `idle-settings.py awake status`, so whichever one
you flip, the other agrees.

After a click the row is redrawn at once (bar_signals.py "awake", the
module's "signal", to the toolbox waybar only); toolbox.sh sends the same
signal when the card opens, so a change made on the Settings page meanwhile
is shown the moment you look. No interval: the row used to re-run this
every 60 s while the card sat folded away, all day, to catch a timed Keep
awake running out. Now a timed one started here also books its own redraw
for the moment it ends (a transient systemd timer, redraw_at), and the card
opening covers one started from Settings.
"""
import json
import os
import subprocess
import sys
import time

IDLE = os.path.expanduser("~/.config/hypr/scripts/idle-settings.py")
HYPR = os.path.expanduser("~/.config/hypr/scripts")
REDRAW_UNIT = "toolbox-awake-redraw"

# Font Awesome 6 Solid: a mug while on, the moon while off (the same pair
# the idle_inhibitor row had).
ICON_ON = ""
ICON_OFF = ""


def awake_status():
    try:
        out = subprocess.run([IDLE, "awake", "status"], capture_output=True, text=True, timeout=10).stdout
        return json.loads(out)
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def row(state):
    """The module's JSON line for an `awake status` answer (None: no answer).
    alt picks the icon from format-icons; the classes are the ones the
    idle_inhibitor row had, so the stylesheet's .activated rule carries over.
    No tooltip: the row has "tooltip": false (its clicks are in the config)."""
    if state is None:
        return {"text": "Keep awake  ?", "alt": "deactivated", "class": "error",
                "tooltip": "idle-settings.py did not answer"}
    if not state.get("on"):
        return {"text": "Keep awake", "alt": "deactivated", "class": "deactivated"}
    until = state.get("until")
    text = f"Keep awake  {time.strftime('%H:%M', time.localtime(until))}" if until else "Keep awake"
    return {"text": text, "alt": "activated", "class": "activated"}


def main():
    args = sys.argv[1:]
    if not args:
        print(json.dumps(row(awake_status())), flush=True)
        return
    if args[0] != "toggle":
        sys.exit(__doc__)
    state = awake_status() or {}
    cmd = ["off"] if state.get("on") else ["on", *args[1:2]]
    subprocess.run([IDLE, "awake", *cmd], capture_output=True, timeout=20)
    redraw()
    if cmd[0] == "on" and len(cmd) > 1:
        redraw_at((awake_status() or {}).get("until"))


def redraw():
    """The row re-runs: its signal (bar_signals.py "awake") to the toolbox
    waybar's main process only, through systemd, like toolbox.sh does."""
    if HYPR not in sys.path:
        sys.path.insert(0, HYPR)
    try:
        import bar_signals
        number = bar_signals.signal_number("awake")
    except (ImportError, KeyError):
        number = 21
    subprocess.run(["systemctl", "--user", "kill", "-s", f"RTMIN+{number}", "--kill-whom=main",
                    "waybar-toolbox.service"], capture_output=True, timeout=5)


def redraw_delay(until, now):
    """Seconds from now to just after a timed Keep awake ends, or None
    (no end, or already past)."""
    if not until or until <= now:
        return None
    return int(until - now) + 2


def redraw_at(until):
    """Book one redraw of the row for when a timed Keep awake runs out
    (systemd-run --on-active: a transient timer, gone after it fires)."""
    delay = redraw_delay(until, time.time())
    if delay is None:
        return
    subprocess.run(["systemctl", "--user", "stop", f"{REDRAW_UNIT}.timer"], capture_output=True, timeout=5)
    subprocess.run(["systemd-run", "--user", "--quiet", "--collect", f"--unit={REDRAW_UNIT}",
                    f"--on-active={delay}", sys.executable, os.path.join(HYPR, "bar_signals.py"), "poke", "awake"],
                   capture_output=True, timeout=10)


if __name__ == "__main__":
    main()
