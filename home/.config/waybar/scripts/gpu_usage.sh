#!/bin/bash
# NVIDIA GPU stats for waybar.
# One nvidia-smi call instead of three, and no bc: nvidia-smi is the expensive
# part here (~25ms each), so collapsing the queries is most of the win.
#
#     gpu_usage.sh          one line, then exit -- for manual runs
#     gpu_usage.sh watch    one line every 5s, forever -- for a module with
#                           no "interval", which waybar reads continuously
#
# Watch mode keeps a single nvidia-smi resident with `-l 5` rather than starting
# one every five seconds: most of the cost of an nvidia-smi run is the driver
# handshake at startup, and a resident process pays that once per session.

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

QUERY=utilization.gpu,temperature.gpu,memory.used,memory.total,power.draw,fan.speed

# History for the sensors panel, watch mode only -- see cpu_usage.sh. One
# "epoch usage temp vram% power" line per sample, last five minutes.
HIST_FILE=
HIST_MAX=60             # 60 x 5s = the last five minutes
hist=()

record() {
    [[ -n $HIST_FILE ]] || return
    hist+=("$*")
    ((${#hist[@]} > HIST_MAX)) && hist=("${hist[@]:1}")
    printf '%s\n' "${hist[@]}" > "$HIST_FILE"
}

unavailable() {
    printf '{"text":"GPU N/A","class":"unavailable"}\n'
}

# --- One JSON line for the sample currently in $usage, $temp, ... ------------
emit() {
    local mem_pct text class vram_x10 label_col

    mem_pct=0
    ((mem_total > 0)) && mem_pct=$((100 * mem_used / mem_total))

    # printf -v rather than $(printf ...): a command substitution forks a
    # subshell, and this runs every few seconds for the life of the bar.
    # Same layout as the CPU pill: neon label, white fixed-width numbers.
    # Compact: load, temperature, VRAM used (GiB). Graphs are in the panel.
    vram_x10=$((mem_used * 10 / 1024))          # MiB -> GiB, one decimal
    class=normal
    (( ${temp%%.*} >= 80 )) && class=critical

    pad2 "$usage" u; pad2 "${temp%%.*}" t
    theme_color gpu '#39ff14' label_col
    # The filled critical pill may want another label colour (cpu_usage.sh).
    [[ $class == critical ]] && theme_color gpu_hot "$label_col" label_col
    printf -v text "<span color='%s'>GPU</span>%s%s%%%s%s°%s%d.%dG" \
        "$label_col" "$SEP" "$u" "$SEP" "$t" "$SEP" "$((vram_x10 / 10))" "$((vram_x10 % 10))"

    # No tooltip: tooltips are off for this pill and the sensors panel shows
    # the detail; the process list here used to cost a second nvidia-smi.

    printf '{"text":"%s","class":"%s","percentage":%d}\n' \
        "$text" "$class" "$usage"

    record "$EPOCHSECONDS $usage ${temp%%.*} $mem_pct ${power%%.*}"
}

# Fallback stream for machines without coreutils' stdbuf: one nvidia-smi per
# sample, which is no worse than what the one-shot mode already costs.
poll_stream() {
    local line
    while :; do
        line=$(nvidia-smi --query-gpu=$QUERY --format=csv,noheader,nounits 2>/dev/null)
        [[ -z $line ]] && return
        printf '%s\n' "$line"
        sleep 5
    done
}

if [[ $1 == watch ]]; then
    mkdir -p "${XDG_RUNTIME_DIR:-/tmp}/waybar-sensors"
    HIST_FILE=${XDG_RUNTIME_DIR:-/tmp}/waybar-sensors/gpu.hist
    # Pick up where the previous instance left off: a bar reload restarts this
    # script, and starting from an empty array would blank the graphs.
    [[ -r $HIST_FILE ]] && mapfile -t hist < "$HIST_FILE"
    # Trim to HIST_MAX: a file written at another sample rate (or HIST_MAX)
    # would otherwise keep its old length forever, one in one out.
    ((${#hist[@]} > HIST_MAX)) && hist=("${hist[@]: -HIST_MAX}")

    # waybar takes a module down by signalling this shell alone, so an
    # nvidia-smi left behind would keep streaming for the rest of the session
    # and a reload would stack up another one. Take it with us.
    trap 'kill "$smi_pid" 2>/dev/null; exit 0' TERM INT HUP

    while :; do
        # nvidia-smi block-buffers its stdout whenever that is not a terminal,
        # so a plain `-l 5` would say nothing for minutes and then arrive in one
        # burst; stdbuf turns the buffering off. The inner `exec` matters: it
        # makes $! the pid of nvidia-smi itself rather than of a wrapper shell
        # that would die and orphan it.
        if command -v stdbuf >/dev/null 2>&1; then
            exec 3< <(exec stdbuf -o0 nvidia-smi --query-gpu=$QUERY \
                                       --format=csv,noheader,nounits -l 5 2>/dev/null)
        else
            exec 3< <(poll_stream)
        fi
        smi_pid=$!

        # Reading in the main shell, not down a pipeline: a pipeline would put
        # this loop in a subshell, where nothing it set would survive.
        while IFS=', ' read -r usage temp mem_used mem_total power fan <&3; do
            # A resident nvidia-smi will occasionally answer [N/A] while the
            # driver is busy; one bad sample must not turn into garbage JSON.
            if [[ -z $usage || $usage != [0-9]* ]]; then
                unavailable
                continue
            fi
            emit
        done
        exec 3<&-
        wait "$smi_pid" 2>/dev/null

        # We only get here if nvidia-smi died or was never there. Say so, then
        # wait before retrying: waybar must never see this script exit, but it
        # must not see it spin either.
        unavailable
        sleep 5
    done
fi

IFS=', ' read -r usage temp mem_used mem_total power fan < <(
    nvidia-smi --query-gpu=$QUERY --format=csv,noheader,nounits 2>/dev/null
)

if [[ -z $usage ]]; then
    unavailable
    exit 0
fi

emit
