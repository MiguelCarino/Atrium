#!/usr/bin/env python3
"""Screen-recording indicator for waybar (custom/recording).

    recording.py          one JSON line, then exit -- for manual runs
    recording.py watch    a JSON line whenever the state or the elapsed time
                          changes, forever -- for a module with no "interval"

The recorder is ~/.config/hypr/scripts/record.sh (ALT+F9 & co.). It leaves one
pid file per gpu-screen-recorder process in $XDG_RUNTIME_DIR, and those files
are all this reads:

    gsr-record.pid   a recording:          red pulsing  REC 01:23  (REC HDR 01:23)
    gsr-replay.pid   the replay buffer:    dim          REPLAY
    neither                                 empty text -> waybar hides the module

Each pid file is: pid / output path / capture target / sdr|hdr, one per line. Its mtime
is when the capture started, so the elapsed time costs one stat() and nothing
has to be rewritten every second.

Polling, not inotify: a 1s tick is needed anyway for the elapsed counter, and
a tick is three stat()s and a /proc read -- no forks, so it is effectively
free. A pid file whose process is gone (crash, monitor unplugged) or whose pid
now belongs to something else reads as idle; record.sh removes it next time.

Click handling lives in record.sh ("click": stop a recording, else save the
replay), so the bar and the keyboard go through the same code.

Icons are Font Awesome 6 codepoints written as escapes, like every other
script here: literal Private-Use characters do not survive copy and paste.
"""

import html
import json
import os
import sys
import time

RUN = os.environ.get("XDG_RUNTIME_DIR", "/tmp")
REC_PID = os.path.join(RUN, "gsr-record.pid")
REPLAY_PID = os.path.join(RUN, "gsr-replay.pid")

ICON_REC = "\uf111"      # circle (the record dot)
ICON_REPLAY = "\uf1da"   # clock-rotate-left

TICK = 1.0


def capture(pidfile):
    """(started_epoch, output, target) if pidfile names a live recorder."""
    try:
        started = os.stat(pidfile).st_mtime
        with open(pidfile) as handle:
            lines = handle.read().splitlines()
        pid = int(lines[0])
        with open(f"/proc/{pid}/comm") as handle:
            # The kernel truncates comm to 15 characters.
            if not handle.read().startswith("gpu-screen-reco"):
                return None
    except (OSError, ValueError, IndexError):
        return None
    # Escaped here once: waybar renders tooltips as Pango markup, and a path
    # with an & or < in it would otherwise blank the whole tooltip.
    output = html.escape(lines[1]) if len(lines) > 1 else ""
    target = html.escape(lines[2]) if len(lines) > 2 else "?"
    return started, output, target


def capture_range(pidfile):
    """"hdr" or "sdr": line 4 of a pid file; older files without it are sdr."""
    try:
        with open(pidfile) as handle:
            lines = handle.read().splitlines()
    except OSError:
        return "sdr"
    return "hdr" if len(lines) > 3 and lines[3] == "hdr" else "sdr"


def clock(seconds):
    seconds = max(0, int(seconds))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:02d}:{secs:02d}"


def status():
    rec = capture(REC_PID)
    replay = capture(REPLAY_PID)
    now = time.time()

    if rec:
        started, output, target = rec
        hdr = capture_range(REC_PID) == "hdr"
        text = f"{ICON_REC} REC {'HDR ' if hdr else ''}{clock(now - started)}"
        tip = [f"Recording {target} in {'HDR' if hdr else 'SDR'}", output, "",
               "Click: stop and save  (or ALT+F9)"]
        if replay:
            # Both at once: the REC pill speaks for both, with the replay
            # glyph tacked on so the buffer is not forgotten under it.
            text += f"  {ICON_REPLAY}"
            tip += ["", f"Instant replay also running on {replay[2]}",
                    "ALT+F10 saves it, ALT+SHIFT+F10 stops it"]
        return {"text": text, "tooltip": "\n".join(tip), "class": "recording"}

    if replay:
        _, _, target = replay
        return {
            "text": f"{ICON_REPLAY} REPLAY",
            "tooltip": "\n".join([
                f"Instant replay: the last 30s of {target}, kept in RAM",
                "",
                "Click: save it  (or ALT+F10)",
                "Right-click: stop the buffer  (or ALT+SHIFT+F10)",
            ]),
            "class": "replay",
        }

    return {"text": "", "tooltip": "", "class": "idle"}


ICON_CAMERA = "\uf030"
SAVED_SECONDS = 2.5      # how long the camera pill flashes after a stop

CAPTURE_TIP = ("Capture\nLeft: screenshot / record panel\n"
               "Right: region to clipboard\nMiddle: Screenshots folder")


def capture_status(saved_until=0.0):
    """The camera pill (custom/capture). It stands in for the start/stop
    notifications record.sh no longer sends: class recording pulses it red
    for as long as a recording runs, class saved flashes it once after."""
    rec = capture(REC_PID)
    if rec:
        started, output, target = rec
        return {"text": ICON_CAMERA, "class": "recording",
                "tooltip": f"Recording {target}  {clock(time.time() - started)}\n"
                           f"{output}\n\nClick: stop and save"}
    if time.time() < saved_until:
        return {"text": ICON_CAMERA, "class": "saved",
                "tooltip": "Recording saved\n\n" + CAPTURE_TIP}
    return {"text": ICON_CAMERA, "class": "idle", "tooltip": CAPTURE_TIP}


def watch_capture():
    last = None
    was_recording = False
    saved_until = 0.0
    while True:
        recording = capture(REC_PID) is not None
        if was_recording and not recording:
            saved_until = time.time() + SAVED_SECONDS
        was_recording = recording
        state = capture_status(saved_until)
        if state != last:
            emit(state)
            last = state
        time.sleep(TICK - (time.time() % TICK) + 0.02)


def capture_click():
    """Left click on the camera pill: stop a running recording right there,
    otherwise open the capture panel. exec, so the click is one process."""
    if capture(REC_PID):
        script = os.path.expanduser("~/.config/hypr/scripts/record.sh")
        os.execv(script, [script, "stop"])
    panel = os.path.join(os.path.dirname(os.path.abspath(__file__)), "panel.py")
    os.execv(sys.executable, [sys.executable, panel, "toggle", "capture"])


def emit(state):
    print(json.dumps(state), flush=True)


def watch():
    last = None
    while True:
        state = status()
        # Idle and replay never change between ticks; only REC's clock does.
        # Printing just the changes keeps waybar from re-rendering a pill
        # that looks the same.
        if state != last:
            emit(state)
            last = state
        # Sleep to the next whole second, so the counter steps evenly instead
        # of drifting against the start time and occasionally skipping one.
        time.sleep(TICK - (time.time() % TICK) + 0.02)


def main():
    try:
        if sys.argv[1:2] == ["capture-click"]:
            capture_click()
        elif sys.argv[1:3] == ["watch", "capture"]:
            watch_capture()
        elif sys.argv[1:2] == ["watch"]:
            watch()
        else:
            emit(status())
    except (BrokenPipeError, KeyboardInterrupt):
        # waybar went away (restart): leave quietly, it starts a new one.
        try:
            sys.stdout = None
        except Exception:
            pass


if __name__ == "__main__":
    main()
