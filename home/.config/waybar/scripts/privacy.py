#!/usr/bin/env python3
"""Privacy indicators for waybar: microphone, camera and location.

Each indicator hides itself while the resource is idle, so anything visible in
the bar means something is using it *right now*.

    privacy.py <mic|camera|location>          JSON status for a custom module
    privacy.py <mic|camera|location> focus    focus the window that is using it
    privacy.py <mic|camera|location> list     plain-text listing, for a terminal
    privacy.py watch <mic|camera|location>    JSON status on every change,
                                              forever, for a module with no
                                              "interval"

All three watch modes are event-driven: mic follows `pactl subscribe`, camera
inotify on the /dev/video* nodes (an open or close of one is exactly "camera
started / stopped"), location geoclue's D-Bus signals (owner changes and
PropertiesChanged), subscribed through GIO without activating geoclue. Each
also re-checks on a slow SAFETY_TICK, in case an event was missed.

Icons are Font Awesome 6 codepoints written as escapes: no Nerd Font is
installed on this machine, and literal Private-Use characters do not survive
being copied around.
"""

import ctypes
import ctypes.util
import html
import json
import os
import select
import signal
import subprocess
import sys
import time

ICONS = {
    "mic": "\uf130",        # microphone
    "camera": "\uf03d",     # video camera: the webcam (the plain camera is Screenshots)
    "location": "\uf3c5",   # location dot
}

# Streams that exist only to draw a level meter, not to actually listen.
IGNORED_APP_IDS = {"org.PulseAudio.pavucontrol", "org.gnome.VolumeControl"}

# `pactl subscribe` reports every event on the server; a recording stream
# appearing or disappearing is the one that always matters.
STREAM_EVENTS = (b"source-output",)

# Client and server events matter too -- an app can hold a stream open and only
# change its properties -- but our own probing registers a client for the
# duration of every `pactl list`, so these events are also our own echo. They
# are honoured except in the moment right after we emitted, which is exactly
# when the echo lands. See ECHO_GUARD.
CLIENT_EVENTS = (b"client", b"server")

# One application starting a stream produces a handful of events within a few
# milliseconds. Wait for the burst to settle rather than emitting five
# identical lines, but keep the wait short enough to feel instant.
DEBOUNCE = 0.15

# How long after an emit our own probe traffic is ignored. Without this the
# echo described above would re-trigger the probe forever.
ECHO_GUARD = 0.25


def run(cmd, timeout=3):
    try:
        done = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return done.stdout if done.returncode == 0 else ""
    except (subprocess.SubprocessError, OSError):
        return ""


def proc_name(pid):
    try:
        with open(f"/proc/{pid}/comm") as handle:
            return handle.read().strip()
    except OSError:
        return None


# --------------------------------------------------------------------------
# Microphone
# --------------------------------------------------------------------------
def mic_users():
    raw = run(["pactl", "-f", "json", "list", "source-outputs"])
    if not raw.strip():
        return []
    try:
        streams = json.loads(raw)
    except ValueError:
        return []

    # Recording the desktop (a ".monitor" source) is not microphone access.
    monitors, source_names = set(), {}
    try:
        for src in json.loads(run(["pactl", "-f", "json", "list", "sources"]) or "[]"):
            label = src.get("description") or src.get("name") or ""
            source_names[src.get("index")] = label
            source_names[src.get("name")] = label
            if str(src.get("name", "")).endswith(".monitor"):
                monitors.add(src.get("index"))
                monitors.add(src.get("name"))
    except ValueError:
        pass

    users = []
    for stream in streams:
        if stream.get("source") in monitors:
            continue
        props = stream.get("properties") or {}
        if props.get("application.id") in IGNORED_APP_IDS:
            continue
        pid = props.get("application.process.id")
        pid = int(pid) if str(pid).isdigit() else None
        app = (props.get("application.name")
               or props.get("media.name")
               or (proc_name(pid) if pid else None)
               or "unknown")
        users.append({"app": app, "pid": pid,
                      "detail": source_names.get(stream.get("source"), "")})
    return users


# --------------------------------------------------------------------------
# Camera
# --------------------------------------------------------------------------
def camera_users():
    """Anything holding an open fd on a /dev/video* node. Cheaper and more
    reliable than shelling out to fuser/lsof, and it gives us the pid for free."""
    found = {}
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        fd_dir = f"/proc/{pid}/fd"
        try:
            entries = os.listdir(fd_dir)
        except OSError:
            continue  # not ours, or gone already
        for fd in entries:
            try:
                target = os.readlink(f"{fd_dir}/{fd}")
            except OSError:
                continue
            if target.startswith("/dev/video"):
                entry = found.setdefault(int(pid), {
                    "app": proc_name(pid) or "unknown",
                    "pid": int(pid),
                    "devices": set(),
                })
                entry["devices"].add(target)
    users = list(found.values())
    for user in users:
        user["detail"] = ", ".join(sorted(user.pop("devices")))
    return users


# --------------------------------------------------------------------------
# Location
# --------------------------------------------------------------------------
def geoclue_running():
    """Never query the property blind: org.freedesktop.GeoClue2 is D-Bus
    activatable, so polling it every couple of seconds would keep geoclue
    permanently alive -- the opposite of what a privacy indicator is for."""
    for pid in os.listdir("/proc"):
        if pid.isdigit() and proc_name(pid) == "geoclue":
            return True
    return False


def location_users():
    if not geoclue_running():
        return []
    out = run([
        "busctl", "--system", "get-property",
        "org.freedesktop.GeoClue2", "/org/freedesktop/GeoClue2/Manager",
        "org.freedesktop.GeoClue2.Manager", "InUse",
    ])
    if out.strip() != "b true":
        return []

    # Best effort: name the clients. Geoclue exposes one object per client,
    # and the desktop id is the useful part.
    users = []
    tree = run(["busctl", "--system", "tree", "org.freedesktop.GeoClue2"])
    for line in tree.splitlines():
        path = line.strip().lstrip("|-`= ").strip()
        if "/Client/" not in path:
            continue
        desktop = run([
            "busctl", "--system", "get-property",
            "org.freedesktop.GeoClue2", path,
            "org.freedesktop.GeoClue2.Client", "DesktopId",
        ]).strip()
        name = desktop.split('"')[1] if '"' in desktop else path.rsplit("/", 1)[-1]
        users.append({"app": name, "pid": None, "detail": path})
    return users or [{"app": "an application", "pid": None, "detail": "geoclue"}]


PROBES = {"mic": mic_users, "camera": camera_users, "location": location_users}
LABELS = {"mic": "Microphone", "camera": "Camera", "location": "Location"}


# --------------------------------------------------------------------------
# Output modes
# --------------------------------------------------------------------------
def emit_status(kind):
    users = PROBES[kind]()
    if not users:
        # Empty text hides the module entirely.
        print(json.dumps({"text": "", "tooltip": "", "class": "idle"}), flush=True)
        return

    names = []
    for user in users:
        if user["app"] not in names:
            names.append(user["app"])
    count = len(users)
    label = ICONS[kind] + (f" {count}" if count > 1 else "")

    lines = [f"<b>{LABELS[kind]} in use</b>"]
    for user in users:
        pid = f" (pid {user['pid']})" if user.get("pid") else ""
        # Escaped: the tooltip is Pango markup, and an app name or path with
        # an & or < in it would otherwise blank the whole tooltip.
        lines.append(f"  {html.escape(user['app'])}{pid}")
        if user.get("detail"):
            lines.append(f"    {html.escape(user['detail'])}")
    # No click hint: the mic/camera/location pills have "tooltip": false.

    print(json.dumps({
        "text": label,
        "tooltip": "\n".join(lines),
        "class": "active",
        "alt": ",".join(names),
    }), flush=True)


def emit_list(kind):
    users = PROBES[kind]()
    print(f"{LABELS[kind]}: {'in use' if users else 'idle'}\n")
    for user in users:
        pid = f"pid {user['pid']}" if user.get("pid") else "-"
        print(f"  {user['app']:<28} {pid:<12} {user.get('detail') or ''}")
    if not users:
        print("  nothing is using it")


def do_focus(kind):
    for user in PROBES[kind]():
        if not user.get("pid"):
            continue
        # hyprctl dispatch is evaluated as Lua under this config, so the
        # classic `focuswindow pid:N` form is a syntax error here.
        run(["hyprctl", "dispatch",
             f'hl.dsp.focus({{ window = "pid:{user["pid"]}" }})'])
        return


# --------------------------------------------------------------------------
# Watch mode (microphone only)
# --------------------------------------------------------------------------
def emit_status_safe(kind):
    """A watcher has to outlive its own errors: an exception raised here would
    end the module for the rest of the session, not just for one sample."""
    try:
        emit_status(kind)
    except Exception as exc:
        print(json.dumps({"text": "", "tooltip": f"privacy.py: {exc}",
                          "class": "error"}), flush=True)


def follow_events(proc):
    """Re-emit on every relevant event from a running `pactl subscribe`.

    Returns when pactl stops talking to us, so the caller can restart it. Reads
    the pipe with os.read instead of iterating proc.stdout, because select()
    knows nothing about bytes already sitting in a Python-side buffer."""
    fd = proc.stdout.fileno()
    os.set_blocking(fd, False)
    tail = b""
    deadline = None          # when the burst in progress is considered settled
    quiet_until = 0.0        # our own probe traffic is ignored until then

    while True:
        now = time.monotonic()
        timeout = max(0.0, deadline - now) if deadline is not None else None
        try:
            ready, _, _ = select.select([fd], [], [], timeout)
        except OSError:
            return

        if ready:
            try:
                chunk = os.read(fd, 65536)
            except BlockingIOError:
                continue
            except OSError:
                return
            if not chunk:
                return       # pactl exited
            # Only whole lines can be matched safely; a read can split one.
            data = tail + chunk
            tail = data.rpartition(b"\n")[2]
            events = data[:len(data) - len(tail)]
            if deadline is None:
                relevant = any(marker in events for marker in STREAM_EVENTS)
                if not relevant and time.monotonic() >= quiet_until:
                    relevant = any(marker in events for marker in CLIENT_EVENTS)
                if relevant:
                    deadline = time.monotonic() + DEBOUNCE
            continue

        # select() timed out, so the burst has gone quiet: report it.
        deadline = None
        emit_status_safe("mic")
        quiet_until = time.monotonic() + ECHO_GUARD


SAFETY_TICK = 60.0   # s: camera/location re-check even with no event


# --------------------------------------------------------------------------
# Camera and location watchers
# --------------------------------------------------------------------------
class Inotify:
    """Minimal inotify through libc: the stdlib has none, and this is all the
    camera watcher needs. The fd is non-blocking and select()-able."""
    IN_OPEN, IN_CLOSE_WRITE, IN_CLOSE_NOWRITE = 0x20, 0x08, 0x10
    IN_CREATE, IN_DELETE = 0x100, 0x200
    IN_NONBLOCK, IN_CLOEXEC = 0o4000, 0o2000000

    def __init__(self):
        self.libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
        self.fd = self.libc.inotify_init1(self.IN_NONBLOCK | self.IN_CLOEXEC)
        if self.fd < 0:
            raise OSError(ctypes.get_errno(), "inotify_init1")

    def add(self, path, mask):
        return self.libc.inotify_add_watch(self.fd, path.encode(), mask) >= 0

    def drain(self):
        """Read and discard whatever is queued; only "something happened"
        matters here, the probe works out what."""
        try:
            while os.read(self.fd, 65536):
                pass
        except BlockingIOError:
            pass


def camera_events():
    """An fd that becomes readable when any /dev/video* node is opened or
    closed, or one appears or goes away (hotplug). The watches are set up
    again on hotplug by the caller, since a new node needs its own watch."""
    ino = Inotify()
    ino.add("/dev", Inotify.IN_CREATE | Inotify.IN_DELETE)
    for name in os.listdir("/dev"):
        if name.startswith("video"):
            ino.add(f"/dev/{name}", Inotify.IN_OPEN | Inotify.IN_CLOSE_WRITE
                    | Inotify.IN_CLOSE_NOWRITE)
    return ino


def watch_camera():
    """Camera use is a process holding an fd on a /dev/video* node. The
    /proc walk that names the process (camera_users) is the expensive part, so
    it only runs after inotify reports an open or close -- not every 5 s.
    Opening the node is also how a probe like v4l2 enumeration looks, so a
    burst is debounced and the probe decides whether anything still holds it."""
    last = None
    ino = camera_events()
    next_tick = 0.0
    while True:
        now = time.monotonic()
        try:
            ready, _, _ = select.select([ino.fd], [], [],
                                        max(0.0, next_tick - now))
        except OSError:
            ready = []
        if ready:
            time.sleep(DEBOUNCE)   # let the open/close burst finish
            ino.drain()
            # Rebuild the watches so a newly plugged camera is covered.
            os.close(ino.fd)
            ino = camera_events()
        last = emit_if_changed("camera", last)
        next_tick = time.monotonic() + SAFETY_TICK


def watch_location():
    """Event-driven, without ever activating geoclue. Two D-Bus signal
    subscriptions through GIO, both plain match rules on the bus -- neither
    calls into geoclue, so neither can start it (`gdbus monitor --dest` DOES
    start it: it resolves the name with auto-start; measured 2026-10):

      NameOwnerChanged for org.freedesktop.GeoClue2   geoclue started/exited
      PropertiesChanged from geoclue's Manager         InUse flipped

    Either one triggers a re-probe after a short debounce; location_users()
    stays the source of truth and only queries geoclue while it is running.
    gi is imported here, not at the top, so the mic/camera modes and the
    one-shot status calls do not pay for it."""
    import gi
    gi.require_version("Gio", "2.0")
    from gi.repository import Gio, GLib

    state = {"last": None, "pending": False}

    def probe():
        state["pending"] = False
        state["last"] = emit_if_changed("location", state["last"])
        return False

    def poke(*_args):
        if not state["pending"]:
            state["pending"] = True
            GLib.timeout_add(int(DEBOUNCE * 1000), probe)

    def tick():
        poke()
        return True

    bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
    bus.signal_subscribe("org.freedesktop.DBus", "org.freedesktop.DBus",
                         "NameOwnerChanged", "/org/freedesktop/DBus",
                         "org.freedesktop.GeoClue2",
                         Gio.DBusSignalFlags.NONE, poke)
    bus.signal_subscribe("org.freedesktop.GeoClue2",
                         "org.freedesktop.DBus.Properties", "PropertiesChanged",
                         "/org/freedesktop/GeoClue2/Manager", None,
                         Gio.DBusSignalFlags.NONE, poke)
    probe()
    GLib.timeout_add_seconds(int(SAFETY_TICK), tick)
    GLib.MainLoop().run()


def emit_if_changed(kind, last):
    """Print the status line only when it differs from the previous one, so a
    re-check that finds nothing new costs waybar nothing. Returns the line."""
    try:
        users = PROBES[kind]()
        key = json.dumps(users, sort_keys=True, default=str)
    except Exception as exc:  # noqa: BLE001 - a watcher must outlive its probe
        key = f"error: {exc}"
    if key != last:
        emit_status_safe(kind)
    return key


def exit_once(*_):
    """SIGTERM -> a normal exit (finally blocks run, no child left behind),
    once only: a bar stop sends SIGTERM to the whole unit and waybar sends
    its own, and the second landing while the first exit is cleaning up
    (inside Popen.__del__) printed an "Exception ignored ... SystemExit"
    traceback into the journal on every bar restart."""
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    sys.exit(0)


def watch_mic():
    """Event-driven microphone status: the current state now, then a fresh line
    whenever pulse says something changed.

    Camera and location have their own watchers above (inotify and D-Bus
    signal subscriptions)."""
    # waybar stops a module by signalling it, and the default disposition would
    # kill us without running the cleanup below, leaving `pactl subscribe`
    # behind until its next write happened to fail (exit_once).
    signal.signal(signal.SIGTERM, exit_once)

    while True:
        emit_status_safe("mic")
        try:
            pactl = subprocess.Popen(["pactl", "subscribe"],
                                     stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL)
        except OSError:
            time.sleep(5)    # pactl is not installed; do not spin on finding out
            continue
        try:
            follow_events(pactl)
        finally:
            pactl.terminate()
            try:
                pactl.wait(timeout=2)
            except subprocess.SubprocessError:
                pactl.kill()
            pactl.stdout.close()
        # A pipewire-pulse restart takes the subscription down with it. Pick it
        # back up, but slowly enough that a permanently broken pactl cannot
        # turn this loop into a fork bomb.
        time.sleep(2)


def main():
    if sys.argv[1:2] == ["watch"]:
        watchers = {"mic": watch_mic, "camera": watch_camera,
                    "location": watch_location}
        if len(sys.argv) != 3 or sys.argv[2] not in watchers:
            print(f"usage: {sys.argv[0]} watch <mic|camera|location>",
                  file=sys.stderr)
            raise SystemExit(2)
        # waybar stops a module with SIGTERM; exit through Python so the
        # finally blocks run and no pactl child is left behind (exit_once).
        signal.signal(signal.SIGTERM, exit_once)
        try:
            watchers[sys.argv[2]]()
        except BrokenPipeError:
            pass        # waybar went away
        return
    if len(sys.argv) < 2 or sys.argv[1] not in PROBES:
        print(f"usage: {sys.argv[0]} <mic|camera|location> [focus|list]",
              file=sys.stderr)
        raise SystemExit(2)
    kind = sys.argv[1]
    mode = sys.argv[2] if len(sys.argv) > 2 else "status"
    try:
        if mode == "focus":
            do_focus(kind)
        elif mode == "list":
            emit_list(kind)
        else:
            emit_status(kind)
    except Exception as exc:  # a broken probe must not blank the bar
        if mode == "status":
            print(json.dumps({"text": "", "tooltip": f"privacy.py: {exc}",
                              "class": "error"}))
        else:
            print(f"error: {exc}", file=sys.stderr)


if __name__ == "__main__":
    main()
