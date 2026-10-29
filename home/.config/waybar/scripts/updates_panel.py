#!/usr/bin/env python3
"""Updates panel -- what the updates pill opens.

    UPDATES  ·  4 packages, 1 flatpak                         Re-check
    checked 3 min ago
    PACKAGES
    gstreamer1-plugins-ugly                        1:1.28.8-1.fc44
    ...
    FLATPAKS
    org.mozilla.firefox
                                                   [ Upgrade ]

The list is the last check updates.sh made (the pill's own script), cached in
$XDG_RUNTIME_DIR/waybar-updates.tsv, so the panel opens at once instead of
running dnf. Re-check signals the pill (bar_signals.py "updates"); it runs the check again,
rewrites the cache, and the panel redraws when the file changes -- one dnf
run, shared by both.

A new kernel in the list gets a line of its own: with the NVIDIA driver
loaded (nvidia_driver; any other GPU needs no such check and is told so),
that is the update that can leave it without a module, and the reason Upgrade runs
safe-upgrade.sh (btrfs snapshot, dnf, build + check the NVIDIA module for the
new kernel, flatpak, firmware listing) in a terminal rather than a bare dnf.
When it finishes, safe-upgrade.sh itself redraws the updates and reboot pills
(bar_signals.py "updates", "reboot"): this card has closed by then.

The list scrolls; the card is panelui.CARD_HEIGHT tall, the same as the
notification panel next to it on the bar.

    updates_panel.py [x,y]   desktop position of the click that opened it
"""

import os
import subprocess
import sys
import time

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk, Pango  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import panelui  # noqa: E402
import themecolors  # noqa: E402

CACHE = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "waybar-updates.tsv")
UPGRADE = os.path.join(HERE, "safe-upgrade.sh")
WIDTH = 460
MAGENTA = themecolors.hex("danger", "#ff2a6d")   # the theme's color.danger


def read_cache():
    data = {"checked": 0, "status": "unknown", "pkgs": [], "flatpaks": []}
    try:
        with open(CACHE) as handle:
            for line in handle:
                f = line.rstrip("\n").split("\t")
                if f[0] == "checked" and len(f) > 1:
                    data["checked"] = int(f[1])
                elif f[0] == "status" and len(f) > 1:
                    data["status"] = f[1]
                elif f[0] == "pkg" and len(f) > 2:
                    data["pkgs"].append((f[1], f[2]))
                elif f[0] == "flatpak" and len(f) > 1:
                    data["flatpaks"].append(f[1])
    except (OSError, ValueError):
        return None
    return data


def ago(epoch):
    if not epoch:
        return "never checked"
    minutes = int(time.time() - epoch) // 60
    if minutes < 1:
        return "checked just now"
    if minutes < 60:
        return f"checked {minutes} min ago"
    return f"checked {minutes // 60} h {minutes % 60:02d} min ago"


def label(text, cls, xalign=0.0):
    widget = Gtk.Label(label=text)
    widget.get_style_context().add_class(cls)
    widget.set_xalign(xalign)
    return widget


def redraw_pill(name):
    """Redraw a bar pill by its name in ~/.config/hypr/scripts/bar_signals.py
    (the one table of signal numbers); a direct kill, no pkill fork."""
    hypr = os.path.expanduser("~/.config/hypr/scripts")
    if hypr not in sys.path:
        sys.path.insert(0, hypr)
    try:
        import bar_signals
        bar_signals.poke(name)
    except Exception:       # no bar, or no hypr scripts: nothing to redraw
        pass


def nvidia_driver():
    """Is the NVIDIA kernel driver loaded? Only then is a new kernel worth a
    module check (safe-upgrade.sh skips it otherwise). /sys, no fork."""
    return os.path.isdir("/sys/module/nvidia")


class Updates(panelui.Panel):
    def build(self):
        self.card.set_size_request(WIDTH, panelui.CARD_HEIGHT)
        self.mtime = 0
        self.waiting = False

        head = Gtk.Box(spacing=8)
        self.title = label("UPDATES", "kb-heading")
        head.pack_start(self.title, True, True, 0)
        self.recheck = Gtk.Button(label="Re-check")
        self.recheck.get_style_context().add_class("ctl-link")
        self.recheck.set_valign(Gtk.Align.START)
        self.recheck.connect("clicked", lambda _b: self.check())
        head.pack_end(self.recheck, False, False, 0)
        self.card.pack_start(head, False, False, 0)

        self.when = label("", "ctl-sub")
        self.card.pack_start(self.when, False, False, 0)
        self.kernel = label("", "ctl-sub")
        self.kernel.set_line_wrap(True)
        self.kernel.set_no_show_all(True)
        self.card.pack_start(self.kernel, False, False, 0)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)
        scroll.set_margin_top(6)
        self.body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        scroll.add(self.body)
        self.card.pack_start(scroll, True, True, 0)

        self.upgrade = Gtk.Button(label="Upgrade")
        self.upgrade.get_style_context().add_class("dev-pick")
        self.upgrade.set_halign(Gtk.Align.END)
        self.upgrade.set_margin_top(6)
        self.upgrade.set_tooltip_text("In a terminal: btrfs snapshot, dnf upgrade, "
                                      + ("NVIDIA module check for the new kernel, " if nvidia_driver() else "")
                                      + "flatpak update, firmware list")
        self.upgrade.connect("clicked", lambda _b: self.run_upgrade())
        self.card.pack_start(self.upgrade, False, False, 0)
        self.draw()

    def on_ready(self):
        GLib.timeout_add(1000, self.poll)

    # -- data ------------------------------------------------------------------
    def poll(self):
        try:
            mtime = os.path.getmtime(CACHE)
        except OSError:
            mtime = 0
        if mtime != self.mtime:
            self.waiting = False
            self.draw()
        else:
            self.when.set_text("checking..." if self.waiting else ago(self.data["checked"] if self.data else 0))
        return True

    def check(self):
        self.waiting = True
        self.recheck.set_sensitive(False)
        self.when.set_text("checking...")
        redraw_pill("updates")

    def run_upgrade(self):
        try:
            subprocess.Popen(["kitty", "-e", UPGRADE], stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True)
        except OSError:
            pass
        self.quit()

    # -- drawing ----------------------------------------------------------------
    def draw(self):
        try:
            self.mtime = os.path.getmtime(CACHE)
        except OSError:
            self.mtime = 0
        self.data = data = read_cache()
        self.recheck.set_sensitive(not self.waiting)
        for child in self.body.get_children():
            self.body.remove(child)

        if data is None:
            self.title.set_text("UPDATES")
            self.when.set_text("no check yet -- Re-check runs one")
            self.upgrade.set_sensitive(False)
            self.body.show_all()
            return

        pkgs, flatpaks = data["pkgs"], data["flatpaks"]
        counts = []
        if pkgs:
            counts.append(f"{len(pkgs)} package{'s' * (len(pkgs) != 1)}")
        if flatpaks:
            counts.append(f"{len(flatpaks)} flatpak{'s' * (len(flatpaks) != 1)}")
        self.title.set_text("UPDATES" + (f"  ·  {', '.join(counts)}" if counts else ""))
        status = {"timeout": "  ·  last check timed out (mirrors slow?)",
                  "error": "  ·  last check failed"}.get(data["status"], "")
        self.when.set_text(("checking..." if self.waiting else ago(data["checked"])) + status)

        if any(name.startswith("kernel-core") for name, _v in pkgs):
            self.kernel.set_markup(
                f"<span foreground='{MAGENTA}'>Includes a new kernel</span> -- "
                + ("Upgrade builds and checks the NVIDIA module for it and says whether a reboot is safe."
                   if nvidia_driver() else "Upgrade snapshots / first; reboot when it is done."))
            self.kernel.show()
        else:
            self.kernel.hide()

        if not pkgs and not flatpaks:
            self.body.pack_start(label("System is up to date", "ctl-sub"), False, False, 0)
        if pkgs:
            self.body.pack_start(label("PACKAGES", "kb-heading"), False, False, 0)
            grid = Gtk.Grid(column_spacing=12, row_spacing=2)
            for row, (name, version) in enumerate(sorted(pkgs)):
                base, _dot, arch = name.rpartition(".")
                pkg = label(base or name, "sn-value")
                pkg.set_hexpand(True)
                pkg.set_ellipsize(Pango.EllipsizeMode.END)
                pkg.set_width_chars(18)
                pkg.set_tooltip_text(name)
                grid.attach(pkg, 0, row, 1, 1)
                grid.attach(label(version, "sn-label", 1.0), 1, row, 1, 1)
            self.body.pack_start(grid, False, False, 0)
        if flatpaks:
            head = label("FLATPAKS", "kb-heading")
            head.set_margin_top(8)
            self.body.pack_start(head, False, False, 0)
            for app in sorted(flatpaks):
                row = label(app, "sn-value")
                row.set_ellipsize(Pango.EllipsizeMode.END)
                self.body.pack_start(row, False, False, 0)
        self.upgrade.set_sensitive(bool(pkgs or flatpaks))
        self.body.show_all()


if __name__ == "__main__":
    panelui.run(Updates)
