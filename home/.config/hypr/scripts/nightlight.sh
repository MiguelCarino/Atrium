#!/usr/bin/env bash
# Night light: warm the screens in the evening, on a schedule, with a manual
# override that lasts until the next scheduled boundary.
#
#   nightlight.sh on [temp]   force on (optional Kelvin, e.g. 3500) until the next boundary
#   nightlight.sh off         force off until the next boundary
#   nightlight.sh toggle      flip whatever is in effect now (SUPER+N)
#   nightlight.sh auto        apply the schedule (or a still-valid override);
#                             lua/nightlight.lua runs this every 5 min, at startup and
#                             after every config reload
#   nightlight.sh status      one line for humans; `status --json` for a waybar
#                             custom module ({text, tooltip, class, alt}) and
#                             Settings > Screens (mode, start, end, temp too)
#
# The lasting settings (Settings > Screens > Night light writes them with these):
#
#   nightlight.sh mode auto|on|off   auto = follow the schedule; on / off = all
#                             the time, until set back to auto
#   nightlight.sh start HH:MM        when the schedule turns it on
#   nightlight.sh end HH:MM          ... and off (crossing midnight is fine)
#   nightlight.sh temp <K>           how warm, 1000-6500
#   nightlight.sh config             JSON: {mode, start, end, temp}
#
# They live in ~/.local/state/hypr/nightlight.conf (mode=, start=, end=,
# temp=), read on every call; a missing file or key means the default in the
# configuration block below. scripts/theme-schedule.py reads start / end from
# the same file, so the theme's day and night move with them.
#
# Two backends, picked per call:
#
#   hyprsunset   the proper tool. Applies a colour-transform matrix (CTM)
#                through Hyprland's hyprland-ctm-control protocol, so it costs
#                no rendering at all and does not touch damage tracking or
#                direct scanout. NOT INSTALLED when this was written, so every
#                hyprsunset line below is from its documentation, not from a
#                run on this machine:
#                  hyprsunset -t 4000                     start at 4000K
#                  hyprctl hyprsunset temperature 4000    change it live (IPC,
#                                                         a socket hyprsunset
#                                                         opens in the Hyprland
#                                                         instance dir)
#                  hyprctl hyprsunset identity            back to neutral
#                What hyprctl prints on success/failure was not observable, so
#                hs_ipc() below treats "exit 0 and no error-ish word" as success
#                and otherwise falls back to restarting the daemon with -t,
#                which is the one form every hyprsunset version has.
#
#   screen_shader  works today with nothing installed. decoration.screen_shader
#                is a GLSL fragment shader Hyprland runs over each finished
#                frame; ours multiplies RGB by the white point of the target
#                temperature. Set/cleared at runtime with
#                  hyprctl eval 'hl.config({ decoration = { screen_shader = "<path>" } })'
#                and "" is what turns it off -- verified: after setting "",
#                `hyprctl getoption decoration:screen_shader` reads str "" and
#                the pixels are back to their exact original values.
#                Costs: while a screen shader is set every frame is fully
#                redrawn through an extra pass and direct scanout is off, so a
#                fullscreen game pays a little for it. Gamemode does not turn
#                night light off; SUPER+N does, until the next boundary.
#                Verified on this machine: a bar pixel on DP-1 went
#                (8,31,38) -> (8,25,25) and white on DP-2 went
#                (255,255,255) -> (255,206,166) at 4000K, i.e. exactly the
#                multipliers, and grim/screencopy captures include the effect.
#
# HDR (DP-1, cm = "hdr"): the shader runs on the composited image in the
# OUTPUT's encoding, one shader for all monitors -- it cannot tell DP-1 from
# the SDR screens. When DP-1 really is in HDR that image is PQ-encoded, and
# multiplying PQ code values is not the same as scaling light: blue/green drop
# by noticeably more than on the SDR screens, so DP-1 will look warmer and a
# little dimmer than DP-2/HDMI-A-1 at the same temperature. Untested in that
# state: when this was written `hyprctl monitors -j` reported
# colorManagementPreset "srgb" for DP-1 despite cm = "hdr", and the measured
# multiplication above was the plain sRGB one. If DP-1 looks too orange, raise
# TEMP for it by eye -- or install hyprsunset, whose CTM is the
# compositor-sanctioned path and the one Hyprland's CM is designed around.
#
# Why a manual action only lasts until the next boundary: "I want it off
# tonight" should not mean "off forever until I remember to turn it back on".
# Forcing it at 23:00 holds until 07:00; forcing it at noon holds until 20:00;
# after that the schedule owns the screen again. The override lives in
# $XDG_RUNTIME_DIR, so it also dies with the login session, never stale.

set -u

# ----------------------------- configuration -----------------------------
# The defaults: nightlight.conf (below) overrides each one it has a valid
# value for. scripts/theme-schedule.py reads these two lines as its own
# fallback, so keep them as START="HH:MM" / END="HH:MM".
START="20:00"      # night light comes on at this time ...
END="07:00"        # ... and goes off at this one (crossing midnight is fine)
TEMP=4000          # Kelvin. 6500 is neutral; 3400-4500 is the usual evening range
MODE="auto"        # auto (the schedule) | on | off (all the time)
BACKEND="auto"     # auto (screen-color, else hyprsunset if installed, else shader) | screen-color | hyprsunset | shader
# -------------------------------------------------------------------------

# The lasting settings. NL_CONF exists for the tests, like NL_STATE_DIR below.
DEFAULT_START=$START DEFAULT_END=$END
CONF="${NL_CONF:-${XDG_STATE_HOME:-$HOME/.local/state}/hypr/nightlight.conf}"

valid_hm() { [[ $1 =~ ^([01]?[0-9]|2[0-3]):[0-5][0-9]$ ]]; }
valid_temp() { [[ $1 =~ ^[0-9]+$ ]] && (( $1 >= 1000 && $1 <= 6500 )); }
two_digit() { local h=${1%:*}; printf '%02d:%s' "$((10#$h))" "${1#*:}"; }  # 7:00 -> 07:00

# A value that does not check out is skipped, so a hand-edited typo leaves the
# default in place rather than breaking the schedule.
if [[ -r $CONF ]]; then
    while IFS='=' read -r key value; do
        value=${value//[[:space:]]/}
        case $key in
            start) valid_hm "$value" && START=$(two_digit "$value") ;;
            end)   valid_hm "$value" && END=$(two_digit "$value") ;;
            temp)  valid_temp "$value" && TEMP=$value ;;
            mode)  [[ $value == @(auto|on|off) ]] && MODE=$value ;;
        esac
    done < "$CONF"
    # Equal times (only a hand edit can do that: `start` / `end` refuse it)
    # would make the window the whole day: back to the defaults' pair.
    [[ $START == "$END" ]] && { START=$DEFAULT_START; END=$DEFAULT_END; }
fi

save_conf() {  # writes all four, atomically (the 5-minute timer may be reading it)
    mkdir -p "$(dirname "$CONF")"
    printf 'mode=%s\nstart=%s\nend=%s\ntemp=%s\n' "$MODE" "$START" "$END" "$TEMP" > "$CONF.tmp" &&
        mv -f "$CONF.tmp" "$CONF"
}

# State lives in tmpfs and is per-session. NL_STATE_DIR / NL_NOW / NL_DRY exist
# only so the schedule logic can be tested without touching the real state,
# clock or screen (NL_DRY=1 records what would be applied and changes nothing).
STATE_DIR="${NL_STATE_DIR:-${XDG_RUNTIME_DIR:-/tmp}/nightlight}"
STATE="$STATE_DIR/override"    # "mode temp until_epoch"
LAST="$STATE_DIR/last"         # what was last applied, for change notifications
mkdir -p "$STATE_DIR"

now() { echo "${NL_NOW:-$(date +%s)}"; }

notify() {  # replaces its own previous toast instead of stacking
    [[ -n ${NL_DRY:-} ]] && { echo "DRY notify: $*" >&2; return; }
    notify-send -a "Night light" -h string:x-canonical-private-synchronous:nightlight \
        -t 2500 "$@" 2>/dev/null || true
}

# ------------------------------- schedule -------------------------------
hm_to_min() { local h=${1%:*} m=${1#*:}; echo $((10#$h * 60 + 10#$m)); }

in_window() {  # 0 (true) when the schedule says "on" at epoch $1
    local cur s e
    cur=$(date -d "@$1" +%H:%M); cur=$(hm_to_min "$cur")
    s=$(hm_to_min "$START"); e=$(hm_to_min "$END")
    if (( s < e )); then (( cur >= s && cur < e ))
    else (( cur >= s || cur < e )); fi    # window wraps midnight (the normal case)
}

next_boundary() {  # epoch of the next START or END strictly after epoch $1
    local t=$1 best="" c day hm
    for hm in "$START" "$END"; do
        for day in 0 1; do
            # date -d does the calendar maths, so DST days are handled.
            c=$(date -d "$(date -d "@$t" +%F) $hm $day day" +%s)
            if (( c > t )); then
                [[ -z $best || $c -lt $best ]] && best=$c
                break
            fi
        done
    done
    echo "$best"
}

# What the settings alone say at epoch $1, no override: "on|off <temp> why
# until". why is "schedule" (MODE=auto) or "always" (MODE=on / off); until is
# the next boundary either way, so an override made in "always" mode still
# ends at a sensible time rather than never.
# The ambient desktop (scripts/ambient.py, Settings > Ambient) may nudge the
# warmth of the SETTINGS' night light by a few hundred K -- warmer late at
# night, a little cooler in a focus block: one signed number in
# $STATE_DIR/ambient (tmpfs, gone with the session). An override (SUPER+N,
# `on K`) is yours and is never nudged; no file = exactly TEMP.
ambient_temp() {
    local d t
    d=$(cat "$STATE_DIR/ambient" 2>/dev/null)
    [[ $d =~ ^-?[0-9]{1,4}$ ]] || { echo "$TEMP"; return; }
    t=$(( TEMP + d )); (( t < 1000 )) && t=1000; (( t > 6500 )) && t=6500
    echo "$t"
}

base() {
    local b; b=$(next_boundary "$1")
    case $MODE in
        on)  echo "on $(ambient_temp) always $b" ;;
        off) echo "off $TEMP always $b" ;;
        *)   if in_window "$1"; then echo "on $(ambient_temp) schedule $b"
             else echo "off $TEMP schedule $b"; fi ;;
    esac
}

# Prints "on <temp>" or "off" plus why, honouring a live override and
# deleting an expired one.
desired() {
    local t mode otemp until
    t=$(now)
    if [[ -r $STATE ]] && read -r mode otemp until < "$STATE" && (( t < until )); then
        echo "$mode $otemp override $until"; return
    fi
    rm -f "$STATE"
    base "$t"
}

# ------------------------------- backends -------------------------------
# screen-color.py: the same colour matrix as hyprsunset, but one per screen,
# so the per-screen brightness / colour (display panel, launcher) and the
# night light multiply instead of fighting over the one CTM client slot.
SCREEN_COLOR="$(dirname "$(readlink -f "$0")")/screen-color.py"

pick_backend() {
    case $BACKEND in
        screen-color|hyprsunset|shader) echo "$BACKEND" ;;
        *) if [[ -x $SCREEN_COLOR ]]; then echo screen-color
           elif command -v hyprsunset >/dev/null; then echo hyprsunset; else echo shader; fi ;;
    esac
}

# Kelvin -> RGB multipliers (Tanner Helland's fit of the blackbody curve, the
# same family of approximation hyprsunset and most night-light tools use).
# Clamped to 1000..6600 so 6500 comes out as ~neutral rather than blue-tinted.
rgb_for() {
    awk -v k="$1" 'function cl(x){return x<0?0:(x>255?255:x)}
    BEGIN {
        if (k < 1000) k = 1000; if (k > 6600) k = 6600; t = k / 100
        r = (t <= 66) ? 255 : 329.698727446 * (t - 60) ^ -0.1332047592
        g = (t <= 66) ? 99.4708025861 * log(t) - 161.1195681661 \
                      : 288.1221695283 * (t - 60) ^ -0.0755148492
        b = (t >= 66) ? 255 : (t <= 19 ? 0 : 138.5177312231 * log(t - 10) - 305.0447927307)
        printf "%.4f, %.4f, %.4f", cl(r)/255, cl(g)/255, cl(b)/255
    }'
}

shader_current() {
    hyprctl getoption decoration:screen_shader -j 2>/dev/null |
        python3 -c 'import json,sys; print(json.load(sys.stdin).get("str",""))' 2>/dev/null
}

shader_set() {  # $1 = path or "" to disable
    hyprctl eval "hl.config({ decoration = { screen_shader = \"$1\" } })" >/dev/null
}

shader_on() {
    # One file per temperature: Hyprland only recompiles when the PATH changes,
    # so a new temperature needs a new name. Generated into tmpfs on demand,
    # which keeps the script the single source of truth for the shader.
    local f="$STATE_DIR/warm-$1.frag"
    if [[ ! -s $f ]]; then
        cat > "$f" <<EOF
#version 300 es
// Generated by ~/.config/hypr/scripts/nightlight.sh -- edits are overwritten.
// Night light at ${1}K: scale each channel by the blackbody white point.
// Applied to the already-encoded output image (see the HDR note in the script).
precision highp float;
in vec2 v_texcoord;
uniform sampler2D tex;
out vec4 fragColor;
void main() {
    vec4 c = texture(tex, v_texcoord);
    fragColor = vec4(c.rgb * vec3($(rgb_for "$1")), c.a);
}
EOF
    fi
    [[ $(shader_current) == "$f" ]] || shader_set "$f"
    # Drop the files for other temperatures so they do not pile up in tmpfs
    # for the whole session (only once the new one is live).
    [[ $(shader_current) == "$f" ]] &&
        find "$STATE_DIR" -maxdepth 1 -name 'warm-*.frag' ! -name "${f##*/}" -delete
    return 0
}

shader_off() {
    # Only clear a shader that is ours: if something else ever sets a screen
    # shader, night light being "off" should not wipe it.
    [[ $(shader_current) == "$STATE_DIR"/warm-*.frag ]] && shader_set ""
    return 0
}

hs_ipc() {  # hyprctl hyprsunset ... ; succeeds only if it looked like it worked
    local out
    out=$(hyprctl hyprsunset "$@" 2>&1) || return 1
    ! grep -qiE "error|couldn|fail|invalid|unknown|no such" <<<"$out"
}

hs_on() {
    if pgrep -x hyprsunset >/dev/null && hs_ipc temperature "$1"; then return; fi
    pkill -x hyprsunset; sleep 0.2
    # 9>&- : do not hand the flock fd to the daemon. It outlives this script,
    # so an inherited fd 9 kept the lock held for the whole session and every
    # later call (SUPER+N, the timer, the waybar button) timed out on it.
    setsid -f hyprsunset -t "$1" >/dev/null 2>&1 9>&-
}

hs_off() {
    pgrep -x hyprsunset >/dev/null || return 0
    hs_ipc identity || pkill -x hyprsunset
}

# One hint per session when running on the fallback, so the 5-minute timer
# does not nag but the first toggle still says how to get the better backend.
hint_install() {
    [[ $BACKEND == auto ]] || return 0
    command -v hyprsunset >/dev/null && return 0
    [[ -e $STATE_DIR/hinted ]] && return 0
    touch "$STATE_DIR/hinted"
    notify "hyprsunset is not installed: sudo dnf install hyprsunset" \
        "Using the screen-shader fallback for now (works, but costs a render pass)."
}

apply() {  # $1 = on|off, $2 = temp
    local be; be=$(pick_backend)
    if [[ -n ${NL_DRY:-} ]]; then echo "DRY apply $1 $2 via $be" >&2; echo "$1 $2" > "$LAST"; return; fi
    if [[ $be == screen-color ]]; then
        shader_off
        if [[ $1 == on ]]; then "$SCREEN_COLOR" night "$2" 9>&-; else "$SCREEN_COLOR" night off 9>&-; fi
    elif [[ $be == hyprsunset ]]; then
        if ! command -v hyprsunset >/dev/null; then
            notify "hyprsunset is not installed: sudo dnf install hyprsunset" \
                "BACKEND=hyprsunset is set in nightlight.sh; nothing was changed."
            return 1
        fi
        # A shader left over from before hyprsunset was installed would stack
        # on top of the CTM and double the warmth.
        shader_off
        if [[ $1 == on ]]; then hs_on "$2"; else hs_off; fi
    else
        hint_install
        if [[ $1 == on ]]; then shader_on "$2"; else shader_off; fi
    fi
    # Refresh the waybar button (custom/nightlight, "signal": 11) only when
    # the state really changed, not on every 5-minute tick.
    [[ $(cat "$LAST" 2>/dev/null) == "$1 $2" ]] || pkill -RTMIN+11 -x waybar
    echo "$1 $2" > "$LAST"
}

# ------------------------------- commands -------------------------------
hhmm() { date -d "@$1" +%H:%M; }

set_override() {  # $1 = on|off, $2 = temp; drop it if it just matches the settings
    local t b bmode; t=$(now); b=$(next_boundary "$t")
    read -r bmode _ < <(base "$t")
    if [[ $1 == "$bmode" ]] && { [[ $1 == off ]] || [[ $2 == "$TEMP" ]]; }; then
        rm -f "$STATE"
    else
        echo "$1 $2 $b" > "$STATE"
    fi
    apply "$1" "$2"
    if [[ $1 == on ]]; then notify "Night light on" "${2}K until $(hhmm "$b")"
    else notify "Night light off" "until $(hhmm "$b")"; fi
}

cmd=${1:-status}

# Serialise: the 5-minute timer and a key press can land together, and both
# read-modify-write the same files.
# A key press that times out here must not vanish silently, so the
# interactive commands say so; auto (the timer) and status stay quiet.
exec 9>"$STATE_DIR/lock"
flock -w 5 9 || {
    [[ $cmd == auto || $cmd == status ]] ||
        notify "Night light busy" "another nightlight.sh is still running; try again"
    exit 1
}

# Apply what is wanted now, quietly: after a settings change the panel that
# made it is the feedback, not a toast.
reapply() {
    local mode temp
    read -r mode temp _ < <(desired)
    apply "$mode" "$temp"
}

config_json() {
    printf '{"mode":"%s","start":"%s","end":"%s","temp":%s}' "$MODE" "$START" "$END" "$TEMP"
}

case $cmd in
    on)
        temp=${2:-$TEMP}
        # 6500 is the ceiling: rgb_for clamps at 6600 (~neutral), so anything
        # higher would look identical yet claim e.g. "10000K" in the toast.
        valid_temp "$temp" || { echo "temperature must be 1000-6500 K" >&2; exit 2; }
        set_override on "$temp" ;;
    mode)
        [[ ${2:-} == @(auto|on|off) ]] || { echo "mode: auto, on or off" >&2; exit 2; }
        # A new lasting choice replaces any "until the next boundary" one.
        MODE=$2; save_conf; rm -f "$STATE"; reapply
        config_json; echo ;;
    start|end)
        valid_hm "${2:-}" || { echo "$cmd: HH:MM, e.g. 20:30" >&2; exit 2; }
        new=$(two_digit "$2")
        other=$([[ $cmd == start ]] && echo "$END" || echo "$START")
        # Equal times would make the window either empty or the whole day.
        [[ $new != "$other" ]] || { echo "start and end cannot be the same time" >&2; exit 2; }
        if [[ $cmd == start ]]; then START=$new; else END=$new; fi
        # The override ran until a boundary that may have just moved.
        save_conf; rm -f "$STATE"; reapply
        config_json; echo ;;
    temp)
        valid_temp "${2:-}" || { echo "temperature must be 1000-6500 K" >&2; exit 2; }
        TEMP=$2; save_conf
        # A night light forced on keeps going, at the new warmth.
        if [[ -r $STATE ]] && read -r omode _ ountil < "$STATE" && [[ $omode == on ]]; then
            echo "on $TEMP $ountil" > "$STATE"
        fi
        reapply
        config_json; echo ;;
    config)
        config_json; echo ;;
    off)
        set_override off "$TEMP" ;;
    toggle)
        read -r mode temp _ < <(desired)
        if [[ $mode == on ]]; then set_override off "$TEMP"; else set_override on "$temp"; fi ;;
    auto)
        read -r mode temp why until < <(desired)
        prev=$(cat "$LAST" 2>/dev/null)
        apply "$mode" "$temp" || exit 1
        # Toast only on a real schedule transition, not on every 5-minute tick
        # or the re-apply after a config reload.
        if [[ -n $prev && ${prev%% *} != "$mode" && $why == schedule ]]; then
            notify "Night light $mode" "scheduled, until $(hhmm "$until")"
        fi ;;
    status)
        read -r mode temp why until < <(desired)
        be=$(pick_backend)
        case $MODE in
            on)  plan="on all the time at ${TEMP}K" ;;
            off) plan="off all the time" ;;
            *)   plan="$START-$END at ${TEMP}K" ;;
        esac
        if [[ $why == always ]]; then held="$why"; else held="$why until $(hhmm "$until")"; fi
        if [[ ${2:-} == --json ]]; then
            tip="Night light $mode ($held)\\nBackend: $be\\nSchedule: $plan"
            # Never empty: waybar hides a custom module whose text is "", and
            # this one is a button that has to stay clickable while off.
            [[ $mode == on ]] && txt="${temp}K" || txt="off"
            # text / alt / class / tooltip are the waybar module's; the rest
            # is for Settings > Screens (state = what is on screen now).
            printf '{"text":"%s","alt":"%s","class":"%s","tooltip":"%s","state":"%s","now_temp":%s,"why":"%s","until":"%s","mode":"%s","start":"%s","end":"%s","temp":%s}\n' \
                "$txt" "$mode" "$mode" "$tip" "$mode" "$temp" "$why" "$(hhmm "$until")" \
                "$MODE" "$START" "$END" "$TEMP"
        else
            if [[ $mode == on ]]; then s="on ${temp}K"; else s="off"; fi
            echo "night light $s ($held), backend $be, schedule $plan"
        fi ;;
    *)
        echo "usage: ${0##*/} on [temp] | off | toggle | auto | status [--json]" >&2
        echo "       ${0##*/} mode auto|on|off | start HH:MM | end HH:MM | temp K | config" >&2
        exit 2 ;;
esac
