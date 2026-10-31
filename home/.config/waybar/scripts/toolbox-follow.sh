#!/usr/bin/env bash
# waybar.service's ExecStartPost (~/.config/systemd/user/waybar.service.d/
# hyprland.conf): the top bar is up, so a toolbox still holding the bar's
# pills (generated/config-toolbox-nobar: the top bar was off, hypr/scripts/
# dock.py TOP BAR OFF) starts again from its own config, or each pill would
# show twice. That is the bar coming back without bar-restart.sh -- the dock
# stopped (its ExecStopPost), or a `systemctl start` by hand. In a restart of
# both (bar-restart.sh) the toolbox is down here, and this does nothing.
pid=$(systemctl --user show -p MainPID --value waybar-toolbox.service 2>/dev/null)
[[ -n $pid && $pid != 0 ]] || exit 0
grep -qs config-toolbox-nobar "/proc/$pid/cmdline" || exit 0
exec systemctl --user --no-block try-restart waybar-toolbox.service
