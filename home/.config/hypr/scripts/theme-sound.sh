#!/usr/bin/env bash
# The desktop theme's sounds (~/.config/themes/<theme>/sounds/, rendered by
# make-theme-sounds.py).
#
#   theme-sound.sh notify | switch   play the current theme's sound for it
#   theme-sound.sh on | off          theme sounds on / off (sounds= in display.conf)
#   theme-sound.sh status            on or off
#   theme-sound.sh volume [0-100]    print / set their level (sound_volume=, default 35)
#
# mako runs `notify` for every notification it shows (on-notify in
# mako/config; mako/sections turns it off for low urgency and Do Not
# Disturb), theme.py runs `switch` after a theme change. Silent when off,
# when Do Not Disturb is on, and for a theme with no such file.

STATE="${XDG_STATE_HOME:-$HOME/.local/state}/hypr/display.conf"
THEMES="$HOME/.config/themes"
DEFAULT_VOLUME=35   # % of the file's level; the files peak at -13 dBFS, loud next to speech

get() { sed -n "s/^$1=//p" "$STATE" 2>/dev/null | tail -n1; }

set_key() {  # same format display.py writes: key=value, sorted, atomic
    local tmp="$STATE.tmp.$$"
    mkdir -p "$(dirname "$STATE")"
    { grep -v "^$1=" "$STATE" 2>/dev/null; echo "$1=$2"; } | sort > "$tmp" && mv "$tmp" "$STATE"
}

level() {  # sound_volume= as 0-100, the default when unset or malformed
    local v; v=$(get sound_volume)
    [[ $v =~ ^[0-9]{1,3}$ ]] && (( 10#$v <= 100 )) && echo $((10#$v)) || echo "$DEFAULT_VOLUME"
}

case ${1:-} in
    on|off)  set_key sounds "$1" ;;
    status)  [[ $(get sounds) == off ]] && echo off || echo on ;;
    volume)
        if [[ -z ${2:-} ]]; then level
        elif [[ $2 =~ ^[0-9]{1,3}$ ]] && (( 10#$2 <= 100 )); then set_key sound_volume $((10#$2))
        else echo "theme-sound.sh: volume is 0-100" >&2; exit 2
        fi ;;
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
        [[ -r $file ]] || exit 0
        vol=$(level)
        # The ambient desktop (ambient.py, Settings > Ambient) may turn the
        # notification sound down further in a focus block or at night:
        # volume=0-100 in its runtime file (none = no change; 0 = silent).
        amb=$(sed -n 's/^volume=\([0-9]\{1,3\}\)$/\1/p' "${XDG_RUNTIME_DIR:-/tmp}/ambient-sound.conf" 2>/dev/null)
        if [[ $1 == notify && -n $amb ]] && (( amb < 100 )); then
            vol=$(( vol * amb / 100 ))
        fi
        (( vol == 0 )) && exit 0
        (( vol >= 100 )) && exec pw-play "$file"
        exec pw-play --volume "$(printf '0.%02d' "$vol")" "$file" ;;
    *) sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//'; exit 2 ;;
esac
