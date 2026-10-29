#!/usr/bin/env python3
"""Pick any window on any workspace from a wofi list and focus it.

Bound to SUPER+W in lua/binds.lua. By default it lists every window, most
recently focused first, so the top entry is the one you were just in --
Enter on it is "go back".

Which windows, in what order and how many rows show are Settings > Windows >
Window switcher's (switcher_conf.py, $XDG_STATE_HOME/hypr/switcher.conf),
read each time it opens: scope all / workspace / monitor (the focused
workspace's or screen's windows only, from `hyprctl activeworkspace -j`),
order recent / workspace, special on / off (scratchpad windows), lines.

Focusing goes through the Lua dispatcher (hl.dsp.focus with an address
selector) because this machine configures Hyprland in Lua: the classic
`hyprctl dispatch focuswindow` form is a syntax error here.
"""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import switcher_conf  # noqa: E402  (no GTK: the options and arrange())


def hyprctl_json(*what):
    """`hyprctl <what> -j` parsed; None when it fails."""
    try:
        r = subprocess.run(["hyprctl", *what, "-j"], capture_output=True, text=True, timeout=5)
        return json.loads(r.stdout)
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def focused(active):
    """(workspace id, monitor id) from `hyprctl activeworkspace -j`; None
    for what it does not say (the scope then lists every window)."""
    active = active if isinstance(active, dict) else {}
    ws, mon = active.get("id"), active.get("monitorID")
    return (ws if isinstance(ws, int) else None, mon if isinstance(mon, int) else None)


def label(c):
    ws = c["workspace"]["name"].removeprefix("special:")
    app = c["class"].rsplit(".", 1)[-1] or "?"
    return f"{ws:>6}  {app:<16}  {c['title'][:90]}"


def windows(clients, active, conf):
    """The windows to list, in order, for these options."""
    workspace_id, monitor_id = focused(active)
    if conf["scope"] == "all":
        workspace_id = monitor_id = None
    return switcher_conf.arrange(clients or [], conf, workspace_id=workspace_id, monitor_id=monitor_id)


def wofi_argv(count, rows):
    return ["wofi", "--dmenu", "--insensitive", "--prompt", "window",
            "--width", "900", "--lines", str(min(count, rows) + 1)]


def picked(pick, clients):
    """The address of the picked row; None for no pick. wofi --dmenu returns
    typed text as-is when it matches no entry; that is not a pick, so it is
    ignored rather than crashing on int()."""
    try:
        return clients[int(pick.split(" ", 1)[0])]["address"]
    except (ValueError, IndexError, KeyError):
        return None


def main():
    conf = switcher_conf.read_conf()
    active = hyprctl_json("activeworkspace") if conf["scope"] != "all" else None
    clients = windows(hyprctl_json("clients"), active, conf)
    if not clients:
        return
    lines = [f"{i:02d} {label(c)}" for i, c in enumerate(clients)]
    pick = subprocess.run(wofi_argv(len(lines), switcher_conf.lines(conf)),
                          input="\n".join(lines), capture_output=True, text=True).stdout.strip()
    addr = picked(pick, clients) if pick else None
    if addr:
        subprocess.run(["hyprctl", "dispatch", f"hl.dsp.focus({{ window = 'address:{addr}' }})"],
                       capture_output=True)


if __name__ == "__main__":
    main()
