#!/bin/bash
# GPU stats for waybar, whoever made the card: the numbers come from
# ~/.config/hypr/scripts/gpu.py (NVML in-process on NVIDIA, sysfs / fdinfo on
# AMD and Intel), never from a forked nvidia-smi.
#
#     gpu_usage.sh          one line, then exit -- for manual runs
#     gpu_usage.sh watch    one line every 5s, forever -- for a module with
#                           no "interval", which waybar reads continuously
#
# Watch mode keeps a single `gpu.py stream 5` resident: it opens the card once
# (NVML's init is the expensive part, ~25-80 ms) and then prints a CSV line
# every five seconds. A number the card does not report (an iGPU has no VRAM
# of its own, some cards no temperature) comes as N/A and is left out of the
# pill. With no graphics card the pill is hidden (empty text), and the script
# idles instead of polling.

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

GPU_PY=${GPU_PY:-$HOME/.config/hypr/scripts/gpu.py}   # the tests point it at a stand-in

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

# No card at all: an empty text hides the pill (waybar hides a custom module
# whose text is empty), and there is nothing to poll for the rest of the
# session -- a card does not appear without a reboot.
no_card() {
    printf '{"text":"","class":"none"}\n'
}

num() {   # num <value>: is it a number (gpu.py says N/A for what is unknown)?
    [[ $1 =~ ^[0-9]+(\.[0-9]+)?$ ]]
}

# --- One JSON line for the sample currently in $usage, $temp, ... ------------
emit() {
    local mem_pct text class vram_x10 label_col t_txt v_txt temp_i power_i

    mem_pct=0
    num "$mem_used" && num "$mem_total" && ((mem_total > 0)) && mem_pct=$((100 * mem_used / mem_total))

    # printf -v rather than $(printf ...): a command substitution forks a
    # subshell, and this runs every few seconds for the life of the bar.
    # Same layout as the CPU pill: neon label, white fixed-width numbers.
    # Compact: load, temperature, VRAM used (GiB). Graphs are in the panel.
    # What the card does not report is left out (an iGPU: no VRAM field).
    class=normal
    t_txt="" v_txt="" temp_i=0 power_i=0
    if num "$temp"; then
        temp_i=${temp%%.*}
        (( temp_i >= 80 )) && class=critical
        pad2 "$temp_i" t
        t_txt="$SEP$t°"
    fi
    if num "$mem_used" && num "$mem_total" && ((mem_total > 0)); then
        vram_x10=$((mem_used * 10 / 1024))          # MiB -> GiB, one decimal
        v_txt="$SEP$((vram_x10 / 10)).$((vram_x10 % 10))G"
    fi
    num "$power" && power_i=${power%%.*}

    pad2 "$usage" u
    theme_color gpu '#39ff14' label_col
    # The filled critical pill may want another label colour (cpu_usage.sh).
    [[ $class == critical ]] && theme_color gpu_hot "$label_col" label_col
    printf -v text "<span color='%s'>GPU</span>%s%s%%%s%s" \
        "$label_col" "$SEP" "$u" "$t_txt" "$v_txt"

    # No tooltip: tooltips are off for this pill and the sensors panel shows
    # the detail (gpu.py table: every app's VRAM and share of the card).

    printf '{"text":"%s","class":"%s","percentage":%d}\n' \
        "$text" "$class" "$usage"

    record "$EPOCHSECONDS $usage $temp_i $mem_pct $power_i"
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

    # waybar takes a module down by signalling this shell alone, so a stream
    # left behind would keep running for the rest of the session and a
    # reload would stack up another one. Take it with us.
    trap 'kill "$smi_pid" 2>/dev/null; exit 0' TERM INT HUP

    while :; do
        # python3 -u: unbuffered, or the lines would arrive in bursts down a
        # pipe. The inner `exec` makes $! the stream itself, not a wrapper
        # shell that would die and orphan it.
        exec 3< <(exec python3 -u "$GPU_PY" stream 5 2>/dev/null)
        smi_pid=$!

        # Reading in the main shell, not down a pipeline: a pipeline would put
        # this loop in a subshell, where nothing it set would survive.
        while IFS=', ' read -r usage temp mem_used mem_total power fan <&3; do
            if [[ $usage == none ]]; then
                # No graphics card: hide the pill and idle (sleep in the
                # background + wait, so the trap still ends us at once).
                exec 3<&-
                no_card
                while :; do sleep 3600 & smi_pid=$!; wait "$smi_pid"; done
            fi
            # A busy driver can miss one sample (N/A); one bad sample must
            # not turn into garbage JSON.
            if ! num "$usage"; then
                unavailable
                continue
            fi
            usage=${usage%%.*}
            emit
        done
        exec 3<&-
        wait "$smi_pid" 2>/dev/null

        # We only get here if the stream died. Say so, then wait before
        # retrying: waybar must never see this script exit, but it must not
        # see it spin either.
        unavailable
        sleep 5
    done
fi

IFS=', ' read -r usage temp mem_used mem_total power fan < <(
    python3 "$GPU_PY" stream 0 2>/dev/null | head -n 1
)

if [[ $usage == none ]]; then
    no_card
    exit 0
fi
if ! num "$usage"; then
    unavailable
    exit 0
fi
usage=${usage%%.*}
emit
