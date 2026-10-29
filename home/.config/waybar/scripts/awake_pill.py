#!/usr/bin/env python3
"""Keep-awake pill on the main bar (custom/keepawake): a lit mug while Keep
awake is on -- with its end time when it has one -- and nothing otherwise.
One click turns it off.

    awake_pill.py watch     JSON lines forever, for a module with no
                            "interval" (a line only when the pill changes)
    awake_pill.py once      one line and exit
    awake_pill.py off       turn Keep awake off (the pill's click)

The switch itself is the toolbox's Keep awake row and Settings > Power
(idle-settings.py awake, a systemd idle lock); this only shows it where it
can be seen with the toolbox folded away, so the screens staying on is
never a mystery. It asks the same `idle-settings.py awake status` the row
does, but only when there is a reason to: idle-settings.py writes
$XDG_RUNTIME_DIR/keep-awake.json when Keep awake goes on and removes it
when it goes off, so the watcher stats that file every STAT_EVERY seconds
(no fork) and asks only when the file appears, changes or goes -- and,
while it exists, every RECHECK seconds and just after a timed one's end
(a lock can also end without the file going: its timer runs out, or the
unit is stopped by hand).
"""

import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import toolbox_awake  # noqa: E402  (the toolbox row: awake_status, the off switch)

RUNTIME = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
AWAKE_FILE = os.path.join(RUNTIME, "keep-awake.json")
STAT_EVERY = 2.0        # s between looks at the file
RECHECK = 60.0          # s between asks while the file is there
ICON = toolbox_awake.ICON_ON


def file_mark(path=AWAKE_FILE):
    """(mtime_ns, size) of the state file, or None while it is absent."""
    try:
        st = os.stat(path)
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size)


def should_ask(prev_mark, mark, last_ask, now, until=None, recheck=RECHECK):
    """Is it time for a real `awake status`? When the file appeared, changed
    or went; while it exists, every recheck seconds; and once a timed Keep
    awake's end (until) has passed since the last ask."""
    if mark != prev_mark:
        return True
    if mark is None:
        return False
    if now - last_ask >= recheck:
        return True
    return bool(until) and last_ask < until <= now


def pill(state):
    """The module's JSON for an `awake status` answer: hidden unless on."""
    if not state or not state.get("on"):
        return {"text": "", "class": "off"}
    until = state.get("until")
    if until:
        end = time.strftime("%H:%M", time.localtime(until))
        return {"text": f"{ICON} {end}", "class": "on",
                "tooltip": f"Keep awake until {end} -- the screens will not dim or lock"}
    return {"text": ICON, "class": "on",
            "tooltip": "Keep awake is on -- the screens will not dim or lock"}


def watch():
    prev_mark, last_ask, state, last_line = object(), 0.0, None, None
    while True:
        # Wall-clock time throughout: `until` is one (a timed Keep awake's end).
        mark, now = file_mark(), time.time()
        if should_ask(prev_mark, mark, last_ask, now, (state or {}).get("until")):
            state = toolbox_awake.awake_status() if mark is not None else {"on": False}
            last_ask = now
        prev_mark = mark
        line = json.dumps(pill(state))
        if line != last_line:
            try:
                sys.stdout.write(line + "\n")
                sys.stdout.flush()
            except BrokenPipeError:
                return
            last_line = line
        time.sleep(STAT_EVERY)


def turn_off():
    """The pill's click: the same as the toolbox row's toggle while on."""
    subprocess.run([toolbox_awake.IDLE, "awake", "off"], capture_output=True, timeout=20)
    toolbox_awake.redraw()


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "once"
    if cmd == "watch":
        watch()
    elif cmd == "off":
        turn_off()
    else:
        print(json.dumps(pill(toolbox_awake.awake_status())))


if __name__ == "__main__":
    main()
