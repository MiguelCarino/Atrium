#!/usr/bin/env python3
"""Storage (Settings > Storage): how full every disk is, what is big in your
home folder, the trash and the caches, and the automatic clean-up.

    storage.py status [--json]      every mounted filesystem (size, used, free,
                                    how full), the automatic clean-up settings
                                    and when it last ran, btrfs snapshots
    storage.py sizes [--json]       the trash (one per disk) and ~/.cache: total,
                                    thumbnails, the biggest folders in it
    storage.py home [--json] [--cached] [--max-age S]
                                    the biggest folders in ~ (du, at the lowest
                                    CPU and disk priority; ~40 s). The answer is
                                    kept in ~/.cache/storage/home.json and
                                    reused for --max-age seconds (default 6 h);
                                    --cached never scans, it says what is kept
    storage.py empty-trash          empty every trash (gio trash --empty)
    storage.py clear-cache <name>   delete what is inside ~/.cache/<name>; a
                                    folder a running program has open is left
                                    alone and the program named
    storage.py clear-thumbnails     the same for ~/.cache/thumbnails (Files and
                                    the file pickers draw them again as needed)
    storage.py auto trash on|off    delete trash older than the age below, daily
    storage.py auto temp on|off     delete your own temporary files (/tmp,
                                    /var/tmp) older than the age below, daily
    storage.py auto days <N>        that age, in days
    storage.py cleanup [--dry-run]  what the daily timer runs: the two above,
                                    if they are on; --dry-run only lists

The clean-up settings are GNOME's own (gsettings org.gnome.desktop.privacy
remove-old-trash-files, remove-old-temp-files, old-files-age), so Files' own
preferences show the same switches. GNOME applies them from gsd-housekeeping,
which does not run outside GNOME; here storage-cleanup.timer (a systemd user
timer, ~/.config/systemd/user) runs `storage.py cleanup` once a day instead.
`auto` turns the timer on while either switch is on and off when both are,
and cleanup reads the switches again every time, so a stray run with both
off does nothing. The last run is kept in ~/.local/state/hypr/storage-cleanup.json.

Snapshots are snapper's (snapshots.py, set up by setup-root.sh); their space
shows only when btrfs quotas are on (snapper setup-quota), since btrfs cannot
say otherwise how much a snapshot holds on its own.
"""
import datetime
import fcntl
import json
import math
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import urllib.parse

HOME = os.path.expanduser("~")
CACHE_HOME = os.environ.get("XDG_CACHE_HOME") or os.path.join(HOME, ".cache")
STATE_HOME = os.environ.get("XDG_STATE_HOME") or os.path.join(HOME, ".local", "state")
DATA_HOME = os.environ.get("XDG_DATA_HOME") or os.path.join(HOME, ".local", "share")
HOME_CACHE = os.path.join(CACHE_HOME, "storage", "home.json")
LAST_RUN = os.path.join(STATE_HOME, "hypr", "storage-cleanup.json")
TIMER = "storage-cleanup.timer"
SCHEMA = "org.gnome.desktop.privacy"
HOME_MAX_AGE = 6 * 3600
TOP = 12                # folders listed for ~ and for ~/.cache
UID = os.getuid()
# Filesystems that are not disks: findmnt --real already leaves out /proc,
# /sys and the like, but not these.
NOT_DISKS = {"tmpfs", "devtmpfs", "ramfs", "squashfs", "overlay", "efivarfs", "rpc_pipefs", "autofs",
             "fuse.portal", "fuse.gvfsd-fuse", "nsfs", "tracefs", "bpf", "zram"}
WARNING, CRITICAL = 85, 90      # the pill turns yellow at 85; this page calls 90 "nearly full"


def human(size):
    """Decimal units, as the disk pill and drive makers use: 4.1 T, 640 G."""
    size = float(size or 0)
    for unit in ("B", "K", "M", "G", "T", "P"):
        if size < 1000 or unit == "P":
            return f"{size:.0f} {unit}" if unit in "BKM" else f"{size:.1f} {unit}"
        size /= 1000
    return ""


def run(*cmd, timeout=30):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        return subprocess.CompletedProcess(cmd, 1, "", str(exc))


# -- filesystems -------------------------------------------------------------------
def percent(used, avail):
    """How full, the way df counts it: used out of what you can use (btrfs
    and ext4 hold some space back, so size alone would read too low), rounded
    up so 96.1 % never shows as 96."""
    total = (used or 0) + (avail or 0)
    return math.ceil(100 * used / total) if total else 0


def level(pct):
    return "critical" if pct >= CRITICAL else "warning" if pct >= WARNING else ""


def parse_findmnt(text):
    """findmnt --real --list -J -b: one entry per device (a btrfs disk mounted
    as / and /home is one disk, listed with both places), in mount order."""
    try:
        rows = json.loads(text or "{}").get("filesystems") or []
    except ValueError:
        return []
    found, order = {}, []
    for r in rows:
        source, fstype = r.get("source") or "", r.get("fstype") or ""
        if fstype in NOT_DISKS or not r.get("size"):
            continue
        device = source.split("[", 1)[0]           # /dev/nvme0n1p3[/home] -> the device
        if device not in found:
            used, avail = int(r.get("used") or 0), int(r.get("avail") or 0)
            found[device] = {"device": device, "fstype": fstype, "label": r.get("label") or "",
                             "size": int(r["size"]), "used": used, "avail": avail,
                             "percent": percent(used, avail), "targets": []}
            found[device]["level"] = level(found[device]["percent"])
            order.append(device)
        found[device]["targets"].append(r.get("target") or "")
    return [found[d] for d in order]


def filesystems():
    out = run("findmnt", "--real", "--list", "-J", "-b", "-o", "TARGET,SOURCE,FSTYPE,LABEL,SIZE,USED,AVAIL")
    return parse_findmnt(out.stdout)


# -- trash ---------------------------------------------------------------------------
def trash_dirs(targets):
    """Every trash you have: the home one, and on each other disk the
    .Trash-<uid> folder (or .Trash/<uid>) Files makes there, so deleting on
    a big disk does not copy it into home."""
    dirs = [(os.path.join(DATA_HOME, "Trash"), HOME)]
    for top in targets:
        if top in ("/", HOME) or not top:
            continue
        for d in (os.path.join(top, f".Trash-{UID}"), os.path.join(top, ".Trash", str(UID))):
            if os.path.isdir(d):
                dirs.append((d, top))
    return [(d, top) for d, top in dirs if os.path.isdir(d)]


def du(path, depth=None, timeout=600):
    """{path: bytes} from du -x -B1 (one filesystem; errors -- a folder you
    cannot read -- skipped), at the lowest CPU and disk priority."""
    cmd = ["nice", "-n", "19", "ionice", "-c", "3", "du", "-x", "-B1"]
    cmd += [f"--max-depth={depth}"] if depth is not None else ["-s"]
    return parse_du(run(*cmd, path, timeout=timeout).stdout)


def parse_du(text):
    sizes = {}
    for line in (text or "").splitlines():
        size, _, path = line.partition("\t")
        if size.isdigit() and path:
            sizes[path] = int(size)
    return sizes


def trash_info(d):
    files = os.path.join(d, "files")
    try:
        items = sum(1 for n in os.listdir(os.path.join(d, "info")) if n.endswith(".trashinfo"))
    except OSError:
        items = 0
    size = du(files).get(files, 0) if os.path.isdir(files) else 0
    return {"dir": d, "size": size, "items": items}


def deletion_date(text):
    """The DeletionDate of a .trashinfo (local time, as the spec says), or None."""
    for line in (text or "").splitlines():
        if line.startswith("DeletionDate="):
            try:
                when = datetime.datetime.fromisoformat(line.split("=", 1)[1].strip())
            except ValueError:
                return None
            # The spec says local time with no zone; a file that has one
            # anyway is read in local time too, so it compares with "now".
            return when.astimezone().replace(tzinfo=None) if when.tzinfo else when
    return None


def old_trash(d, days, now):
    """[(info file, item)] in trash folder d deleted more than `days` ago.
    An info file with no readable date is left alone."""
    cutoff = now - datetime.timedelta(days=days)
    info = os.path.join(d, "info")
    out = []
    try:
        names = sorted(os.listdir(info))
    except OSError:
        return out
    for name in names:
        if not name.endswith(".trashinfo"):
            continue
        try:
            with open(os.path.join(info, name), encoding="utf-8", errors="replace") as f:
                when = deletion_date(f.read())
        except OSError:
            continue
        if when is not None and when < cutoff:
            out.append((os.path.join(info, name), os.path.join(d, "files", name[:-len(".trashinfo")])))
    return out


# -- temporary files -------------------------------------------------------------------
def temp_dirs():
    return sorted({tempfile.gettempdir(), "/tmp", "/var/tmp"})


def old_temp(top, days, now_ts, uid=UID):
    """Your own files under `top` not read, written or changed for `days`
    days, deepest first (so a folder comes after what is in it). Only
    regular files, symlinks and folders: never a socket or pipe a running
    program is listening on, never anything of another user's."""
    cutoff = now_ts - days * 86400
    out = []
    try:
        dev = os.lstat(top).st_dev
    except OSError:
        return out
    for dirpath, dirnames, filenames in os.walk(top, topdown=False):
        for name in filenames + dirnames:
            path = os.path.join(dirpath, name)
            try:
                st = os.lstat(path)
            except OSError:
                continue
            # Another disk mounted in there is not a temporary file.
            if st.st_uid != uid or st.st_dev != dev or not (
                    stat.S_ISREG(st.st_mode) or stat.S_ISLNK(st.st_mode) or stat.S_ISDIR(st.st_mode)):
                continue
            if max(st.st_atime, st.st_mtime, st.st_ctime) < cutoff:
                out.append((path, stat.S_ISDIR(st.st_mode)))
    return out


# -- caches ----------------------------------------------------------------------------
def cache_sizes():
    sizes = du(CACHE_HOME, depth=1)
    total = sizes.pop(CACHE_HOME, sum(sizes.values()))
    top = sorted(((os.path.basename(p), s) for p, s in sizes.items()), key=lambda x: -x[1])
    return {"dir": CACHE_HOME, "total": total, "thumbnails": dict(top).get("thumbnails", 0),
            "top": [{"name": n, "size": s} for n, s in top[:TOP]]}


def holders(path):
    """Names of your running programs with a file, or their working folder,
    inside `path` (from /proc: only your own processes are readable)."""
    path = os.path.realpath(path).rstrip("/") + "/"
    names = set()
    for pid in os.listdir("/proc"):
        if not pid.isdigit() or int(pid) == os.getpid():
            continue
        base = f"/proc/{pid}"
        links = []
        try:
            links.append(os.readlink(f"{base}/cwd"))
            links += [os.readlink(f"{base}/fd/{fd}") for fd in os.listdir(f"{base}/fd")]
        except OSError:
            pass
        if any((link + "/").startswith(path) for link in links):
            try:
                with open(f"{base}/comm") as f:
                    names.add(f.read().strip())
            except OSError:
                names.add(pid)
    return sorted(names)


def cache_folder(name):
    """~/.cache/<name>, or None when name is not one plain folder in it."""
    if not name or "/" in name or name in (".", ".."):
        return None
    path = os.path.join(CACHE_HOME, name)
    if os.path.islink(path) or not os.path.isdir(path):
        return None
    return path


def clear_folder(path):
    """Delete what is inside path (the folder itself stays, with its
    permissions). Returns (bytes freed, problems)."""
    before = du(path).get(path, 0)
    problems = []
    for name in os.listdir(path):
        p = os.path.join(path, name)
        try:
            if os.path.isdir(p) and not os.path.islink(p):
                shutil.rmtree(p)
            else:
                os.unlink(p)
        except OSError as exc:
            problems.append(f"{name}: {exc.strerror}")
    return max(0, before - du(path).get(path, 0)), problems


def clear_cache(name):
    path = cache_folder(name)
    if path is None:
        sys.exit(f"No folder called {name!r} in {CACHE_HOME}")
    busy = holders(path)
    if busy:
        sys.exit(f"{', '.join(busy[:4])} {'is' if len(busy) == 1 else 'are'} using ~/.cache/{name}: "
                 "close it and try again")
    freed, problems = clear_folder(path)
    print(f"Freed {human(freed)} from ~/.cache/{name}")
    if problems:
        sys.exit(f"Some files could not be deleted ({len(problems)}): {problems[0]}")


# -- home ------------------------------------------------------------------------------
def home_entries(sizes, home=HOME):
    """du's {path: bytes} for ~ at depth 1 -> (total, [{name, size}] biggest first)."""
    total = sizes.pop(home, None)
    rows = sorted(((os.path.basename(p), s) for p, s in sizes.items() if p != home), key=lambda x: -x[1])
    if total is None:
        total = sum(s for _n, s in rows)
    return total, [{"name": n, "size": s} for n, s in rows[:TOP]]


def read_home_cache():
    try:
        with open(HOME_CACHE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def home(max_age=HOME_MAX_AGE, cached_only=False):
    """The kept answer when it is young enough; otherwise one du (a second
    caller waits for the first one's answer instead of scanning again)."""
    kept = read_home_cache()
    if cached_only or (kept and time.time() - kept.get("time", 0) < max_age):
        return kept
    os.makedirs(os.path.dirname(HOME_CACHE), exist_ok=True)
    with open(HOME_CACHE + ".lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        kept = read_home_cache()
        if kept and time.time() - kept.get("time", 0) < max_age:
            return kept
        started = time.time()
        sizes = du(HOME, depth=1, timeout=1800)
        if not sizes:
            # du was cut off or could not run: say so (None) rather than
            # keep an empty answer that would be shown for the next 6 hours.
            return None
        total, rows = home_entries(sizes)
        data = {"time": int(time.time()), "took": round(time.time() - started), "total": total, "top": rows}
        tmp = HOME_CACHE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f)
        os.replace(tmp, HOME_CACHE)
        return data


# -- the automatic clean-up ------------------------------------------------------------------
def gget(key):
    return run("gsettings", "get", SCHEMA, key).stdout.strip()


def auto_settings():
    days = gget("old-files-age").replace("uint32", "").strip()
    return {"trash": gget("remove-old-trash-files") == "true", "temp": gget("remove-old-temp-files") == "true",
            "days": int(days) if days.isdigit() else 30}


def timer_state():
    out = run("systemctl", "--user", "show", TIMER, "-p", "UnitFileState,ActiveState,NextElapseUSecRealtime").stdout
    props = dict(line.split("=", 1) for line in out.splitlines() if "=" in line)
    return {"enabled": props.get("UnitFileState") == "enabled", "active": props.get("ActiveState") == "active",
            "next": props.get("NextElapseUSecRealtime") or ""}


def want_timer(settings):
    return bool(settings["trash"] or settings["temp"])


def set_auto(what, value):
    """Write the GNOME switch, then turn the timer on or off to match."""
    if what in ("trash", "temp"):
        if value not in ("on", "off"):
            sys.exit("on or off")
        r = run("gsettings", "set", SCHEMA, f"remove-old-{what}-files", "true" if value == "on" else "false")
    elif what == "days":
        if not value.isdigit() or not 1 <= int(value) <= 365:
            sys.exit("days: a number from 1 to 365")
        r = run("gsettings", "set", SCHEMA, "old-files-age", f"uint32 {int(value)}")
    else:
        sys.exit("auto trash|temp|days <value>")
    if r.returncode:
        sys.exit(f"gsettings: {r.stderr.strip() or 'failed'}")
    on = want_timer(auto_settings())
    r = run("systemctl", "--user", "enable" if on else "disable", "--now", TIMER)
    if r.returncode:
        sys.exit(f"systemctl: {(r.stderr.strip().splitlines() or ['failed'])[-1]}")


def cleanup(dry_run=False, now=None):
    s = auto_settings()
    now = now or datetime.datetime.now()
    removed, freed, problems = 0, 0, []

    def gone(path, is_dir=False):
        nonlocal removed, freed
        try:
            size = 0 if is_dir else os.lstat(path).st_size
            if dry_run:
                print(path)
            elif is_dir:
                os.rmdir(path)          # only empties: what was in it went first
            else:
                os.unlink(path)
            removed += 1
            freed += size
        except OSError as exc:
            if not is_dir:              # a folder with something young still in it stays, quietly
                problems.append(f"{path}: {exc.strerror}")

    if s["trash"]:
        for d, _top in trash_dirs([t for f in filesystems() for t in f["targets"]]):
            for info, item in old_trash(d, s["days"], now):
                if os.path.isdir(item) and not os.path.islink(item):
                    # A whole folder was trashed: it goes as one item.
                    size = du(item).get(item, 0)
                    if dry_run:
                        print(item)
                    else:
                        try:
                            shutil.rmtree(item)
                        except OSError as exc:
                            problems.append(f"{item}: {exc.strerror}")
                            continue
                    removed += 1
                    freed += size
                elif os.path.lexists(item):
                    gone(item)
                # The info file goes too, or Files would list an item with nothing behind it.
                if not dry_run:
                    try:
                        os.unlink(info)
                    except OSError:
                        pass
    if s["temp"]:
        for top in temp_dirs():
            for path, is_dir in old_temp(top, s["days"], now.timestamp()):
                gone(path, is_dir)
    result = {"time": int(time.time()), "removed": removed, "freed": freed, "problems": problems[:20],
              "trash": s["trash"], "temp": s["temp"], "days": s["days"], "dry_run": dry_run}
    if not dry_run:
        os.makedirs(os.path.dirname(LAST_RUN), exist_ok=True)
        with open(LAST_RUN, "w") as f:
            json.dump(result, f)
    return result


def last_run():
    try:
        with open(LAST_RUN) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


# -- snapshots --------------------------------------------------------------------------------
def parse_snapper(text, config="root"):
    """snapper --jsonout list -> {count, used} (used None when btrfs quotas
    are off and snapper cannot say)."""
    try:
        rows = [r for r in json.loads(text)[config] if r.get("number") not in (0, None)]
    except (ValueError, KeyError, TypeError):
        return None
    sizes = [r.get("used-space") for r in rows]
    known = [s for s in sizes if isinstance(s, int)]
    return {"count": len(rows), "used": sum(known) if known and len(known) == len(sizes) else None}


def snapshots():
    configs = run("snapper", "--jsonout", "list-configs", timeout=10)
    try:
        names = [c["config"] for c in json.loads(configs.stdout).get("configs", [])]
    except (ValueError, AttributeError, KeyError, TypeError):
        names = []
    if configs.returncode or not names:
        return {"set_up": False, "installed": shutil.which("snapper") is not None}
    out = {"set_up": True, "configs": {}}
    for name in names:
        r = run("snapper", "-c", name, "--jsonout", "list", "--columns", "number,used-space", timeout=20)
        out["configs"][name] = parse_snapper(r.stdout, name) if r.returncode == 0 else None
    return out


# -- reports -------------------------------------------------------------------------------------
def status():
    return {"filesystems": filesystems(), "auto": auto_settings(), "timer": timer_state(),
            "last_run": last_run(), "snapshots": snapshots(), "temp_dirs": temp_dirs()}


def sizes():
    targets = [t for f in filesystems() for t in f["targets"]]
    return {"trash": [dict(trash_info(d), mount=top) for d, top in trash_dirs(targets)],
            "cache": cache_sizes()}


def print_status(s):
    for f in s["filesystems"]:
        print(f"{' and '.join(f['targets'])}\t{f['percent']}%\t{human(f['used'])} of {human(f['size'])}"
              f"\t{human(f['avail'])} free\t{f['fstype']}")
    a = s["auto"]
    print(f"auto clean-up: trash {'on' if a['trash'] else 'off'}, temp {'on' if a['temp'] else 'off'}, "
          f"after {a['days']} days; timer {'on' if s['timer']['enabled'] else 'off'}")


def main(argv):
    cmd = argv[0] if argv else "status"
    as_json = "--json" in argv
    # Asking for help never does anything, and the commands that delete
    # take exactly their own arguments: `empty-trash --help` must not empty.
    if any(a in ("-h", "--help", "help") for a in argv):
        sys.exit(__doc__)
    if (cmd in ("empty-trash", "clear-thumbnails") and len(argv) != 1) or (
            cmd == "clear-cache" and len(argv) != 2):
        sys.exit(f"{cmd}: unexpected arguments {' '.join(argv[1:])!r}\n\n{__doc__}")
    if cmd == "status":
        s = status()
        print(json.dumps(s)) if as_json else print_status(s)
    elif cmd == "sizes":
        s = sizes()
        if as_json:
            print(json.dumps(s))
        else:
            for t in s["trash"]:
                print(f"trash {t['dir']}\t{human(t['size'])}\t{t['items']} items")
            print(f"~/.cache\t{human(s['cache']['total'])}\tthumbnails {human(s['cache']['thumbnails'])}")
    elif cmd == "home":
        age = HOME_MAX_AGE
        if "--max-age" in argv:
            i = argv.index("--max-age")
            age = int(argv[i + 1]) if i + 1 < len(argv) and argv[i + 1].isdigit() else age
        data = home(age, cached_only="--cached" in argv)
        if as_json:
            print(json.dumps(data))
        elif data:
            for r in data["top"]:
                print(f"{human(r['size'])}\t~/{r['name']}")
    elif cmd == "empty-trash":
        r = run("gio", "trash", "--empty", timeout=1800)
        if r.returncode:
            sys.exit(f"gio trash: {r.stderr.strip() or 'failed'}")
        print("Emptied the trash")
    elif cmd == "clear-cache" and len(argv) > 1:
        clear_cache(argv[1])
    elif cmd == "clear-thumbnails":
        clear_cache("thumbnails")
    elif cmd == "auto" and len(argv) > 2:
        set_auto(argv[1], argv[2])
    elif cmd == "cleanup":
        r = cleanup(dry_run="--dry-run" in argv)
        print(f"{'would remove' if r['dry_run'] else 'removed'} {r['removed']}, {human(r['freed'])}")
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
