#!/usr/bin/env python3
"""A log of which window had the focus, for "what was I working on
yesterday at 3pm" (ask-desktop.py) -- activity-log.service.

Follows Hyprland's event socket: activewindow (class, title -- also sent when
the focused window's title changes), workspace / focusedmon (where the focus
is). One JSON line per change of focus, to $XDG_STATE_HOME/hypr/activity.jsonl:

    {"t": epoch, "class": ..., "title": ..., "workspace": ..., "monitor": ...}

A line lasts until the next one, so a period's length is the gap to the next
line. Nothing focused (an empty workspace, the screen locked) is a line with
class "" so it ends the period before it.

Private windows are written as class "private" with no title -- the time is
kept, what was in them is not: KeePassXC, and any title saying "Private
Browsing" / "Incognito" / "InPrivate".

Apps you add in Settings > Privacy (privacy.conf activity_exclude, see
privacy_settings.py) are private the same way; the list is re-read whenever
the file changes, no restart needed.

Lines older than the kept days (privacy.conf activity_keep_days, default 30)
are pruned at the start and every PRUNE_S.

    activity-log.py                   the service: follow the focus
    activity-log.py info [--json]     how much is logged: entries, since when,
                                      size (never what is in them)
    activity-log.py prune             drop what is older than the kept days now
    activity-log.py forget hour|day|all
                                      drop the last hour / the last 24 hours /
                                      everything. A gap line ends the period
                                      that was running at the cut, so it does
                                      not stretch over the forgotten time; the
                                      service is then told (SIGUSR1) to note
                                      the window focused now afresh.
    activity-log.py hide <class>      make that app's past lines private too
"""
import json
import os
import re
import select
import signal
import socket
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import privacy_settings  # noqa: E402  (privacy.conf: kept days, private apps)

STATE = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"),
                     "hypr", "activity.jsonl")
PRUNE_S = 6 * 3600
PRIVATE_CLASS = re.compile(r"keepassxc", re.I)
PRIVATE_TITLE = re.compile(r"private browsing|incognito|inprivate", re.I)
FORGET_S = {"hour": 3600, "day": 86400}
UNIT = "activity-log.service"


def socket_path():
    sig = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")
    base = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/run/user/%d" % os.getuid()), "hypr")
    if not sig:
        try:
            sig = sorted(os.listdir(base))[-1]
        except (OSError, IndexError):
            return None
    return os.path.join(base, sig, ".socket2.sock")


def is_private(cls, title, exclude=()):
    """Is this window private: KeePassXC, a private-browsing title, or a
    class the user listed (lower-case, exact)?"""
    return bool(PRIVATE_CLASS.search(cls) or PRIVATE_TITLE.search(title) or cls.lower() in exclude)


def read_lines():
    try:
        with open(STATE) as handle:
            return handle.readlines()
    except OSError:
        return None


def write_lines(lines):
    tmp = STATE + ".tmp"
    with open(tmp, "w") as handle:
        handle.writelines(lines)
    os.replace(tmp, STATE)


def line_time(line):
    try:
        return json.loads(line)["t"]
    except (ValueError, KeyError, TypeError):
        return None


def prune():
    lines = read_lines()
    if lines is None:
        return
    cutoff = time.time() - privacy_settings.keep_days(privacy_settings.load()) * 86400
    keep = [line for line in lines if (line_time(line) or 0) >= cutoff]
    if len(keep) != len(lines):
        write_lines(keep)


def forget_lines(lines, cutoff):
    """The lines to keep when forgetting everything from `cutoff` on: those
    before it, plus a gap line at the cut when the last kept one is a
    window (so its period ends there instead of running over the gap)."""
    keep = [line for line in lines if (line_time(line) or cutoff) < cutoff]
    if keep:
        try:
            last = json.loads(keep[-1])
        except ValueError:
            last = {}
        if last.get("class"):
            keep.append(json.dumps({"t": round(cutoff, 1), "class": "", "title": "",
                                    "workspace": last.get("workspace", ""), "monitor": last.get("monitor", "")})
                        + "\n")
    return keep


def hide_lines(lines, cls):
    """The lines with every period of window class `cls` made private."""
    out = []
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if (row.get("class") or "").lower() == cls:
            row.update({"class": "private", "title": ""})
            line = json.dumps(row, ensure_ascii=False) + "\n"
        out.append(line)
    return out


def forget(span):
    if span == "all":
        for path in (STATE, STATE + ".tmp"):
            try:
                os.unlink(path)
            except FileNotFoundError:
                pass
    else:
        lines = read_lines()
        if lines:
            write_lines(forget_lines(lines, time.time() - FORGET_S[span]))
    subprocess.run(["systemctl", "--user", "kill", "-s", "USR1", "--kill-whom=main", UNIT],
                   capture_output=True, timeout=10)


def info():
    lines = read_lines() or []
    times = [t for t in map(line_time, lines) if t is not None]
    try:
        size = os.path.getsize(STATE)
    except OSError:
        size = 0
    return {"path": STATE, "entries": len(times), "since": min(times) if times else None,
            "bytes": size}


class Log:
    def __init__(self):
        self.last = None
        self.workspace = ""
        self.monitor = ""

    def write(self, cls, title):
        if is_private(cls, title, privacy_settings.excluded(privacy_settings.load())):
            cls, title = "private", ""
        if (cls, title) == self.last:
            return
        self.last = (cls, title)
        os.makedirs(os.path.dirname(STATE), exist_ok=True)
        with open(STATE, "a") as handle:
            handle.write(json.dumps({"t": round(time.time(), 1), "class": cls, "title": title,
                                     "workspace": self.workspace, "monitor": self.monitor},
                                    ensure_ascii=False) + "\n")

    def event(self, line):
        name, _, data = line.partition(">>")
        if name == "activewindow":
            cls, _, title = data.partition(",")      # the title may hold commas, the class not
            self.write(cls, title)
        elif name == "workspace":
            self.workspace = data
        elif name == "focusedmon":
            self.monitor, _, self.workspace = data.partition(",")


def seed(log):
    """What has the focus right now, so a fresh start has a line too."""
    try:
        out = subprocess.run(["hyprctl", "activewindow", "-j"], capture_output=True, text=True,
                             timeout=3).stdout
        win = json.loads(out or "{}")
    except (OSError, subprocess.SubprocessError, ValueError):
        return
    log.workspace = str((win.get("workspace") or {}).get("name", ""))
    log.write(win.get("class", ""), win.get("title", ""))


def main():
    path = socket_path()
    if not path:
        sys.exit("activity-log: cannot locate Hyprland's event socket")
    prune()
    log = Log()

    def fresh(_sig, _frame):
        # After a "forget": the window focused now gets a line of its own,
        # even if it is the one that had the focus before the cut.
        log.last = None
        seed(log)
    signal.signal(signal.SIGUSR1, fresh)
    next_prune = time.monotonic() + PRUNE_S
    while True:
        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.connect(path)
        except OSError:
            time.sleep(2)
            continue
        buf = b""
        seed(log)
        with sock:
            while True:
                ready, _, _ = select.select([sock], [], [], 600)
                if ready:
                    chunk = sock.recv(65536)
                    if not chunk:
                        break           # Hyprland restarted: reconnect
                    buf += chunk
                    *lines, buf = buf.split(b"\n")
                    for line in lines:
                        log.event(line.decode("utf-8", "replace"))
                if time.monotonic() >= next_prune:
                    next_prune = time.monotonic() + PRUNE_S
                    prune()


def cli(argv):
    cmd = argv[0]
    if cmd == "info":
        data = info()
        if "--json" in argv:
            print(json.dumps(data))
        else:
            since = time.strftime("%Y-%m-%d %H:%M", time.localtime(data["since"])) if data["since"] else "-"
            print(f"{data['entries']} entries since {since}, {data['bytes'] // 1024} KiB  ({data['path']})")
    elif cmd == "prune":
        prune()
    elif cmd == "forget" and len(argv) == 2 and argv[1] in ("hour", "day", "all"):
        forget(argv[1])
    elif cmd == "hide" and len(argv) == 2 and privacy_settings.clean_class(argv[1]):
        lines = read_lines()
        if lines:
            write_lines(hide_lines(lines, privacy_settings.clean_class(argv[1])))
    else:
        sys.exit("activity-log: info [--json] | prune | forget hour|day|all | hide <class>")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        cli(sys.argv[1:])
    else:
        main()
