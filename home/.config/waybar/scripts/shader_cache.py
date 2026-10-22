#!/usr/bin/env python3
"""Shader caches: how big, and clearing them -- behind the disk panel's
SHADER CACHES section.

    shader_cache.py scan              JSON: every cache, with size and owner
    shader_cache.py clean orphans     every Steam cache whose game is uninstalled
    shader_cache.py clean <appid>     one game's Steam cache
    shader_cache.py clean nvidia      the driver's own GL / DX caches
    shader_cache.py clean mesa        Mesa's (unused on NVIDIA; just in case)

What is in there
----------------
Steam keeps one folder per game in <library>/steamapps/shadercache/<appid>/:
Fossilize pipeline databases (fozpipelinesv6 -- almost all of the size),
transcoded video (fozmediav1), the DXVK state cache and NVIDIA's cache for
that game. All of it is rebuilt on demand: deleting it costs a slower first
launch (Steam pre-compiles again, or the game stutters while it compiles as
it goes), never data. Saves are not in here.

ORPHANS are folders whose appid has no appmanifest in any library -- the game
was uninstalled and Steam left its cache behind. Those are pure waste, and
the safe big win.

A game that is RUNNING is never cleared (its cache is open), and neither is
one Steam is processing right now (a fossilize_replay process for that appid).

Libraries come from Steam's own libraryfolders.vdf, so a new library is
picked up with no edit here.
"""

import json
import os
import re
import shutil
import subprocess
import sys

STEAM = os.path.expanduser("~/.local/share/Steam")
LIBRARY_VDF = os.path.join(STEAM, "steamapps", "libraryfolders.vdf")
OTHER = {
    "nvidia": [os.path.expanduser("~/.cache/nvidia"), os.path.expanduser("~/.nv")],
    "mesa": [os.path.expanduser("~/.cache/mesa_shader_cache"),
             os.path.expanduser("~/.cache/mesa_shader_cache_db")],
}
OTHER_LABELS = {"nvidia": "NVIDIA driver cache", "mesa": "Mesa cache"}


def libraries():
    try:
        with open(LIBRARY_VDF) as handle:
            paths = re.findall(r'"path"\s+"([^"]+)"', handle.read())
    except OSError:
        paths = [STEAM]
    return [p for p in dict.fromkeys(paths) if os.path.isdir(os.path.join(p, "steamapps"))]


def installed():
    """appid -> name, from every library's appmanifest_*.acf."""
    names = {}
    for lib in libraries():
        apps = os.path.join(lib, "steamapps")
        for entry in os.listdir(apps):
            m = re.match(r"appmanifest_(\d+)\.acf$", entry)
            if not m:
                continue
            try:
                with open(os.path.join(apps, entry), errors="replace") as handle:
                    name = re.search(r'"name"\s+"([^"]*)"', handle.read())
            except OSError:
                name = None
            names[m.group(1)] = name.group(1) if name else f"app {m.group(1)}"
    return names


def sizes(paths):
    """path -> bytes, one `du` for the lot, at idle IO priority."""
    paths = [p for p in paths if os.path.exists(p)]
    if not paths:
        return {}
    out = subprocess.run(["nice", "-n", "19", "ionice", "-c", "3", "du", "-s", "-B1", "--", *paths],
                         capture_output=True, text=True).stdout
    result = {}
    for line in out.splitlines():
        size, _, path = line.partition("\t")
        result[path] = int(size)
    return result


def busy_appids():
    """appids that a running game or a running fossilize_replay belongs to."""
    busy = set()
    for pid in filter(str.isdigit, os.listdir("/proc")):
        try:
            with open(f"/proc/{pid}/environ", "rb") as handle:
                env = handle.read()
        except OSError:
            continue
        m = re.search(rb"(?:^|\0)(?:SteamAppId|SteamGameId)=(\d+)", env)
        if m and m.group(1) != b"0":
            busy.add(m.group(1).decode())
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as handle:
                cmd = handle.read()
        except OSError:
            continue
        if b"fossilize_replay" in cmd:
            busy.update(x.decode() for x in re.findall(rb"shadercache/(\d+)/", cmd))
    return busy


def scan():
    names = installed()
    busy = busy_appids()
    caches = []
    dirs = []
    for lib in libraries():
        root = os.path.join(lib, "steamapps", "shadercache")
        if os.path.isdir(root):
            dirs += [os.path.join(root, d) for d in os.listdir(root) if d.isdigit()]
    measured = sizes(dirs)
    for path in dirs:
        appid = os.path.basename(path)
        caches.append({
            "appid": appid, "path": path, "size": measured.get(path, 0),
            "name": names.get(appid, f"uninstalled ({appid})"),
            "installed": appid in names, "busy": appid in busy,
            "library": path.split("/steamapps/")[0],
        })
    caches.sort(key=lambda c: -c["size"])
    other = []
    for key, paths in OTHER.items():
        measured = sizes(paths)
        total = sum(measured.values())
        if total:
            other.append({"key": key, "name": OTHER_LABELS[key], "size": total,
                          "paths": [p for p in paths if os.path.exists(p)]})
    orphans = [c for c in caches if not c["installed"]]
    return {
        "steam": caches,
        "steam_total": sum(c["size"] for c in caches),
        "orphans": len(orphans),
        "orphans_size": sum(c["size"] for c in orphans if not c["busy"]),
        "other": other,
    }


def remove(path):
    shutil.rmtree(path, ignore_errors=True)


def clean(what):
    data = scan()
    freed = 0
    if what == "orphans":
        for c in data["steam"]:
            if not c["installed"] and not c["busy"]:
                remove(c["path"])
                freed += c["size"]
    elif what in OTHER:
        if what == "nvidia" and any(c["busy"] for c in data["steam"]):
            sys.exit("a game is running; its driver cache is in use -- close it first")
        for entry in data["other"]:
            if entry["key"] == what:
                for path in entry["paths"]:
                    remove(path)
                freed += entry["size"]
    elif what.isdigit():
        match = [c for c in data["steam"] if c["appid"] == what]
        if not match:
            sys.exit(f"no shader cache for appid {what}")
        for c in match:
            if c["busy"]:
                sys.exit(f"{c['name']} is running (or Steam is compiling its shaders) -- not cleared")
            remove(c["path"])
            freed += c["size"]
    else:
        sys.exit(f"clean: orphans, nvidia, mesa or an appid -- not {what!r}")
    print(json.dumps({"freed": freed}))


def main(argv):
    if argv[:1] == ["scan"]:
        print(json.dumps(scan()))
    elif argv[:1] == ["clean"] and len(argv) == 2:
        clean(argv[1])
    else:
        print(__doc__.strip(), file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main(sys.argv[1:])
