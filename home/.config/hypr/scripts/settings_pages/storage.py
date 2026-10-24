"""Settings page: how full every disk is, what is big in your home folder,
the trash, the caches, the automatic clean-up, USB drives and snapshots.

Everything goes through ~/.config/hypr/scripts/storage.py (sizes, emptying,
clearing, the clean-up switches and its daily timer) and automount.py (the
USB drive choices); the page reads them back after every change. Three
readings, so the quick one is never held up by the slow ones:

    storage.py status --json   the disks and the switches     (instant)
    storage.py sizes --json    the trash and ~/.cache (du)     (a few seconds)
    storage.py home --json     the biggest folders in ~ (du)   (~40 s; kept 6 h)

The home scan is shown from what storage.py kept first and only redone when
that is old, or on "Scan again". Emptying the trash and clearing a cache
take two clicks: the first swaps the link for a question and Yes / Cancel.
"""
from gi.repository import GLib, Gtk  # noqa: F401

from .common import *  # noqa: F401,F403  (the shared helpers and paths)

import os  # noqa: E402
import subprocess  # noqa: E402
import time  # noqa: E402

PAGE = {"id": "storage", "title": "Storage", "icon": "", "group": "System", "order": 30,
        "keywords": ["disk", "disco", "space", "espacio", "disk usage", "free space", "full",
                     "almacenamiento", "trash", "papelera", "cache", "clean up", "cleanup", "big folders",
                     "home folder", "usb drives", "automount", "snapshots", "btrfs", "partitions"]}

STORAGE = os.path.join(HYPR, "storage.py")
SETTINGS = os.path.join(HYPR, "settings.py")
FILES = "nautilus"
HOME = os.path.expanduser("~")
HOME_MAX_AGE = 6 * 3600         # as storage.py: an older scan is redone when the page is shown
DAYS = [7, 14, 30, 60, 90]
CACHE_ROWS = 6                  # biggest ~/.cache folders listed
HOME_ROWS = 10


def human(size):
    """Decimal units, as the disk pill and the disk panel show them."""
    size = float(size or 0)
    for unit in ("B", "K", "M", "G", "T", "P"):
        if size < 1000 or unit == "P":
            return f"{size:.0f} {unit}" if unit in "BKM" else f"{size:.1f} {unit}"
        size /= 1000
    return ""


def tilde(path):
    return "~" + path[len(HOME):] if path == HOME or path.startswith(HOME + "/") else path


def fs_title(fs):
    """"/ and /home", "/mnt/Andromeda", with the label when it says more."""
    places = " and ".join(tilde(t) for t in fs["targets"])
    label = fs.get("label") or ""
    name = os.path.basename(fs["targets"][0]) if fs["targets"] else ""
    return f"{places}  ({label})" if label and label.lower() not in (name.lower(), "") else places


def fs_sub(fs):
    bits = [f"{human(fs['used'])} of {human(fs['size'])} used", f"{human(fs['avail'])} free"]
    if fs["level"] == "critical":
        bits.insert(0, "nearly full")
    return "  ·  ".join(bits)


def full_warning(filesystems):
    """One line naming every disk at 90 % or more, or ""."""
    full = [f for f in filesystems if f["level"] == "critical"]
    if not full:
        return ""
    names = ", ".join(f"{' and '.join(f['targets'])} ({f['percent']} %, {human(f['avail'])} left)" for f in full)
    return f"!  Nearly full: {names}. Empty its trash below or move something off it."


def trash_title(t):
    return "Trash in your home folder" if t["mount"] == HOME else f"Trash on {t['mount']}"


def trash_sub(t):
    if not t["items"] and not t["size"]:
        return "empty"
    return f"{human(t['size'])} in {t['items']} item{'s' if t['items'] != 1 else ''}"


def scanned_sub(data, now=None):
    if not data:
        return "not scanned yet"
    age = int((now or time.time()) - data.get("time", 0))
    return f"{human(data['total'])} in all  ·  scanned {ago(age)}  ·  other disks not counted"


def day_chips(current):
    values = sorted(set(DAYS) | {current})
    return [(str(d), f"{d} days") for d in values]


def cleanup_sub(auto, timer, last):
    if not (auto["trash"] or auto["temp"]):
        return "nothing is deleted on its own"
    what = " and ".join(w for w, on in (("trash", auto["trash"]), ("your temporary files", auto["temp"])) if on)
    bits = [f"{what} older than {auto['days']} days, deleted daily"]
    if not timer.get("enabled"):
        bits.append("!  its timer is off: flip a switch off and on")
    if last:
        bits.append(f"last run {ago(int(time.time() - last['time']))}: {last['removed']} removed, "
                    f"{human(last['freed'])} freed" + (f", {len(last['problems'])} could not be"
                                                       if last.get("problems") else ""))
    else:
        bits.append("has not run yet")
    return "  ·  ".join(bits)


def snapshot_sub(snaps):
    if not snaps.get("set_up"):
        return "not set up, so none take space (see Maintenance)"
    parts = []
    for name, c in (snaps.get("configs") or {}).items():
        if c is None:
            parts.append(f"{name}: snapper did not answer")
        elif c["used"] is None:
            parts.append(f"{name}: {c['count']} snapshots, size not measured")
        else:
            parts.append(f"{name}: {c['count']} snapshots holding {human(c['used'])}")
    return "  ·  ".join(parts) or "no snapper configs"


def snapshot_details(snaps):
    """The why and the root steps behind snapshot_sub, for its fold."""
    if not snaps.get("set_up"):
        return "The Maintenance page says how to set snapper up (one root step)."
    lines = []
    for name, c in (snaps.get("configs") or {}).items():
        if c is None:
            lines.append(f"{name}: snapper may need root to list it.")
        elif c["used"] is None:
            lines.append(f"{name}: btrfs quotas are off, so their own space is not measured: "
                         f"sudo snapper -c {name} setup-quota")
    return "\n".join(lines) or "Sizes are each snapshot's own space (btrfs quotas)."


def attempt(*cmd, timeout=1800):
    """(ok, message): what the command printed when it worked, else its own
    complaint from stderr. Called from background() only."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"{os.path.basename(cmd[0])}: {exc}"
    if r.returncode == 0:
        return True, r.stdout.strip()
    return False, (r.stderr.strip().splitlines() or [f"{os.path.basename(cmd[0])} failed ({r.returncode})"])[-1]


def bar(pct, lvl=""):
    """The disk panel's usage bar (its dk-bar classes: yellow / magenta)."""
    b = Gtk.LevelBar.new_for_interval(0, 100)
    b.set_mode(Gtk.LevelBarMode.CONTINUOUS)
    for offset in ("low", "high", "full"):
        b.remove_offset_value(offset)
    b.set_value(max(0, min(100, pct)))
    style = b.get_style_context()
    style.add_class("dk-bar")
    if lvl:
        style.add_class(lvl)
    b.set_hexpand(True)
    b.set_valign(Gtk.Align.CENTER)
    return b


def wrapped(text, cls="ctl-sub"):
    lab = dp.label(text, cls)
    lab.set_line_wrap(True)
    return lab


class Page:
    def __init__(self):
        self.widget = page_box()
        w = self.widget
        self.updating = False
        self.scanning = False
        self.status = None
        # The last command's result (an error, or "Freed 2.1 G"), shown at
        # the top until the next one.
        self.message = wrapped("")
        self.message.set_no_show_all(True)
        w.pack_start(self.message, False, False, 0)

        w.pack_start(heading("DISKS"), False, False, 0)
        self.disks = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        w.pack_start(self.disks, False, False, 0)
        w.pack_start(links_row(link("Disk panel", lambda: spawn(PANEL, "toggle", "disk")),
                               link("Disk Usage Analyzer", lambda: spawn("baobab"))), False, False, 0)
        w.pack_start(sep(), False, False, 0)

        w.pack_start(heading("BIGGEST IN YOUR HOME FOLDER"), False, False, 0)
        self.home_sub = wrapped("checking…")
        w.pack_start(self.home_sub, False, False, 0)
        self.home = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        w.pack_start(self.home, False, False, 0)
        self.rescan = link("Scan again", lambda: self.scan_home(force=True))
        w.pack_start(links_row(self.rescan, link("Open in Disk Usage Analyzer", lambda: spawn("baobab", HOME))),
                     False, False, 0)
        w.pack_start(sep(), False, False, 0)

        w.pack_start(heading("TRASH"), False, False, 0)
        self.trash = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        w.pack_start(self.trash, False, False, 0)
        self.trash_links = Gtk.Box(spacing=6)
        self.trash_links.set_halign(Gtk.Align.END)
        w.pack_start(self.trash_links, False, False, 0)
        self.draw_trash_links()
        w.pack_start(sep(), False, False, 0)

        w.pack_start(heading("CACHES"), False, False, 0)
        self.cache = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        w.pack_start(self.cache, False, False, 0)
        w.pack_start(wrapped("Safe to clear: it is rebuilt when needed."), False, False, 0)
        w.pack_start(details(wrapped(
            "A cache only saves time: whatever is cleared is downloaded or worked out again when it is next "
            "needed (the first start of a game or a browser is slower, a downloaded model or package is "
            "fetched again). A folder a running program has open is left alone, and the program named.")),
            False, False, 0)
        w.pack_start(sep(), False, False, 0)

        w.pack_start(heading("AUTOMATIC CLEAN-UP"), False, False, 0)
        self.switches = {}
        for key, icon, title, sub in (
                ("trash", "\uf1f8", "Empty old trash", "trash older than the age below"),
                ("temp", "\uf254", "Delete old temporary files",
                 "your files in /tmp and /var/tmp unused that long")):
            sw = Gtk.Switch()
            sw.connect("state-set", lambda _s, state, k=key: self.switched(
                lambda: self.do(STORAGE, "auto", k, "on" if state else "off"), state))
            grid, _sub = row(icon, title, sub, sw)
            self.switches[key] = sw
            w.pack_start(grid, False, False, 0)
        grid, self.days_sub = row("\uf017", "After", "")
        w.pack_start(grid, False, False, 0)
        self.days = Chips(lambda k: None if self.updating else self.do(STORAGE, "auto", "days", k))
        self.days.widget.set_max_children_per_line(7)
        self.days.widget.set_min_children_per_line(len(DAYS))
        self.days.widget.set_halign(Gtk.Align.START)
        w.pack_start(self.days.widget, False, False, 0)
        w.pack_start(sep(), False, False, 0)

        w.pack_start(heading("USB DRIVES"), False, False, 0)
        self.usb = {}
        for key, icon, title, sub in (
                ("mount", "\uf287", "Mount drives when they are plugged in",
                 "when off, a drive waits until you open it"),
                ("open", "\uf07c", "Open them in Files", "a window on the drive once mounted")):
            sw = Gtk.Switch()
            sw.connect("state-set", lambda _s, state, k=key: self.switched(
                lambda: self.do(AUTOMOUNT, "set", k, "on" if state else "off"), state))
            grid, sub_label = row(icon, title, sub, sw)
            self.usb[key] = (sw, sub_label, sub)
            w.pack_start(grid, False, False, 0)
        w.pack_start(links_row(link("Open Devices", lambda: spawn(SETTINGS, "devices"))),
                     False, False, 0)
        w.pack_start(sep(), False, False, 0)

        w.pack_start(heading("SNAPSHOTS"), False, False, 0)
        grid, self.snap_sub = row("\uf1da", "System snapshots", "checking…")
        w.pack_start(grid, False, False, 0)
        w.pack_start(links_row(link("Open Maintenance", lambda: spawn(SETTINGS, "system"))), False, False, 0)
        self.snap_more = wrapped("")
        self.snap_more.set_selectable(True)
        w.pack_start(details(self.snap_more), False, False, 0)

    # -- actions ---------------------------------------------------------------------
    def switched(self, act, _state):
        if not self.updating:
            act()
        return True             # the switch moves when refresh() says the setting did

    def do(self, *cmd):
        # Emptying a big trash or clearing a big cache takes a while: say it
        # has started, so a second click does not look needed.
        if cmd[1:2] in (("empty-trash",), ("clear-cache",), ("clear-thumbnails",)):
            self.message.set_text("working…")
            self.message.set_visible(True)
        background(lambda: attempt(*cmd), self.done)

    def done(self, result):
        ok, text = result
        self.message.set_text(text if ok else f"!  {text}")
        self.message.set_visible(bool(text))
        self.refresh()

    def confirm(self, box, question, yes, cmd, restore):
        """Swap the links in `box` for a question and Yes / Cancel."""
        clear(box)
        box.pack_start(wrapped(question), False, False, 0)
        box.pack_start(link(yes, lambda: (restore(), self.do(*cmd))), False, False, 0)
        box.pack_start(link("Cancel", restore), False, False, 0)
        box.show_all()

    def draw_trash_links(self):
        box = self.trash_links
        clear(box)
        box.pack_start(link("Open the trash", lambda: spawn(FILES, "trash:///")), False, False, 0)
        box.pack_start(link("Empty trash…", lambda: self.confirm(
            box, "Delete everything in every trash for good?", "Yes, empty it", (STORAGE, "empty-trash"),
            self.draw_trash_links)), False, False, 0)
        box.show_all()

    def scan_home(self, force=False):
        if self.scanning:
            return
        self.scanning = True
        self.rescan.set_sensitive(False)
        self.home_sub.set_text("scanning… (about a minute)")
        args = ("--max-age", "0") if force else ("--max-age", str(HOME_MAX_AGE))
        background(lambda: run_json(STORAGE, "home", "--json", *args, timeout=1800), self.scanned)

    def scanned(self, data):
        self.scanning = False
        self.rescan.set_sensitive(True)
        self.show_home(data)

    # -- drawing ---------------------------------------------------------------------
    def refresh(self):
        if self.status is None and not self.disks.get_children():
            self.disks.pack_start(dp.label("checking…", "ctl-sub"), False, False, 0)
            self.disks.show_all()
        background(lambda: (run_json(STORAGE, "status", "--json", timeout=30),
                            run_json(AUTOMOUNT, "get", "--json", timeout=10)), self.show_status)
        background(lambda: run_json(STORAGE, "sizes", "--json", timeout=600), self.show_sizes)
        if not self.scanning:
            background(lambda: run_json(STORAGE, "home", "--json", "--cached", timeout=10), self.show_cached_home)

    def show_cached_home(self, data):
        if self.scanning:
            return
        self.show_home(data)
        if not data or time.time() - data.get("time", 0) >= HOME_MAX_AGE:
            self.scan_home()

    def show_home(self, data):
        if self.scanning:
            return
        self.home_sub.set_text(scanned_sub(data))
        clear(self.home)
        if data:
            biggest = max([r["size"] for r in data["top"]] or [1]) or 1
            for r in data["top"][:HOME_ROWS]:
                line = Gtk.Box(spacing=10)
                name = link(f"~/{r['name']}", lambda n=r["name"]: spawn(FILES, os.path.join(HOME, n)))
                name.set_size_request(220, -1)
                name.get_child().set_xalign(0)
                name.set_tooltip_text("Open in Files")
                line.pack_start(name, False, False, 0)
                line.pack_start(bar(100 * r["size"] / biggest), True, True, 0)
                size = dp.label(human(r["size"]), "ctl-value")
                size.set_size_request(70, -1)
                line.pack_start(size, False, False, 0)
                self.home.pack_start(line, False, False, 0)
        self.home.show_all()

    def show_status(self, data):
        status, usb = data
        clear(self.disks)
        if not status:
            self.disks.pack_start(dp.label("storage.py did not answer", "ctl-sub"), False, False, 0)
            self.disks.show_all()
            return
        self.status = status
        self.updating = True
        warn = full_warning(status["filesystems"])
        if warn:
            self.disks.pack_start(wrapped(warn), False, False, 0)
        for fs in status["filesystems"]:
            value = dp.label(f"{fs['percent']} %", "ctl-value")
            grid, _ = row("\uf0a0" if fs["level"] != "critical" else "\uf071", fs_title(fs), fs_sub(fs), value)
            grid.attach(bar(fs["percent"], fs["level"]), 1, 2, 2, 1)
            grid.set_tooltip_text(f"{fs['fstype']} on {os.path.basename(fs['device'])}")
            self.disks.pack_start(grid, False, False, 0)
        self.disks.show_all()

        auto = status["auto"]
        for key, sw in self.switches.items():
            sw.set_state(auto[key])
            sw.set_active(auto[key])
        self.days.set(day_chips(auto["days"]), str(auto["days"]))
        self.days_sub.set_text(cleanup_sub(auto, status["timer"], status.get("last_run")))

        if usb:
            for key, (sw, sub_label, sub) in self.usb.items():
                sw.set_state(usb[key])
                sw.set_active(usb[key])
                sub_label.set_text(sub)
            # Opening needs a mount first; with mounting off, Open on the
            # notification mounts and opens in one go anyway.
            self.usb["open"][0].set_sensitive(usb["mount"])
            if not usb["mount"]:
                self.usb["open"][1].set_text("needs mounting on plug-in (off)")
        else:
            self.usb["mount"][1].set_text("automount.py did not answer")
        self.snap_sub.set_text(snapshot_sub(status["snapshots"]))
        self.snap_more.set_text(snapshot_details(status["snapshots"]))
        self.updating = False

    def show_sizes(self, data):
        clear(self.trash)
        clear(self.cache)
        if not data:
            self.trash.pack_start(dp.label("storage.py did not answer", "ctl-sub"), False, False, 0)
            self.trash.show_all()
            return
        for t in data["trash"]:
            grid, _ = row("\uf1f8", trash_title(t), trash_sub(t), dp.label(human(t["size"]), "ctl-value"))
            self.trash.pack_start(grid, False, False, 0)
        self.trash.pack_start(wrapped("Each disk has its own trash; space frees once it is emptied."),
                              False, False, 0)
        self.trash.show_all()

        c = data["cache"]
        grid, _ = row("\uf1c0", "~/.cache", "kept by programs to load faster", dp.label(human(c["total"]), "ctl-value"))
        self.cache.pack_start(grid, False, False, 0)
        self.cache_row("thumbnails", "Thumbnails", c["thumbnails"],
                       "previews in Files; redrawn as needed",
                       ("clear-thumbnails",))
        for entry in [e for e in c["top"] if e["name"] != "thumbnails"][:CACHE_ROWS]:
            self.cache_row(entry["name"], f"~/.cache/{entry['name']}", entry["size"], "",
                           ("clear-cache", entry["name"]))
        self.cache.show_all()

    def cache_row(self, key, title, size, sub, args):
        line = Gtk.Box(spacing=10)
        name = dp.label(title, "ctl-title")
        name.set_size_request(220, -1)
        name.set_ellipsize(3)       # Pango.EllipsizeMode.END
        line.pack_start(name, False, False, 0)
        if sub:
            line.pack_start(wrapped(sub), True, True, 0)
        else:
            line.pack_start(Gtk.Box(), True, True, 0)
        line.pack_start(dp.label(human(size), "ctl-value"), False, False, 0)
        links = Gtk.Box(spacing=6)

        def restore():
            clear(links)
            links.pack_start(link("Clear…", lambda: self.confirm(
                links, f"Delete {human(size)}?", "Yes, clear it", (STORAGE, *args), restore)), False, False, 0)
            links.show_all()
        restore()
        line.pack_start(links, False, False, 0)
        self.cache.pack_start(line, False, False, 0)
