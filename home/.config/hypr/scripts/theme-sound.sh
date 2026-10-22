#!/usr/bin/env bash
# The desktop theme's sounds (~/.config/themes/<theme>/sounds/, rendered by
# make-theme-sounds.py).
#
#   theme-sound.sh notify | switch   play the current theme's sound for it
#   theme-sound.sh on | off          theme sounds on / off (sounds= in display.conf)
#   theme-sound.sh status            on or off
#
# mako runs `notify` for every notification it shows (on-notify in
# mako/config; mako/sections turns it off for low urgency and Do Not
# Disturb), theme.py runs `switch` after a theme change. Silent when off,
# when Do Not Disturb is on, and for a theme with no such file.

STATE="${XDG_STATE_HOME:-$HOME/.local/state}/hypr/display.conf"
THEMES="$HOME/.config/themes"

get() { sed -n "s/^$1=//p" "$STATE" 2>/dev/null | tail -n1; }

set_key() {  # same format display.py writes: key=value, sorted, atomic
    local tmp="$STATE.tmp.$$"
    mkdir -p "$(dirname "$STATE")"
    { grep -v "^$1=" "$STATE" 2>/dev/null; echo "$1=$2"; } | sort > "$tmp" && mv "$tmp" "$STATE"
}

case ${1:-} in
    on|off)  set_key sounds "$1" ;;
    status)  [[ $(get sounds) == off ]] && echo off || echo on ;;
    notify|switch)
        # Visual alerts (Settings > Accessibility): a screen flash for each
        # notification. accessibility.py alert does nothing unless they are on,
        # and it comes before the sounds check because turning visual alerts on
        # turns the sounds off. In the background so mako never waits on it.
        if [[ $1 == notify ]] && ! makoctl mode 2>/dev/null | grep -qx do-not-disturb; then
            "$HOME/.config/hypr/scripts/accessibility.py" alert >/dev/null 2>&1 &
        fi
        [[ $(get sounds) == off ]] && exit 0
        [[ $1 == notify ]] && makoctl mode 2>/dev/null | grep -qx do-not-disturb && exit 0
        file="$THEMES/$(get theme)/sounds/$1.wav"
        [[ -n $(get theme) ]] || file="$THEMES/cyberpunk/sounds/$1.wav"
        # The ambient desktop (ambient.py, Settings > Ambient) may turn the
        # notification sound down in a focus block or at night: volume=0-100
        # in its runtime file (none = full volume; 0 = silent).
        vol=$(sed -n 's/^volume=\([0-9]\{1,3\}\)$/\1/p' "${XDG_RUNTIME_DIR:-/tmp}/ambient-sound.conf" 2>/dev/null)
        if [[ $1 == notify && -n $vol ]] && (( vol < 100 )); then
            (( vol == 0 )) && exit 0
            [[ -r $file ]] && exec pw-play --volume "$(printf '0.%02d' "$vol")" "$file"
        fi
        [[ -r $file ]] && exec pw-play "$file" ;;
    *) sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//'; exit 2 ;;
esac
