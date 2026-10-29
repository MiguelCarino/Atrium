#!/usr/bin/env python3
"""The window switcher's options (window-switcher.py, SUPER+W): which
windows it lists, in what order, and how long the list is. Settings >
Windows > Window switcher writes them; the switcher reads them each time it
opens.

    switcher_conf.py status [--json]   the options in force, their defaults,
                                       and whether window-switcher.py reads them
    switcher_conf.py set KEY VALUE
    switcher_conf.py reset KEY

The keys ($XDG_STATE_HOME/hypr/switcher.conf, key=value; missing = default):

    scope    all | workspace | monitor   every window (the default), the
                                         focused workspace's, or the
                                         focused screen's
    order    recent | workspace          most recently focused first (the
                                         default: Enter on the top one is
                                         "go back"), or by workspace number
    special  on | off                    list scratchpad windows (special
                                         workspaces) too (default on)
    lines    10 | 15 | 20 | 25           rows shown before it scrolls

No GTK here: the switcher imports arrange() and lines() and stays quick.
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
STATE_DIR = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"), "hypr")
CONF = os.path.join(STATE_DIR, "switcher.conf")
SWITCHER = os.path.join(HERE, "window-switcher.py")
KEYS = {
    "scope": ("all", ("all", "workspace", "monitor")),
    "order": ("recent", ("recent", "workspace")),
    "special": ("on", ("on", "off")),
    "lines": ("15", ("10", "15", "20", "25")),
}


def read_conf(path=None):
    """{key: value} for every key: the file's when valid, else the default."""
    out = {k: d for k, (d, _c) in KEYS.items()}
    try:
        with open(path or CONF) as handle:
            for line in handle:
                m = re.match(r"^\s*(\w+)\s*=\s*(.*?)\s*$", line)
                if m and m[1] in KEYS and m[2] in KEYS[m[1]][1]:
                    out[m[1]] = m[2]
    except OSError:
        pass
    return out


def write_conf(values, path=None):
    path = path or CONF
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w") as handle:
        handle.write("# Window switcher (switcher_conf.py; Settings > Windows). Missing = default.\n")
        for key in KEYS:
            if key in values and values[key] != KEYS[key][0]:
                handle.write(f"{key}={values[key]}\n")
    os.replace(tmp, path)


def check(key, value):
    if key not in KEYS:
        raise ValueError(f"no setting {key!r} (have: {', '.join(KEYS)})")
    if value not in KEYS[key][1]:
        raise ValueError(f"{key} is one of {', '.join(KEYS[key][1])}, not {value!r}")
    return value


def _ws_number(c):
    ws = c.get("workspace") or {}
    n = ws.get("id")
    return n if isinstance(n, int) and n > 0 else 10 ** 6 + abs(n or 0)


def arrange(clients, conf=None, workspace_id=None, monitor_id=None):
    """`hyprctl clients -j` -> the windows the switcher lists, in order.
    workspace_id / monitor_id: the focused ones (for scope)."""
    conf = conf or read_conf()
    out = [c for c in clients if c.get("mapped", True)]
    if conf["special"] == "off":
        out = [c for c in out if not str((c.get("workspace") or {}).get("name", "")).startswith("special:")]
    if conf["scope"] == "workspace" and workspace_id is not None:
        out = [c for c in out if (c.get("workspace") or {}).get("id") == workspace_id]
    elif conf["scope"] == "monitor" and monitor_id is not None:
        out = [c for c in out if c.get("monitor") == monitor_id]
    if conf["order"] == "workspace":
        out.sort(key=lambda c: (_ws_number(c), c.get("focusHistoryID", 0)))
    else:
        out.sort(key=lambda c: c.get("focusHistoryID", 0))
    return out


def lines(conf=None):
    return int((conf or read_conf())["lines"])


def wired(path=SWITCHER):
    """Does window-switcher.py read these options yet?"""
    try:
        with open(path) as handle:
            return "switcher_conf" in handle.read()
    except OSError:
        return False


def main(argv):
    cmd = argv[0] if argv else "status"
    if cmd == "status":
        data = {"values": read_conf(), "defaults": {k: d for k, (d, _c) in KEYS.items()},
                "choices": {k: list(c) for k, (_d, c) in KEYS.items()}, "wired": wired(), "conf": CONF}
        print(json.dumps(data) if "--json" in argv else "\n".join(f"{k}={v}" for k, v in data["values"].items()))
    elif cmd == "set" and len(argv) == 3:
        try:
            value = check(argv[1], argv[2])
        except ValueError as exc:
            sys.exit(f"switcher_conf.py: {exc}")
        conf = read_conf()
        conf[argv[1]] = value
        write_conf(conf)
        print(f"{argv[1]}={value}")
    elif cmd == "reset" and len(argv) == 2 and argv[1] in KEYS:
        conf = read_conf()
        conf[argv[1]] = KEYS[argv[1]][0]
        write_conf(conf)
        print(f"{argv[1]}={KEYS[argv[1]][0]}")
    else:
        sys.exit(__doc__.strip())


if __name__ == "__main__":
    main(sys.argv[1:])
