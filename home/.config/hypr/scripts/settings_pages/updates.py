"""Settings page: software updates (software-updates.py).

    UPDATES               what is waiting: packages (security ones first and
                          marked with their severity), flatpaks, when the
                          last check ran; Check now, Update now
    RESTART               reboot needed?, the NVIDIA module for the newest
                          kernel, what the last safe-upgrade.sh run said
    HISTORY               the last update and the latest dnf transactions,
                          each with what it changed
    SNAPSHOTS             whether snapper snapshots every update (status only:
                          setting it up, Snapshot now and Undo are on the
                          Maintenance page -- Open Maintenance)
    FIRMWARE              fwupd's pending firmware, listed only
    AUTOMATIC CHECKS      how often the updates pill checks by itself

Everything comes from software-updates.py, the one backend the bar pill's
cache, the launcher and this page share; every part of it that runs dnf,
needs-restarting, snapper or fwupd goes through background(), so the page
draws at once and fills in. "Update now" opens safe-upgrade.sh in a terminal
-- the same run as the pill's Upgrade button, never anything quieter -- so the
snapshot, the NVIDIA module check and the "safe to reboot" verdict always
happen. "Check now" asks the pill to check (one dnf run, shared) and the page
watches the pill's cache file to redraw when it lands.
"""
from gi.repository import GLib, Gtk, Pango  # noqa: F401

from .common import *  # noqa: F401,F403  (the shared helpers and paths)

import os  # noqa: E402
import subprocess  # noqa: E402
import time  # noqa: E402

PAGE = {"id": "updates", "title": "Software updates", "icon": "\uf49e", "group": "System", "order": 70,
        "keywords": ["update", "upgrade", "actualizaciones", "dnf", "packages", "flatpak", "security updates",
                     "reboot needed", "kernel", "nvidia module", "firmware", "fwupd", "dnf history", "snapper",
                     "check for updates"]}

BACKEND = os.path.join(HYPR, "software-updates.py")
SETTINGS = os.path.join(HYPR, "settings.py")
CACHE = os.environ.get("SOFTWARE_UPDATES_CACHE") or os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"),
                                                                 "waybar-updates.tsv")   # the pill's cache
LIST_MAX = 40               # package rows shown before "... and N more"
CHECK_WAIT_S = 200          # updates.sh waits up to 180 s for the lock, then 150 s for dnf
INTERVAL_CHIPS = [("1h", "Hourly"), ("3h", "3 h"), ("6h", "6 h"), ("12h", "12 h"), ("24h", "Daily"),
                  ("login", "At login")]
INTERVAL_SECONDS = {"1h": 3600, "3h": 10800, "6h": 21600, "12h": 43200, "24h": 86400}
SEVERITY_ORDER = {"Critical": 0, "Important": 1, "Moderate": 2, "Low": 3}


def plural(n, word):
    return f"{n} {word}{'s' if n != 1 else ''}"


def when(epoch):
    """An epoch as the page says it: "today 09:16", "yesterday 21:30",
    "Mon 12 Oct 08:00"."""
    if not epoch:
        return "never"
    t = time.localtime(epoch)
    today = time.localtime()
    days = (time.mktime(today[:3] + (0, 0, 0, 0, 0, -1)) - time.mktime(t[:3] + (0, 0, 0, 0, 0, -1))) // 86400
    hm = time.strftime("%H:%M", t)
    return f"today {hm}" if days == 0 else f"yesterday {hm}" if days == 1 else time.strftime("%a %d %b %H:%M", t)


def small(text, wrap=True):
    lab = dp.label(text, "ctl-sub")
    if wrap:
        lab.set_line_wrap(True)
        lab.set_max_width_chars(90)
    return lab


def vbox():
    return Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)


def describe_cmd(t):
    """The transaction's command line, options and all, cut to fit a line."""
    cmd = t.get("command_line") or "PackageKit (Software)"
    return cmd if len(cmd) <= 60 else cmd[:59] + "…"


def copy(text):
    try:
        subprocess.run(["wl-copy", text], timeout=5)
    except (OSError, subprocess.SubprocessError):
        pass


class Page:
    def __init__(self):
        self.widget = page_box()
        w = self.widget
        self.checking_since = 0
        self.cache_mtime = None
        self.interval_busy = False
        self.last_pending = None        # what show_pending drew, for the summary line
        self.interval = None            # the pill's interval, from show_system
        self.interval_error = None      # why the last change did not save, until the next one

        w.pack_start(heading("UPDATES"), False, False, 0)
        self.summary_row, self.summary_sub = row("\uf49e", "Looking…", "")
        w.pack_start(self.summary_row, False, False, 0)
        self.check_btn = link("Check now", self.check)
        w.pack_start(links_row(self.check_btn, link("Update now…", lambda: spawn(BACKEND, "upgrade"))),
                     False, False, 0)
        self.upgrade_note = small("Update now opens safe-upgrade.sh in a terminal: a snapshot of the system, "
                                  "dnf upgrade (it asks for your password), the NVIDIA module built and checked "
                                  "for the new kernel, flatpaks, then a firmware listing and whether a reboot "
                                  "is safe.")
        w.pack_start(self.upgrade_note, False, False, 0)
        self.pending = vbox()
        w.pack_start(self.pending, False, False, 0)

        w.pack_start(sep(), False, False, 0)
        w.pack_start(heading("RESTART"), False, False, 0)
        self.restart = vbox()
        w.pack_start(self.restart, False, False, 0)

        w.pack_start(sep(), False, False, 0)
        w.pack_start(heading("HISTORY"), False, False, 0)
        self.last = vbox()              # the last update, from show_system
        w.pack_start(self.last, False, False, 0)
        self.history = vbox()
        w.pack_start(self.history, False, False, 0)

        w.pack_start(sep(), False, False, 0)
        w.pack_start(heading("SNAPSHOTS BEFORE UPDATES"), False, False, 0)
        self.snaps = vbox()
        w.pack_start(self.snaps, False, False, 0)

        w.pack_start(sep(), False, False, 0)
        w.pack_start(heading("FIRMWARE"), False, False, 0)
        self.firmware = vbox()
        w.pack_start(self.firmware, False, False, 0)

        w.pack_start(sep(), False, False, 0)
        w.pack_start(heading("AUTOMATIC CHECKS"), False, False, 0)
        self.interval_row, self.interval_sub = row("\uf017", "The updates pill checks", "")
        w.pack_start(self.interval_row, False, False, 0)
        self.chips = Chips(self.set_interval)
        self.chips.widget.set_max_children_per_line(len(INTERVAL_CHIPS))
        w.pack_start(self.chips.widget, False, False, 0)
        w.pack_start(small("Checks only download the package lists (as you, no password) and never install "
                           "anything; they run at the lowest CPU and disk priority. Updates are installed only "
                           "when you press Update now."), False, False, 0)

    # -- loading -----------------------------------------------------------------
    def refresh(self):
        for box, text in ((self.pending, "reading the last check…"), (self.restart, "checking…"),
                          (self.history, "reading dnf history…"), (self.snaps, "checking…"),
                          (self.firmware, "asking fwupd…")):
            clear(box)
            box.pack_start(small(text), False, False, 0)
        self.widget.show_all()
        self.load_pending()
        background(lambda: run_json(BACKEND, "system", "--json", timeout=90), self.show_system)
        background(lambda: run_json(BACKEND, "history", "5", "--json", timeout=40), self.show_history)
        background(lambda: run_json(BACKEND, "firmware", "--json", timeout=100), self.show_firmware)

    def load_pending(self):
        background(lambda: run_json(BACKEND, "pending", "--json", timeout=70), self.show_pending)

    def check(self):
        """Ask the pill to check, then watch its cache for the new result."""
        try:
            self.cache_mtime = os.path.getmtime(CACHE)
        except OSError:
            self.cache_mtime = 0
        self.checking_since = time.time()
        self.check_btn.set_sensitive(False)
        self.summary_sub.set_text("checking now… (a slow mirror can take a couple of minutes)")
        background(lambda: run(BACKEND, "check", timeout=10), lambda _r: None)
        GLib.timeout_add(1000, self.watch_check)

    def watch_check(self):
        try:
            mtime = os.path.getmtime(CACHE)
        except OSError:
            mtime = 0
        if mtime != self.cache_mtime or time.time() - self.checking_since > CHECK_WAIT_S:
            self.checking_since = 0
            self.check_btn.set_sensitive(True)
            self.load_pending()
            return False
        return True

    def set_interval(self, key):
        if self.interval_busy:
            return
        self.interval_busy = True
        self.interval_error = None
        self.interval_sub.set_text("saving… (the bar restarts to pick it up)")
        background(lambda: run_json(BACKEND, "interval", key, "--json", timeout=30), self.interval_saved)

    def interval_saved(self, out):
        """out: the backend's {"interval", "value"} once saved; None when it
        refused or could not write the waybar config (said under the chips
        until the next change, instead of silently showing the old value)."""
        self.interval_busy = False
        if not out:
            self.interval_error = "could not save it: run `software-updates.py interval` in a terminal to see why"
        background(lambda: run_json(BACKEND, "system", "--json", timeout=90), self.show_system)

    # -- drawing -----------------------------------------------------------------
    def show_pending(self, p):
        clear(self.pending)
        if self.checking_since:
            self.check_btn.set_sensitive(False)
        if not p:
            self.summary_row.get_child_at(1, 0).set_text("Could not read the updates")
            self.summary_sub.set_text("software-updates.py did not answer")
            self.pending.show_all()
            return
        title = self.summary_row.get_child_at(1, 0)
        if not p["cache"]:
            title.set_text("Not checked yet")
            self.summary_sub.set_text("no check since you logged in -- Check now runs one")
            self.pending.show_all()
            return
        pkgs, flatpaks = p["pkgs"], p["flatpaks"]
        total = len(pkgs) + len(flatpaks)
        title.set_text("Up to date" if not total else f"{plural(total, 'update')} waiting")
        parts = []
        if pkgs:
            parts.append(plural(len(pkgs), "package"))
            if p["security"]:
                worst = min((x["security"] for x in pkgs if x["security"]),
                            key=lambda s: SEVERITY_ORDER.get(s, 9))
                parts.append(f"{p['security']} security (worst: {worst})")
            elif p["security"] is None:
                parts.append("security status unknown")
        if flatpaks:
            parts.append(plural(len(flatpaks), "flatpak"))
        status = {"timeout": "the last check timed out (mirrors slow?)", "error": "the last check failed",
                  }.get(p["status"])
        self.summary_parts = parts + [f"checked {when(p['checked'])}"] + ([status] if status else [])
        self.last_pending = p
        self.show_summary()

        if p["kernel"]:
            self.pending.pack_start(small("Includes a new kernel: Update now builds and checks the NVIDIA module "
                                          "for it and says whether a reboot is safe."), False, False, 0)
        if pkgs:
            ordered = sorted(pkgs, key=lambda x: (SEVERITY_ORDER.get(x["security"], 8) if x["security"] else 9,
                                                  x["name"]))
            grid = Gtk.Grid(column_spacing=12, row_spacing=2)
            grid.set_margin_start(32)
            for i, pkg in enumerate(ordered[:LIST_MAX]):
                base, _dot, arch = pkg["name"].rpartition(".")
                name = dp.label(base or pkg["name"], "sn-value")
                name.set_hexpand(True)
                name.set_ellipsize(Pango.EllipsizeMode.END)
                name.set_tooltip_text(pkg["name"] + (f"\n{pkg['advisory']}" if pkg["advisory"] else ""))
                grid.attach(name, 0, i, 1, 1)
                grid.attach(dp.label(f"security · {pkg['security']}" if pkg["security"] else "", "ctl-value"),
                            1, i, 1, 1)
                grid.attach(dp.label(pkg["version"], "sn-label", 1.0), 2, i, 1, 1)
            self.pending.pack_start(grid, False, False, 0)
            if len(ordered) > LIST_MAX:
                self.pending.pack_start(small(f"… and {len(ordered) - LIST_MAX} more"), False, False, 0)
        if flatpaks:
            fl = small("Flatpaks:  " + ",  ".join(flatpaks))
            fl.set_margin_start(32)
            self.pending.pack_start(fl, False, False, 0)
        self.pending.show_all()

    def show_summary(self):
        """The line under "N updates waiting": the counts, the last check and,
        once show_system knows the interval, when the pill checks next at the
        latest (its timer runs from the bar's start, so a check you asked for
        does not move it -- hence "by")."""
        if self.last_pending is None:
            return
        parts = list(self.summary_parts)
        checked = self.last_pending["checked"]
        if isinstance(self.interval, int) and checked and checked + self.interval > time.time():
            parts.append(f"next automatic check by {time.strftime('%H:%M', time.localtime(checked + self.interval))}")
        line = "  ·  ".join(parts)
        if self.checking_since:
            line = "checking now…  ·  " + line
        self.summary_sub.set_text(line)

    def show_system(self, s):
        for box in (self.restart, self.snaps, self.last):
            clear(box)
        if not s:
            for box in (self.restart, self.snaps):
                box.pack_start(small("software-updates.py did not answer"), False, False, 0)
                box.show_all()
            return
        self.show_restart(s)
        self.show_last(s.get("last_update"))
        self.show_snaps(s["snapshots"])
        self.show_interval(s["interval"])
        self.interval = s["interval"]
        self.show_summary()

    def show_restart(self, s):
        r = s["reboot"]
        title = {True: "Restart needed", False: "No restart needed", None: "Restart: could not tell"}[r["needed"]]
        sub = (("  ·  ".join(r["reasons"][:4]) + ("  ·  …" if len(r["reasons"]) > 4 else "")) if r["reasons"]
               else "nothing core changed since this boot" if r["needed"] is False
               else "needs-restarting did not answer" if r["needed"] is None else "")
        grid, _ = row("\uf01e", title, f"running kernel {s['running_kernel']}"
                      + (f"  ·  newest installed {s['newest_kernel']}" if s["newest_kernel"] != s["running_kernel"]
                         else "") + (f"\n{sub}" if sub else ""))
        self.restart.pack_start(grid, False, False, 0)

        n = s["nvidia"]
        if n["verdict"] != "none":
            text = {"ok": ("NVIDIA driver ready for the newest kernel",
                           f"driver {n['driver']}  ·  module {n['module']} built for {n['kernel']}"
                           + ("  ·  safe to reboot into it" if s["newest_kernel"] != s["running_kernel"] else "")),
                    "missing": ("Do not reboot yet: no NVIDIA module for the newest kernel",
                                f"driver {n['driver']}, kernel {n['kernel']}: run Update now (it builds the "
                                f"module) or `sudo akmods --force --kernels {n['kernel']}`; the running kernel "
                                "still works"),
                    "mismatch": ("Do not reboot yet: the NVIDIA module is older than the driver",
                                 f"module {n['module']} for {n['kernel']}, driver {n['driver']}: run "
                                 f"`sudo akmods --force --kernels {n['kernel']}`")}[n["verdict"]]
            loaded = f"  ·  loaded now: {n['loaded']}" if n["loaded"] and n["loaded"] != n["driver"] else ""
            grid, _ = row("\uf26c", text[0], text[1] + loaded)
            self.restart.pack_start(grid, False, False, 0)
            if n["verdict"] != "ok":
                self.restart.pack_start(links_row(link("Copy the command", lambda k=n["kernel"]: copy(
                    f"sudo akmods --force --kernels {k}"))), False, False, 0)

        rec = s["record"]
        if rec:
            verdict = {"safe": "said it was safe to reboot", "unsafe": "said DO NOT REBOOT (NVIDIA module)",
                       "not-needed": "no new kernel to boot into"}.get(rec.get("reboot"), "")
            nv = {"ok": "NVIDIA module matched the driver", "missing": "no NVIDIA module was built",
                  "mismatch": "the NVIDIA module did not match the driver", "none": ""}.get(rec.get("nvidia"), "")
            dnf = "" if rec.get("dnf") in ("0", None) else f"dnf exited {rec['dnf']}"
            kern = (f"kernel {rec.get('kernel_before')} → {rec.get('kernel_after')}"
                    if rec.get("kernel_before") != rec.get("kernel_after") else "")
            grid, _ = row("\uf46c", f"Last safe upgrade: {when(rec['finished'])}",
                          "  ·  ".join(x for x in (verdict, nv, kern, dnf) if x))
            self.restart.pack_start(grid, False, False, 0)
        if s.get("upgrade_running"):
            self.restart.pack_start(small("An update (safe-upgrade.sh) is running in a terminal now: "
                                          "this section is redrawn when you come back to the page."),
                                    False, False, 0)
        self.restart.show_all()

    def show_last(self, upd):
        """The spec's "last update time": the newest dnf transaction that was
        an update (not an install), which the five rows below may not hold."""
        if upd:
            grid, _ = row("\uf46c", f"Last updated {when(upd.get('end_time'))}",
                          f"{plural(upd.get('altered_count', 0), 'package')}  ·  {describe_cmd(upd)}  ·  "
                          f"transaction {upd.get('id')}")
        else:
            grid, _ = row("\uf46c", "No update in dnf history", "nothing has run dnf upgrade on this system yet")
        self.last.pack_start(grid, False, False, 0)
        self.last.show_all()

    def show_snaps(self, snap):
        """Status only: the controls (Snapshot now, Undo, the one-time setup
        command) live on the Maintenance page, so there is one of each."""
        if snap["snapper"]:
            grid, _ = row("\uf030", "Snapper takes a snapshot before and after every update",
                          f"{snap['status']}  ·  / only: your files in /home are never rolled back  ·  "
                          "undo an update from Maintenance")
        else:
            grid, _ = row("\uf030", "Snapshots before updates",
                          "Snapper is not set up yet: Update now still takes a read-only btrfs snapshot "
                          "of / first (the last 3 are kept in /.snapshots-pre-upgrade). One-click undo "
                          "needs snapper, set up once as root from Maintenance.")
        self.snaps.pack_start(grid, False, False, 0)
        if not snap["snapper"] and snap["pre_upgrade"]:
            self.snaps.pack_start(small("Kept: " + ",  ".join(snap["pre_upgrade"][:3])), False, False, 0)
        self.snaps.pack_start(links_row(link("Open Maintenance", lambda: spawn(SETTINGS, "system"))),
                              False, False, 0)
        self.snaps.show_all()

    def show_interval(self, value):
        key = {v: k for k, v in INTERVAL_SECONDS.items()}.get(value, "login" if value == "once" else None)
        self.chips.set(INTERVAL_CHIPS, key)
        if self.interval_busy:
            return
        if self.interval_error:
            self.interval_sub.set_text(self.interval_error)
        elif key == "login":
            self.interval_sub.set_text("once each time the bar starts (at login), then only when you press "
                                       "Check now or right-click the pill")
        elif key:
            self.interval_sub.set_text("every hour" if value == 3600 else "once a day" if value == 86400
                                       else f"every {value // 3600} hours")
        else:
            self.interval_sub.set_text(f"every {value} s (set by hand in waybar/config)"
                                       if isinstance(value, int) else "the pill is not in the bar's config")

    def show_history(self, rows):
        clear(self.history)
        if not rows:
            self.history.pack_start(small("dnf history is empty or did not answer"), False, False, 0)
            self.history.show_all()
            return
        for t in rows:
            grid, _ = row("\uf1da", t.get("title", "?")[:80], f"{when(t.get('end_time'))}  ·  "
                          f"{plural(t.get('altered_count', 0), 'package')}"
                          + ("" if t.get("status", "Ok") == "Ok" else f"  ·  {t['status']}"),
                          link("What changed", lambda i=t["id"]: spawn(BACKEND, "changes", str(i))))
            self.history.pack_start(grid, False, False, 0)
        self.history.show_all()

    def show_firmware(self, fw):
        clear(self.firmware)
        if not fw:
            self.firmware.pack_start(small("fwupd did not answer"), False, False, 0)
        elif not fw["available"]:
            grid, _ = row("\uf2db", "Firmware updates", "fwupd is not installed (sudo dnf install fwupd)")
            self.firmware.pack_start(grid, False, False, 0)
        elif not fw["devices"]:
            grid, _ = row("\uf2db", "Firmware is up to date" if not fw.get("error") else "Firmware: could not tell",
                          "from the LVFS metadata fwupd last downloaded  ·  devices whose makers publish "
                          "to LVFS only (often the SSD, the mouse, the monitor; rarely the BIOS)")
            self.firmware.pack_start(grid, False, False, 0)
        else:
            for d in fw["devices"]:
                grid, _ = row("\uf2db", d["device"], f"{d['current']} → {d['new']}"
                              + (f"  ·  {d['summary']}" if d["summary"] else ""))
                self.firmware.pack_start(grid, False, False, 0)
            self.firmware.pack_start(small("Listed only, never flashed from here: install them with "
                                           "`fwupdmgr update` in a terminal; most "
                                           "devices install on the next reboot."), False, False, 0)
            self.firmware.pack_start(links_row(link("Copy the command", lambda: copy("fwupdmgr update"))),
                                     False, False, 0)
        self.firmware.show_all()
