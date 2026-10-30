#!/bin/bash
# CPU load / temperature / RAM for waybar.
# Usage comes from /proc/stat deltas (the old `top -bn1` reported the
# since-boot average, not current load). Zero forks on the hot path.
#
#     cpu_usage.sh          one line, then exit -- for manual runs
#     cpu_usage.sh watch    one line every 5s, forever -- for a module with
#                           no "interval", which waybar reads continuously
#
# Watch mode exists because respawning bash every few seconds costs more than
# the measurement it performs. It also lets the previous /proc/stat sample stay
# in a variable, so between ticks nothing is written to disk at all.

# Spacing for the pill text, written as escapes (both are invisible):
#   SEP  U+2002 en space between the fields -- half an em, about twice a
#        normal space, so "23%  60°  16.2G" reads as three numbers
#   FIG  U+2007 figure space -- exactly one digit wide in a tabular font, to
#        pad a one-digit value; an ASCII space is narrower than a digit in
#        Plex, so padding with it still let the pill shift by a few pixels
SEP=$'\u2002'
FIG=$'\u2007'
pad2() {   # pad2 <n> <var>: n as two digit-widths, into var (no fork)
    if (( $1 < 10 )); then printf -v "$2" '%s%d' "$FIG" "$1"; else printf -v "$2" '%d' "$1"; fi
}

# theme_color <key> <fallback> <var>: a colour from the desktop theme
# (theme.conf color.<key> -> ~/.config/waybar/generated/colors.conf, written by
# ~/.config/hypr/scripts/theme.py; themecolors.py documents it), into var.
# Builtins only -- no fork -- so it is cheap enough to call on every tick,
# which is what lets a theme switch reach this long-running script at once.
# A missing file or key leaves the fallback (cyberpunk's colour).
THEME_COLORS=$HOME/.config/waybar/generated/colors.conf
theme_color() {
    local k v
    printf -v "$3" '%s' "$2"
    [[ -r $THEME_COLORS ]] || return 0
    while IFS='=' read -r k v; do
        [[ $k == "$1" && $v =~ ^#[0-9a-fA-F]{6}$ ]] && printf -v "$3" '%s' "$v"
    done < "$THEME_COLORS"
}

# One-shot mode has nowhere else to keep the previous sample. A single file is
# enough now: only one bar is left, so there is no second poller to race with.
STATE=${XDG_RUNTIME_DIR:-/tmp}/waybar-cpu.state

prev_total=0 prev_busy=0
TEMP_INPUT=

# The CPU's maker (AuthenticAMD / GenuineIntel in /proc/cpuinfo), read once:
# it picks the pill's colour -- AMD red, Intel blue, in the theme's CPU shade
# (theme.py vendor_colors); another maker keeps the theme's CPU colour.
CPU_VENDOR=
while IFS=': ' read -r key value; do
    if [[ $key == vendor_id* ]]; then
        case $value in
            *AuthenticAMD*) CPU_VENDOR=amd ;;
            *GenuineIntel*) CPU_VENDOR=intel ;;
        esac
        break
    fi
done < /proc/cpuinfo

# On a narrow screen (barfit.py) the pill is two meters instead of numbers
# -- load and RAM, 25% a segment (vbars.sh) -- so the bar's right side leaves
# the centre capsules centred; a hot CPU still turns the pill critical (red),
# and the panel (left click) has the numbers. Asked once: a bar that moves to
# another screen starts this script again.
NARROW=
. "$(dirname "$0")/vbars.sh"

# History for the sensors panel (scripts/sensors_panel.py), watch mode only:
# the last HIST_MAX samples, one "epoch usage temp mem%" line each, rewritten
# in place every tick. It lives in XDG_RUNTIME_DIR (tmpfs), so this is a RAM
# write, and keeping it here means the graphs are already full the moment the
# panel opens instead of starting from nothing.
HIST_FILE=
HIST_MAX=60             # 60 x 5s = the last five minutes
POWER_FILE=/run/cpu-power/watts
hist=()

record() {
    [[ -n $HIST_FILE ]] || return
    hist+=("$*")
    ((${#hist[@]} > HIST_MAX)) && hist=("${hist[@]:1}")
    printf '%s\n' "${hist[@]}" > "$HIST_FILE"
}

# --- CPU usage: delta of /proc/stat against the previous sample ---------------
# Leaves the result in $usage and the raw counters in $prev_total/$prev_busy,
# ready to serve as the baseline for the next call.
sample_cpu() {
    local user nice system idle iowait irq softirq steal
    local idle_all busy total d_total d_busy
    read -r _ user nice system idle iowait irq softirq steal _ < /proc/stat
    idle_all=$((idle + iowait))
    busy=$((user + nice + system + irq + softirq + steal))
    total=$((idle_all + busy))

    d_total=$((total - prev_total))
    d_busy=$((busy - prev_busy))
    prev_total=$total prev_busy=$busy

    if ((d_total > 0)); then
        usage=$((100 * d_busy / d_total))
    else
        usage=0
    fi
    ((usage > 100)) && usage=100
}

# --- Temperature: resolve k10temp by name; hwmonN numbering is not stable ----
find_temp_input() {
    local hwmon name label value
    TEMP_INPUT=
    for hwmon in /sys/class/hwmon/hwmon*; do
        [[ -r $hwmon/name ]] || continue
        read -r name < "$hwmon/name"
        [[ $name == k10temp ]] || continue
        for label in "$hwmon"/temp*_label; do
            [[ -r $label ]] || continue
            read -r value < "$label"
            if [[ $value == Tctl ]]; then
                TEMP_INPUT=${label%_label}_input
                return
            fi
        done
    done
}

read_temp() {
    # Watch mode resolves the sensor once and then reuses the path. A module
    # reload would renumber hwmon underneath us, so a path that stopped being
    # readable means "look the sensor up again", not "no sensor".
    local milli
    [[ -r $TEMP_INPUT ]] || find_temp_input
    temp=0
    [[ -r $TEMP_INPUT ]] || return
    read -r milli < "$TEMP_INPUT"
    temp=$((milli / 1000))
}

# --- One JSON line for the current $usage ------------------------------------
emit() {
    local temp key value mem_total mem_avail mem_used mem_x10
    local mem_pct text class label_col

    read_temp

    # Memory: /proc/meminfo -> GiB for the pill, % for the panel's RAM graph.
    mem_total=0 mem_avail=0
    while read -r key value _; do
        case $key in
            MemTotal:)     mem_total=$value ;;
            MemAvailable:) mem_avail=$value; break ;;
        esac
    done < /proc/meminfo
    mem_used=$((mem_total - mem_avail))
    mem_x10=$((mem_used * 10 / 1048576))      # kB -> GiB, one decimal, no bc
    mem_pct=0
    ((mem_total > 0)) && mem_pct=$((100 * mem_used / mem_total))

    # printf -v rather than $(printf ...): a command substitution forks a
    # subshell, and this runs every few seconds for the life of the bar.
    # Fixed-width fields so the pill does not jitter as the numbers change.
    # Compact: load, temperature, RAM used (GiB). Graphs are in the panel.
    class=normal
    ((temp >= 80 || usage >= 90)) && class=critical

    pad2 "$usage" u; pad2 "$temp" t
    theme_color cpu '#ff2a6d' label_col
    [[ -n $CPU_VENDOR ]] && theme_color "cpu_$CPU_VENDOR" "$label_col" label_col
    # Critical fills the whole pill with the theme's alarm colour, and a label
    # in the theme's CPU colour can vanish on it (navy on red in win95): the
    # theme may name a second colour for that state, color.cpu_hot.
    [[ $class == critical ]] && theme_color cpu_hot "$label_col" label_col
    # No "CPU" word: the whole pill is in the theme's CPU colour (the GPU's
    # is another), which says which one it is in a third of the width.
    if [[ $NARROW == yes ]]; then
        vbars "$label_col" text "$usage" "$mem_pct"
    else
        printf -v text "<span color='%s'>%s%%%s%s°%s%d.%dG</span>" \
            "$label_col" "$u" "$SEP" "$t" "$SEP" "$((mem_x10 / 10))" "$((mem_x10 % 10))"
    fi

    # No tooltip: the bar has tooltips off for this pill (the sensors panel,
    # left click, shows the detail), and building one cost a ps fork a tick.

    # "meters": the pill drops the width a theme gives it for the numbers.
    local class_json="\"$class\""
    [[ $NARROW == yes ]] && class_json="[\"$class\",\"meters\"]"
    printf '{"text":"%s","class":%s,"percentage":%d}\n' \
        "$text" "$class_json" "$usage"

    # CPU package power, when something publishes it: the counter (RAPL) is
    # root-only, so a small root service would have to write a 5 s average
    # in watts to POWER_FILE. Without one the history simply has no fifth
    # column and the panel's POWER row says how to get it. A read, not a fork.
    local watts=""
    [[ -r $POWER_FILE ]] && read -r watts < "$POWER_FILE"
    record "$EPOCHSECONDS $usage $temp $mem_pct${watts:+ $watts}"
}

if [[ $1 == watch ]]; then
    NARROW=$("$(dirname "$0")/barfit.py" narrow 2>/dev/null)
    mkdir -p "${XDG_RUNTIME_DIR:-/tmp}/waybar-sensors"
    HIST_FILE=${XDG_RUNTIME_DIR:-/tmp}/waybar-sensors/cpu.hist
    # Pick up where the previous instance left off: a bar reload restarts this
    # script, and starting from an empty array would blank the graphs.
    [[ -r $HIST_FILE ]] && mapfile -t hist < "$HIST_FILE"
    # Trim to HIST_MAX: a file written at another sample rate (or HIST_MAX)
    # would otherwise keep its old length forever, one in one out.
    ((${#hist[@]} > HIST_MAX)) && hist=("${hist[@]: -HIST_MAX}")
    # Prime the delta before the first line: emitting straight away would
    # report the since-boot average, which is what this script exists to avoid.
    find_temp_input
    sample_cpu
    # First line after half a second rather than a full tick, so the pill
    # does not sit missing for 5 s after every bar (re)start.
    # Waiting without forking: /usr/bin/sleep is a new process per tick
    # (12 a minute, the most forks of any pill -- bar-audit.py). read -t on a
    # pipe nobody ever writes to is bash's own timer: it just times out.
    exec {tick}<> <(:)
    nap() { read -rt "$1" -u "$tick" _; }
    nap 0.5
    sample_cpu
    emit
    while :; do
        # 5 s, was 2 s: the pill is a glance. The usage is a delta, so it
        # still averages the whole gap.
        nap 5
        sample_cpu
        emit
    done
fi

# One-shot: the previous sample comes from the state file, and sample_cpu
# replaces prev_* with the fresh counters that the next run will read back.
[[ -r $STATE ]] && read -r prev_total prev_busy < "$STATE"
sample_cpu
printf '%s %s\n' "$prev_total" "$prev_busy" > "$STATE"
emit
