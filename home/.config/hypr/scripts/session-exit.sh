#!/bin/sh
# End the Hyprland session the right way for however it was started.
# Used by SUPER+SHIFT+M (lua/binds.lua) and Log out in the power menu
# (waybar/scripts/power_panel.py), so the two can never disagree.
#
#   uwsm-managed session ("Hyprland (uwsm-managed)" at the greeter):
#       `uwsm stop` -- stops the compositor unit AND takes down
#       graphical-session.target, so the portal, polkit agent and anything
#       else bound to the session stop cleanly instead of lingering into the
#       next login.
#   plain session ("Hyprland"): Hyprland's own exit, as before. Note the Lua
#       dispatch syntax; the classic `hyprctl dispatch exit` is a syntax
#       error with this config.
#
# `uwsm check is-active` exits 0 only inside a uwsm-managed session (checked:
# it returns 1 in the plain one), so this is safe in both.

# First the windows still open go to the automatic session slot, for
# "where was I" at the next login (sessions.py; closed-windows.service's
# ExecStop does it again under uwsm, which keeps the fuller of the two).
timeout 4 python3 "$(dirname "$0")/sessions.py" autosave --exit >/dev/null 2>&1

if command -v uwsm >/dev/null 2>&1 && uwsm check is-active >/dev/null 2>&1; then
    exec uwsm stop
fi
exec hyprctl dispatch 'hl.dsp.exit()'
