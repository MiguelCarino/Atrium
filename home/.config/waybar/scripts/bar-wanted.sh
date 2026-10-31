#!/usr/bin/env bash
# waybar.service's ExecCondition (~/.config/systemd/user/waybar.service.d/
# hyprland.conf): exit 1 skips the top bar -- not a failure, and no
# Restart= loop -- while bar-settings.py wanted says "off" (the dock's
# top_bar is off and dock.service is up: hypr/scripts/dock.py, TOP BAR OFF).
# Only that exact word skips it: a broken or missing bar-settings.py, a
# traceback, anything else, and the bar starts as always.
[[ $(/usr/bin/python3 "$HOME/.config/hypr/scripts/bar-settings.py" wanted 2>/dev/null) == off ]] && exit 1
exit 0
