#!/usr/bin/env python3
"""Safe mode for the Hyprland config (hypr-guard.service).

After every config load it asks Hyprland for errors (`hyprctl configerrors`):

  * none   -> this config is "last working": hyprland.lua, lua/*.lua and the
             *.conf files next to it are copied to $XDG_STATE_HOME/hypr/
             last-good/
  * errors -> a critical toast with the first error and two buttons:
             "Restore last working" and "Show errors". At login (the first
             load this service sees) it restores by itself instead: a
             desktop that came up broken should not wait for a click.

A restore never loses your edit: the files it replaces are moved to
~/.config/hypr/broken-<date-time>/ first, then last-good is copied back and
Hyprland reloads.

    hypr-guard.py daemon     the service
    hypr-guard.py check      errors now (exit 1 when there are some)
    hypr-guard.py restore    restore last-good now
    hypr-guard.py save       mark the current config as last working
"""
import datetime
import filecmp
import glob
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time

HYPR = os.path.expanduser("~/.config/hypr")
GOOD = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"),
                    "hypr", "last-good")


def config_files():
    """Paths relative to HYPR that make up the config."""
    names = ["hyprland.lua"] + [os.path.relpath(p, HYPR) for p in glob.glob(os.path.join(HYPR, "lua", "*.lua"))]
    names += [os.path.relpath(p, HYPR) for p in glob.glob(os.path.join(HYPR, "*.conf"))]
    return sorted(n for n in names if os.path.isfile(os.path.join(HYPR, n)))


def errors():
    try:
        out = subprocess.run(["hyprctl", "configerrors", "-j"], capture_output=True, text=True, timeout=5).stdout
        return [e for e in json.loads(out or "[]") if e.strip()]
    except (OSError, subprocess.SubprocessError, ValueError):
        return []


def save():
    tmp = GOOD + ".tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    for name in config_files():
        os.makedirs(os.path.dirname(os.path.join(tmp, name)), exist_ok=True)
        shutil.copy2(os.path.join(HYPR, name), os.path.join(tmp, name))
    shutil.rmtree(GOOD, ignore_errors=True)
    os.replace(tmp, GOOD)


def restore():
    """Move the differing files aside, put last-good back, reload. Returns
    the broken-* folder (None if nothing differed or there is no last-good)."""
    if not os.path.isdir(GOOD):
        return None
    good = sorted(os.path.relpath(p, GOOD) for p in glob.glob(os.path.join(GOOD, "**", "*"), recursive=True)
                  if os.path.isfile(p))
    current = config_files()
    changed = [n for n in sorted(set(good) | set(current))
               if not (n in good and n in current and filecmp.cmp(os.path.join(GOOD, n), os.path.join(HYPR, n),
                                                                  shallow=False))]
    if not changed:
        return None
    aside = os.path.join(HYPR, "broken-" + datetime.datetime.now().strftime("%Y%m%d-%H%M%S"))
    for name in changed:
        src = os.path.join(HYPR, name)
        if os.path.exists(src):
            os.makedirs(os.path.dirname(os.path.join(aside, name)), exist_ok=True)
            shutil.move(src, os.path.join(aside, name))
        if name in good:
            os.makedirs(os.path.dirname(src), exist_ok=True)
            shutil.copy2(os.path.join(GOOD, name), src)
    subprocess.run(["hyprctl", "reload"], capture_output=True, timeout=10)
    return aside


def notify(title, body, actions=(), urgency="critical"):
    cmd = ["notify-send", "-a", "Hyprland config", "-u", urgency, "-i", "dialog-warning", title, body]
    if actions:
        cmd[1:1] = ["--wait"] + [f"--action={k}={v}" for k, v in actions]
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=3600).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def restored_toast(aside):
    notify("Config restored to the last working one",
           f"Your edited files are in {os.path.relpath(aside, os.path.expanduser('~'))}/ -- "
           "fix them there and copy them back.", urgency="normal")


class Guard:
    def __init__(self):
        self.first = True
        self.asking = False

    def loaded(self):
        time.sleep(0.5)                 # let Hyprland finish collecting errors
        errs = errors()
        first, self.first = self.first, False
        if not errs:
            save()
            return
        if first and os.path.isdir(GOOD):
            aside = restore()
            if aside:
                restored_toast(aside)
                return
        if self.asking:
            return
        self.asking = True
        threading.Thread(target=self.ask, args=(errs,), daemon=True).start()

    def ask(self, errs):
        try:
            pick = notify(f"Hyprland config has {len(errs)} error{'s' if len(errs) != 1 else ''}",
                          errs[0][:300], (("restore", "Restore last working"), ("show", "Show errors")))
            if pick == "restore":
                aside = restore()
                if aside:
                    restored_toast(aside)
            elif pick == "show":
                subprocess.Popen(["kitty", "--hold", "--title", "Hyprland config errors", "sh", "-c",
                                  "hyprctl configerrors"], start_new_session=True)
        finally:
            self.asking = False


def socket_path():
    sig = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")
    base = os.path.join(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"), "hypr")
    if not sig:
        try:
            sig = sorted(os.listdir(base))[-1]
        except (OSError, IndexError):
            return None
    return os.path.join(base, sig, ".socket2.sock")


def daemon():
    guard = Guard()
    guard.loaded()                      # the load that happened at login
    while True:
        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.connect(socket_path())
        except (OSError, TypeError):
            time.sleep(2)
            continue
        buf = b""
        with sock:
            while True:
                chunk = sock.recv(65536)
                if not chunk:
                    break
                buf += chunk
                *lines, buf = buf.split(b"\n")
                if any(line.startswith(b"configreloaded>>") for line in lines):
                    guard.loaded()


def main(argv):
    cmd = argv[0] if argv else "check"
    if cmd == "daemon":
        daemon()
    elif cmd == "check":
        errs = errors()
        print("\n".join(errs) if errs else "no errors")
        sys.exit(1 if errs else 0)
    elif cmd == "restore":
        aside = restore()
        print(f"restored; your files are in {aside}" if aside else "nothing to restore")
    elif cmd == "save":
        save()
        print(f"saved to {GOOD}")
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
