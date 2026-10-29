#!/usr/bin/env python3
"""Memory-pressure pill (custom/mempressure): nothing while memory is calm,
a memory chip and the pressure when it is not.

    memory_pill.py watch    JSON lines forever, for a module with no
                            "interval" (a line only when the pill changes)
    memory_pill.py once     one line and exit (to try it by hand)

The level is memory.py's (the CPU panel's MEMORY section), so the pill and
the panel never disagree about what "tight" means:

    calm      some avg10 < 5 and at least 15 % available   -> hidden
    warn      some avg10 >= 5, or under 15 % available     -> .warn
    crit      full avg10 >= 2, or under 6 % available      -> .crit

(some = the share of the last 10 s that at least one task waited for
memory; full = that every task did -- /proc/pressure/memory.) The text is
the pressure when there is any, else what is left: "12% wait", "1.4G free".

Event-light on purpose: one long-running process, woken every TICK seconds,
reads two small /proc files and forks nothing. The tooltip's top five
processes cost a walk over /proc/*/statm -- done only while the pill is
showing, never while it is hidden. Click: the CPU panel, whose MEMORY
section has the full list (PSS, by app) with End buttons.
"""

import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import memory  # noqa: E402  (the CPU panel's numbers: meminfo, pressure, levels)

TICK = 10.0             # s between looks
TOP = 5                 # processes in the tooltip
ICON = ""         # Font Awesome: memory (a RAM stick)
CLASSES = {"warning": "warn", "critical": "crit"}


def level_class(level):
    """memory.reading()'s level -> the pill's class; None while calm."""
    return CLASSES.get(level)


def top_rss(rows, n=TOP):
    """The n biggest (name, rss bytes) from (pid, name, rss) rows, the same
    name summed (twenty "Web Content" are one browser's worth), biggest
    first, then by name for a stable order."""
    sums = {}
    for _pid, name, rss in rows:
        sums[name] = sums.get(name, 0) + rss
    return sorted(sums.items(), key=lambda kv: (-kv[1], kv[0]))[:n]


def read_rows(proc="/proc"):
    """(pid, comm, rss bytes) of every process this user can see. RSS is the
    cheap number (statm); the CPU panel shows the honest one (PSS)."""
    rows = []
    try:
        pids = [p for p in os.listdir(proc) if p.isdigit()]
    except OSError:
        return rows
    for pid in pids:
        try:
            with open(f"{proc}/{pid}/statm") as handle:
                rss = int(handle.read().split()[1]) * memory.PAGE
            with open(f"{proc}/{pid}/comm") as handle:
                comm = handle.read().strip()
        except (OSError, ValueError, IndexError):
            continue
        if rss:
            rows.append((int(pid), comm, rss))
    return rows


def pill_text(reading):
    """"12% wait" while tasks are stalling on memory, else "1.4G free"."""
    if reading["some"] >= 1:
        return f"{ICON} {reading['some']:.0f}% wait"
    return f"{ICON} {memory.human(reading['available'])} free"


def tooltip(reading, top):
    """Why the pill is up, then the top processes by RSS."""
    lines = [f"Memory is {'critically ' if reading['level'] == 'critical' else ''}tight",
             f"{memory.human(reading['available'])} available of {memory.human(reading['total'])}"
             f" · swap {memory.human(reading['swap_used'])} used",
             f"pressure: some {reading['some']:.1f}% · full {reading['full']:.1f}% (last 10 s)"]
    if top:
        lines.append("")
        lines += [f"{memory.human(size):>7}  {name}" for name, size in top]
    return "\n".join(lines)


def pill(reading, top=()):
    """The module's JSON: empty text (waybar hides the pill) while calm."""
    cls = level_class(reading["level"])
    if cls is None:
        return {"text": "", "class": "calm"}
    return {"text": pill_text(reading), "tooltip": tooltip(reading, top), "class": cls}


def current():
    reading = memory.reading()
    top = top_rss(read_rows()) if level_class(reading["level"]) else ()
    return pill(reading, top)


def safe_current():
    try:
        return current()
    except Exception as exc:  # noqa: BLE001 - a watcher must outlive its errors
        return {"text": "", "class": "error", "tooltip": f"memory_pill.py: {exc}"}


def watch():
    last = None
    while True:
        line = json.dumps(safe_current())
        if line != last:
            try:
                sys.stdout.write(line + "\n")
                sys.stdout.flush()
            except BrokenPipeError:
                return
            last = line
        time.sleep(TICK)


def main():
    if sys.argv[1:2] == ["watch"]:
        watch()
    else:
        print(json.dumps(safe_current()))


if __name__ == "__main__":
    main()
