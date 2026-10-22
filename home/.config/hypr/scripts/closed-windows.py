#!/usr/bin/env python3
"""Reopen the last closed window -- Ctrl+Shift+T for apps
(closed-windows.service, and ALT+SHIFT+T in lua/binds.lua).

    closed-windows.py            the service: follow Hyprland's event socket
    closed-windows.py reopen     start the most recently closed window again,
                                 on its workspace, floating / size / position as
                                 it was (then it is off the list)
    closed-windows.py list [--json]   the list, newest first

The service keeps, for every open window, what it would take to start it
again -- sessions.py's capture(), the same rules as a saved session (the
folder of a terminal, the file and second of an mpv, the .desktop entry of
the rest; never a command line with a secret on it) -- refreshed when a
window opens, moves, floats, goes fullscreen or changes title (a `cd`
retitles most terminals), at most every REFRESH_S, and each one at least
every RECAPTURE_S (mpv's position). Hyprland's request socket answers
`clients` in well under a millisecond, so this costs next to nothing.

When a window closes it goes on a stack of the last KEEP, unless it was
transient: a dialog / picker / the bar's panels / a scratchpad (capture()
leaves those out), open for less than MIN_ALIVE_S, a small floating popup,
or a secondary window -- its app still has an older window open (a
browser's second window, a settings dialog): starting the app again would
not bring that one back. Terminals are the exception, each of their
windows is its own.

The stack is $XDG_RUNTIME_DIR/closed-windows.json (gone at logout, as it
should be), written under a lock so `reopen` and the service never clobber
each other. Stopping the service (logout, shutdown) also runs
`sessions.py autosave --exit` (ExecStop in the unit).
"""
import fcntl
import json
import os
import select
import socket
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import desklog  # noqa: E402
import sessions  # noqa: E402  (capture, restore: one way to relaunch a window)

STACK = os.path.join(sessions.RUNTIME, "closed-windows.json")
KEEP = 20
MIN_ALIVE_S = 3
REFRESH_S = 1.5
RECAPTURE_S = 20
POPUP = (220, 120)      # a floating window smaller than this is a popup
DIRTY = {"openwindow", "movewindowv2", "changefloatingmode", "fullscreen", "windowtitlev2",
         "activewindowv2", "pin", "moveworkspacev2"}


# -- the stack -----------------------------------------------------------------------
class Stack:
    """The file, locked for each read-modify-write."""

    def __enter__(self):
        self.lock = open(STACK + ".lock", "w")
        fcntl.flock(self.lock, fcntl.LOCK_EX)
        try:
            with open(STACK) as handle:
                self.items = json.load(handle)
            if not isinstance(self.items, list):
                self.items = []
        except (OSError, ValueError):
            self.items = []
        self.changed = False
        return self

    def __exit__(self, *exc):
        if self.changed:
            sessions.write_json(STACK, self.items[-KEEP:])
        self.lock.close()


# -- the service ---------------------------------------------------------------------
def signature(client):
    return (client.get("title"), (client.get("workspace") or {}).get("name"), tuple(client.get("at") or ()),
            tuple(client.get("size") or ()), client.get("floating"), client.get("fullscreen"),
            client.get("pinned"))


class Tracker:
    """Every open window: {address: {"rec", "why", "opened", "pid", "seq",
    "sig", "at"}} -- what to relaunch it with, or why not."""

    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.windows = {}
        self.seq = 0
        self.dirty = True
        self.last_refresh = 0.0
        self.settings_at = -1e9
        self.settings, self.private = dict(sessions.DEFAULTS), set()

    def opened(self, address):
        """openwindow: note when (the refresh that follows captures it)."""
        self.seq += 1
        self.windows.setdefault(address, {"rec": None, "why": "not seen yet", "pid": None, "sig": None,
                                          "at": -1e9})
        self.windows[address].update(opened=self.clock(), seq=self.seq)
        self.dirty = True

    def refresh(self, clients=None, monitors=None):
        now = self.clock()
        if now - self.settings_at > 60:
            self.settings, self.private = sessions.load_settings(), sessions.private_classes()
            self.settings_at = now
        clients = sessions.hypr_json("clients") if clients is None else clients
        if clients is None:
            return
        monitors = sessions.hypr_json("monitors") if monitors is None else monitors
        index = sessions.desktop_index()
        live = set()
        for client in clients:
            addr = client.get("address")
            if not addr or not client.get("mapped", True):
                continue
            live.add(addr)
            win = self.windows.get(addr)
            if win is None:     # open before the service started: its age is unknown, call it old
                self.seq += 1
                win = self.windows[addr] = {"opened": None, "seq": self.seq, "sig": None, "at": -1e9}
            sig = signature(client)
            if sig != win["sig"] or now - win["at"] > RECAPTURE_S:
                win["rec"], win["why"] = sessions.capture(client, monitors, self.settings, self.private, index)
                win.update(sig=sig, at=now, pid=client.get("pid"), floating=client.get("floating"),
                           size=client.get("size"))
        for addr, win in list(self.windows.items()):
            # Gone without a closewindow yet: its event may be on its way
            # (kept a while for it), or Hyprland restarted.
            if addr not in live and win.get("sig") is not None:
                win.setdefault("gone", now)
                if now - win["gone"] > 10:
                    del self.windows[addr]
        self.last_refresh, self.dirty = now, False

    def closed(self, address):
        """closewindow: the record to push, or None (and why, for the journal)."""
        win = self.windows.pop(address, None)
        if not win:
            return None, "unknown"
        rec = win.get("rec")
        if rec is None:
            return None, win.get("why") or "nothing to start"
        if win.get("opened") is not None and self.clock() - win["opened"] < MIN_ALIVE_S:
            return None, "open only a moment"
        size = win.get("size") or (0, 0)
        if win.get("floating") and (size[0] < POPUP[0] or size[1] < POPUP[1]):
            return None, "a popup"
        if rec["kind"] != "terminal" and any(
                w.get("pid") == win.get("pid") and w.get("seq", 0) < win.get("seq", 0) and "gone" not in w
                for w in self.windows.values()):
            return None, "a secondary window of an app still open"
        rec = dict(rec)
        rec.pop("shared", None)
        return rec, None


def push(rec):
    with Stack() as stack:
        stack.items.append({"closed": int(time.time()), "record": rec})
        stack.items = stack.items[-KEEP:]
        stack.changed = True


def handle(tracker, line):
    name, _, data = line.partition(">>")
    if name == "openwindow":
        tracker.opened("0x" + data.split(",", 1)[0])
    elif name == "closewindow":
        rec, why = tracker.closed("0x" + data.strip())
        if rec:
            push(rec)
            desklog.log("closed-windows", f"closed: {rec['app']} ({rec['kind']}, workspace {rec['workspace']})",
                        "debug")
        else:
            desklog.log("closed-windows", f"not kept: {why}", "debug")
    elif name in DIRTY:
        tracker.dirty = True


def socket2():
    path = sessions.hypr_dir()
    return os.path.join(path, ".socket2.sock") if path else None


def serve():
    tracker = Tracker()
    while True:
        path = socket2()
        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.connect(path or "")
        except OSError:
            time.sleep(2)
            continue
        tracker.windows.clear()
        tracker.refresh()
        buf = b""
        with sock:
            while True:
                wait = max(0.05, REFRESH_S - (tracker.clock() - tracker.last_refresh)) if tracker.dirty \
                    else RECAPTURE_S
                ready, _, _ = select.select([sock], [], [], wait)
                if ready:
                    chunk = sock.recv(65536)
                    if not chunk:
                        break           # Hyprland restarted: reconnect
                    buf += chunk
                    *lines, buf = buf.split(b"\n")
                    for line in lines:
                        handle(tracker, line.decode("utf-8", "replace"))
                if tracker.dirty and tracker.clock() - tracker.last_refresh >= REFRESH_S \
                        or tracker.clock() - tracker.last_refresh >= RECAPTURE_S:
                    tracker.refresh()


# -- the commands --------------------------------------------------------------------
def reopen():
    with Stack() as stack:
        if not stack.items:
            sessions.Notifier()("No closed window to reopen", "")
            return 1
        item = stack.items.pop()
        stack.changed = True
    rec = item["record"]
    result = sessions.restore_records([rec], rec["app"], skip_open=False)
    if not result["placed"]:
        sessions.Notifier()(f"{rec['app']} did not open a window", "it is off the list", "normal")
        return 1
    return 0


def ago(seconds):
    return f"{seconds} s" if seconds < 90 else f"{seconds // 60} min" if seconds < 5400 else f"{seconds // 3600} h"


def main(argv):
    if not argv:
        serve()
    elif argv[0] == "reopen":
        sys.exit(reopen())
    elif argv[0] == "list":
        with Stack() as stack:
            items = list(reversed(stack.items))
        if "--json" in argv:
            print(json.dumps(items))
            return
        now = int(time.time())
        for i, item in enumerate(items, 1):
            rec = item["record"]
            print(f"{i:>2}. {ago(now - item['closed']):>7} ago  ws {rec['workspace']:<4} {rec['app']}"
                  + (f" -- {rec['title'][:60]}" if rec.get("title") else ""))
        if not items:
            print("nothing closed yet")
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
