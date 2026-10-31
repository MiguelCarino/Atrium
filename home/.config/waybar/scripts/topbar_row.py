#!/usr/bin/env python3
"""The toolbox card's Top bar row (custom/keybinds#topbar in config-toolbox:
the name gives it the plain row's look in every theme, as the Microphone
row's does; config-toolbox says why): the top bar on or off, a click to
switch it (hypr/scripts/dock.py set top_bar, TOP BAR OFF there).

The top bar can only be off while the dock or the taskbar runs, so without
one the row prints no text and waybar hides it.

    topbar_row.py           one JSON line, then exit
    topbar_row.py toggle    switch the top bar (folds the card away first:
                            the toolbox restarts with the new layout)
"""
import json
import os
import subprocess
import sys

HYPR = os.path.expanduser("~/.config/hypr/scripts")
sys.path.insert(0, HYPR)
TOOLBOX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "toolbox.sh")
GLYPH = ""          # Font Awesome window-maximize, as on Settings > Dock & taskbar
# "bar" is part of Font Awesome icon names ("bars", "chart-bar"): a zero-width
# non-joiner between the letters keeps a ligature off the words (mic_row.py).
WORD = "‌".join("Top bar")


def settings():
    try:
        import dock
        return dock.read_settings()
    except Exception:         # noqa: BLE001 - no dock: no row
        return {}


def row(cfg):
    if not cfg.get("enabled"):
        return {"text": "", "tooltip": "", "class": "none"}
    on = cfg.get("top_bar", True)
    return {"text": f"{GLYPH}   {WORD} {'on' if on else 'off'}",
            "tooltip": f"The top bar is {'on' if on else 'off'}\nclick: turn it {'off' if on else 'on'}",
            "class": "on" if on else "off"}


def toggle():
    cfg = settings()
    if not cfg.get("enabled"):
        return 1
    subprocess.run([TOOLBOX, "hide"], stdin=subprocess.DEVNULL)
    want = "off" if cfg.get("top_bar", True) else "on"
    return subprocess.run([os.path.join(HYPR, "dock.py"), "set", "top_bar", want],
                          stdin=subprocess.DEVNULL).returncode


def main():
    if sys.argv[1:2] == ["toggle"]:
        return toggle()
    print(json.dumps(row(settings())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
