#!/usr/bin/env bash
# The toolbox's start (ExecStart in ~/.config/systemd/user/waybar-toolbox.
# service): waybar on the config bar-settings.py toolbox-config-path names --
# ~/.config/waybar/config-toolbox, or with the top bar off generated/
# config-toolbox-nobar, the same card with the bar's pills nothing else shows
# on top. toolbox-config-path falls back to the file itself on any problem,
# and so does this if it cannot run at all.
config=$(/usr/bin/python3 "$HOME/.config/hypr/scripts/bar-settings.py" toolbox-config-path 2>/dev/null)
[[ -f $config ]] || config=$HOME/.config/waybar/config-toolbox
# style-toolbox.css imports this one (bar-settings.py card_css writes it): a
# missing import is a CSS error, so it is there even when the above was not.
lines=$HOME/.config/waybar/generated/toolbox-lines.css
[[ -f $lines ]] || { mkdir -p "${lines%/*}" && : > "$lines"; }
exec /usr/bin/waybar -c "$config" -s "$HOME/.config/waybar/style-toolbox.css"
