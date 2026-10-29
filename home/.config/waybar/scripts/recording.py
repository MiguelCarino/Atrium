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

Event-driven, not a 1 s poll: both watchers (this pill and the capture
pill, `watch capture`) sleep on inotify for the three pid files appearing,
changing or going away in $XDG_RUNTIME_DIR (PidFiles), and tick only while
there is something to tick for -- once a second while REC's clock runs, a
slow re-check while a capture is live (so a recorder that crashed without
removing its pid file still reads as idle within CRASH_CHECK s), and once a
minute (SAFETY_TICK) when idle. They used to stat the same files every
second, both of them, all day. A pid file whose process is gone (crash,
monitor unplugged) or whose pid now belongs to something else reads as
idle; record.sh removes it next time.

No tooltips: both modules have "tooltip": false (the capture panel is the
long form, and click hints are in the config), so none is built.

Click handling lives in record.sh ("click": stop a recording, else save the
replay), so the bar and the keyboard go through the same code.

Icons are Font Awesome 6 codepoints written as escapes, like every other
script here: literal Private-Use characters do not survive copy and paste.
"""

import ctypes
import ctypes.util
import html
import json
import os
import select
import struct
import sys
import time

RUN = os.environ.get("XDG_RUNTIME_DIR", "/tmp")
REC_PID = os.path.join(RUN, "gsr-record.pid")
REPLAY_PID = os.path.join(RUN, "gsr-replay.pid")
MEMO_PID = os.path.join(RUN, "memo.pid")      # hypr/scripts/memo.py: pid / output / "memo"

ICON_REC = "\uf111"      # circle (the record dot)
ICON_REPLAY = "\uf1da"   # clock-rotate-left

TICK = 1.0
CRASH_CHECK = 5.0       # s between re-checks while a capture is live
SAFETY_TICK = 60.0      # s between re-checks when idle
WATCHED = {os.path.basename(p) for p in (REC_PID, REPLAY_PID, MEMO_PID)}


class PidFiles:
    """inotify on $XDG_RUNTIME_DIR, reporting only the pid files above. The
    stdlib has no inotify; this is the same libc route privacy.py takes.
    Without it (no libc inotify, the dir unwatchable) wait() just sleeps,
    which is the old polling."""
    IN_MODIFY, IN_CLOSE_WRITE, IN_MOVED_FROM, IN_MOVED_TO = 0x2, 0x8, 0x40, 0x80
    IN_CREATE, IN_DELETE = 0x100, 0x200
    IN_NONBLOCK, IN_CLOEXEC = 0o4000, 0o2000000
    HEADER = struct.Struct("iIII")

    def __init__(self, folder=RUN):
        self.fd = -1
        try:
            libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
            fd = libc.inotify_init1(self.IN_NONBLOCK | self.IN_CLOEXEC)
            mask = (self.IN_MODIFY | self.IN_CLOSE_WRITE | self.IN_MOVED_FROM | self.IN_MOVED_TO
                    | self.IN_CREATE | self.IN_DELETE)
            if fd >= 0 and libc.inotify_add_watch(fd, folder.encode(), mask) >= 0:
                self.fd = fd
            elif fd >= 0:
                os.close(fd)
        except (OSError, AttributeError):
            self.fd = -1

    @classmethod
    def names(cls, data):
        """The file names in a buffer of inotify events."""
        out, pos = [], 0
        while pos + cls.HEADER.size <= len(data):
            _wd, _mask, _cookie, length = cls.HEADER.unpack_from(data, pos)
            pos += cls.HEADER.size
            out.append(data[pos:pos + length].rstrip(b"\0").decode(errors="replace"))
            pos += length
        return out

    def wait(self, timeout):
        """Until one of the pid files changes (True) or timeout s pass (False)."""
        if self.fd < 0:
            time.sleep(timeout)
            return False
        deadline = time.monotonic() + timeout
        while True:
            left = deadline - time.monotonic()
            if left <= 0 or not select.select([self.fd], [], [], left)[0]:
                return False
            hit = False
            try:
                while True:
                    hit |= bool(WATCHED.intersection(self.names(os.read(self.fd, 65536))))
            except BlockingIOError:
                pass
            if hit:
                time.sleep(0.05)    # record.sh writes the file in a few steps
                return True


def until_next_second():
    return TICK - (time.time() % TICK) + 0.02


FRESH_S = 3.0           # a pid file this new may name a recorder still starting
FRESH_TICK = 0.25


def next_wait(base, now=None, run=RUN):
    """How long to sleep when the pill shows no live capture (base: the
    idle or crash-check pace), unless a pid file was written in the last
    FRESH_S: record.sh writes the pid of `setsid gpu-screen-recorder &`
    before that child has exec'd (its comm still says bash), so the read
    the inotify event triggers can see no recorder yet -- re-read every
    FRESH_TICK until it settles instead of waiting out a minute."""
    now = time.time() if now is None else now
    for name in WATCHED:
        try:
            if now - os.stat(os.path.join(run, name)).st_mtime < FRESH_S:
                return min(base, FRESH_TICK)
        except OSError:
            pass
    return base


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
        started, _output, _target = rec
        hdr = capture_range(REC_PID) == "hdr"
        text = f"{ICON_REC} REC {'HDR ' if hdr else ''}{clock(now - started)}"
        if replay:
            # Both at once: the REC pill speaks for both, with the replay
            # glyph tacked on so the buffer is not forgotten under it.
            text += f"  {ICON_REPLAY}"
        return {"text": text, "class": "recording"}

    if replay:
        return {"text": f"{ICON_REPLAY} REPLAY", "class": "replay"}

    return {"text": "", "class": "idle"}


# photo-film: the pill opens screenshots, recordings, voice memos and notes --
# media of every kind, not just the camera it used to show.
ICON_CAMERA = "\uf87c"
SAVED_SECONDS = 2.5      # how long the camera pill flashes after a stop

def memo():
    """(started_epoch, output) while memo.py records (its ffmpeg is alive)."""
    try:
        started = os.stat(MEMO_PID).st_mtime
        with open(MEMO_PID) as handle:
            lines = handle.read().splitlines()
        with open(f"/proc/{int(lines[0])}/comm") as handle:
            if handle.read().strip() != "ffmpeg":
                return None
    except (OSError, ValueError, IndexError):
        return None
    return started, html.escape(lines[1]) if len(lines) > 1 else ""


def capture_status(saved_until=0.0):
    """The camera pill (custom/capture). It stands in for the start/stop
    notifications record.sh no longer sends: class recording pulses it red
    for as long as a recording (or a voice memo) runs, class saved flashes it
    once after."""
    if capture(REC_PID) or memo():
        return {"text": ICON_CAMERA, "class": "recording"}
    if time.time() < saved_until:
        return {"text": ICON_CAMERA, "class": "saved"}
    return {"text": ICON_CAMERA, "class": "idle"}


def watch_capture():
    last = None
    was_recording = False
    saved_until = 0.0
    files = PidFiles()
    while True:
        recording = capture(REC_PID) is not None or memo() is not None
        if was_recording and not recording:
            saved_until = time.time() + SAVED_SECONDS
        was_recording = recording
        state = capture_status(saved_until)
        if state != last:
            emit(state)
            last = state
        if state["class"] == "saved":
            files.wait(max(0.05, saved_until - time.time()))
        else:
            files.wait(next_wait(CRASH_CHECK if recording else SAFETY_TICK))


def capture_click():
    """Left click on the capture pill: stop a running recording or voice memo right there,
    otherwise open the capture panel. exec, so the click is one process."""
    if capture(REC_PID):
        script = os.path.expanduser("~/.config/hypr/scripts/record.sh")
        os.execv(script, [script, "stop"])
    if memo():
        script = os.path.expanduser("~/.config/hypr/scripts/memo.py")
        os.execv(sys.executable, [sys.executable, script, "stop"])
    panel = os.path.join(os.path.dirname(os.path.abspath(__file__)), "panel.py")
    os.execv(sys.executable, [sys.executable, panel, "toggle", "capture"])


def emit(state):
    print(json.dumps(state), flush=True)


def watch():
    last = None
    files = PidFiles()
    while True:
        state = status()
        # Idle and replay never change between ticks; only REC's clock does.
        # Printing just the changes keeps waybar from re-rendering a pill
        # that looks the same.
        if state != last:
            emit(state)
            last = state
        # REC: to the next whole second, so the counter steps evenly instead
        # of drifting against the start time and occasionally skipping one.
        if state["class"] == "recording":
            files.wait(until_next_second())
        else:
            files.wait(next_wait(CRASH_CHECK if state["class"] == "replay" else SAFETY_TICK))


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
