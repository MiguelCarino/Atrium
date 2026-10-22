#!/usr/bin/env python3
"""Notification bell (custom/notifications) and the data behind the
notification panel.

    notifications.py            one JSON line for waybar
    notifications.py list       history + on-screen ones, newest first, as JSON
    notifications.py dnd        toggle Do Not Disturb, refresh the bell
    notifications.py clear      dismiss what is on screen, hide the history so far

The bell is a bell while notifications pop up, a struck-through bell in Do Not
Disturb (mako's do-not-disturb mode, the same one ALT+SHIFT+D toggles), and
either way it carries the number of UNREAD notifications -- like the count on
the git logo. Unread means newer than the last time the history panel was
opened: mako has no command to empty its history, so counting all of it would
only ever climb to max-history and stay there. mako's ids only grow, so "read"
is one number, the highest id the panel has shown, kept in tmpfs (SEEN).

mako keeps the history in memory only -- it is gone at logout -- and records no
time for an entry, so the panel can show what and from whom, newest first,
but not when.
"""

import json
import os
import subprocess
import sys

SIGNAL = 14
SEEN = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "notifications-seen")
# mako cannot empty its history either, so "Clear" in the panel is the same
# trick: the highest id cleared, and the panel shows only what came after it.
CLEARED = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "notifications-cleared")
ICON_ON = "\uf0f3"         # bell
ICON_DND = "\uf1f6"        # bell-slash


def makoctl(*args):
    try:
        return subprocess.run(["makoctl", *args], capture_output=True, text=True,
                              timeout=3).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def dnd_on():
    return "do-not-disturb" in makoctl("mode").split()


def read_id(path):
    try:
        with open(path) as handle:
            return int(handle.read().strip() or 0)
    except (OSError, ValueError):
        return 0


def clear():
    """Dismiss what is on screen and hide everything up to now from the
    panel and the count. New notifications show up as usual."""
    items = all_entries()
    newest = max((n.get("id", 0) for n in items), default=0)
    makoctl("dismiss", "--all")
    for path in (CLEARED, SEEN):
        if newest > read_id(path):
            with open(path, "w") as handle:
                handle.write(str(newest))
    subprocess.run(["pkill", f"-RTMIN+{SIGNAL}", "-x", "waybar"])


def entries():
    """What the panel lists: everything since the last Clear."""
    cleared = read_id(CLEARED)
    return [n for n in all_entries() if n.get("id", 0) > cleared]


def all_entries():
    out = []
    for source, cmd in (("shown", "list"), ("history", "history")):
        try:
            data = json.loads(makoctl(cmd, "-j") or "[]")
        except ValueError:
            data = []
        for item in data:
            item["source"] = source
            out.append(item)
    # ids only ever grow, so the biggest is the newest.
    return sorted(out, key=lambda n: -n.get("id", 0))


def seen():
    return read_id(SEEN)


def mark_seen(items):
    """The panel calls this when it opens: everything shown is read."""
    newest = max((n.get("id", 0) for n in items), default=0)
    if newest > seen():
        with open(SEEN, "w") as handle:
            handle.write(str(newest))
    subprocess.run(["pkill", f"-RTMIN+{SIGNAL}", "-x", "waybar"])


def bar():
    dnd = dnd_on()
    items = entries()
    count = sum(1 for n in items if n.get("id", 0) > seen())
    tip = (f"{'Do Not Disturb is on -- popups are held back' if dnd else 'Notifications'}"
           f"\n{count} unread, {len(items)} in history"
           "\n\nClick: history (marks them read)   Right-click: Do Not Disturb")
    return {"text": f"{ICON_DND if dnd else ICON_ON}{f' {count}' if count else ''}",
            "tooltip": tip, "class": "dnd" if dnd else "on"}


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "list":
        print(json.dumps(entries()))
    elif cmd == "clear":
        clear()
    elif cmd == "dnd":
        makoctl("mode", "-t", "do-not-disturb")
        subprocess.run(["pkill", f"-RTMIN+{SIGNAL}", "-x", "waybar"])
    else:
        print(json.dumps(bar()))


if __name__ == "__main__":
    main()
