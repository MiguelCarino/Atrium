#!/usr/bin/env python3
"""Where a notification came from: the window to go to, or the app to open.

Clicking a notification takes you to whoever sent it. The island
(island.py, its "Go to <app>" button and a click on the card) and mako's
own popups (mako/config: on-button-left runs `notify_source.py go $id`)
both ask this file.

How the sender is found, best first:
  1. its process -- the island asks the bus for the caller's pid
     (GetConnectionUnixProcessID) as the call goes by and reads its parents
     from /proc at once (item["pids"]; notify-send is gone a moment later);
     the window whose pid is that process or one of its parents is the one
     (a browser tab's helper process, a script run in a terminal: the
     terminal);
  2. its names -- the app name and the desktop-entry hint against each
     window's class (both as given, and the last part of a reverse-DNS id:
     "org.mozilla.firefox" also matches "firefox"), and against the
     installed app the notification names (its id, StartupWMClass, program
     and Name).
Several windows of the app: the one used most recently.

No window: the installed app is opened instead ("Open <app>"), unless the
notification has its own default action (clicking it already asks the app,
which opens what it needs -- opening the app as well would make two).
Neither: nothing to go to (the desktop's own scripts, notify-send from a
shell...), and the click only does what it always did.

    notify_source.py go ID      mako's popup was clicked: go there, then
                                run its default action or dismiss it
    notify_source.py where ID   what a click would do (for a look)
"""
import json
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# app names that say nothing about who sent it
GENERIC = {"", "notify-send", "notify", "notification", "notifications", "dunstify", "desktop"}
MAX_PARENTS = 64


# -- pure -------------------------------------------------------------------------------------
def norm(name):
    name = str(name or "").strip().lower()
    return name[:-8] if name.endswith(".desktop") else name


def variants(name):
    """A name, its reverse-DNS tail and the two without separators:
    "org.gnome.Nautilus" -> {org.gnome.nautilus, nautilus, orggnomenautilus}."""
    name = norm(name)
    if not name or name in GENERIC:
        return set()
    out = {name, name.rsplit(".", 1)[-1]}
    out |= {"".join(ch for ch in v if ch.isalnum()) for v in list(out)}
    return {v for v in out if v and v not in GENERIC}


def app_keys(app):
    """Every name an installed app goes by (an `installed_apps()` dict)."""
    if not app:
        return set()
    out = set()
    for field in ("id", "wmclass", "exec", "name"):
        out |= variants(app.get(field))
    return out


def item_keys(item):
    return variants(item.get("app")) | variants(item.get("desktop_entry"))


def resolve_app(item, apps):
    """The installed app the notification names: its desktop-entry hint
    exactly, else one whose names include the app name. None: unknown."""
    entry = norm(item.get("desktop_entry"))
    if entry:
        for app in apps:
            if norm(app.get("id")) == entry:
                return app
    keys = item_keys(item)
    if not keys:
        return None
    hits = [app for app in apps if app_keys(app) & keys]
    hits.sort(key=lambda a: (bool(a.get("hidden")), norm(a.get("id"))))
    return hits[0] if hits else None


def window_keys(client):
    return variants(client.get("class")) | variants(client.get("initialClass"))


def ancestors(pid, ppid_of, limit=MAX_PARENTS):
    """pid, its parent, theirs ... up to (not including) pid 1."""
    out = []
    while isinstance(pid, int) and pid > 1 and pid not in out and len(out) < limit:
        out.append(pid)
        pid = ppid_of(pid)
    return out


def _recent(clients):
    """Most recently focused first (focusHistoryID 0 is the focused one)."""
    return sorted(clients, key=lambda c: c.get("focusHistoryID", 1 << 30)
                  if c.get("focusHistoryID", -1) >= 0 else 1 << 30)


def find_window(item, clients, app=None, ppid_of=None):
    """The window the notification came from, or None."""
    clients = [c for c in clients or [] if c.get("address") and c.get("mapped", True)]
    chain = list(item.get("pids") or [])
    if not chain and item.get("pid") and ppid_of is not None:
        chain = ancestors(item["pid"], ppid_of)
    if chain:
        for pid in chain:
            own = [c for c in clients if c.get("pid") == pid]
            if own:
                return _recent(own)[0]
    keys = item_keys(item) | app_keys(app)
    if not keys:
        return None
    named = [c for c in clients if window_keys(c) & keys]
    return _recent(named)[0] if named else None


def has_default(item):
    return any(key == "default" for key, _label in item.get("actions") or [])


def target(item, clients, apps, ppid_of=None):
    """What a click on the notification leads to:
        {"kind": "window", "address": ..., "label": "Firefox"}
        {"kind": "launch", "app_id": "org.mozilla.firefox.desktop", "label": ...}
    or None. "launch" only when the notification has no default action of
    its own (see the docstring at the top)."""
    app = resolve_app(item, apps)
    win = find_window(item, clients, app, ppid_of)
    if win is not None:
        own = item.get("app") if norm(item.get("app")) not in GENERIC else ""
        label = (app or {}).get("name") or own or win.get("class") or "the window"
        return {"kind": "window", "address": win["address"], "label": str(label)}
    if app is not None and not app.get("hidden") and not has_default(item):
        return {"kind": "launch", "app_id": app["id"], "label": str(app.get("name") or app["id"])}
    return None


def button_label(tgt, limit=18):
    """The card's button: "Go to Firefox" / "Open Firefox"."""
    if not tgt:
        return ""
    name = tgt["label"] if len(tgt["label"]) <= limit else tgt["label"][:limit - 1] + "…"
    return ("Go to " if tgt["kind"] == "window" else "Open ") + name


# -- the system -------------------------------------------------------------------------------
def ppid_of(pid):
    """The parent's pid from /proc, or 0."""
    try:
        with open(f"/proc/{pid}/stat") as fh:
            stat = fh.read()
        return int(stat[stat.rindex(")") + 2:].split()[1])
    except (OSError, ValueError, IndexError):
        return 0


_APPS = (None, 0.0)
APPS_TTL = 600                # s: an app installed meanwhile is found within this


def installed_apps():
    """The installed apps (Gio's list of .desktop files), cached for
    APPS_TTL: [{id, name, wmclass, exec, hidden}]."""
    global _APPS
    now = time.monotonic()
    if _APPS[0] is not None and now - _APPS[1] < APPS_TTL:
        return _APPS[0]
    apps = []
    try:
        import gi
        gi.require_version("Gio", "2.0")
        from gi.repository import Gio
        for info in Gio.AppInfo.get_all():
            if not hasattr(info, "get_startup_wm_class"):       # not a .desktop file
                continue
            exe = os.path.basename(info.get_executable() or "")
            if exe in ("env", "flatpak", "sh", "bash"):
                exe = ""
            apps.append({"id": info.get_id() or "", "name": info.get_name() or "",
                         "wmclass": info.get_startup_wm_class() or "", "exec": exe,
                         "hidden": not info.should_show()})
    except (ImportError, ValueError):
        pass
    _APPS = (apps, now)
    return apps


def clients():
    import desk_common
    return desk_common.hypr_request("clients", json=True) or []


def go_argv(tgt):
    """The command that focuses the window (its workspace comes along) or
    opens the app, or None."""
    if not tgt:
        return None
    if tgt["kind"] == "window":
        addr = tgt.get("address") or ""
        if not (addr.startswith("0x") and len(addr) > 2
                and all(c in "0123456789abcdefABCDEF" for c in addr[2:])):
            return None
        return ["hyprctl", "dispatch", f"hl.dsp.focus({{ window = 'address:{addr}' }})"]
    if shutil.which("uwsm"):
        return ["uwsm", "app", "--", tgt["app_id"]]
    return ["gtk-launch", tgt["app_id"]]


def go(tgt):
    """Run go_argv() and leave it running; True when it started."""
    argv = go_argv(tgt)
    if not argv:
        return False
    try:
        subprocess.Popen(argv, start_new_session=True, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except OSError:
        return False


def mako_item(nid):
    """The notification `makoctl list -j` has under that id, as an
    island_notify item, or None."""
    import island_notify
    try:
        out = subprocess.run(["makoctl", "list", "-j"], capture_output=True, text=True, timeout=3).stdout
        listed = json.loads(out or "[]")
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    if isinstance(listed, dict):              # older makoctl: {"data": [[...]]}
        listed = [_flatten(e) for e in (listed.get("data") or [[]])[0]]
    for entry in listed:
        if str(entry.get("id")) == str(nid):
            return island_notify.from_mako(entry)
    return None


def _flatten(entry):
    return {k.replace("-", "_"): (v.get("data") if isinstance(v, dict) and "data" in v else v)
            for k, v in entry.items()}


def main(argv):
    if len(argv) != 2 or argv[0] not in ("go", "where") or not argv[1].isdigit():
        print(__doc__.split("\n\n")[-1].rstrip(), file=sys.stderr)
        return 2
    cmd, nid = argv
    item = mako_item(nid)
    if item is None:
        print(f"notify_source: no notification {nid}", file=sys.stderr)
        return 1
    tgt = target(item, clients(), installed_apps())
    if cmd == "where":
        print(json.dumps({"app": item.get("app"), "target": tgt, "button": button_label(tgt)}))
        return 0
    go(tgt)
    # what clicking the popup did before: the default action, else close it
    action = ["invoke", "-n", nid, "default"] if has_default(item) else ["dismiss", "-n", nid]
    subprocess.run(["makoctl", *action], timeout=5, capture_output=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
