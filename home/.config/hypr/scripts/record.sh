#!/bin/bash
# Screen recording and instant replay with gpu-screen-recorder (NVENC).
#
#     record.sh monitor        record the focused monitor   (again = stop)
#     record.sh region         slurp a region and record it (again = stop)
#     record.sh stop           stop the recording and finalise the file
#     record.sh toggle-replay  start/stop an instant-replay buffer of the
#                              focused monitor (the last 30 s unless Settings
#                              says otherwise), held in RAM
#     record.sh save-replay    write the replay buffer out to a file
#     record.sh stop-replay    stop the replay buffer if it runs (never starts
#                              one -- for the pill's right-click)
#     record.sh click          what the waybar pill does: stop a recording if
#                              one runs, else save the replay buffer
#     record.sh status         "recording" / "replay" / "idle", one per line
#     record.sh sdr | hdr      record in SDR (the default) or HDR from now on
#     record.sh toggle-range   flip between the two (ALT+CTRL+F9)
#     record.sh range          the current choice: "sdr" or "hdr"
#
# Bound to ALT+F9 / ALT+SHIFT+F9 / ALT+F10 / ALT+SHIFT+F10 in lua/binds.lua --
# the ShadowPlay keys, on purpose: on a machine with a 4090 those are the keys
# your fingers already know. The bar pill is scripts/recording.py in waybar.
#
# A recording and the replay buffer are separate gpu-screen-recorder processes
# and may run at the same time (the 4090's NVENC has sessions to spare). Each
# has its own pid file in $XDG_RUNTIME_DIR; that file IS the single-instance
# lock and the bar's only source of truth:
#
#     line 1  pid           line 2  output file (or directory, for replay)
#     line 3  what is being captured (a screen, e.g. DP-1, or a WxH+X+Y region)
#     line 4  the dynamic range it is captured in: sdr or hdr
#
# and its mtime is the moment the capture started, which is where the bar's
# elapsed-time counter comes from -- so nothing has to tick a file every second.
#
# Every signal the recorder honours is in `man gpu-screen-recorder` (SIGNALS):
# SIGINT stops a recording AND finalises the file (moov atom written -- a
# SIGTERM/SIGKILL'd mp4 is unplayable), SIGINT on a replay buffer just discards
# it, SIGUSR1 saves the replay buffer.
#
# The folder, the sound, the frame rate and the replay length are Settings >
# Screenshots & recording's (capture-settings.py, kept in
# ~/.local/state/hypr/capture.conf), read when a capture starts -- a running
# one keeps what it started with. The environment beats them, for a one-off:
#     REC_DIR=/path   output directory          (default ~/Videos/Recordings)
#     REC_CODEC=hevc  see "-k" in --help        (default: from sdr/hdr)
#     REC_FPS=120     capture rate              (default 60)
#     REC_MIC=1       also record the default microphone (with desktop audio)
#     REC_MONITOR=DP-2  capture this output instead of the focused one
#     REC_QUIET=1     no notifications (used by the self-test)

set -u

OUT_DIR=$HOME/Videos/Recordings
RUN=${XDG_RUNTIME_DIR:-/tmp}
REC_PID=$RUN/gsr-record.pid
REPLAY_PID=$RUN/gsr-replay.pid
REC_LOG=$RUN/gsr-record.log
REPLAY_LOG=$RUN/gsr-replay.log
LOCK=$RUN/gsr-record.lock

# SDR or HDR is a sticky choice, kept in RANGE_FILE so it survives a reboot,
# and read each time a capture starts -- see pick_video.
RANGE_FILE=${XDG_STATE_HOME:-$HOME/.local/state}/record-range
FPS=60
REPLAY_SECONDS=30
# Desktop audio by default; the microphone only when asked for, because a
# mic that is unexpectedly in a clip is a worse surprise than one that is
# missing. "a|b" mixes both into one track.
AUDIO=default_output

# Shared by recordings and the replay buffer:
#   -encoder gpu    NVENC. No -fallback-cpu-encoding: if NVENC is broken we want
#                   an error notification, not a silent 3440x1440 x264 job
#                   eating every core in the middle of a game.
#   -ac aac         gsr's default for mp4 is opus, which several editors and
#                   phone players refuse inside an mp4 container.
#   -ab 256         AAC at 256 kbps instead of gsr's 160: transparent for
#                   game audio and music, and a rounding error next to video.
#   -tune quality   NVENC's slower presets (default is "performance"). The
#                   4090 has the headroom; costs no game FPS, only encoder time.
#   -v no           otherwise it prints an FPS line every second into the log.
#
# Built by load_settings, which runs only when a capture starts: `status`
# and the save keys must stay instant, and need none of it.
COMMON=()

load_settings() {
    local cfg
    mapfile -t cfg < <("$(dirname -- "$SELF")/capture-settings.py" \
                       get rec_dir rec_fps replay_seconds rec_audio 2>/dev/null)
    if (( ${#cfg[@]} == 4 )); then
        OUT_DIR=${cfg[0]}; FPS=${cfg[1]}; REPLAY_SECONDS=${cfg[2]}
        case ${cfg[3]} in
            both) AUDIO="default_output|default_input" ;;
            mic)  AUDIO=default_input ;;
            none) AUDIO="" ;;
            *)    AUDIO=default_output ;;
        esac
    fi
    OUT_DIR=${REC_DIR:-$OUT_DIR}
    FPS=${REC_FPS:-$FPS}
    [[ ${REC_MIC:-0} == 1 ]] && AUDIO="default_output|default_input"
    # No -a at all is gsr's "no audio track" (an empty -a is an error).
    COMMON=(-c mp4 -f "$FPS" ${AUDIO:+-a "$AUDIO" -ac aac -ab 256}
            -tune quality -encoder gpu -v no)
}

# Recordings: constant quality (-bm qp) at gsr's top preset. A recording's
# size is whatever it needs to be; what matters is that motion and text do
# not turn to mush. Roughly 1.5-2x the size of very_high.
REC_QUALITY=(-bm qp -q ultra)

# Replay buffer: constant bitrate, which is what the man page recommends for
# replay -- the buffer lives in RAM, and CBR makes its size predictable:
# 80 Mbit/s x 30 s = ~300 MB, whatever is on screen (5 minutes: ~3 GB).
REPLAY_QUALITY=(-bm cbr -q 80000 -replay-storage ram)

SELF=$(readlink -f "$0")

# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

# One notification slot per kind, replaced in place: starting, stopping and
# starting again should not stack three bubbles.
notify() {   # notify <tag> <urgency> <title> [body]
    [[ ${REC_QUIET:-0} == 1 ]] && { echo "$3${4:+: $4}"; return; }
    notify-send -a "Recorder" -u "$2" -i media-record \
        -h "string:x-canonical-private-synchronous:rec-$1" "$3" "${4:-}"
}

# Notification for a finished file, with Play / Folder buttons. notify-send
# --wait blocks until the bubble is clicked or expires, so it runs detached;
# the caller (a Hyprland bind or a waybar click) must not hang on it.
notify_file() {   # notify_file <tag> <title> <file>
    local file=$3 size
    size=$(du -h -- "$file" 2>/dev/null | cut -f1)
    if [[ ${REC_QUIET:-0} == 1 ]]; then echo "$2: $file ($size)"; return; fi
    (
        act=$(notify-send -a "Recorder" -i video-x-generic --wait \
                -h "string:x-canonical-private-synchronous:rec-$1" \
                -A "default=Play" -A "play=Play" -A "folder=Show folder" \
                "$2" "$file  ($size)")
        case $act in
            default|play) xdg-open "$file" ;;
            folder)       xdg-open "$(dirname -- "$file")" ;;
        esac
    ) >/dev/null 2>&1 9>&- &
    disown
}

# Prints the pid in <pidfile> if that process is alive AND is still the
# recorder. A pid file can outlive its process (a crash, a monitor unplugged
# mid-recording), and after enough uptime the number is reused by something
# else entirely -- so `kill -0` alone is not enough to trust it with a signal.
live_pid() {   # live_pid <pidfile>
    local pid comm
    [[ -r $1 ]] || return 1
    read -r pid < "$1" || return 1
    [[ $pid =~ ^[0-9]+$ ]] || { rm -f -- "$1"; return 1; }
    # comm is truncated to 15 characters by the kernel.
    comm=$(cat "/proc/$pid/comm" 2>/dev/null) || { rm -f -- "$1"; return 1; }
    [[ $comm == gpu-screen-reco* ]] || { rm -f -- "$1"; return 1; }
    echo "$pid"
}

# The line worth showing from a recorder log: its first "gsr error", which
# names the cause (the tail is often just a list of valid monitors), else the
# last few lines.
log_reason() {   # log_reason <log>
    grep -m1 'error' "$1" 2>/dev/null || grep -v '^\s*$' "$1" 2>/dev/null | tail -n 3
    echo "(log: $1)"
}

need() {   # need <command>: tell the user, do not fail silently
    command -v "$1" >/dev/null && return 0
    notify err critical "$1 is not installed" "sudo dnf install $1"
    exit 1
}

chosen_range() {   # "sdr" or "hdr"; anything unreadable is sdr
    local range=""
    read -r range < "$RANGE_FILE" 2>/dev/null
    [[ $range == hdr ]] && echo hdr || echo sdr
}

# Hyprland's colour-management preset is "hdr" or "hdredid" while a monitor
# runs in HDR, "srgb" (and friends) otherwise.
monitor_is_hdr() {   # monitor_is_hdr <name>
    hyprctl monitors -j 2>/dev/null |
        jq -e --arg m "$1" 'any(.[]; .name == $m and (.colorManagementPreset | test("^hdr")))' \
        >/dev/null 2>&1
}

# The monitor under a desktop point (slurp's coordinates are logical, so the
# monitor's pixel size is divided by its scale), else the focused one.
monitor_at() {   # monitor_at <x> <y>
    local mon
    mon=$(hyprctl monitors -j 2>/dev/null | jq -r --argjson x "$1" --argjson y "$2" \
        'first(.[] | select($x >= .x and $x < .x + .width / .scale and
                            $y >= .y and $y < .y + .height / .scale) | .name) // empty' 2>/dev/null)
    [[ -n $mon ]] && echo "$mon" || focused_monitor
}

# Sets VIDEO (the codec args) and RANGE for a capture of <monitor>.
#
#   sdr  h264. Not hevc/av1, although the 4090 encodes all three in hardware:
#        these files get dropped into Discord, browsers and chat apps, and
#        h264 is the one codec every one of them plays inline. An HDR monitor
#        is tone-mapped down to SDR by gsr, so it still looks right.
#   hdr  hevc_hdr: 10-bit HDR10 (PQ, BT.2020), the HDR flavour players and
#        YouTube take most widely. Only looks right in an HDR-aware player on
#        an HDR screen -- which is why it is not the default. A monitor that
#        is not in HDR mode has nothing to capture in HDR, so it falls back to
#        SDR and says so.
#
# REC_CODEC, when set, beats both.
pick_video() {   # pick_video <monitor>
    if [[ -n ${REC_CODEC:-} ]]; then
        VIDEO=(-k "$REC_CODEC")
        [[ $REC_CODEC == *hdr* ]] && RANGE=hdr || RANGE=sdr
        return
    fi
    if [[ $(chosen_range) == hdr ]]; then
        if monitor_is_hdr "$1"; then
            VIDEO=(-k hevc_hdr); RANGE=hdr
            return
        fi
        notify range normal "$1 is not in HDR mode" \
            "Capturing in SDR. Turn HDR on for $1 to record HDR."
    fi
    VIDEO=(-k h264); RANGE=sdr
}

set_range() {   # set_range sdr|hdr
    local hint
    mkdir -p -- "$(dirname -- "$RANGE_FILE")"
    echo "$1" > "$RANGE_FILE"
    if [[ $1 == hdr ]]; then
        hint="HEVC HDR10 -- needs an HDR player and screen to look right."
    else
        hint="h264 -- plays everywhere. HDR monitors are tone-mapped."
    fi
    if live_pid "$REC_PID" >/dev/null || live_pid "$REPLAY_PID" >/dev/null; then
        hint+=$'\n'"Captures already running keep their range; this applies to the next one."
    fi
    notify range low "Recording in ${1^^}" "$hint"
}

focused_monitor() {
    local mon=${REC_MONITOR:-}
    [[ -n $mon ]] && { echo "$mon"; return; }
    mon=$(hyprctl monitors -j 2>/dev/null | jq -r '.[] | select(.focused) | .name' 2>/dev/null)
    # None focused (the instant a screen goes away): the primary (screens.py).
    [[ -n $mon ]] || mon=$("$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/screens.py" primary 2>/dev/null)
    echo "$mon"
}

# Start gpu-screen-recorder detached and write the pid file. pick_video must
# have run first: VIDEO goes in the args, RANGE into the pid file.
#
# setsid gives it a session of its own, so it outlives this script and the
# Hyprland exec that ran it; in a non-interactive shell the background child is
# not a group leader, so setsid execs in place and $! is the recorder itself
# (live_pid checks that by comm before anything is signalled).
#
# A capture that fails (bad region, NVENC unavailable, KMS capture denied)
# dies within a few hundred ms, so we wait a moment and report the log's tail
# rather than leaving a pid file for a process that never really started.
launch() {   # launch <pidfile> <log> <output> <target> -- <gsr args...>
    local pidfile=$1 log=$2 out=$3 target=$4 pid
    shift 5
    # 9>&- : do not hand the flock fd (see dispatch) to the recorder, or the
    # lock would be held for as long as the recording runs.
    setsid gpu-screen-recorder "$@" >"$log" 2>&1 </dev/null 9>&- &
    pid=$!
    printf '%s\n%s\n%s\n%s\n' "$pid" "$out" "$target" "$RANGE" > "$pidfile"
    sleep 0.8
    if ! live_pid "$pidfile" >/dev/null; then
        rm -f -- "$pidfile"
        notify err critical "Recorder failed to start" "$(log_reason "$log")"
        return 1
    fi
}

# --------------------------------------------------------------------------
# recording
# --------------------------------------------------------------------------

stop_recording() {
    local pid out waited=0
    pid=$(live_pid "$REC_PID") || { notify rec low "No recording running"; return 1; }
    out=$(sed -n 2p "$REC_PID")
    kill -INT "$pid"
    # Finalising is quick (the moov atom, plus flushing the encoder), but a
    # long 1440p recording on a busy disk can take a couple of seconds. Poll
    # rather than `wait`: the recorder is not our child once setsid'd.
    while kill -0 "$pid" 2>/dev/null && (( waited < 150 )); do
        sleep 0.1; (( waited++ ))
    done
    rm -f -- "$REC_PID"
    if kill -0 "$pid" 2>/dev/null; then
        notify rec critical "Recorder did not stop" "pid $pid is still running after 15s"
        return 1
    fi
    if [[ -s $out ]]; then
        notify_file rec "Recording saved" "$out"
    else
        notify rec critical "Recording failed" "$(log_reason "$REC_LOG")"
        return 1
    fi
}

start_recording() {   # start_recording monitor|region
    local mode=$1 target region="" out stamp xy
    need gpu-screen-recorder
    load_settings

    # Same key twice = stop. That turns ALT+F9 into the one key you need to
    # remember, and you never have to aim for the bar mid-game.
    if live_pid "$REC_PID" >/dev/null; then
        stop_recording
        return
    fi

    if [[ $mode == region ]]; then
        if command -v slurp >/dev/null; then
            # %wx%h+%x+%y is exactly gsr's region format for -w. A plain
            # click with no drag gives a 0x0 region, which gsr reads as "the
            # whole monitor under that point" -- a free monitor picker.
            #
            # The lock is released while slurp waits: the picker can stay open
            # for as long as you like, and holding the lock through it made
            # every other record.sh (ALT+F10 save-replay, the pill's clicks)
            # queue behind it and fail with "Recorder busy" after 20 s.
            flock -u 9
            region=$(slurp -f '%wx%h+%x+%y') || { notify rec low "Recording cancelled"; return 1; }
            flock -w 20 9 || { notify err critical "Recorder busy" "Another record.sh is still running"; return 1; }
            # Something else may have started a recording while the picker was
            # open (the lock was free); a second recorder would clobber its pid
            # file, so the earlier one wins.
            if live_pid "$REC_PID" >/dev/null; then
                notify rec normal "Already recording" "Another recording started while you were picking a region"
                return 1
            fi
            target=region
        else
            notify rec normal "slurp is not installed" \
                "sudo dnf install slurp -- recording the focused monitor instead"
            mode=monitor
        fi
    fi
    [[ $mode == monitor ]] && target=$(focused_monitor)
    if [[ -n $region ]]; then
        xy=${region#*+}                 # WxH+X+Y -> X+Y
        pick_video "$(monitor_at "${xy%%+*}" "${xy#*+}")"
    else
        pick_video "$target"
    fi

    mkdir -p -- "$OUT_DIR"
    stamp=$(date +%Y-%m-%d_%H-%M-%S)
    out=$OUT_DIR/Recording_${region:+region_}${region:-$target}_$stamp.mp4
    # A region's "+" and "x" are fine in a filename but ugly; keep it readable.
    out=${out//+/_}

    # -w takes a monitor name or a region (WxH+X+Y) directly. The older
    # `-w region -region WxH+X+Y` form is deprecated since gsr 6.x and logs a
    # warning on every recording, so both cases share the -w spelling now.
    launch "$REC_PID" "$REC_LOG" "$out" "${region:-$target}" -- \
        -w "${region:-$target}" "${COMMON[@]}" "${VIDEO[@]}" "${REC_QUALITY[@]}" -o "$out" || return 1
    notify rec normal "Recording ${region:-$target} in ${RANGE^^}" \
        "$out
ALT+F9 or the REC pill in the bar to stop"
}

# --------------------------------------------------------------------------
# instant replay
# --------------------------------------------------------------------------

toggle_replay() {
    local pid mon
    need gpu-screen-recorder
    if pid=$(live_pid "$REPLAY_PID"); then
        # SIGINT on a replay buffer discards it; nothing is written.
        kill -INT "$pid"
        rm -f -- "$REPLAY_PID"
        notify replay low "Instant replay off" "The buffer was discarded"
        return
    fi
    load_settings
    mon=$(focused_monitor)
    pick_video "$mon"
    mkdir -p -- "$OUT_DIR"
    # -o is a DIRECTORY in replay mode; gsr names each save Replay_<date>.mp4.
    # -sc runs this script again after every save with "<file> replay", which
    # is the only way to learn the saved file's name when saving by signal --
    # see the dispatch at the bottom.
    launch "$REPLAY_PID" "$REPLAY_LOG" "$OUT_DIR" "$mon" -- \
        -w "$mon" -r "$REPLAY_SECONDS" "${COMMON[@]}" "${VIDEO[@]}" "${REPLAY_QUALITY[@]}" \
        -sc "$SELF" -o "$OUT_DIR" || return 1
    notify replay normal "Instant replay on: $mon (${RANGE^^})" \
        "Keeping the last ${REPLAY_SECONDS}s in RAM. ALT+F10 saves it."
}

save_replay() {
    local pid
    pid=$(live_pid "$REPLAY_PID") || {
        notify replay normal "Instant replay is off" "ALT+SHIFT+F10 starts the buffer"
        return 1
    }
    # The "saved" notification comes from the -sc hook once the file exists.
    kill -USR1 "$pid"
}

status() {
    local any=0
    live_pid "$REC_PID" >/dev/null && { echo recording; any=1; }
    live_pid "$REPLAY_PID" >/dev/null && { echo replay; any=1; }
    (( any )) || echo idle
}

# --------------------------------------------------------------------------
# dispatch
# --------------------------------------------------------------------------

# gpu-screen-recorder's -sc hook: called as `record.sh <saved file> <type>`.
# An absolute path can never be a subcommand, so it is safe to recognise here.
# The length is read from the running buffer's own command line, not the
# settings: those may have changed since it started.
if [[ ${1:-} == /* && ${2:-} =~ ^(regular|replay|screenshot)$ ]]; then
    secs=$(pid=$(live_pid "$REPLAY_PID") && tr '\0' '\n' < "/proc/$pid/cmdline" | grep -A1 -x -- -r | tail -n1)
    notify_file replay "Replay saved (up to the last ${secs:-$REPLAY_SECONDS}s)" "$1"
    exit 0
fi

# Saving the replay only reads a pid file and sends SIGUSR1, so it never needs
# the lock -- and must not wait on it: a save queued behind a long stop or an
# open region picker would capture the wrong 30 s, or none. Same for the
# pill's click when no recording runs (that click IS a save).
if [[ ${1:-} == save-replay ]] ||
   { [[ ${1:-} == click ]] && ! live_pid "$REC_PID" >/dev/null; }; then
    save_replay
    exit
fi

# Serialise everything that reads-then-writes pid files: a double-tapped key
# must not start two recorders. -w 20: a stop may legitimately take a while.
exec 9>"$LOCK"
flock -w 20 9 || { notify err critical "Recorder busy" "Another record.sh is still running"; exit 1; }

case ${1:-} in
    monitor|region) start_recording "$1" ;;
    stop)           stop_recording ;;
    toggle-replay)  toggle_replay ;;
    stop-replay)    live_pid "$REPLAY_PID" >/dev/null && toggle_replay ;;
    save-replay)    save_replay ;;
    click)
        if live_pid "$REC_PID" >/dev/null; then stop_recording
        else save_replay
        fi ;;
    status)         status ;;
    sdr|hdr)        set_range "$1" ;;
    toggle-range)   [[ $(chosen_range) == hdr ]] && set_range sdr || set_range hdr ;;
    range)          chosen_range ;;
    *)
        sed -n '2,18p' "$SELF" | sed 's/^# \{0,1\}//'
        exit 2 ;;
esac
