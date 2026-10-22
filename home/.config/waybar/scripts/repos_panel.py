#!/usr/bin/env python3
"""Git panel -- what the git pill opens: every repo in your projects folder with something
to do, and the three things you would do about it.

    REPOS                                              [Rescan]
    name   branch                       [Pull] [Commit]
    3 changed, 2 unpushed

    Rescan   `git fetch` every repo, then rescan -- the only network call, so
             "behind" is fresh and Pull has something to do
    Pull     fast-forward only (`git pull --ff-only`): it never merges or
             rebases, so it cannot make a mess; anything else is reported in
             the row and left to you
    Sync     dotfiles only: ~/.config is the live config and the repo a copy
             of it (sync.sh), so "N to sync from ~" is work not in the repo
             yet. Sync opens a terminal: copy, review, then y/N to commit+push.
    Commit   opens a terminal in the repo: the changes, a message prompt, the
             commit as you (global user.name / user.email, no co-author lines),
             then a y/N to push. On a repo with nothing to commit but commits
             not pushed, the button is Push and goes straight to that question.
    Preview  only on a repo with a static site (a CNAME next to an
             index.html -- repos.site_dir()): serves that folder on
             localhost as it is on disk, uncommitted changes included, and
             opens it, so you can look before you push. The server keeps
             running (2 h at most); Stop ends it sooner.

Unpushed work is lit magenta: those commits exist on this disk only. All of
it is repos.py (the pill's script), so the pill and the panel never disagree.
The last scan is shown at once from tmpfs, then a local rescan (no fetch)
follows; Rescan adds the fetch.

    repos_panel.py [x,y]   desktop position of the click that opened it
"""

import json
import os
import subprocess
import sys
import threading

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk, Pango  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import panelui  # noqa: E402
import themecolors  # noqa: E402
import repos  # noqa: E402

SIGNAL = 15                 # custom/repos
MAGENTA = themecolors.hex("danger", "#ff2a6d")   # the theme's color.danger


def label(text, cls, xalign=0.0):
    widget = Gtk.Label(label=text)
    widget.get_style_context().add_class(cls)
    widget.set_xalign(xalign)
    return widget


def pick(text, on_click, sensitive=True):
    button = Gtk.Button(label=text)
    button.get_style_context().add_class("dev-pick")
    button.set_valign(Gtk.Align.CENTER)
    button.set_sensitive(sensitive)
    button.connect("clicked", lambda _b: on_click())
    return button


class Repos(panelui.Panel):
    def build(self):
        self.status = {}            # path -> one-line result of the last pull
        self.busy = set()           # paths with a pull running
        self.fetching = False

        head = Gtk.Box(spacing=8)
        self.title = label("REPOS", "kb-heading")
        head.pack_start(self.title, True, True, 0)
        self.rescan_button = Gtk.Button(label="Rescan")
        self.rescan_button.get_style_context().add_class("ctl-link")
        self.rescan_button.set_tooltip_text("git fetch every repo, then rescan")
        self.rescan_button.connect("clicked", lambda _b: self.rescan())
        head.pack_end(self.rescan_button, False, False, 0)
        self.card.pack_start(head, False, False, 0)

        self.body = Gtk.Grid(column_spacing=8, row_spacing=2)
        self.card.pack_start(self.body, False, False, 0)
        self.repos = None
        try:
            with open(repos.CACHE) as handle:
                self.repos = json.load(handle)
        except (OSError, ValueError):
            pass
        self.draw()

    def on_ready(self):
        # A quick local rescan (no network) right away, so stale tmpfs data
        # is only ever on screen for a moment.
        self.in_thread(repos.scan, self.scanned)

    # -- work off the GTK thread ------------------------------------------------
    def in_thread(self, work, done):
        def run():
            result = work()
            GLib.idle_add(lambda: (done(result), False)[1])
        threading.Thread(target=run, daemon=True).start()

    def scanned(self, result):
        self.repos = result
        self.fetching = False
        self.rescan_button.set_label("Rescan")
        self.rescan_button.set_sensitive(True)
        subprocess.run(["pkill", f"-RTMIN+{SIGNAL}", "-x", "waybar"])
        self.draw()

    def rescan(self):
        self.fetching = True
        self.rescan_button.set_label("fetching...")
        self.rescan_button.set_sensitive(False)
        self.status = {}
        self.in_thread(repos.fetch, self.scanned)

    def pull(self, repo):
        path = repo["path"]
        self.busy.add(path)
        self.draw()

        def done(result):
            ok, text = result
            self.busy.discard(path)
            self.status[path] = (ok, text)
            self.in_thread(repos.scan, self.scanned)
        self.in_thread(lambda: repos.pull(path), done)

    def sync_dotfiles(self):
        try:
            subprocess.Popen(["kitty", "-e", os.path.join(HERE, "dotfiles.py"), "sync"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True)
        except OSError:
            pass
        self.quit()

    def commit(self, repo):
        try:
            subprocess.Popen(["kitty", "--directory", repo["path"],
                              os.path.join(HERE, "repos.py"), "commit", repo["path"]],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True)
        except OSError:
            pass
        self.quit()

    def preview(self, repo):
        path = repo["path"]

        def done(result):
            ok, text = result
            if not ok:
                self.status[path] = (False, f"preview: {text}")
                self.draw()
                return
            try:
                subprocess.Popen(["xdg-open", text], stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL, start_new_session=True)
            except OSError:
                pass
            self.quit()
        self.in_thread(lambda: repos.preview(path), done)

    def stop_preview(self, repo):
        path = repo["path"]

        def done(_result):
            self.status[path] = (True, "preview stopped")
            self.draw()
        self.in_thread(lambda: repos.preview_stop(path), done)

    # -- drawing -------------------------------------------------------------------
    def draw(self):
        for child in self.body.get_children():
            self.body.remove(child)
        if self.repos is None:
            self.body.attach(label("scanning...", "ctl-sub"), 0, 0, 3, 1)
            self.body.show_all()
            return
        todo = [r for r in self.repos if repos.needs_attention(r)]
        # The change counter: files changed or new across every repo, plus
        # dotfiles drift, plus commits not pushed.
        changes = sum(r["changed"] + r["untracked"] + r.get("drift", 0) for r in self.repos)
        unpushed = sum(r["ahead"] for r in self.repos)
        counts = [f"{changes} changed"] if changes else []
        if unpushed:
            counts.append(f"{unpushed} unpushed")
        self.title.set_text("REPOS" + (f"  \u00b7  {', '.join(counts)}" if counts else ""))
        # Unpushed first: those are the ones at risk.
        todo.sort(key=lambda r: (-(r["ahead"] > 0 or not r["upstream"]), r["name"].lower()))
        row = 0
        if not todo:
            self.body.attach(label(f"all {len(self.repos)} repos clean and pushed", "ctl-sub"),
                             0, row, 3, 1)
            row += 1
        for repo in todo:
            row = self.repo_rows(repo, row)
        clean = len(self.repos) - len(todo)
        if todo and clean:
            note = label(f"{clean} more clean and pushed", "ctl-sub")
            note.set_margin_top(6)
            self.body.attach(note, 0, row, 3, 1)
        self.body.show_all()

    def repo_rows(self, repo, row):
        path = repo["path"]
        name = label(repo["name"], "sn-value")
        name.set_hexpand(True)
        name.set_ellipsize(Pango.EllipsizeMode.END)
        # A minimum as well as a maximum: an ellipsizing label in a grid asks
        # for no width at all, and the name collapsed to "...".
        name.set_width_chars(16)
        name.set_max_width_chars(22)
        self.body.attach(name, 0, row, 1, 1)
        self.body.attach(label(repo["branch"], "sn-label", 1.0), 1, row, 1, 1)

        buttons = Gtk.Box(spacing=4)
        pulling = path in self.busy
        buttons.pack_start(pick("pulling..." if pulling else "Pull", lambda: self.pull(repo),
                                sensitive=not pulling and repo["upstream"] and not self.fetching),
                           False, False, 0)
        if repo.get("drift"):
            buttons.pack_start(pick("Sync", self.sync_dotfiles), False, False, 0)
        has_changes = repo["changed"] or repo["untracked"]
        to_push = repo["ahead"] or not repo["upstream"]
        if has_changes or to_push:
            buttons.pack_start(pick("Commit" if has_changes else "Push",
                                    lambda: self.commit(repo)), False, False, 0)
        # .get(): a scan cached in tmpfs before previews existed has no key.
        if repo.get("previewable"):
            running = repos.previewing(path)
            button = pick("Preview", lambda: self.preview(repo))
            live = repo.get("website")
            button.set_tooltip_text((f"Open {running}" if running else
                                     "Serve this repo's site on localhost, as it is on disk")
                                    + (f"\nLive: {live}" if live else ""))
            buttons.pack_start(button, False, False, 0)
            if running:
                buttons.pack_start(pick("Stop", lambda: self.stop_preview(repo)), False, False, 0)
        self.body.attach(buttons, 2, row, 1, 2)

        detail = repos.describe(repo) or "clean"
        if path in self.status:
            ok, text = self.status[path]
            detail = text if ok else f"pull: {text}"
        sub = label(detail, "sn-label")
        sub.set_ellipsize(Pango.EllipsizeMode.END)
        sub.set_max_width_chars(40)
        if to_push or (path in self.status and not self.status[path][0]):
            sub.set_markup(f"<span foreground='{MAGENTA}'>{GLib.markup_escape_text(detail)}</span>")
        self.body.attach(sub, 0, row + 1, 2, 1)
        return row + 2


if __name__ == "__main__":
    panelui.run(Repos)
