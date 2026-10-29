#!/usr/bin/env python3
"""On-screen keyboard: show or hide one, for a touch screen, a tablet mode
or a hand that cannot type on the real keyboard.

    osk.py toggle              show it, or hide it if it is up
    osk.py show | hide
    osk.py status [--json]     which keyboard, installed or not, up or not,
                               the settings (for Settings > Accessibility)
    osk.py set auto on|off     squeekboard only: come up by itself when a text
                               field is focused (GNOME's screen-keyboard
                               setting, which squeekboard follows)
    osk.py set prefer auto|wvkbd|squeekboard

Two keyboards are known, whichever is installed (both: wvkbd, unless
prefer= says otherwise):

  wvkbd (wvkbd-mobintl, the "mobile international" layout; plain wvkbd too)
      a small layer-shell keyboard made for wlroots compositors. Started
      hidden once (--hidden) and then shown and hidden with its own signals:
      SIGUSR2 shows, SIGUSR1 hides -- no restart, no flicker. Only the
      process this script started is signalled (its pid in
      $XDG_RUNTIME_DIR/osk.pid, checked against /proc/<pid>/comm).
  squeekboard
      GNOME's / Phosh's keyboard. It answers on the session bus (sm.puri.OSK0:
      SetVisible, the Visible property); this starts it in the background
      when it is not running. It can also come up by itself when a text field
      is focused -- `set auto on`.

Neither installed: status says so (and the package names), toggle tells
you once with a notification instead of failing silently.

Settings: $XDG_STATE_HOME/hypr/osk.conf (prefer=, auto=). The key is
whatever lua/binds.lua binds with the description "... On-screen keyboard"
(SUPER+CTRL+K is the one meant for it); status reports it as "key".
"""
import json
import os
import shutil
import signal
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
RUNTIME = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
PID_FILE = os.path.join(RUNTIME, "osk.pid")
STATE_DIR = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"), "hypr")
CONF = os.path.join(STATE_DIR, "osk.conf")
NOTIFY = os.path.join(HERE, "notify")
WVKBD = ("wvkbd-mobintl", "wvkbd")          # the binaries, best first
PACKAGES = {"wvkbd": "wvkbd", "squeekboard": "squeekboard"}
DEFAULTS = {"prefer": "auto", "auto": "off"}
CHOICES = {"prefer": ("auto", "wvkbd", "squeekboard"), "auto": ("on", "off")}
SQ_BUS = ("sm.puri.OSK0", "/sm/puri/OSK0", "sm.puri.OSK0")
A11Y_SCHEMA = ("org.gnome.desktop.a11y.applications", "screen-keyboard-enabled")


# -- settings ----------------------------------------------------------------------------
def read_conf(path=None):
    out = dict(DEFAULTS)
    try:
        with open(path or CONF) as handle:
            for line in handle:
                key, sep, value = line.strip().partition("=")
                key, value = key.strip(), value.strip()
                if sep and key in CHOICES and value in CHOICES[key]:
                    out[key] = value
    except OSError:
        pass
    return out


def write_conf(values, path=None):
    path = path or CONF
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w") as handle:
        handle.write("# On-screen keyboard (osk.py). Missing = default.\n")
        for key in DEFAULTS:
            handle.write(f"{key}={values.get(key, DEFAULTS[key])}\n")
    os.replace(tmp, path)


def check(key, value):
    """The value to store, or ValueError with why."""
    if key not in CHOICES:
        raise ValueError(f"no setting {key!r} (have: {', '.join(CHOICES)})")
    if value not in CHOICES[key]:
        raise ValueError(f"{key} is one of {', '.join(CHOICES[key])}, not {value!r}")
    return value


# -- which keyboard ----------------------------------------------------------------------
def installed(which=shutil.which):
    """{"wvkbd": binary or None, "squeekboard": binary or None}."""
    return {"wvkbd": next((b for b in WVKBD if which(b)), None),
            "squeekboard": "squeekboard" if which("squeekboard") else None}


def pick(have, prefer="auto"):
    """The keyboard to use: the preferred one when it is installed, else
    wvkbd, else squeekboard, else None."""
    if prefer in have and have[prefer]:
        return prefer
    for name in ("wvkbd", "squeekboard"):
        if have.get(name):
            return name
    return None


def missing_text(have):
    """'' when one is installed, else what to install (in words)."""
    if any(have.values()):
        return ""
    return ("No on-screen keyboard is installed: install wvkbd (small, made for this kind of "
            "desktop) or squeekboard (GNOME's)")


# -- wvkbd -------------------------------------------------------------------------------
def _read(path):
    try:
        with open(path) as handle:
            return handle.read()
    except OSError:
        return ""


def wvkbd_pid(pidfile=PID_FILE, proc="/proc"):
    """The pid of the wvkbd this script started, when it still runs."""
    try:
        pid = int(_read(pidfile).split()[0])
    except (IndexError, ValueError):
        return None
    comm = _read(f"{proc}/{pid}/comm").strip()
    return pid if comm.startswith("wvkbd") else None


def wvkbd_shown(pidfile=PID_FILE):
    """Shown or not, as this script last left it (wvkbd has no query)."""
    parts = _read(pidfile).split()
    return len(parts) > 1 and parts[1] == "shown"


def wvkbd_mark(pid, shown, pidfile=PID_FILE):
    os.makedirs(os.path.dirname(pidfile), exist_ok=True)
    with open(pidfile, "w") as handle:
        handle.write(f"{pid} {'shown' if shown else 'hidden'}\n")


def wvkbd_start(binary, hidden=True):
    """Start wvkbd detached (hidden: it waits for SIGUSR2). Its pid."""
    argv = [binary, "-L", "300"] + (["--hidden"] if hidden else [])
    p = subprocess.Popen(argv, start_new_session=True, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return p.pid


def wvkbd_set(binary, show, kill=os.kill):
    pid = wvkbd_pid()
    if pid is None:
        if not show:
            return False
        pid = wvkbd_start(binary, hidden=False)
        wvkbd_mark(pid, True)
        return True
    try:
        kill(pid, signal.SIGUSR2 if show else signal.SIGUSR1)
    except OSError:                     # it quit between the check and now
        if not show:
            return False
        pid = wvkbd_start(binary, hidden=False)
    wvkbd_mark(pid, show)
    return show


# -- squeekboard -------------------------------------------------------------------------
def gdbus(*args, timeout=3):
    try:
        r = subprocess.run(["gdbus", *args], capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout if r.returncode == 0 else None


def parse_visible(out):
    """gdbus' answer to the Visible property -> True / False / None."""
    if not out:
        return None
    if "true" in out:
        return True
    if "false" in out:
        return False
    return None


def sq_visible():
    name, path, iface = SQ_BUS
    return parse_visible(gdbus("call", "--session", "--dest", name, "--object-path", path,
                               "--method", "org.freedesktop.DBus.Properties.Get", iface, "Visible"))


def sq_set(show):
    name, path, iface = SQ_BUS
    if sq_visible() is None:            # not running (or not answering)
        if not show:
            return False                # nothing up to hide: do not start one
        subprocess.Popen(["squeekboard"], start_new_session=True, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(20):
            time.sleep(0.15)
            if sq_visible() is not None:
                break
    gdbus("call", "--session", "--dest", name, "--object-path", path,
          "--method", f"{iface}.SetVisible", "true" if show else "false")
    return show


def sq_auto(on):
    """squeekboard comes up for text fields when GNOME's screen-keyboard
    setting is on; gsettings may be missing (then nothing changes)."""
    schema, key = A11Y_SCHEMA
    try:
        subprocess.run(["gsettings", "set", schema, key, "true" if on else "false"],
                       capture_output=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        pass


# -- the key ---------------------------------------------------------------------------
MOD_BITS = (("SUPER", 64), ("CTRL", 4), ("ALT", 8), ("SHIFT", 1))


def bound_key(binds):
    """The key that toggles the keyboard, "SUPER+CTRL+K", from `hyprctl
    binds -j` (found by its description, since a Lua bind's arg is only an
    index); "" while lua/binds.lua has none."""
    for b in binds or []:
        if not isinstance(b, dict) or b.get("submap"):
            continue
        if "on-screen keyboard" in str(b.get("description", "")).lower():
            mask = int(b.get("modmask", 0) or 0)
            mods = [name for name, bit in MOD_BITS if mask & bit]
            return "+".join(mods + [str(b.get("key", "")).upper()])
    return ""


def live_bound_key():
    try:
        r = subprocess.run(["hyprctl", "binds", "-j"], capture_output=True, text=True, timeout=3)
        return bound_key(json.loads(r.stdout or "[]"))
    except (OSError, subprocess.SubprocessError, ValueError):
        return ""


# -- the commands ------------------------------------------------------------------------
def shown(kind):
    if kind == "wvkbd":
        return wvkbd_pid() is not None and wvkbd_shown()
    if kind == "squeekboard":
        return bool(sq_visible())
    return False


def set_shown(show):
    conf = read_conf()
    have = installed()
    kind = pick(have, conf["prefer"])
    if kind is None:
        try:
            subprocess.run([NOTIFY, "-a", "On-screen keyboard", "No on-screen keyboard installed",
                            "Install wvkbd or squeekboard (Settings > Accessibility says more)."],
                           timeout=5)
        except (OSError, subprocess.SubprocessError):
            pass
        sys.exit("osk.py: " + missing_text(have))
    if kind == "wvkbd":
        return wvkbd_set(have["wvkbd"], show)
    return sq_set(show)


def status():
    conf = read_conf()
    have = installed()
    kind = pick(have, conf["prefer"])
    return {"keyboard": kind, "installed": have, "shown": shown(kind) if kind else False,
            "settings": conf, "missing": missing_text(have),
            "packages": PACKAGES, "auto_supported": kind == "squeekboard", "conf": CONF,
            "key": live_bound_key()}


def main(argv):
    cmd = argv[0] if argv else "toggle"
    if cmd == "toggle":
        st = status()
        set_shown(not st["shown"])
    elif cmd in ("show", "hide"):
        set_shown(cmd == "show")
    elif cmd == "status":
        st = status()
        if "--json" in argv:
            print(json.dumps(st))
        else:
            print(st["missing"] or f"{st['keyboard']}: {'shown' if st['shown'] else 'hidden'}")
    elif cmd == "set" and len(argv) == 3:
        try:
            value = check(argv[1], argv[2])
        except ValueError as exc:
            sys.exit(f"osk.py: {exc}")
        conf = read_conf()
        conf[argv[1]] = value
        write_conf(conf)
        if argv[1] == "auto":
            sq_auto(value == "on")
        print(f"{argv[1]}={value}")
    else:
        sys.exit(__doc__.strip())


if __name__ == "__main__":
    main(sys.argv[1:])
