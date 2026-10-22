"""Settings page: health, snapshots, backup, config safe mode."""
from gi.repository import GLib, Gtk  # noqa: F401

from .common import *  # noqa: F401,F403  (the shared helpers and paths)

import os  # noqa: E402
import subprocess  # noqa: E402
import time  # noqa: E402

PAGE = {"id": "system", "title": "Maintenance", "icon": "\uf0ad", "group": "System", "order": 80,
        "keywords": ["health check", "doctor", "failed services", "logs", "errors", "snapshots", "snapper",
                     "backup", "dotfiles", "safe mode", "restore config", "broken config", "hyprland config",
                     "keyboard shortcuts"]}


class Page:
    def __init__(self):
        self.widget = page_box()
        w = self.widget
        w.pack_start(heading("HEALTH"), False, False, 0)
        self.health = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        w.pack_start(self.health, False, False, 0)
        w.pack_start(links_row(link("Check again", self.refresh),
                               link("Restart what failed", lambda: (run(DOCTOR, "--fix", timeout=60), self.refresh())),
                               link("Errors today", lambda: spawn(PANEL, "toggle", "logs"))), False, False, 0)
        w.pack_start(sep(), False, False, 0)
        w.pack_start(heading("SNAPSHOTS"), False, False, 0)
        self.snaps = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        w.pack_start(self.snaps, False, False, 0)
        w.pack_start(sep(), False, False, 0)
        w.pack_start(heading("BACKUP"), False, False, 0)
        self.backup_row, self.backup_sub = row("", "Dotfiles backup to GitHub", "")
        w.pack_start(self.backup_row, False, False, 0)
        w.pack_start(links_row(link("Back up now", lambda: (
            run("systemctl", "--user", "start", "--no-block", "dotfiles-backup.service"),
            GLib.timeout_add(1500, lambda: (self.refresh(), False)[1])))), False, False, 0)
        w.pack_start(sep(), False, False, 0)
        w.pack_start(heading("HYPRLAND CONFIG"), False, False, 0)
        self.guard_row, self.guard_sub = row("", "Safe mode", "")
        w.pack_start(self.guard_row, False, False, 0)
        w.pack_start(links_row(link("Restore the last working config", lambda: (
            run(GUARD, "restore"), self.refresh())), link("Open Keyboard shortcuts", lambda: spawn(os.path.join(HYPR, "settings.py"), "shortcuts"))),
            False, False, 0)

    def refresh(self):
        clear(self.health)
        self.health.pack_start(dp.label("checking…", "ctl-sub"), False, False, 0)
        self.health.show_all()
        background(lambda: run_json(DOCTOR, "--json", timeout=60), self.show_health)
        background(lambda: (run(SNAPSHOTS, "status").strip(), run_json(SNAPSHOTS, "list", "--json")), self.show_snaps)
        result = run("systemctl", "--user", "show", "dotfiles-backup.service", "-p", "Result",
                     "-p", "ExecMainExitTimestamp", "-p", "ActiveState")
        props = dict(line.split("=", 1) for line in result.splitlines() if "=" in line)
        nxt = run("systemctl", "--user", "show", "dotfiles-backup.timer", "-p", "NextElapseUSecRealtime")
        nxt = nxt.split("=", 1)[-1].strip()
        last = props.get("ExecMainExitTimestamp") or "not yet"
        state = "running now" if props.get("ActiveState") == "activating" else (
            "last run OK" if props.get("Result") == "success" and last != "not yet" else
            f"last run: {props.get('Result')}" if last != "not yet" else "not run yet")
        self.backup_sub.set_text(f"every evening at 21:30  ·  {state}  ·  last: {last}  ·  next: {nxt or '?'}")
        good = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"),
                            "hypr", "last-good")
        try:
            saved = time.strftime("%a %H:%M", time.localtime(os.path.getmtime(good)))
        except OSError:
            saved = "never"
        errors = run(GUARD, "check").strip()
        self.guard_sub.set_text(f"{errors}  ·  last working config saved {saved}  ·  a broken reload offers "
                                "to restore it; your edits are kept aside in ~/.config/hypr/broken-*/")

    def show_health(self, data):
        clear(self.health)
        if not data:
            self.health.pack_start(dp.label("doctor.py did not answer", "ctl-sub"), False, False, 0)
        else:
            bad = [c for c in data["checks"] if c["level"] in ("warn", "fail")]
            grid, _ = row("", "All good" if not bad else f"{len(bad)} thing{'s' if len(bad) != 1 else ''} "
                          "to look at", f"{len(data['checks'])} checks: services, timers, config, disk, logs, "
                          "snapshots, backups")
            self.health.pack_start(grid, False, False, 0)
            for c in bad:
                lab = dp.label(f"{'✗' if c['level'] == 'fail' else '!'}  {c['name']}: {c['text'].splitlines()[0][:110]}",
                               "ctl-sub")
                self.health.pack_start(lab, False, False, 0)
        self.health.show_all()

    def show_snaps(self, data):
        status, rows = data
        clear(self.snaps)
        if status == "not set up" or rows is None:
            grid, _ = row("", "Not set up yet", "Automatic snapshots before every update need one step as "
                          "root. Copy the command and run it in a terminal.")
            self.snaps.pack_start(grid, False, False, 0)
            self.snaps.pack_start(links_row(link("Copy the command", lambda: subprocess.run(
                ["wl-copy", f"sudo {SETUP_ROOT}"]))), False, False, 0)
        else:
            grid, _ = row("", "Snapshots", status + "  ·  before and after every update, hourly and daily")
            self.snaps.pack_start(grid, False, False, 0)
            for e in [r for r in rows if r["kind"] == "update" and r["post"]][:5]:
                sub = f"{e['date']}  ·  snapshots {e['pre']}..{e['post']}"
                g, _ = row("", e["text"][:70] or "update", sub,
                           link("Undo…", lambda p=e["pre"], q=e["post"]: spawn(SNAPSHOTS, "undo", str(p), str(q))))
                self.snaps.pack_start(g, False, False, 0)
            self.snaps.pack_start(links_row(link("Snapshot now", lambda: (
                run(SNAPSHOTS, "create", "from Settings"), self.refresh()))), False, False, 0)
        self.snaps.show_all()


