#!/usr/bin/env bash
# Show / hide the toolbox section: the second waybar (config-toolbox,
# waybar-toolbox.service) holding game mode, night light, keep awake, shortcuts and
# the tray, which drops down under the sliders pill on the main bar -- or,
# while the dock or the taskbar runs, comes up next to their toolbox button.
#
#   toolbox.sh toggle    the sliders pill's on-click, and the dock's button
#   toolbox.sh hide      fold it away if it is open (panel.py, the shortcuts row)
#   toolbox.sh status    JSON for the sliders pill: class "open" lights it;
#                        empty (waybar hides the pill) while the dock runs
#   toolbox.sh refit     fold it away and place it again for where its button
#                        is now, restarting the hidden toolbox if that moved
#                        it (dock.py: switched on or off, a new layout, edge
#                        or autohide -- never on a click)
#
# THE PILL AND THE DOCK. hypr/scripts/dock.py has a toolbox button of its own
# (the taskbar's beside the tray, the dock's after a line at its end), so
# while it runs the top bar's sliders pill is one button too many and goes:
# `status` prints an empty text. "While it runs" is DOCK_BUTTON below, the
# file dock.py writes with where that button is (toolbox_fit.py places the
# card from it) and removes when it stops: there, and its pid alive (a crash
# leaves the file behind). Not dock.json's "enabled": a dock switched on that
# failed to start would leave no button anywhere. dock.py pokes the pill
# (signal 12) when the button comes and goes, and `dock.py set on|off` does.
# Builtins only -- status runs on every redraw of the pill.
#
# waybar only has a toggle (SIGUSR1), no show or hide. Whether the card is
# open is asked of Hyprland each time (shown, below): waybar hides a bar by
# moving its layer surface to the bottom layer, so the toolbox is open while
# its surface is on top or overlay. A flag file remembering it used to be the
# only record, and the restart that refits the card (it starts hidden, and the
# unit deletes the flag) wiped it while the card was showing -- from then on
# every click did the opposite and the card stayed open. The flag is still
# written, after the fact, only for `status`, which runs on every redraw of
# the pill and should not call hyprctl.

set -u
FLAG=${XDG_RUNTIME_DIR:-/tmp}/waybar-toolbox.open
# The signal numbers are in ~/.config/hypr/scripts/bar_signals.py (the
# one table); `signals` reads them, only on a flip -- status runs on every
# redraw of the pill and needs none -- and in one call (a python start is
# ~20 ms, and this is the click's own latency). The fallbacks are today's.
BAR_SIGNALS=$HOME/.config/hypr/scripts/bar_signals.py
signals() {
    HANDLE_SIGNAL=12 AWAKE_SIGNAL=21 NIGHT_SIGNAL=11
    local nums
    nums=$("$BAR_SIGNALS" number toolbox awake nightlight 2>/dev/null) &&
        read -r -d '' HANDLE_SIGNAL AWAKE_SIGNAL NIGHT_SIGNAL <<< "$nums"
}

DISMISS_PID=${XDG_RUNTIME_DIR:-/tmp}/waybar-toolbox-dismiss.pid
DOCK_BUTTON=${XDG_RUNTIME_DIR:-/run/user/$UID}/dock-toolbox.json

# True while dock.py runs and has its toolbox button (see the top).
docked() {
    local text=''
    [[ -r $DOCK_BUTTON ]] || return 1
    read -r -d '' text < "$DOCK_BUTTON"
    [[ $text =~ \"pid\":\ *([0-9]+) ]] || return 1
    [[ -e /proc/${BASH_REMATCH[1]} ]]
}

# The click-outside catcher (toolbox_dismiss.py) lives exactly as long as the
# section is open. The cmdline check is because pids get recycled.
dismiss_stop() {
    local pid
    pid=$(cat "$DISMISS_PID" 2>/dev/null) || return 0
    grep -qs toolbox_dismiss.py "/proc/$pid/cmdline" && kill "$pid" 2>/dev/null
    rm -f "$DISMISS_PID"
}

dismiss_start() {
    dismiss_stop
    setsid python3 "$(dirname "$0")/toolbox_dismiss.py" >/dev/null 2>&1 9>&- &
    echo $! > "$DISMISS_PID"
}

# True once waybar-toolbox's main process catches SIGUSR1 (bit 10 of SigCgt
# in /proc/<pid>/status), within about 5 s.
wait_for_usr1() {
    local pid mask i
    for ((i = 0; i < 50; i++)); do
        pid=$(systemctl --user show -p MainPID --value waybar-toolbox.service 2>/dev/null)
        if [[ -n $pid && $pid != 0 ]]; then
            mask=$(sed -n 's/^SigCgt:[[:space:]]*//p' "/proc/$pid/status" 2>/dev/null)
            [[ -n $mask ]] && (( (16#$mask >> 9) & 1 )) && return 0
        fi
        sleep 0.1
    done
    return 1
}

# True while the card is showing (see the top of this file).
shown() {
    hyprctl layers -j 2>/dev/null | jq -e '[.[].levels | to_entries[]
        | select(.key == "2" or .key == "3") | .value[]
        | select(.namespace == "waybar-toolbox")] | length > 0' >/dev/null
}

flip() {
    signals
    local was=0
    shown && was=1
    # Opening: close any popup panel first (CPU, network, calendar...), the
    # mirror of panel.py folding this section away when a panel opens -- one
    # card under the bar at a time. close-all is a pid-file check per panel,
    # no GTK, so it costs nothing when none is open.
    (( was )) || python3 "$(dirname "$0")/panel.py" close-all
    # Then fit the box to the card (toolbox_fit.py), restarting the hidden
    # toolbox if the tray count moved; it starts hidden. A restart, not
    # SIGUSR2: waybar 0.15 can crash on an in-place reload (bar-restart.sh
    # says why). The toggle below must wait until the new waybar handles
    # SIGUSR1 -- sent earlier, the default action of USR1 would kill it.
    if (( ! was )) && python3 "$(dirname "$0")/toolbox_fit.py"; then
        systemctl --user restart waybar-toolbox.service 9>&-
        wait_for_usr1 || return
        sleep 0.3       # the handler is in; give the layer surface a moment
    fi
    systemctl --user kill -s USR1 --kill-whom=main waybar-toolbox.service || return
    if (( was )); then
        rm -f "$FLAG"; dismiss_stop
    else
        # The card's real width, now that it is drawn (toolbox_fit.py says
        # why it is measured): when it differs from what the fit assumed --
        # a theme opened for the first time -- refit and show it again.
        sleep 0.15
        if python3 "$(dirname "$0")/toolbox_fit.py" measure; then
            systemctl --user restart waybar-toolbox.service 9>&-
            wait_for_usr1 && sleep 0.3 \
                && systemctl --user kill -s USR1 --kill-whom=main waybar-toolbox.service
        fi
        # The Keep awake and Night light rows ask again (toolbox_awake.py,
        # nightlight.sh status), so a change made elsewhere while the card
        # was folded away is right the moment it opens. Neither row polls.
        systemctl --user kill -s "RTMIN+$AWAKE_SIGNAL" --kill-whom=main waybar-toolbox.service
        systemctl --user kill -s "RTMIN+$NIGHT_SIGNAL" --kill-whom=main waybar-toolbox.service
        # Last, after any refit restart (whose ExecStartPre deletes the flag).
        : > "$FLAG"; dismiss_start
    fi
    # Re-run the handle's exec so its lit state follows. Only the main bar
    # has the handle; --kill-whom=main keeps the signal off module scripts.
    systemctl --user kill -s "RTMIN+$HANDLE_SIGNAL" --kill-whom=main waybar.service
}

# The flag is only right if no two flips interleave: two at once both read the
# same state and send two toggles, leaving the flag inverted for good. status
# only reads, and runs from inside the RTMIN signal flip sends, so it skips this.
if [[ ${1:-} != status ]]; then
    exec 9> "${XDG_RUNTIME_DIR:-/tmp}/waybar-toolbox.lock"
    flock 9
fi

case ${1:-} in
    toggle) flip ;;
    hide)
        # Cheap when nothing is open (panel.py and voice.py call this before
        # every panel): only the flag or a catcher left behind leads to a look.
        if [[ -e $FLAG || -e $DISMISS_PID ]]; then
            if shown; then
                flip
            else        # already folded away: clear what says otherwise
                rm -f "$FLAG"; dismiss_stop; signals
                systemctl --user kill -s "RTMIN+$HANDLE_SIGNAL" --kill-whom=main waybar.service
            fi
        fi ;;
    refit)
        signals
        shown && flip       # a restart starts it hidden: fold it first, the proper way
        if python3 "$(dirname "$0")/toolbox_fit.py"; then
            # try-restart: a toolbox not running yet reads the new include
            # when it starts anyway.
            systemctl --user try-restart waybar-toolbox.service 9>&-
        fi
        systemctl --user kill -s "RTMIN+$HANDLE_SIGNAL" --kill-whom=main waybar.service ;;
    status)
        # No tooltip: custom/toolbox has "tooltip": false (the card is what
        # the click opens).
        if docked; then
            printf '{"text": "", "class": "docked"}\n'
        elif [[ -e $FLAG ]]; then
            printf '{"text": "", "class": "open"}\n'
        else
            printf '{"text": "", "class": "closed"}\n'
        fi ;;
    *) echo "usage: toolbox.sh toggle|hide|status|refit" >&2; exit 2 ;;
esac
exit 0
