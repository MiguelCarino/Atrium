#!/usr/bin/env python3
"""Which apps are using the network, and how fast -- for the network panel.

    netprocs.py          two samples a second apart, printed as a table

Linux keeps byte counters per TCP SOCKET, not per process: `ss -tinp` shows
each connection's bytes_received / bytes_acked (sent and confirmed) and the
process that owns it. Two samples apart, summed per app, give a download and
upload rate. Only your own processes are visible -- root's (dnf, systemd)
would need root -- which is the right set for "what of mine is downloading".

The limit, said once here and once in the panel: UDP has no such counters.
QUIC (YouTube and most of Google in a browser), qBittorrent's uTP and most
games' traffic are UDP, so for those apps the connection count is right but
the rate is only the TCP part of what they move. Per-process UDP accounting
needs eBPF and root; nethogs-style capture needs root too.

Apps are grouped by process name; connections are TCP + UDP sockets
(`ss -tuap`), excluding listeners.
"""

import re
import subprocess
import time

USERS = re.compile(r'\("([^"]+)",pid=(\d+)')


def ss(*flags):
    try:
        return subprocess.run(["ss", "-H", *flags], capture_output=True, text=True,
                              timeout=3).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def tcp_bytes():
    """(local, peer, pid) -> (name, received, sent) for every TCP socket."""
    out = {}
    lines = ss("-tinp").splitlines()
    i = 0
    while i < len(lines):
        head = lines[i]
        info = lines[i + 1] if i + 1 < len(lines) and lines[i + 1][:1].isspace() else ""
        i += 2 if info else 1
        match = USERS.search(head)
        if not match:
            continue
        parts = head.split()
        key = (parts[3], parts[4], int(match.group(2))) if len(parts) > 4 else None
        rx = re.search(r"bytes_received:(\d+)", info)
        tx = re.search(r"bytes_acked:(\d+)", info)
        if key:
            out[key] = (match.group(1), int(rx.group(1)) if rx else 0, int(tx.group(1)) if tx else 0)
    return out


def connections():
    """name -> (count, set of pids), TCP + UDP, established/connected only."""
    out = {}
    for line in ss("-tuap", "state", "connected").splitlines():
        for name, pid in USERS.findall(line):
            count, pids = out.get(name, (0, set()))
            pids.add(int(pid))
            out[name] = (count + 1, pids)
    return out


class Sampler:
    """Call it every second or two; each call returns the apps ranked by
    traffic since the previous call (the first call has no rates yet)."""

    def __init__(self):
        self.prev, self.when = tcp_bytes(), time.monotonic()

    def __call__(self, limit=8):
        now_bytes, now = tcp_bytes(), time.monotonic()
        elapsed = max(now - self.when, 1e-3)
        rates = {}
        for key, (name, rx, tx) in now_bytes.items():
            before = self.prev.get(key)
            if before:
                drx, dtx = max(rx - before[1], 0), max(tx - before[2], 0)
                r = rates.setdefault(name, [0.0, 0.0])
                r[0] += drx / elapsed
                r[1] += dtx / elapsed
        self.prev, self.when = now_bytes, now
        apps = []
        for name, (count, pids) in connections().items():
            down, up = rates.get(name, (0.0, 0.0))
            apps.append({"name": name, "conns": count, "pids": sorted(pids),
                         "down": down, "up": up})
        apps.sort(key=lambda a: (-(a["down"] + a["up"]), -a["conns"], a["name"]))
        return apps[:limit]


def rate(bps):
    for unit in ("B/s", "K/s", "M/s", "G/s"):
        if bps < 1024 or unit == "G/s":
            return f"{bps:.0f} {unit}" if unit == "B/s" else f"{bps:.1f} {unit}"
        bps /= 1024
    return ""


if __name__ == "__main__":
    sample = Sampler()
    time.sleep(1)
    for app in sample():
        print(f"{app['name']:24} {app['conns']:4d} conn  down {rate(app['down']):>10}  up {rate(app['up']):>10}")
