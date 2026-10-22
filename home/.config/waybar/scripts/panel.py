#!/usr/bin/env python3
"""Lifetime of the bar's popup panels: media, calendar, shortcuts, audio, network, cpu, gpu, disk, weather, power, language, capture, display, repos, notifications, updates.

    panel.py toggle <flyout|calendar|keybinds|audio|network|cpu|gpu|disk|weather|power|language|capture|display|repos|notifications|updates|logs>    show it, or hide it if it is already up
    panel.py close  <flyout|calendar|keybinds|audio|network|cpu|gpu|disk|weather|power|language|capture|display|repos|notifications|updates|logs>    hide it unconditionally
    panel.py close-all                   used when the bar itself goes away
    panel.py toggle power                the session menu: lock, suspend, log out, reboot, power off
    panel.py toggle <name> --at X,Y      open centred on X,Y instead of the pointer
    panel.py toggle <name> --at bar-right  ... under the far right of the bar (keyboard binds)

A panel is a short-lived process holding one gtk-layer-shell window, started
and killed from the bar pill that owns it. That is deliberate: a window that
does not exist cannot leak, cannot eat a click meant for the desktop, and needs
no code to hide itself.

Kept free of any gi import on purpose — player.py runs this for every click and
pulling in GTK to send a signal would be absurd. The windows themselves live in
panelui.py.
"""

import json
import os
import signal
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
RUNTIME = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "waybar-panels")

PANELS = {
    "flyout": "flyout.py",
    "calendar": "calendar_panel.py",
    "keybinds": "keybinds_panel.py",
    "audio": "audio_panel.py",
    "network": "network_panel.py",
    "cpu": "cpu_panel.py",
    "gpu": "gpu_panel.py",
    "disk": "disk_panel.py",
    "weather": "weather_panel.py",
    "power": "power_panel.py",
    "language": "language_panel.py",
    "capture": "capture_panel.py",
    "display": "display_panel.py",
    "repos": "repos_panel.py",
    "notifications": "notifications_panel.py",
    "updates": "updates_panel.py",
    "logs": "logs_panel.py",
}


def script_for(name):
    return os.path.join(HERE, PANELS[name])


def pid_file(name):
    return os.path.join(RUNTIME, f"{name}.pid")


def running(name):
    """0 unless the pid file still names this panel. The cmdline check matters:
    pids get recycled, and this number is only ever used as a kill target."""
    try:
        with open(pid_file(name)) as handle:
            pid = int(handle.read().strip())
        with open(f"/proc/{pid}/cmdline", "rb") as handle:
            if PANELS[name].encode() not in handle.read():
                return 0
    except (OSError, ValueError, KeyError):
        return 0
    return pid


def close(name):
    pid = running(name)
    if pid:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
    try:
        os.remove(pid_file(name))
    except OSError:
        pass


def cursor_pos():
    """A Wayland client cannot ask where the pointer is, and by the time the
    panel has started the pointer may have moved — so it is read here, inside
    the click that opens it. The panel centres itself on this x."""
    try:
        out = subprocess.run(["hyprctl", "cursorpos"], capture_output=True,
                             text=True, timeout=1).stdout
        x, y = (int(part.strip()) for part in out.split(",")[:2])
        return f"{x},{y}"
    except (subprocess.SubprocessError, OSError, ValueError):
        return ""


def bar_right():
    """The far right end of the bar, for panels opened from a keyboard bind.
    With a pill click the pointer IS on the pill; with a key it can be on any
    monitor, and the panel would open on one that has no bar at all. The bar's
    layer is looked up rather than hard-coded, so a layout change follows."""
    try:
        out = subprocess.run(["hyprctl", "layers", "-j"], capture_output=True,
                             text=True, timeout=1).stdout
        for mon in json.loads(out).values():
            for layers in mon.get("levels", {}).values():
                for layer in layers:
                    if layer.get("namespace") == "waybar-main":
                        # 20 px in from the edge: inside the last pill. The
                        # panel clamps itself to the monitor anyway.
                        return (f"{layer['x'] + layer['w'] - 20},"
                                f"{layer['y'] + layer['h'] // 2}")
    except (subprocess.SubprocessError, OSError, ValueError, KeyError, TypeError):
        pass
    return cursor_pos()      # no bar running: the pointer is the best guess


def open_panel(name, at=""):
    os.makedirs(RUNTIME, exist_ok=True)
    # The toolbox section (scripts/toolbox.sh) drops down in the same strip
    # under the bar; fold it away too, for the same one-at-a-time reason.
    subprocess.run([os.path.join(HERE, "toolbox.sh"), "hide"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if at == "bar-right":
        at = bar_right()
    proc = subprocess.Popen(
        [sys.executable, script_for(name), at or cursor_pos()],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True)   # outlives this script and the click that ran it
    with open(pid_file(name), "w") as handle:
        handle.write(str(proc.pid))


def toggle(name, at=""):
    if running(name):
        close(name)
        return
    # Only one panel at a time: two glass cards fighting for the same strip of
    # screen under the bar looks like a bug, not a feature.
    for other in PANELS:
        if other != name:
            close(other)
    open_panel(name, at)


def main():
    action = sys.argv[1] if len(sys.argv) > 1 else ""
    name = sys.argv[2] if len(sys.argv) > 2 else ""
    at = sys.argv[4] if len(sys.argv) > 4 and sys.argv[3] == "--at" else ""
    if action == "close-all":
        for panel in PANELS:
            close(panel)
    elif name not in PANELS:
        print(__doc__.strip(), file=sys.stderr)
        sys.exit(2)
    elif action == "toggle":
        toggle(name, at)
    elif action == "close":
        close(name)
    else:
        print(__doc__.strip(), file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
