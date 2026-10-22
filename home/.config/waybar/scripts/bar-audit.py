#!/usr/bin/env python3
"""Bar cost audit: what the bar's scripts cost while they sit there.

    bar-audit.py [SECONDS]      measure for SECONDS (default 30), print a table

For every process under the two waybars (main + toolbox) and the bar's
helper services (workspace-tint, wallpaper-slideshow), grouped by script:

    cpu ms/min    CPU time used, user + system, scaled to a minute
    wakeups/s     context switches -- how often it is woken to do anything;
                  a sleeping watcher should be near its tick rate, not above
    forks/min     new processes started under it (a pill whose exec runs on
                  an interval forks every time; a watcher should fork ~never)
    rss           resident memory now

It reads /proc only, polling every POLL seconds for new processes, so the
audit itself shows up as one quiet python3 outside the waybar tree. Child
processes that come and go between two polls are still counted as forks (the
pid counter is compared), but their CPU is only seen if they live long enough
to be sampled -- the CPU of short execs is therefore a LOWER bound; the fork
count is what to look at for those.
"""

import os
import sys
import time

POLL = 0.25
SERVICES = ("workspace-tint", "wallpaper-slideshow")
TICK = os.sysconf("SC_CLK_TCK")
PAGE = os.sysconf("SC_PAGE_SIZE")


def read(path):
    try:
        with open(path, "rb") as handle:
            return handle.read()
    except OSError:
        return b""


def stat(pid):
    raw = read(f"/proc/{pid}/stat").decode(errors="replace")
    if not raw:
        return None
    # comm can contain spaces and parentheses: split after the LAST ')'.
    rest = raw[raw.rfind(")") + 2:].split()
    return {"ppid": int(rest[1]), "cpu": int(rest[11]) + int(rest[12])}


def switches(pid):
    total = 0
    for line in read(f"/proc/{pid}/status").decode(errors="replace").splitlines():
        if line.startswith(("voluntary_ctxt_switches", "nonvoluntary_ctxt_switches")):
            total += int(line.split()[1])
    return total


def label(pid):
    """What a human calls this process: the script for interpreters."""
    args = [a.decode(errors="replace") for a in read(f"/proc/{pid}/cmdline").split(b"\0") if a]
    if not args:
        return None
    exe = os.path.basename(args[0])
    if exe in ("python3", "python", "bash", "sh") and len(args) > 1:
        script = next((a for a in args[1:] if not a.startswith("-")), args[1])
        extra = [a for a in args[args.index(script) + 1:]][:2]
        return " ".join([os.path.basename(script)] + extra)
    if exe == "waybar":
        return "waybar (toolbox)" if any("toolbox" in a for a in args) else "waybar (main)"
    return exe


def roots():
    found = []
    for pid in filter(str.isdigit, os.listdir("/proc")):
        args = read(f"/proc/{pid}/cmdline")
        name = os.path.basename(args.split(b"\0")[0]).decode(errors="replace")
        if name == "waybar" or any(s.encode() in args for s in SERVICES):
            found.append(int(pid))
    return found


def tree():
    """pid -> (root pid, ppid) for every process under a root."""
    parents = {}
    for pid in filter(str.isdigit, os.listdir("/proc")):
        st = stat(pid)
        if st:
            parents[int(pid)] = st["ppid"]
    rootset = set(roots())
    members = {}
    for pid in parents:
        cur, seen = pid, 0
        while cur and cur not in rootset and seen < 64:
            cur, seen = parents.get(cur, 0), seen + 1
        if cur in rootset:
            members[pid] = cur
    return members


def main():
    seconds = float(sys.argv[1]) if len(sys.argv) > 1 else 30.0
    start = {}
    seen_pids = set()
    forks = {}

    def sample(into):
        for pid, _root in tree().items():
            st = stat(pid)
            name = label(pid)
            if not st or not name:
                continue
            into[pid] = (name, st["cpu"], switches(pid), st["ppid"])

    sample(start)
    seen_pids.update(start)
    print(f"Measuring {len(start)} processes for {seconds:.0f} s ...", file=sys.stderr)
    t0 = time.monotonic()
    while time.monotonic() - t0 < seconds:
        time.sleep(POLL)
        now = {}
        sample(now)
        for pid, (_name, _cpu, _sw, ppid) in now.items():
            if pid not in seen_pids:
                seen_pids.add(pid)
                parent = start.get(ppid) or now.get(ppid)
                key = parent[0] if parent else "?"
                forks[key] = forks.get(key, 0) + 1
                start.setdefault(pid, (now[pid][0], 0, 0, ppid))
    elapsed = time.monotonic() - t0
    end = {}
    sample(end)

    rows = {}
    for pid, (name, cpu0, sw0, _p) in start.items():
        if pid not in end:
            continue
        _n, cpu1, sw1, _pp = end[pid]
        rss = 0
        try:
            rss = int(read(f"/proc/{pid}/statm").split()[1]) * PAGE
        except (IndexError, ValueError):
            pass
        row = rows.setdefault(name, [0.0, 0.0, 0, 0])
        row[0] += (cpu1 - cpu0) / TICK * 1000 * 60 / elapsed
        row[1] += (sw1 - sw0) / elapsed
        row[3] += rss
    for name, count in forks.items():
        rows.setdefault(name, [0.0, 0.0, 0, 0])[2] += count * 60 / elapsed

    print(f"{'process':44} {'cpu ms/min':>11} {'wakeups/s':>10} {'forks/min':>10} {'rss':>8}")
    total = [0.0, 0.0, 0.0]
    for name, (cpu, wake, fk, rss) in sorted(rows.items(), key=lambda kv: -(kv[1][0] + kv[1][2] * 5)):
        total[0] += cpu
        total[1] += wake
        total[2] += fk
        print(f"{name[:44]:44} {cpu:11.1f} {wake:10.1f} {fk:10.1f} {rss / 2**20:7.0f}M")
    print(f"{'TOTAL':44} {total[0]:11.1f} {total[1]:10.1f} {total[2]:10.1f}")
    print(f"\n{total[0] / 600:.2f}% of one core on average over {elapsed:.0f} s.")


if __name__ == "__main__":
    main()
