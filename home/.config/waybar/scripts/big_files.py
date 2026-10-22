#!/usr/bin/env python3
"""The biggest files on each drive -- behind the disk panel's BIGGEST FILES
section.

    big_files.py scan [--json]       walk every mounted drive now, keep the result
    big_files.py cached [--json]     the last result, without walking anything
    big_files.py [--json]            the last result if younger than MAX_AGE_S,
                                     else a scan
    big_files.py delete PATH --trash|--for-good
                                     the panel's Delete: to the trash (gio trash),
                                     or gone for good (unlink). Refused unless PATH
                                     is in the last result, is still a plain file
                                     (not a link) of the size listed, and no
                                     program has it open (a running game, a
                                     loaded model, a playing film); then it leaves
                                     the kept result too

A drive is a physical disk (disk.read_disks(): lsblk), and its files are
those of every filesystem mounted from it -- / and /home on one btrfs are one
drive. Each mount point is walked with `find -xdev` (so another filesystem
mounted inside it, a btrfs subvolume such as the snapshots, /proc, a USB stick
under /run/media, is not walked twice or at all), only files of MIN_SIZE and
up, at the lowest CPU and I/O priority (nice 19, ionice idle): a few seconds
for an SSD, a minute or more for a big spinning disk, and nothing for the
desktop to notice. Folders this user cannot read are skipped (no sudo), so
what is listed is what this user can see -- and could delete.

The result is kept in $XDG_CACHE_HOME/hypr/big-files.json, so the panel shows
it at once and only rescans in the background when it is old. One scan at a
time (a lock next to it): a second `scan` while one runs waits for it and
returns its result, so opening the panel again never starts another walk. Nothing is
ever deleted here: the panel only opens a file's folder.
"""
import fcntl
import json
import os
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from disk import mountpoints, read_disks  # noqa: E402

MIN_SIZE = "+100M"      # find -size: files smaller than this are never the biggest
PER_DRIVE = 6           # kept per drive
MAX_AGE_S = 3600
SKIP_FS = {"swap", "vfat", "squashfs", "iso9660"}   # the EFI partition, swap, images
CACHE = os.path.join(os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"),
                     "hypr", "big-files.json")


def biggest(lines, keep=PER_DRIVE):
    """[(size, path)] from find's "SIZE\\tPATH" lines, biggest first, each
    path once (two mount points of one filesystem can both reach a file)."""
    seen, out = set(), []
    for line in lines:
        size, _, path = line.partition("\t")
        if not path or path in seen or not size.isdigit():
            continue
        seen.add(path)
        out.append((int(size), path))
    out.sort(key=lambda item: -item[0])
    return out[:keep]


def walk(mount):
    """find's lines for one mount point (empty when it cannot be read)."""
    cmd = ["nice", "-n", "19", "ionice", "-c", "3",
           "find", mount, "-xdev", "-type", "f", "-size", MIN_SIZE, "-printf", "%s\\t%p\\n"]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, errors="replace", timeout=1800)
    except (OSError, subprocess.SubprocessError):
        return []
    return out.stdout.splitlines()


def scan():
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    with open(CACHE + ".lock", "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:                 # another scan is walking: wait for its result
            fcntl.flock(lock, fcntl.LOCK_EX)
            return cached()
        return walk_all()


def walk_all():
    drives = []
    for disk, filesystems in read_disks() or []:
        mounts = [m for fs in filesystems if fs.get("fstype") not in SKIP_FS
                  for m in mountpoints(fs) if m.startswith("/") and m != "/boot"]
        if not mounts:
            continue
        lines = []
        for mount in mounts:
            lines += walk(mount)
        drives.append({"drive": (disk.get("model") or disk["name"]).strip(), "name": disk["name"],
                       "mounts": mounts,
                       "files": [{"size": s, "path": p} for s, p in biggest(lines)]})
    data = {"scanned": time.time(), "min_size": MIN_SIZE, "drives": drives}
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(CACHE), prefix=".big-files-")
    with os.fdopen(fd, "w") as handle:
        json.dump(data, handle)
    os.replace(tmp, CACHE)
    return data


def open_by(path):
    """The programs (comm names) holding path open, from /proc (our own
    processes are all this user can see, which is whose files these are)."""
    who = set()
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        fds = f"/proc/{pid}/fd"
        try:
            for fd in os.listdir(fds):
                if os.readlink(os.path.join(fds, fd)) == path:
                    with open(f"/proc/{pid}/comm") as handle:
                        who.add(handle.read().strip())
                    break
        except OSError:
            continue
    return sorted(who)


def delete(path, for_good):
    """None when done, else why not (the checks in the docstring)."""
    data = cached() or {}
    listed = {f["path"]: f["size"] for d in data.get("drives", []) for f in d["files"]}
    if path not in listed:
        return "not in the last scan's list: scan again first"
    if os.path.islink(path) or not os.path.isfile(path):
        return "it is no longer a plain file there"
    if os.path.getsize(path) != listed[path]:
        return "it changed since the scan: scan again first"
    users = open_by(path)
    if users:
        return "in use by " + ", ".join(users) + ": close it first"
    try:
        if for_good:
            os.unlink(path)
        else:
            out = subprocess.run(["gio", "trash", path], capture_output=True, text=True, timeout=600)
            if out.returncode:
                return (out.stderr or "gio trash failed").strip()[:200]
    except (OSError, subprocess.SubprocessError) as exc:
        return str(exc)
    for d in data.get("drives", []):
        d["files"] = [f for f in d["files"] if f["path"] != path]
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(CACHE), prefix=".big-files-")
    with os.fdopen(fd, "w") as handle:
        json.dump(data, handle)
    os.replace(tmp, CACHE)
    return None


def cached():
    try:
        with open(CACHE) as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


def main(argv):
    cmd = next((a for a in argv if not a.startswith("--")), "")
    if cmd == "delete":
        rest = [a for a in argv[1:] if not a.startswith("--")]
        how = [a for a in argv if a in ("--trash", "--for-good")]
        if len(rest) != 1 or len(how) != 1:
            print("big_files.py delete PATH --trash|--for-good", file=sys.stderr)
            return 2
        why = delete(rest[0], how[0] == "--for-good")
        if why:
            print(why, file=sys.stderr)
            return 1
        return 0
    if cmd == "scan":
        data = scan()
    elif cmd == "cached":
        data = cached()
    elif cmd == "":
        data = cached()
        if not data or time.time() - data.get("scanned", 0) > MAX_AGE_S:
            data = scan()
    else:
        print(__doc__.split("\n\n")[1])
        return 2
    if "--json" in argv:
        print(json.dumps(data))
    elif data:
        for d in data["drives"]:
            print(f"{d['drive']}  ({', '.join(d['mounts'])})")
            for f in d["files"]:
                print(f"  {f['size'] / 2**30:8.1f} GiB  {f['path']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
