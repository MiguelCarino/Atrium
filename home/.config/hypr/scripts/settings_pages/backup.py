"""Settings page (a tab of Storage): Backup -- backup.py's daily, encrypted
copy of your folders through restic or kopia.

    BACKUP          the last good backup, the repository's size, Run now,
                    Open the repository (a folder), the snapshots, how to restore
    WHERE           the repository (a folder or a restic URL), the engine, the
                    password (kept in the keyring, or a 0600 file), Create the
                    repository (only on that click: `backup.py init`)
    WHAT            the folders included and the patterns left out, each with a
                    remove button; Add folder... and Add pattern
    KEEP            how many daily / weekly / monthly snapshots stay
    SCHEDULE        the daily backup.timer on / off

Neither restic nor kopia installed: the page says so first and names the
package to install; the rest is still editable, so everything is ready when
it is. Nothing is kept here: every control runs backup.py (set, include,
exclude, password store, schedule, run, init) and the page redraws from
`backup.py status --json`.
"""
from .common import *  # noqa: F401,F403  (the shared helpers and paths; Gtk 3)

from gi.repository import GLib, Gtk  # noqa: E402,F401

import os  # noqa: E402
import subprocess  # noqa: E402

PAGE = {"id": "backup", "title": "Backup", "icon": "", "group": "System", "order": 31,
        "parent": "storage", "tab": "Backup",
        "keywords": ["backup", "back up", "restic", "kopia", "copia de seguridad", "respaldo", "restore",
                     "restaurar", "snapshots", "repository", "external drive", "nas", "sftp", "encrypted"]}

BACKUP = os.path.join(HYPR, "backup.py")
ENGINES = [("auto", "Automatic"), ("restic", "restic"), ("kopia", "kopia")]
PASSWORDS = [("keyring", "In the keyring"), ("file", "In a file")]
KEEPS = [("keep_daily", "Daily"), ("keep_weekly", "Weekly"), ("keep_monthly", "Monthly")]


# -- pure helpers (tests/test_backup_page.py) -----------------------------------------------
def summary_text(data):
    """The line under "Backup": when, how big, the schedule."""
    state = data.get("state") or {}
    if not data.get("configured"):
        return "not set up yet" if data.get("installed") else "needs restic or kopia"
    bits = [f"last good backup {data.get('last_ok_text') or 'never'}"]
    if data.get("repo_size_text"):
        bits.append(f"repository {data['repo_size_text']}")
    bits.append("every day" if (data.get("timer") or {}).get("enabled") else "not scheduled")
    if state.get("last_run") and not state.get("ok"):
        bits.insert(0, "the last run FAILED")
    return "  ·  ".join(bits)


def missing_text(data):
    """"" when an engine is installed, else what to install and why."""
    if data.get("installed"):
        return ""
    return ("Backups are made by restic (or kopia), which is not installed. Install it with "
            f"`sudo dnf install {data.get('package') or 'restic'}`, then come back here.")


def last_run_text(state):
    """The details of the last run: what it added, how long, any warning."""
    if not state.get("last_run"):
        return "No backup has run yet."
    if not state.get("ok"):
        return f"Last run failed: {state.get('error') or '?'}"
    parts = []
    if state.get("added") is not None:
        parts.append(f"added {human_bytes(state['added'])}")
    if state.get("files") is not None:
        parts.append(f"{state['files']} files looked at")
    if state.get("duration") is not None:
        parts.append(f"took {state['duration']} s")
    text = "Last run: " + (", ".join(parts) or "done")
    if state.get("warning"):
        text += f". Note: {state['warning']}"
    return text


def human_bytes(size):
    size = float(size or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1000 or unit == "TB":
            return f"{size:.0f} {unit}" if unit in ("B", "KB") else f"{size:.1f} {unit}"
        size /= 1000
    return ""


def password_kind(value):
    """backup.conf's password= as the chips show it."""
    return "file" if (value or "").startswith("file:") else "keyring"


def tilde(path, home=os.path.expanduser("~")):
    return "~" + path[len(home):] if path == home or path.startswith(home + "/") else path


class Page:
    def __init__(self):
        self.widget = page_box()
        w = self.widget
        self.data = {}
        self.updating = False

        self.missing = dp.label("", "ctl-sub")
        self.missing.set_line_wrap(True)
        self.missing.set_selectable(True)
        self.missing.set_no_show_all(True)
        w.pack_start(self.missing, False, False, 0)

        w.pack_start(heading("BACKUP"), False, False, 0)
        grid, self.summary = row("", "Backup of your files", "")
        w.pack_start(grid, False, False, 0)
        self.problems = dp.label("", "ctl-sub")
        self.problems.set_line_wrap(True)
        w.pack_start(self.problems, False, False, 0)
        self.run_link = link("Run now", self.run_now)
        self.open_link = link("Open the repository", lambda: spawn(BACKUP, "open"))
        w.pack_start(links_row(self.run_link, self.open_link, link("Snapshots", self.show_snapshots)),
                     False, False, 0)
        self.result = dp.label("", "ctl-sub")
        self.result.set_line_wrap(True)
        self.result.set_selectable(True)
        w.pack_start(self.result, False, False, 0)
        self.last = dp.label("", "ctl-sub")
        self.last.set_line_wrap(True)
        self.hint = dp.label("", "ctl-sub")
        self.hint.set_line_wrap(True)
        self.hint.set_selectable(True)
        self.where_file = dp.label("", "ctl-sub")
        self.where_file.set_selectable(True)
        w.pack_start(details(self.last, self.hint, self.where_file, label="Last run and how to restore"),
                     False, False, 0)
        w.pack_start(sep(), False, False, 0)

        w.pack_start(heading("WHERE"), False, False, 0)
        box = Gtk.Box(spacing=8)
        self.repo = Gtk.Entry()
        self.repo.set_hexpand(True)
        self.repo.set_placeholder_text("a folder (an external drive) or sftp:user@host:/backup")
        self.repo.connect("activate", lambda _e: self.save_repo())
        box.pack_start(self.repo, True, True, 0)
        box.pack_start(link("Choose folder...", self.choose_repo), False, False, 0)
        box.pack_start(link("Save", self.save_repo), False, False, 0)
        w.pack_start(box, False, False, 0)
        self.engine = Chips(lambda key: self.set("engine", key))
        grid, self.engine_sub = row("", "Made with", "", None)
        w.pack_start(grid, False, False, 0)
        w.pack_start(self.engine.widget, False, False, 0)

        self.pw_kind = Chips(self.pick_password)
        grid, self.pw_sub = row("", "The repository's password", "", None)
        w.pack_start(grid, False, False, 0)
        w.pack_start(self.pw_kind.widget, False, False, 0)
        box = Gtk.Box(spacing=8)
        self.pw = Gtk.Entry()
        self.pw.set_visibility(False)
        self.pw.set_hexpand(True)
        self.pw.set_placeholder_text("type the password, then Store (it is never shown again)")
        self.pw.connect("activate", lambda _e: self.store_password())
        box.pack_start(self.pw, True, True, 0)
        box.pack_start(link("Store in the keyring", self.store_password), False, False, 0)
        self.pw_box = box
        w.pack_start(box, False, False, 0)
        box = Gtk.Box(spacing=8)
        self.pw_file = Gtk.Entry()
        self.pw_file.set_hexpand(True)
        self.pw_file.set_placeholder_text("~/.config/hypr/backup.pass (chmod 600)")
        self.pw_file.connect("activate", lambda _e: self.save_pw_file())
        box.pack_start(self.pw_file, True, True, 0)
        box.pack_start(link("Save", self.save_pw_file), False, False, 0)
        self.pw_file_box = box
        w.pack_start(box, False, False, 0)
        self.create = links_row(link("Create the repository", self.init))
        w.pack_start(self.create, False, False, 0)
        w.pack_start(sep(), False, False, 0)

        w.pack_start(heading("WHAT"), False, False, 0)
        self.includes = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        w.pack_start(self.includes, False, False, 0)
        w.pack_start(links_row(link("Add folder...", self.add_folder)), False, False, 0)
        w.pack_start(dp.label("Left out", "ctl-sub"), False, False, 0)
        self.excludes = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        w.pack_start(self.excludes, False, False, 0)
        box = Gtk.Box(spacing=8)
        self.pattern = Gtk.Entry()
        self.pattern.set_hexpand(True)
        self.pattern.set_placeholder_text("a folder or a pattern: ~/Videos, *.iso, node_modules")
        self.pattern.connect("activate", lambda _e: self.add_pattern())
        box.pack_start(self.pattern, True, True, 0)
        box.pack_start(link("Leave out", self.add_pattern), False, False, 0)
        w.pack_start(box, False, False, 0)
        w.pack_start(sep(), False, False, 0)

        w.pack_start(heading("KEEP"), False, False, 0)
        box = Gtk.Box(spacing=12)
        self.keeps = {}
        for key, caption in KEEPS:
            spin = Gtk.SpinButton.new_with_range(0, 100, 1)
            spin.connect("value-changed", lambda s, k=key: self.set(k, str(int(s.get_value()))))
            box.pack_start(dp.label(caption, "ctl-sub"), False, False, 0)
            box.pack_start(spin, False, False, 0)
            self.keeps[key] = spin
        w.pack_start(box, False, False, 0)
        w.pack_start(dp.label("Older snapshots are removed after each backup to free their space.", "ctl-sub"),
                     False, False, 0)
        w.pack_start(sep(), False, False, 0)

        w.pack_start(heading("SCHEDULE"), False, False, 0)
        self.daily = Gtk.Switch()
        self.daily.connect("state-set", lambda _s, on: self.schedule(on))
        grid, self.daily_sub = row("", "Back up every day", "", self.daily)
        w.pack_start(grid, False, False, 0)

    # -- actions ----------------------------------------------------------------------------
    def cli(self, *args, then=None, timeout=60, stdin=None):
        """backup.py ARGS in the background; its error (or then's text) in
        the result line, then a redraw."""
        def work():
            try:
                return subprocess.run([BACKUP, *args], capture_output=True, text=True, timeout=timeout,
                                      input=stdin)
            except (OSError, subprocess.SubprocessError) as exc:
                return subprocess.CompletedProcess(args, 1, "", str(exc))

        def done(r):
            text = (r.stderr or "").strip().removeprefix("backup: ") if r.returncode else (then or "")
            if r.returncode == 0 and not then:
                text = (r.stdout or "").strip().splitlines()[-1].removeprefix("backup: ") if r.stdout.strip() else ""
            self.result.set_text(text)
            self.refresh()
        background(work, done)

    def set(self, key, value):
        if not self.updating:
            self.cli("set", key, value)
        return False

    def save_repo(self):
        repo = self.repo.get_text().strip()
        if repo != (self.data.get("conf") or {}).get("repo"):
            self.cli("set", "repo", repo, then="Saved. Store its password, then Create the repository "
                                               "(or Run now, for one that already exists).")

    def choose_repo(self):
        path = self.pick_folder("Where the backup goes")
        if path:
            self.repo.set_text(path)
            self.save_repo()

    def pick_folder(self, title):
        dialog = Gtk.FileChooserDialog(title=title, transient_for=self.widget.get_toplevel(),
                                       action=Gtk.FileChooserAction.SELECT_FOLDER)
        dialog.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Choose", Gtk.ResponseType.OK)
        path = dialog.get_filename() if dialog.run() == Gtk.ResponseType.OK else None
        dialog.destroy()
        return path

    def pick_password(self, kind):
        if self.updating:
            return
        if kind == "keyring":
            self.cli("set", "password", "keyring")
        else:
            self.pw_file_box.set_visible(True)
            self.pw_box.set_visible(False)
            self.pw_file.grab_focus()

    def save_pw_file(self):
        path = self.pw_file.get_text().strip()
        if path:
            self.cli("set", "password", f"file:{path}")

    def store_password(self):
        secret = self.pw.get_text()
        self.pw.set_text("")
        if secret:
            self.cli("password", "store", stdin=secret, then="Password stored in the keyring.")

    def init(self):
        self.result.set_text("creating the repository...")
        self.cli("init", timeout=300)

    def run_now(self):
        self.result.set_text("backing up... (this page can be closed; a failure is a notification)")
        self.run_link.set_sensitive(False)
        subprocess.Popen(["systemd-run", "--user", "--collect", "--quiet", "--unit=backup-now",
                          "--slice=heavy.slice", "--nice=19", "-p", "IOSchedulingClass=idle",
                          "/usr/bin/python3", BACKUP, "run"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        GLib.timeout_add_seconds(5, self.poll_run)

    def poll_run(self):
        """Is the Run now backup still going: asked off the GTK thread (a
        busy user manager must not freeze the window), again in 5 s if so."""
        background(lambda: run("systemctl", "--user", "is-active", "backup-now.service", timeout=5).strip(),
                   self.run_polled)
        return False

    def run_polled(self, active):
        if active in ("active", "activating"):
            GLib.timeout_add_seconds(5, self.poll_run)
            return
        self.run_link.set_sensitive(True)
        self.result.set_text("")
        self.refresh()

    def show_snapshots(self):
        self.result.set_text("reading the snapshots...")

        def done(data):
            data = data or {}
            snaps = data.get("snapshots") or []
            if data.get("error"):
                self.result.set_text(f"could not read them: {data['error']}")
            elif not snaps:
                self.result.set_text("no snapshots yet")
            else:
                lines = [f"{s['time'][:16].replace('T', ' ')}  {s['id']}  {s['host']}" for s in snaps[:12]]
                more = f"\n... and {len(snaps) - 12} older" if len(snaps) > 12 else ""
                self.result.set_text(f"{len(snaps)} snapshots, newest first:\n" + "\n".join(lines) + more)
        background(lambda: run_json(BACKUP, "snapshots", "--json", timeout=300), done)

    def add_folder(self):
        path = self.pick_folder("Back up this folder too")
        if path:
            self.cli("include", "add", tilde(path))

    def add_pattern(self):
        text = self.pattern.get_text().strip()
        if text:
            self.pattern.set_text("")
            self.cli("exclude", "add", text)

    def schedule(self, on):
        if not self.updating:
            self.cli("schedule", "on" if on else "off")
        return False

    # -- drawing ----------------------------------------------------------------------------
    def refresh(self):
        background(lambda: run_json(BACKUP, "status", "--json", timeout=30) or {}, self.draw)

    def list_rows(self, box, items, kind, icon):
        clear(box)
        for item in items:
            grid, _ = row(icon, item, "", link("Remove", lambda i=item: self.cli(kind, "remove", i)))
            box.pack_start(grid, False, False, 0)
        if not items:
            box.pack_start(dp.label("nothing", "ctl-sub"), False, False, 0)

    def draw(self, data):
        if not data:
            self.summary.set_text("could not read backup.py status")
            return
        self.data = data
        conf, state = data.get("conf") or {}, data.get("state") or {}
        self.updating = True
        miss = missing_text(data)
        self.missing.set_text(miss)
        self.missing.set_visible(bool(miss))
        self.summary.set_text(summary_text(data))
        probs = data.get("problems") or []
        self.problems.set_text("  ·  ".join(probs))
        self.run_link.set_sensitive(not probs)
        self.open_link.set_visible(bool(data.get("local")))
        self.last.set_text(last_run_text(state))
        self.hint.set_text((data.get("restore_hint") or "") if data.get("configured") else "")
        self.where_file.set_text(f"Settings file: {data.get('conf_path')}")
        if not self.repo.has_focus():
            self.repo.set_text(conf.get("repo") or "")
        self.engine.set(ENGINES, conf.get("engine", "auto"))
        self.engine_sub.set_text(f"using {data['engine']}" if data.get("engine") else
                                 "installed: " + (", ".join(data.get("installed") or []) or "neither"))
        kind = password_kind(conf.get("password"))
        self.pw_kind.set(PASSWORDS, kind)
        if not self.pw_file.has_focus():
            self.pw_file.set_text(conf["password"][5:] if kind == "file" else "")
        self.pw_sub.set_text("never written in a settings file or on a command line")
        self.list_rows(self.includes, conf.get("include") or [], "include", "")
        self.list_rows(self.excludes, conf.get("exclude") or [], "exclude", "")
        for key, spin in self.keeps.items():
            spin.set_value(int(conf.get(key, 0)))
        timer = data.get("timer") or {}
        self.daily.set_active(bool(timer.get("enabled")))
        self.daily.set_sensitive(bool(data.get("configured")))
        self.daily_sub.set_text("once a day (a missed day runs at the next start), at the lowest priority"
                                if timer.get("enabled") else "off: backups run only when you press Run now")
        self.widget.show_all()
        self.missing.set_visible(bool(miss))
        self.pw_box.set_visible(kind == "keyring")
        self.pw_file_box.set_visible(kind == "file")
        never = not state.get("last_ok")
        self.create.set_visible(bool(conf.get("repo")) and never and bool(data.get("engine")))
        self.open_link.set_visible(bool(data.get("local")))
        self.updating = False
