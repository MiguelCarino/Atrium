#!/usr/bin/env bash
# Show / hide the toolbox section: the second waybar (config-toolbox,
# waybar-toolbox.service) holding game mode, night light, keep awake, shortcuts and
# the tray, which drops down under the sliders pill on the main bar.
#
#   toolbox.sh toggle    the sliders pill's on-click
#   toolbox.sh hide      fold it away if it is open (panel.py, the shortcuts row)
#   toolbox.sh status    JSON for the sliders pill: class "open" lights it
#
# waybar only has a toggle (SIGUSR1), no show or hide, and a hidden waybar
# keeps its layer surface listed in `hyprctl layers`, so whether it is open is
# not something that can be asked. It is tracked in a flag file instead; the
# unit deletes the flag whenever it (re)starts, because waybar starts hidden.

set -u
FLAG=${XDG_RUNTIME_DIR:-/tmp}/waybar-toolbox.open
HANDLE_SIGNAL=12    # "signal" of custom/toolbox in ./config
AWAKE_SIGNAL=21     # "signal" of custom/awake in ./config-toolbox

DISMISS_PID=${XDG_RUNTIME_DIR:-/tmp}/waybar-toolbox-dismiss.pid

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

flip() {
    # Opening: close any popup panel first (CPU, network, calendar...), the
    # mirror of panel.py folding this section away when a panel opens -- one
    # card under the bar at a time. close-all is a pid-file check per panel,
    # no GTK, so it costs nothing when none is open.
    [[ ! -e $FLAG ]] && python3 "$(dirname "$0")/panel.py" close-all
    # Then fit the box to the card (toolbox_fit.py), restarting the hidden
    # toolbox if the tray count moved; it starts hidden. A restart, not
    # SIGUSR2: waybar 0.15 can crash on an in-place reload (bar-restart.sh
    # says why). The toggle below must wait until the new waybar handles
    # SIGUSR1 -- sent earlier, the default action of USR1 would kill it.
    if [[ ! -e $FLAG ]] && python3 "$(dirname "$0")/toolbox_fit.py"; then
        systemctl --user restart waybar-toolbox.service 9>&-
        wait_for_usr1 || return
        sleep 0.3       # the handler is in; give the layer surface a moment
    fi
    systemctl --user kill -s USR1 --kill-whom=main waybar-toolbox.service || return
    if [[ -e $FLAG ]]; then
        rm -f "$FLAG"; dismiss_stop
    else
        : > "$FLAG"; dismiss_start
        # The Keep awake row asks idle-settings.py again (toolbox_awake.py),
        # so a change made on the Settings page while the card was folded
        # away is right the moment it opens.
        systemctl --user kill -s "RTMIN+$AWAKE_SIGNAL" --kill-whom=main waybar-toolbox.service
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
    hide)   [[ -e $FLAG ]] && flip ;;
    status)
        if [[ -e $FLAG ]]; then
            printf '{"text": "", "class": "open", "tooltip": "Hide game mode, night light, keep awake, shortcuts, tray"}\n'
        else
            printf '{"text": "", "class": "closed", "tooltip": "Game mode, night light, keep awake, shortcuts, tray  (click)"}\n'
        fi ;;
    *) echo "usage: toolbox.sh toggle|hide|status" >&2; exit 2 ;;
esac
exit 0
