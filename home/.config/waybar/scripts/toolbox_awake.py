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

After a click the row is redrawn at once (SIGRTMIN+21 to the toolbox
waybar, the module's "signal"); toolbox.sh sends the same signal when the
card opens, so a change made on the Settings page meanwhile is shown the
moment you look. The 60 s interval only catches a timed Keep awake running
out while the card is open.
"""
import json
import os
import subprocess
import sys
import time

IDLE = os.path.expanduser("~/.config/hypr/scripts/idle-settings.py")
SIGNAL = 21             # "signal" of custom/awake in ../config-toolbox

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
    idle_inhibitor row had, so the stylesheet's .activated rule carries over."""
    if state is None:
        return {"text": "Keep awake  ?", "alt": "deactivated", "class": "error",
                "tooltip": "idle-settings.py did not answer"}
    if not state.get("on"):
        return {"text": "Keep awake", "alt": "deactivated", "class": "deactivated",
                "tooltip": "Click: keep the screens on until you turn it off. Right-click: for an hour."}
    until = state.get("until")
    text = f"Keep awake  {time.strftime('%H:%M', time.localtime(until))}" if until else "Keep awake"
    return {"text": text, "alt": "activated", "class": "activated",
            "tooltip": "Nothing dims, locks, turns off or sleeps on idle. Click to turn it off."}


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
    subprocess.run(["systemctl", "--user", "kill", "-s", f"RTMIN+{SIGNAL}", "--kill-whom=main",
                    "waybar-toolbox.service"], capture_output=True, timeout=5)


if __name__ == "__main__":
    main()
