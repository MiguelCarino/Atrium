#!/usr/bin/env python3
"""The numbers behind the CPU panel's MEMORY section (sensors_panel.py).

    memory.py           RAM, swap and pressure now, as JSON
    memory.py apps      the top memory users, grouped by app, as JSON

RAM in use is counted the way `free` counts it (total - available: page cache
that can be dropped is not "used"). The level is PRESSURE, not the
percentage: this box runs several sessions and a browser farm, and 85 % used
with nothing waiting is fine, while 70 % with tasks stalled on reclaim is not.
/proc/pressure/memory says which it is:

    some avg10   % of the last 10 s that at least one task waited for memory
    full avg10   % of it that EVERY task did (the machine stood still)

    ok        some < 5
    warning   some >= 5, or under 15 % available
    critical  full >= 2, or under 6 % available

Reads /proc only -- three small files, no forks.

Grouping for the panel: a process belongs to the systemd unit or scope it runs
in (/proc/PID/cgroup). uwsm starts every app in its own app-*.scope, so that is
"Firefox" or "Steam" with all its helpers, not forty lines of "Web Content".

The size is PSS, not RSS. RSS counts every page a process can see, so pages
SHARED between processes -- the libraries, and in a browser the shared-memory
buffers its content processes talk through -- are counted once per process:
Firefox's 60 processes added up to 21.5 GiB of RSS on a machine with 17 GiB in
use. PSS (/proc/PID/smaps_rollup) splits each shared page between the
processes sharing it, so a group's sum is what it really costs: 15.9 GiB there.
Reading it makes the kernel walk the page tables -- ~0.5 s for every process
on this box -- so apps() ranks everything by the cheap RSS first and reads PSS
only for the groups that could make the list (PSS_CANDIDATES x limit), and
the panel calls it off the GTK thread.
"""

import json
import os
import re
import sys

PAGE = os.sysconf("SC_PAGE_SIZE")


def meminfo():
    info = {}
    with open("/proc/meminfo") as handle:
        for line in handle:
            key, _, rest = line.partition(":")
            info[key] = int(rest.split()[0]) * 1024
    return info


def pressure():
    out = {"some": 0.0, "full": 0.0}
    try:
        with open("/proc/pressure/memory") as handle:
            for line in handle:
                kind, *fields = line.split()
                for field in fields:
                    if field.startswith("avg10="):
                        out[kind] = float(field[6:])
    except OSError:
        pass
    return out


def human(n):
    for unit in ("B", "K", "M", "G", "T"):
        if abs(n) < 1024 or unit == "T":
            return f"{n:.1f}{unit}" if unit in ("G", "T") else f"{n:.0f}{unit}"
        n /= 1024
    return str(n)


def reading():
    m, p = meminfo(), pressure()
    total, avail = m["MemTotal"], m["MemAvailable"]
    used = total - avail
    swap_used = m.get("SwapTotal", 0) - m.get("SwapFree", 0)
    avail_pct = 100 * avail / total
    level = "ok"
    if p["full"] >= 2 or avail_pct < 6:
        level = "critical"
    elif p["some"] >= 5 or avail_pct < 15:
        level = "warning"
    return {"total": total, "used": used, "available": avail,
            "cached": m.get("Cached", 0) + m.get("SReclaimable", 0),
            "swap_total": m.get("SwapTotal", 0), "swap_used": swap_used,
            "some": p["some"], "full": p["full"], "level": level,
            "percent": 100 * used / total}


# -- the panel's process list ----------------------------------------------
SCOPE = re.compile(r"(?:^|/)(app-[^/]*?\.(?:scope|service)|[^/]+\.service)$")


def group_name(pid):
    """A readable name for the unit or scope the process lives in."""
    try:
        with open(f"/proc/{pid}/cgroup") as handle:
            path = handle.read().strip().split("::", 1)[-1]
    except OSError:
        return None
    match = SCOPE.search(path)
    if not match:
        return None
    unit = match.group(1)
    # app-flatpak-com.valvesoftware.Steam-1234.scope -> com.valvesoftware.Steam
    # app-Hyprland-firefox@abc.service / app-uwsm-firefox-xyz.scope -> firefox
    unit = re.sub(r"\.(scope|service)$", "", unit)
    unit = re.sub(r"^app-(flatpak-|Hyprland-|uwsm-|gnome-)?", "", unit)
    unit = re.sub(r"(@[^-]*)?(-[0-9a-f]{6,}|-\d+)*$", "", unit)
    return unit or None


PSS_CANDIDATES = 2      # PSS for twice as many groups as are shown, re-ranked


def pss(pid):
    """Proportional set size in bytes, or None if it cannot be read."""
    try:
        with open(f"/proc/{pid}/smaps_rollup") as handle:
            for line in handle:
                if line.startswith("Pss:"):
                    return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        pass
    return None


def apps(limit=10):
    groups = {}
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        try:
            with open(f"/proc/{entry}/statm") as handle:
                rss = int(handle.read().split()[1]) * PAGE
            with open(f"/proc/{entry}/comm") as handle:
                comm = handle.read().strip()
            with open(f"/proc/{entry}/cmdline", "rb") as handle:
                cmdline = handle.read()
        except (OSError, ValueError, IndexError):
            continue
        if rss == 0:
            continue
        headless = b"--headless" in cmdline
        name = "Headless browsers" if headless else (group_name(entry) or comm)
        # Everything Hyprland starts with a plain exec (terminals, mpv, the
        # file manager...) lands in the compositor's own unit, which would make
        # "wayland-wm" one 10 GB line. Those are told apart by name instead.
        if name.startswith("wayland-wm"):
            name = comm
        g = groups.setdefault(name, {"name": name, "rss": 0, "pids": [], "comm": comm,
                                     "headless": headless})
        g["rss"] += rss
        g["pids"].append(int(entry))
    ranked = sorted(groups.values(), key=lambda g: -g["rss"])[:limit * PSS_CANDIDATES]
    for g in ranked:
        sizes = [pss(pid) for pid in g["pids"]]
        known = [s for s in sizes if s is not None]
        # Another user's process (root's) has no readable smaps: keep RSS.
        g["size"] = sum(known) if known else g["rss"]
    ranked.sort(key=lambda g: -g["size"])
    return ranked[:limit]


def main():
    if sys.argv[1:2] == ["apps"]:
        print(json.dumps(apps(), indent=1))
    else:
        print(json.dumps(reading()))


if __name__ == "__main__":
    main()
