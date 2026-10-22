#!/usr/bin/env python3
"""Disks panel — what the disk pill opens.

The pill can only follow one path (waybar's disk module takes a single
"path"), and it follows /. This lists every physical disk instead, with each
filesystem on it: where it is mounted, how full it is, and a bar that turns
yellow at 85% and magenta at 95% — the same thresholds as the pill's
warning/critical states. Click a filesystem to open it in the file manager.

Everything comes from one `lsblk -J -b` call (read_disks() in disk.py, which
the pill uses too), so filesystems inside LVM or partitions show up under the
disk that holds them.

Two columns, like the CPU and GPU cards: the disks on the left, and on the
right first BIGGEST FILES -- per drive, its BIG_ROWS largest files that this
user can see (big_files.py: a `find` per drive at idle priority, kept in a
cache file; shown from there at once and rescanned in the background when
older than an hour, or on "Scan again"); a click opens the file's folder with
it selected. Delete on a row opens a question under it -- the whole path and
size, then "Move to Trash" (one more click; said plainly that a drive's trash
still holds the space) or "Delete for good" (two more: it turns into "Sure?
Gone for good"), or Cancel. big_files.py delete does it, after checking the
file is still the one listed and nothing has it open. A file already in a
trash folder offers only "Delete for good". Then SHADER CACHES: Steam's per-game caches across every library,
the driver's own, and a Clear button on each (shader_cache.py does the work
and explains what is safe). A Clear takes two clicks -- the first arms it --
and both the scan and the clearing run off the GTK thread, so a 40 GB delete
never freezes the panel.

    disk_panel.py [x,y]   desktop position of the click that opened the panel
"""

import json
import os
import subprocess
import sys
import threading
import time

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import panelui  # noqa: E402
import themecolors  # noqa: E402
from disk import (CRITICAL, WARNING, human, mountpoints, percent,  # noqa: E402
                  read_disks)

POLL_MS = 10000             # usage moves slowly; this only catches a big copy
SHADER_CACHE = os.path.join(HERE, "shader_cache.py")
SHADER_ROWS = 12            # biggest per-game caches listed (the right column is tall)
BIG_FILES = os.path.join(HERE, "big_files.py")
BIG_ROWS = 4                # biggest files listed per drive
ARM_SECONDS = 4
FILE_MANAGER = "nautilus"
TRANSPORT = {"nvme": "NVMe", "sata": "SATA", "usb": "USB", "ata": "ATA"}


def big_files_cache():
    """big_files.py's kept result (its CACHE)."""
    return os.path.join(os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"),
                        "hypr", "big-files.json")


class Disks(panelui.Panel):
    def build(self):
        left, right = panelui.columns(self.card)

        head = Gtk.Label(label="DISKS")
        head.get_style_context().add_class("kb-heading")
        head.set_halign(Gtk.Align.START)
        left.pack_start(head, False, False, 0)

        self.body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        left.pack_start(self.body, False, False, 0)

        button = Gtk.Button(label="Open Disks")
        button.get_style_context().add_class("ctl-link")
        button.set_halign(Gtk.Align.END)
        button.connect("clicked", lambda _b: self.launch(["gnome-disks"]))
        left.pack_start(button, False, False, 0)

        head = Gtk.Box(spacing=8)
        title = Gtk.Label(label="BIGGEST FILES")
        title.get_style_context().add_class("kb-heading")
        head.pack_start(title, False, False, 0)
        self.rescan = Gtk.Button(label="Scan again")
        self.rescan.get_style_context().add_class("ctl-link")
        self.rescan.connect("clicked", lambda _b: self.scan_big(force=True))
        head.pack_end(self.rescan, False, False, 0)
        right.pack_start(head, False, False, 0)
        self.big = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        right.pack_start(self.big, False, False, 0)
        self.big_scanning = False
        self.big_data = None
        self.big_asking = None      # the path whose Delete question is open
        self.big_sure = 0.0         # "Delete for good" armed at (monotonic)
        self.big_working = None     # the path being deleted now
        self.big_msg = ""

        head = Gtk.Label(label="SHADER CACHES")
        head.get_style_context().add_class("kb-heading")
        head.set_halign(Gtk.Align.START)
        right.pack_start(head, False, False, 0)
        self.shaders = Gtk.Grid(column_spacing=12, row_spacing=2)
        right.pack_start(self.shaders, False, False, 0)
        self.shader_data = None
        self.armed = {}             # key -> monotonic time armed
        self.working = None         # what is being cleared right now
        self.shader_note("scanning...")

        self.signature = None
        self.refresh()

    def on_ready(self):
        GLib.timeout_add(POLL_MS, self.poll)
        self.scan_shaders()
        self.scan_big()

    def poll(self):
        self.refresh()
        return True

    # -- content ------------------------------------------------------------
    def refresh(self):
        disks = read_disks()
        # Rebuilt only when something actually changed: a rebuild while the
        # pointer is over a row would drop its hover state for a frame.
        signature = json.dumps(disks, sort_keys=True, default=str)
        if signature == self.signature:
            return
        self.signature = signature

        for child in self.body.get_children():
            self.body.remove(child)
        if disks is None:
            self.body.pack_start(self.note("lsblk failed"), False, False, 0)
        else:
            for index, (disk, filesystems) in enumerate(disks):
                if index:
                    sep = Gtk.Box()
                    sep.get_style_context().add_class("ctl-sep")
                    self.body.pack_start(sep, False, False, 0)
                self.body.pack_start(self.disk_block(disk, filesystems),
                                     False, False, 0)
        self.body.show_all()

    def disk_block(self, disk, filesystems):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        box.get_style_context().add_class("dk-disk")

        title = Gtk.Label(label=(disk.get("model") or disk["name"]).strip())
        title.get_style_context().add_class("ctl-title")
        title.set_halign(Gtk.Align.START)
        box.pack_start(title, False, False, 0)

        bits = [disk["name"], TRANSPORT.get(disk.get("tran") or "",
                                           (disk.get("tran") or "").upper()),
                human(disk.get("size"))]
        if disk.get("rm"):
            bits.append("removable")
        box.pack_start(self.note(" · ".join(b for b in bits if b)), False, False, 0)

        if not filesystems:
            # A disk with nothing readable on it directly: an LVM physical
            # volume whose logical volume lsblk files under its other disk, or
            # simply an empty one.
            kids = disk.get("children") or []
            what = ("LVM physical volume" if disk.get("fstype") == "LVM2_member"
                    else "no filesystem" if not kids else "no mounted filesystem")
            box.pack_start(self.note(what), False, False, 0)
        for fs in filesystems:
            box.pack_start(self.fs_row(fs), False, False, 0)
        return box

    def fs_row(self, fs):
        mounts = mountpoints(fs)
        swap = fs.get("fstype") == "swap"
        size, used = fs.get("fssize"), fs.get("fsused")
        used_pct = percent(fs)

        grid = Gtk.Grid(column_spacing=10, row_spacing=2)
        name = Gtk.Label(label=", ".join(mounts) if mounts else
                         ("swap" if swap else "not mounted"))
        name.get_style_context().add_class("sn-value")
        name.set_halign(Gtk.Align.START)
        name.set_hexpand(True)
        grid.attach(name, 0, 0, 1, 1)

        detail = " ".join(b for b in (fs.get("label"), fs.get("fstype")) if b)
        sub = Gtk.Label(label=detail)
        sub.get_style_context().add_class("sn-label")
        sub.set_halign(Gtk.Align.END)
        grid.attach(sub, 1, 0, 1, 1)

        if used_pct is not None:
            bar = Gtk.LevelBar(min_value=0, max_value=100, value=used_pct)
            bar.set_mode(Gtk.LevelBarMode.CONTINUOUS)
            # GTK's own offsets would colour it in its own palette; the
            # classes below do it in ours.
            for offset in ("low", "high", "full"):
                bar.remove_offset_value(offset)
            style = bar.get_style_context()
            style.add_class("dk-bar")
            if used_pct >= CRITICAL:
                style.add_class("critical")
            elif used_pct >= WARNING:
                style.add_class("warning")
            bar.set_valign(Gtk.Align.CENTER)
            grid.attach(bar, 0, 1, 1, 1)

            value = Gtk.Label(
                label=f"{human(used)} / {human(size)}  {used_pct:3.0f}%")
            value.get_style_context().add_class("sn-label")
            value.set_halign(Gtk.Align.END)
            grid.attach(value, 1, 1, 1, 1)

        if not mounts:
            grid.get_style_context().add_class("dk-fs")
            return grid
        # The whole row is the click target, not just the path.
        button = Gtk.Button()
        button.add(grid)
        button.get_style_context().add_class("dk-fs")
        button.set_tooltip_text(f"Open {mounts[0]} in {FILE_MANAGER}")
        button.connect("clicked",
                       lambda _b: self.launch([FILE_MANAGER, mounts[0]]))
        return button

    # -- biggest files ------------------------------------------------------
    def scan_big(self, force=False):
        """The cached list at once; then, when it is old (or forced), a scan
        in the background and the list again when it is done."""
        def read(*args):
            try:
                out = subprocess.run([BIG_FILES, *args, "--json"], capture_output=True,
                                     text=True, timeout=3600).stdout
                return json.loads(out) if out.strip() else None
            except (OSError, subprocess.SubprocessError, ValueError):
                return None

        def work():
            data = read("cached")
            stale = force or not data or time.time() - data.get("scanned", 0) > 3600
            GLib.idle_add(self.show_big, data, stale)
            if stale:
                GLib.idle_add(self.show_big, read("scan"), False)
        if not self.big_scanning:
            threading.Thread(target=work, daemon=True).start()

    def show_big(self, data, scanning):
        self.big_data = data
        self.big_scanning = scanning
        self.rescan.set_sensitive(not scanning)
        for child in self.big.get_children():
            self.big.remove(child)
        if data:
            for drive in data.get("drives", []):
                if not drive["files"]:
                    continue
                name = Gtk.Label(label=f"{drive['drive']}  ·  {', '.join(drive['mounts'])}")
                name.get_style_context().add_class("sn-label")
                name.set_halign(Gtk.Align.START)
                name.set_ellipsize(3)
                self.big.pack_start(name, False, False, 0)
                for f in drive["files"][:BIG_ROWS]:
                    self.big.pack_start(self.big_row(f), False, False, 0)
        if self.big_msg:
            self.big.pack_start(self.note(self.big_msg), False, False, 0)
        if scanning:
            text = ("looking through the drives (a big hard disk takes a few minutes)..." if not data
                    else "scanning again...")
        elif data:
            mins = int((time.time() - data.get("scanned", 0)) // 60)
            text = (f"files of 100 MB and up you can see  ·  scanned "
                    f"{'just now' if mins < 1 else f'{mins} min ago' if mins < 120 else f'{mins // 60} h ago'}")
        else:
            text = "big_files.py found nothing to scan"
        self.big.pack_start(self.note(text), False, False, 0)
        self.big.show_all()
        return False

    def big_row(self, f):
        grid = Gtk.Grid(column_spacing=12)
        title = Gtk.Label(label=os.path.basename(f["path"]))
        title.get_style_context().add_class("sn-value")
        title.set_halign(Gtk.Align.START)
        title.set_hexpand(True)
        title.set_ellipsize(2)              # Pango.EllipsizeMode.MIDDLE: the end says what it is
        title.set_max_width_chars(38)
        grid.attach(title, 0, 0, 1, 1)
        size = Gtk.Label(label=human(f["size"]))
        size.get_style_context().add_class("sn-label")
        size.set_halign(Gtk.Align.END)
        grid.attach(size, 1, 0, 1, 1)
        home = os.path.expanduser("~")
        folder = os.path.dirname(f["path"])
        if folder == home or folder.startswith(home + "/"):
            folder = "~" + folder[len(home):]
        where = Gtk.Label(label=folder)     # which game a "re_chunk_000.pak" is
        where.get_style_context().add_class("sn-label")
        where.set_halign(Gtk.Align.START)
        where.set_ellipsize(1)              # Pango.EllipsizeMode.START: the near folders count
        where.set_max_width_chars(46)
        grid.attach(where, 0, 1, 2, 1)
        button = Gtk.Button()
        button.add(grid)
        button.get_style_context().add_class("dk-fs")
        button.set_tooltip_text(f["path"] + "\n\nClick: show it in its folder")
        button.connect("clicked", lambda _b: self.launch([FILE_MANAGER, "--select", f["path"]]))
        line = Gtk.Box(spacing=6)
        line.pack_start(button, True, True, 0)
        path = f["path"]
        delete = Gtk.Button(label="deleting..." if self.big_working == path else "Delete")
        delete.get_style_context().add_class("dev-pick")
        delete.set_valign(Gtk.Align.CENTER)
        delete.set_sensitive(self.big_working is None)
        delete.connect("clicked", lambda _b: self.ask_delete(None if self.big_asking == path else path))
        line.pack_start(delete, False, False, 0)
        if self.big_asking != path:
            return line
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.pack_start(line, False, False, 0)
        box.pack_start(self.delete_question(f), False, False, 0)
        return box

    def delete_question(self, f):
        """Under a row whose Delete was pressed: what exactly, and how."""
        path = f["path"]
        in_trash = "/Trash/" in path or "/.Trash-" in path
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.get_style_context().add_class("dk-ask")
        text = (f"Delete {path} ({human(f['size'])})?" +
                ("" if in_trash else "\nMove to Trash can be undone, but the space comes back only "
                 "when that drive's trash is emptied. Delete for good cannot be undone."))
        ask = Gtk.Label(label=text)
        ask.get_style_context().add_class("ctl-sub")
        ask.set_halign(Gtk.Align.START)
        ask.set_line_wrap(True)
        ask.set_max_width_chars(52)
        box.pack_start(ask, False, False, 0)
        buttons = Gtk.Box(spacing=6)
        if not in_trash:
            trash = Gtk.Button(label="Move to Trash")
            trash.get_style_context().add_class("dev-pick")
            trash.connect("clicked", lambda _b: self.do_delete(path, False))
            buttons.pack_start(trash, False, False, 0)
        armed = time.monotonic() - self.big_sure < ARM_SECONDS
        gone = Gtk.Button(label="Delete for good")
        gone.get_style_context().add_class("dev-pick")
        if armed:
            gone.get_style_context().add_class("active")
            gone.get_child().set_markup(
                f"<span foreground='{themecolors.hex('danger', '#ff2a6d')}'>Sure? Gone for good</span>")
        gone.connect("clicked", lambda _b: self.do_delete(path, True))
        buttons.pack_start(gone, False, False, 0)
        cancel = Gtk.Button(label="Cancel")
        cancel.get_style_context().add_class("ctl-link")
        cancel.connect("clicked", lambda _b: self.ask_delete(None))
        buttons.pack_start(cancel, False, False, 0)
        box.pack_start(buttons, False, False, 0)
        return box

    def ask_delete(self, path):
        self.big_asking, self.big_sure, self.big_msg = path, 0.0, ""
        self.show_big(self.big_data, self.big_scanning)

    def do_delete(self, path, for_good):
        if self.big_working:
            return
        if for_good and time.monotonic() - self.big_sure >= ARM_SECONDS:
            self.big_sure = time.monotonic()    # the first click only arms it
            self.show_big(self.big_data, self.big_scanning)
            GLib.timeout_add(ARM_SECONDS * 1000,
                             lambda: (self.show_big(self.big_data, self.big_scanning), False)[1])
            return
        self.big_sure, self.big_asking, self.big_working = 0.0, None, path
        self.big_msg = ""
        self.show_big(self.big_data, self.big_scanning)

        def work():
            try:
                out = subprocess.run([BIG_FILES, "delete", path, "--for-good" if for_good else "--trash"],
                                     capture_output=True, text=True, timeout=900)
                why = (out.stderr or "failed").strip() if out.returncode else ""
            except (OSError, subprocess.SubprocessError) as exc:
                why = str(exc)
            GLib.idle_add(done, why)

        def done(why):
            name = os.path.basename(path)
            self.big_working = None
            self.big_msg = (f"Not deleted: {why}" if why else
                            f"Deleted {name}" if for_good else f"Moved {name} to the trash")
            self.signature = None           # the bars on the left move
            self.refresh()
            try:
                with open(big_files_cache()) as handle:
                    self.big_data = json.load(handle)
            except (OSError, ValueError):
                pass
            self.show_big(self.big_data, self.big_scanning)
            return False
        threading.Thread(target=work, daemon=True).start()

    # -- shader caches ------------------------------------------------------
    def shader_note(self, text):
        for child in self.shaders.get_children():
            self.shaders.remove(child)
        self.shaders.attach(self.note(text), 0, 0, 3, 1)
        self.shaders.show_all()

    def scan_shaders(self):
        def work():
            try:
                out = subprocess.run([SHADER_CACHE, "scan"], capture_output=True,
                                     text=True, timeout=120).stdout
                data = json.loads(out)
            except (OSError, subprocess.SubprocessError, ValueError):
                data = None
            GLib.idle_add(self.show_shaders, data)
        threading.Thread(target=work, daemon=True).start()

    def show_shaders(self, data):
        self.shader_data = data
        if data is None:
            self.shader_note("shader_cache.py scan failed")
            return False
        for child in self.shaders.get_children():
            self.shaders.remove(child)
        rows = []
        if data["orphans"]:
            rows.append(("orphans", f"Uninstalled games ({data['orphans']})",
                         data["orphans_size"], False))
        for c in data["steam"][:SHADER_ROWS]:
            rows.append((c["appid"], c["name"], c["size"], c["busy"]))
        for o in data["other"]:
            rows.append((o["key"], o["name"], o["size"], False))
        total = self.note(f"Steam: {human(data['steam_total'])} in {len(data['steam'])} games"
                          " -- rebuilt on demand, saves are not in here")
        self.shaders.attach(total, 0, 0, 3, 1)
        now = time.monotonic()
        self.armed = {k: t for k, t in self.armed.items() if now - t < ARM_SECONDS}
        for i, (key, name, size, busy) in enumerate(rows, start=1):
            title = Gtk.Label(label=name)
            title.get_style_context().add_class("sn-value")
            title.set_halign(Gtk.Align.START)
            title.set_hexpand(True)
            title.set_ellipsize(3)          # Pango.EllipsizeMode.END
            title.set_max_width_chars(34)
            self.shaders.attach(title, 0, i, 1, 1)
            size_label = Gtk.Label(label=human(size))
            size_label.get_style_context().add_class("sn-label")
            size_label.set_halign(Gtk.Align.END)
            self.shaders.attach(size_label, 1, i, 1, 1)
            if busy:
                text = "in use"
            elif self.working == key:
                text = "clearing..."
            elif key in self.armed:
                text = "Sure?"
            else:
                text = "Clear"
            button = Gtk.Button(label=text)
            button.get_style_context().add_class("dev-pick")
            button.set_sensitive(not busy and self.working is None and size > 0)
            if key in self.armed:
                button.get_style_context().add_class("active")
                button.get_child().set_markup(f"<span foreground='{themecolors.hex('danger', '#ff2a6d')}'>Sure?</span>")
            button.connect("clicked", lambda _b, k=key: self.clear_shader(k))
            self.shaders.attach(button, 2, i, 1, 1)
        self.shaders.show_all()
        return False

    def clear_shader(self, key):
        if key not in self.armed:
            self.armed = {key: time.monotonic()}
            self.show_shaders(self.shader_data)
            # Disarm by itself, so a stray click later is only ever an arm.
            GLib.timeout_add(ARM_SECONDS * 1000,
                             lambda: (self.show_shaders(self.shader_data), False)[1])
            return
        self.armed = {}
        self.working = key
        self.show_shaders(self.shader_data)

        def work():
            subprocess.run([SHADER_CACHE, "clean", key], capture_output=True, timeout=600)
            GLib.idle_add(done)

        def done():
            self.working = None
            self.signature = None       # disk usage changed: redraw the bars
            self.refresh()
            self.scan_shaders()
            return False
        threading.Thread(target=work, daemon=True).start()

    @staticmethod
    def note(text):
        label = Gtk.Label(label=text)
        label.get_style_context().add_class("ctl-sub")
        label.set_halign(Gtk.Align.START)
        return label

    def launch(self, cmd):
        try:
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True)
        except OSError:
            pass
        self.quit()


def main():
    panelui.run(Disks)


if __name__ == "__main__":
    main()
