#!/usr/bin/env python3
"""USB drives: mounted when plugged in, opened in Files, ejected safely.

    automount.py daemon         watch UDisks2 (automount.service): a new
                                removable filesystem is mounted (under
                                /run/media/$USER, as Files would) and a toast
                                offers "Open"; a locked (LUKS) one gets a toast
                                saying to open it in Files to unlock
    automount.py list [--json]  the removable drives mounted now
    automount.py eject [<mountpoint>|all]
                                unmount every filesystem of that drive and
                                power it off, so it can be pulled out; a busy
                                one says which program holds it
    automount.py bar            waybar JSON for custom/drives: a USB glyph
                                while something removable is mounted (read
                                from mountinfo first: no D-Bus while none is)
    automount.py click left|right
                                the pill's clicks (click_plan): one drive --
                                open it / eject it; several -- Files on
                                /run/media/$USER either way, never "eject all"
    automount.py get [--json]   the two choices below
    automount.py set mount on|off
                                off: a plugged-in drive is left unmounted and
                                the toast offers "Open" (which mounts it)
    automount.py set open on|off
                                on: Files opens on the drive as soon as it is
                                mounted (the toast then offers only "Eject")

The choices live in ~/.config/hypr/automount.conf (mount=on, open=off when
there is none -- the old behaviour); the daemon reads it on every plug-in, so
a change needs no restart. Settings > Storage writes it through `set`.

Only removable drives (USB sticks and disks, SD cards); never internal
disks, and never a filesystem udisks marks to ignore or not to automount.
The bar pill is signalled (bar_signals.py "drives") on every change.
"""
import json
import os
import re
import subprocess
import sys
import threading

# gi (PyGObject) is imported on first use (load_gi), not here: it costs
# ~80 ms and ~30 MB, and `bar` -- re-run on every drive change -- usually
# needs none of it (bar_fast).
Gio = GLib = None


def load_gi():
    global Gio, GLib
    if Gio is None:
        import gi  # noqa: F401
        from gi.repository import Gio as _Gio, GLib as _GLib
        Gio, GLib = _Gio, _GLib

BUS = "org.freedesktop.UDisks2"
FS, BLOCK, DRIVE = (BUS + ".Filesystem", BUS + ".Block", BUS + ".Drive")
FILES = "nautilus"
CONF = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "hypr", "automount.conf")
sys.path.insert(0, os.path.expanduser("~/.config/hypr/scripts"))
import desk_common  # noqa: E402  (notify: the notification, through scripts/notify)
DEFAULTS = {"mount": True, "open": False}


# -- the two choices -------------------------------------------------------------
def parse_conf(text):
    """key=on|off lines -> {mount, open}; anything else (comments, typos,
    unknown keys) falls back to the defaults."""
    conf = dict(DEFAULTS)
    for line in (text or "").splitlines():
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().lower()
        if key in conf and value in ("on", "off", "true", "false", "yes", "no", "1", "0"):
            conf[key] = value in ("on", "true", "yes", "1")
    return conf


def format_conf(conf):
    return ("# USB drives (scripts/automount.py; Settings > Storage writes this).\n"
            "# mount: mount a drive when it is plugged in.  open: open it in Files then.\n"
            + "".join(f"{k}={'on' if conf[k] else 'off'}\n" for k in DEFAULTS))


def read_conf():
    try:
        with open(CONF) as f:
            return parse_conf(f.read())
    except OSError:
        return dict(DEFAULTS)


def write_conf(key, value):
    if key not in DEFAULTS or value not in ("on", "off"):
        sys.exit("set mount|open on|off")
    conf = read_conf()
    conf[key] = value == "on"
    os.makedirs(os.path.dirname(CONF), exist_ok=True)
    tmp = CONF + ".tmp"
    with open(tmp, "w") as f:
        f.write(format_conf(conf))
    os.replace(tmp, CONF)


def open_files(point):
    subprocess.Popen([FILES, point], start_new_session=True,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def manager():
    load_gi()
    return Gio.DBusObjectManagerClient.new_for_bus_sync(
        Gio.BusType.SYSTEM, Gio.DBusObjectManagerClientFlags.NONE, BUS, "/org/freedesktop/UDisks2",
        None, None, None)


def prop(obj, iface, name):
    proxy = obj.get_interface(iface)
    if proxy is None:
        return None
    value = proxy.get_cached_property(name)
    return value.unpack() if value is not None else None


def drive_of(mgr, obj):
    path = prop(obj, BLOCK, "Drive")
    return mgr.get_object(path) if path and path != "/" else None


def removable(mgr, obj):
    drive = drive_of(mgr, obj)
    if drive is None:
        return False
    return bool(prop(drive, DRIVE, "Removable") or prop(drive, DRIVE, "MediaRemovable")
                or prop(drive, DRIVE, "ConnectionBus") in ("usb", "sdio"))


def label_of(mgr, obj):
    label = prop(obj, BLOCK, "IdLabel")
    if label:
        return label
    drive = drive_of(mgr, obj)
    name = " ".join(filter(None, (prop(drive, DRIVE, "Vendor"), prop(drive, DRIVE, "Model")))) if drive else ""
    size = prop(obj, BLOCK, "Size") or 0
    return f"{name or 'Drive'} ({size / 1e9:.0f} GB)" if size else (name or "Drive")


def mountpoints(obj):
    points = prop(obj, FS, "MountPoints") or []
    return [bytes(p).rstrip(b"\0").decode() for p in points]


def mounted(mgr):
    """[{mount, label, object}] removable filesystems mounted now."""
    out = []
    for obj in mgr.get_objects():
        if obj.get_interface(FS) and removable(mgr, obj):
            for point in mountpoints(obj):
                out.append({"mount": point, "label": label_of(mgr, obj), "object": obj.get_object_path()})
    return out


def poke_bar():
    """Redraw custom/drives (bar_signals "drives"): the daemon calls this on
    every mount, unmount and removal, so the module needs no polling."""
    try:
        here = os.path.dirname(os.path.abspath(__file__))
        if here not in sys.path:
            sys.path.insert(0, here)
        import bar_signals
        bar_signals.poke("drives")
    except Exception:       # no bar: nothing to redraw
        pass


# -- the bar without D-Bus --------------------------------------------------------
MEDIA = os.path.join("/run/media", os.environ.get("USER") or os.path.basename(os.path.expanduser("~")))


def unescape_mount(field):
    """mountinfo writes a space as \\040 (and tab, newline, backslash alike)."""
    return re.sub(r"\\([0-7]{3})", lambda m: chr(int(m.group(1), 8)), field)


def media_mounts(mountinfo_text, media=None):
    """Mount points under /run/media/$USER (where udisks mounts a drive for
    this user, as Files would) in a /proc/self/mountinfo text."""
    media = (media or MEDIA).rstrip("/") + "/"
    out = []
    for line in mountinfo_text.splitlines():
        f = line.split(" ")
        if len(f) > 4:
            point = unescape_mount(f[4])
            if point.startswith(media):
                out.append(point)
    return out


def bar_rows():
    """The bar's rows: [] straight from mountinfo when nothing is mounted
    under /run/media/$USER or /media (udisks' two homes: per user, and the
    shared one a UDISKS_FILESYSTEM_SHARED rule picks) -- the usual case: no
    gi, no D-Bus -- else udisks' answer, which also checks the drive really
    is removable and has its label."""
    try:
        with open("/proc/self/mountinfo") as handle:
            text = handle.read()
        if not media_mounts(text) and not media_mounts(text, "/media"):
            return []
    except OSError:
        pass
    return mounted(manager())


def click_plan(rows, button):
    """What a click on the pill does, as (action, argument):
    left    one drive: ("open", its mount); several: ("open", /run/media/$USER)
            so Files shows them all side by side
    right   one drive: ("eject", its mount); several: ("open", the media
            folder) -- never "eject everything" from one stray click: Files
            has an eject button per drive"""
    if not rows:
        return ("none", "")
    if len(rows) == 1:
        return ("open" if button == "left" else "eject", rows[0]["mount"])
    return ("open", os.path.dirname(rows[0]["mount"].rstrip("/")) or MEDIA)


def bar_json(rows):
    if not rows:
        return {"text": "", "class": "none"}
    tip = "\n".join(f"{r['label']}  {r['mount']}" for r in rows)
    hint = ("Click: open in Files · Right-click: eject it" if len(rows) == 1 else
            "Click or right-click: Files, with an eject button per drive")
    return {"text": "\uf287" + (f" {len(rows)}" if len(rows) > 1 else ""),
            "tooltip": f"{tip}\n\n{hint}", "class": "mounted"}


def notify(title, body, actions=(), icon="drive-removable-media"):
    """notify-send; returns the action picked (blocks: run in a thread)."""
    return desk_common.notify(title, body, app="Drives", icon=icon, actions=actions, timeout=600)


def background(fn, *args):
    threading.Thread(target=fn, args=args, daemon=True).start()


# -- daemon ----------------------------------------------------------------------
class Daemon:
    def __init__(self):
        self.mgr = manager()
        self.seen = {o.get_object_path() for o in self.mgr.get_objects()}   # present at start: leave alone
        self.mgr.connect("object-added", lambda _m, obj: GLib.timeout_add(700, self.added, obj))
        self.mgr.connect("interface-added", lambda _m, obj, _i: GLib.timeout_add(700, self.added, obj))
        self.mgr.connect("object-removed", self.removed)

    def removed(self, _mgr, obj):
        # Pulled out: udisks reuses the path (block_devices/sdb1) for the next
        # drive in that port, which must be treated as new again.
        self.seen.discard(obj.get_object_path())
        poke_bar()

    def added(self, obj):
        path = obj.get_object_path()
        if path in self.seen or not obj.get_interface(BLOCK) or not removable(self.mgr, obj):
            return False
        if prop(obj, BLOCK, "HintIgnore") or not prop(obj, BLOCK, "HintAuto"):
            return False
        if prop(obj, BLOCK, "IdUsage") == "crypto":
            self.seen.add(path)
            background(notify, f"Locked drive: {label_of(self.mgr, obj)}",
                       "Open it in Files to unlock it with its password.", (), "drive-removable-media")
            return False
        if not obj.get_interface(FS) or mountpoints(obj):
            return False
        self.seen.add(path)
        conf = read_conf()
        label = label_of(self.mgr, obj)
        if not conf["mount"]:
            # Left alone until asked: Open mounts it (and opens it).
            background(self.offer_mount, obj, label)
            return False
        point = self.mount(obj, label)
        if point is None:
            return False
        if conf["open"]:
            open_files(point)
        background(self.offer, label, point, conf["open"])
        return False

    def mount(self, obj, label):
        """Mount through udisks (as Files would); None and a toast if it fails."""
        fs = obj.get_interface(FS)
        if fs is None:              # pulled out before Open was picked
            return None
        try:
            point = fs.call_sync("Mount", GLib.Variant("(a{sv})", ({},)),
                                 Gio.DBusCallFlags.NONE, 15000, None).unpack()[0]
        except GLib.Error as exc:
            background(notify, f"Could not open {label}", exc.message, (), "dialog-warning")
            return None
        poke_bar()
        return point

    def offer(self, label, point, opened=False):
        actions = (("eject", "Eject"),) if opened else (("open", "Open"), ("eject", "Eject"))
        pick = notify(f"{label} is ready", point, actions)
        if pick == "open":
            open_files(point)
        elif pick == "eject":
            eject(point)

    def offer_mount(self, obj, label):
        """Runs in a thread (notify waits); the mount goes back to the main loop."""
        if notify(f"{label} plugged in", "Not opened: automatic mounting is off.", (("open", "Open"),)) == "open":
            GLib.idle_add(lambda: (self.open_later(obj, label), False)[1])

    def open_later(self, obj, label):
        point = mountpoints(obj)[0] if mountpoints(obj) else self.mount(obj, label)
        if point:
            open_files(point)


# -- eject -------------------------------------------------------------------------
def holders(point):
    try:
        out = subprocess.run(["fuser", "-vm", point], capture_output=True, text=True, timeout=5).stderr
    except (OSError, subprocess.SubprocessError):
        return []
    return sorted({line.split()[-1] for line in out.splitlines()[2:] if line.split()})


def eject(target="all"):
    mgr = manager()
    chosen = [m for m in mounted(mgr) if target in ("all", m["mount"])]
    drives, failed = {}, []
    for m in chosen:
        obj = mgr.get_object(m["object"])
        try:
            obj.get_interface(FS).call_sync("Unmount", GLib.Variant("(a{sv})", ({},)),
                                            Gio.DBusCallFlags.NONE, 15000, None)
            drive = drive_of(mgr, obj)
            if drive:
                drives[drive.get_object_path()] = m["label"]
        except GLib.Error as exc:
            who = holders(m["mount"])
            failed.append(f"{m['label']}: in use" + (f" by {', '.join(who)}" if who else f" ({exc.message})"))
    # Every filesystem of a drive must be unmounted before it powers off.
    for path, label in drives.items():
        drive = mgr.get_object(path)
        if any(mountpoints(o) for o in mgr.get_objects() if o.get_interface(FS)
               and prop(o, BLOCK, "Drive") == path):
            continue
        try:
            drive.get_interface(DRIVE).call_sync("PowerOff", GLib.Variant("(a{sv})", ({},)),
                                                 Gio.DBusCallFlags.NONE, 15000, None)
        except GLib.Error:
            pass                    # unmounted is already safe to pull; some readers cannot power off
        notify(f"{label} can be removed", "", (), "media-eject")
    for line in failed:
        notify("Could not eject", line, (), "dialog-warning")
    poke_bar()
    return not failed


def main(argv):
    cmd = argv[0] if argv else "list"
    if cmd == "daemon":
        Daemon()
        GLib.MainLoop().run()
    elif cmd == "list":
        rows = [{"mount": m["mount"], "label": m["label"]} for m in mounted(manager())]
        print(json.dumps(rows) if "--json" in argv else "\n".join(f"{r['label']}\t{r['mount']}" for r in rows))
    elif cmd == "eject":
        sys.exit(0 if eject(argv[1] if len(argv) > 1 else "all") else 1)
    elif cmd == "get":
        conf = read_conf()
        print(json.dumps(dict(conf, conf=CONF)) if "--json" in argv else
              "\n".join(f"{k}={'on' if v else 'off'}" for k, v in conf.items()))
    elif cmd == "set" and len(argv) > 2:
        write_conf(argv[1], argv[2])
    elif cmd == "bar":
        print(json.dumps(bar_json(bar_rows())))
    elif cmd == "click" and argv[1:2] in (["left"], ["right"]):
        action, target = click_plan(bar_rows(), argv[1])
        if action == "open":
            open_files(target)
        elif action == "eject":
            sys.exit(0 if eject(target) else 1)
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
