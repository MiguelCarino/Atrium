#!/usr/bin/env bash
# The top bar's start (ExecStart in ~/.config/systemd/user/waybar.service.d/
# hyprland.conf): waybar on the config bar-settings.py config-path names --
# ~/.config/waybar/config, or with the taskbar on generated/config-taskbar,
# the same bar without the pills the taskbar shows (hypr/scripts/dock.py,
# TOP BAR). config-path falls back to the file itself on any problem, and so
# does this if it cannot run at all.
config=$(/usr/bin/python3 "$HOME/.config/hypr/scripts/bar-settings.py" config-path 2>/dev/null)
[[ -f $config ]] || config=$HOME/.config/waybar/config
exec /usr/bin/waybar -c "$config"
