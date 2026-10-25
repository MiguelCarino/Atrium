#!/usr/bin/env python3
"""Git panel -- what the git pill opens: every repo in your projects folder with something
to do, and the three things you would do about it.

    REPOS                                    [Pull all] [Rescan]
    | name   branch                       [Pull] [Commit]
    | 3 changed, 2 unpushed

    Rescan   `git fetch` every repo, then rescan -- the only network call, so
             "behind" is fresh and Pull has something to do
    Pull     fast-forward only (`git pull --ff-only`): it never merges or
             rebases, so it cannot make a mess; anything else is reported in
             the row and left to you
    Pull all the same Pull for every repo that has an upstream and is behind
             it (pull_all_targets()), one at a time in a thread, so each row
             shows "queued", "pulling..." and then its own result; a summary
             line under the header says how it went. Off while Rescan is
             fetching (a pull racing a fetch of the same repo can fail on
             the ref lock), and off when nothing is behind -- "behind" is as
             of the last fetch, so Rescan first to have something to pull.
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
follows; Rescan adds the fetch. A repo that was pulled (or answered a key)
since the card opened stays in the list with that result even once it is
clean, so a pull never makes its own answer vanish; Rescan clears them.

Keyboard (key_action() is the whole map; nothing is highlighted at first):

    Up/Down, k/j       move the highlighted row (the accent bar at its left)
    PageUp/PageDown    a screenful, less one row kept as context (page_rows())
    Home/End           first / last row
    Enter              the row's main action (main_action()): Sync on the
                       dotfiles repo with drift, Commit/Push when it has work,
                       else Pull
    P / C / V          Pull / Commit (or Push) / Preview the highlighted row
    /                  the filter box, even when the list fits

With nothing highlighted, Enter, P, C and V highlight the top row instead
of acting on a row you cannot see. The highlighted row is scrolled into
view (scroll_value()). Any other printable key opens the filter and starts
the text with it; inside the filter every printable key is text (so p, c,
v, j and k type), Home/End move the caret, and the arrows, PageUp/PageDown
and Enter still drive the rows -- type a few letters and Enter acts on the
top match, which a filter with text always highlights. A filter that starts
with one of the command letters needs a / first. A button Tab has focused
(Rescan, Pull all, a row's Pull / Commit / Preview) takes Enter and Space
itself, as GTK buttons do; the next row move hands the keyboard back to the
rows, so Down then Enter acts on the row, not on that button.

The card is panelui.CARD_HEIGHT tall whatever the list holds (the same as
the CPU, network and updates cards), and the list scrolls inside it. When
the rows are more than fit, the filter box is there from the start; when
they fit it appears on / or the first printable key. Typing keeps the repos
whose name or branch has the text in it -- the clean ones too, so a repo
with nothing to do can still be found and pulled. Esc clears the text and
leaves the box (on an empty box it just leaves it, and a list that fits
hides it again); a further Esc closes the card.

    repos_panel.py [x,y]   desktop position of the click that opened it
"""

import json
import os
import subprocess
import sys
import threading

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk, Pango  # noqa: E402

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


def matches(repo, text):
    """The filter: every word of text in the repo's name or branch."""
    hay = f"{repo['name']} {repo.get('branch') or ''}".lower()
    return all(word in hay for word in text.lower().split())


# -- the keyboard, as pure functions (tests/test_repos_panel.py) ----------------
MOVES = ("up", "down", "pageup", "pagedown", "home", "end")
PAGE = 5            # rows per PageUp/Down before the list has been laid out
# Keys that drive the rows wherever the focus is, the filter box included
# (a one-line Entry has no use for them).
ROW_KEYS = {"Up": "up", "KP_Up": "up", "Down": "down", "KP_Down": "down",
            "Page_Up": "pageup", "KP_Page_Up": "pageup",
            "Page_Down": "pagedown", "KP_Page_Down": "pagedown",
            "Return": "main", "KP_Enter": "main", "ISO_Enter": "main"}
# Rows outside the filter, the caret inside it.
EDGE_KEYS = {"Home": "home", "KP_Home": "home", "End": "end", "KP_End": "end"}
# Outside the filter only: inside it these are text.
LETTER_KEYS = {"k": "up", "j": "down", "p": "pull", "P": "pull", "c": "commit", "C": "commit",
               "v": "preview", "V": "preview", "slash": "filter"}


ACTIVATE_KEYS = ("Return", "KP_Enter", "ISO_Enter", "space", "KP_Space")


def key_action(name, text, in_filter, modified=False, on_button=False):
    """What a key does: one of MOVES, "main", "pull", "commit", "preview",
    "filter" (show the box and focus it), "type" (show it and start the text
    with this key), or None (not ours: Esc and the rest go to the card and
    the focused widget as before). name is Gdk.keyval_name(), text the
    event's string; modified is Ctrl or Alt held, which is never ours, so
    Ctrl+A and friends keep working in the box. on_button: a Gtk.Button has
    the focus (Tab put it there) -- Enter and Space are its own then, or
    Enter ran the highlighted row's action and Space opened the filter
    instead of pressing the button."""
    if modified or (on_button and name in ACTIVATE_KEYS):
        return None
    if name in ROW_KEYS:
        return ROW_KEYS[name]
    if in_filter:
        return None
    if name in EDGE_KEYS:
        return EDGE_KEYS[name]
    if name in LETTER_KEYS:
        return LETTER_KEYS[name]
    if text and text.isprintable():
        return "type"
    return None


def step(index, count, move, page=PAGE):
    """The highlighted row after a move: an index into count rows, or None
    when there are none. index None (nothing highlighted yet): Up and End
    land on the last row, every other move on the first. No wrap-around --
    holding Down stops at the bottom instead of jumping to the top -- and an
    index left over from a longer list is clamped first."""
    if count <= 0:
        return None
    last = count - 1
    if index is None:
        return last if move in ("up", "end") else 0
    index = min(max(index, 0), last)
    if move == "home":
        return 0
    if move == "end":
        return last
    delta = {"up": -1, "down": 1, "pageup": -page, "pagedown": page}.get(move, 0)
    return min(max(index + delta, 0), last)


def page_rows(view_height, row_height):
    """Rows per PageUp/Down: as many as the view shows, less one kept as
    context so the row you were on is still on screen after the jump; PAGE
    until the list has a size."""
    if row_height <= 0 or view_height <= 0:
        return PAGE
    return max(1, int(view_height // row_height) - 1)


def scroll_value(value, page, top, bottom):
    """The scroll position that shows the row from top to bottom (pixels in
    the list), moving the view as little as it can: unchanged when the row is
    already in view, its top at the view's top when it is above (or taller
    than the view), its bottom at the view's bottom when it is below."""
    if top < value or bottom - top >= page:
        return max(0, top)
    if bottom > value + page:
        return bottom - page
    return value


def has_work(repo):
    """Something Commit (or Push) would do: changes to commit, commits to
    push, or a branch with no upstream yet (Push sets it)."""
    return bool(repo["changed"] or repo["untracked"] or repo["ahead"] or not repo["upstream"])


def main_action(repo):
    """Enter on a row. Sync before Commit on the dotfiles repo with drift:
    sync.sh copies ~ in and then commits everything, the repo's own changes
    included, so it is the superset; Commit alone would leave the drift."""
    if repo.get("drift"):
        return "sync"
    return "commit" if has_work(repo) else "pull"


def pull_all_targets(repo_list, busy=()):
    """The repos Pull all fast-forwards: an upstream, behind it, no scan
    error (an errored repo's numbers are not real), and no pull of its own
    already running. Ahead-and-behind (diverged) ones are included: --ff-only
    refuses them, and the row then says so, rather than skipping in silence."""
    return [r for r in repo_list or []
            if r["upstream"] and r.get("behind", 0) > 0 and not r["error"]
            and r["path"] not in busy]


def pull_all_summary(results):
    """The line under the header after Pull all; results are (ok, text) per
    repo in the order pulled."""
    if not results:
        return "Pull all: nothing was behind"
    done = sum(1 for ok, _text in results if ok)
    left = len(results) - done
    text = f"Pull all: {done} of {len(results)} pulled"
    return text + (f", {left} left to you (see the row)" if left else "")


class Repos(panelui.Panel):
    def build(self):
        self.status = {}            # path -> (ok, one line) of the last pull / key answer
        self.busy = set()           # paths with a pull running
        self.queued = set()         # paths Pull all has still to reach
        self.fetching = False
        self.pulling_all = False
        self.filter_pinned = False  # shown by a key, so fit_check keeps it
        self.hl = None              # path of the highlighted row
        self.order = []             # paths of the rows, top to bottom
        self.cells = {}             # path -> (bar, name label) to light up
        self.shown = {}             # path -> repo, for the rows on screen
        self.card.set_size_request(-1, panelui.CARD_HEIGHT)

        head = Gtk.Box(spacing=8)
        self.title = label("REPOS", "kb-heading")
        head.pack_start(self.title, True, True, 0)
        self.rescan_button = Gtk.Button(label="Rescan")
        self.rescan_button.get_style_context().add_class("ctl-link")
        self.rescan_button.set_tooltip_text("git fetch every repo, then rescan")
        self.rescan_button.connect("clicked", lambda _b: self.rescan())
        head.pack_end(self.rescan_button, False, False, 0)
        self.pull_all_button = Gtk.Button(label="Pull all")
        self.pull_all_button.get_style_context().add_class("ctl-link")
        self.pull_all_button.connect("clicked", lambda _b: self.pull_all())
        head.pack_end(self.pull_all_button, False, False, 0)
        self.card.pack_start(head, False, False, 0)

        # Pull all's result; hidden until there is one.
        self.summary = label("", "ctl-sub")
        self.summary.set_no_show_all(True)
        self.summary.set_ellipsize(Pango.EllipsizeMode.END)
        self.card.pack_start(self.summary, False, False, 0)

        # Shown when the list is longer than the card (fit_check), or on a key.
        self.filter = Gtk.Entry()
        self.filter.set_placeholder_text("Filter repos by name or branch")
        self.filter.get_style_context().add_class("panel-entry")
        self.filter.set_margin_top(4)
        self.filter.set_no_show_all(True)
        self.filter.connect("changed", lambda _e: self.filter_changed())
        self.card.pack_start(self.filter, False, False, 0)

        self.scroll = Gtk.ScrolledWindow()
        self.scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.scroll.set_propagate_natural_width(True)
        self.scroll.set_vexpand(True)
        self.scroll.set_margin_top(4)
        self.body = Gtk.Grid(column_spacing=8, row_spacing=2)
        self.scroll.add(self.body)
        self.card.pack_start(self.scroll, True, True, 0)
        self.repos = None
        try:
            with open(repos.CACHE) as handle:
                self.repos = json.load(handle)
        except (OSError, ValueError):
            pass
        self.draw()

    def on_ready(self):
        # GTK gives the first button the focus when the window maps; drop it,
        # so a key is a command from the start (and Enter is not Rescan).
        self.set_focus(None)
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
        self.rescan_button.set_sensitive(not self.pulling_all)
        subprocess.run(["pkill", f"-RTMIN+{SIGNAL}", "-x", "waybar"])
        self.draw()

    def rescan(self):
        self.fetching = True
        self.rescan_button.set_label("fetching...")
        self.rescan_button.set_sensitive(False)
        self.pull_all_button.set_sensitive(False)
        self.status = {}
        self.summary.hide()
        self.in_thread(repos.fetch, self.scanned)

    def can_pull(self, repo):
        return bool(repo["upstream"]) and repo["path"] not in self.busy \
            and not self.fetching and not self.pulling_all

    def pull(self, repo):
        path = repo["path"]
        self.busy.add(path)
        self.draw()

        def done(result):
            ok, text = result
            self.busy.discard(path)
            self.status[path] = (ok, text if ok else f"pull: {text}")
            self.in_thread(repos.scan, self.scanned)
        self.in_thread(lambda: repos.pull(path), done)

    def pull_all(self):
        """Every repo behind its upstream, one `git pull --ff-only` after
        another in one thread: one at a time so the rows report in order and
        the disk and the remotes see one pull, not fifty. Then one local scan
        for the new numbers."""
        targets = pull_all_targets(self.repos, self.busy)
        if not targets or self.fetching or self.pulling_all:
            return
        self.pulling_all = True
        paths = [r["path"] for r in targets]
        self.queued = set(paths)
        self.summary.hide()
        self.rescan_button.set_sensitive(False)
        self.pull_all_button.set_sensitive(False)
        results = []

        def start(i, path):
            self.queued.discard(path)
            self.busy.add(path)
            self.pull_all_button.set_label(f"pulling {i + 1}/{len(paths)}...")
            self.draw()
            return False

        def one(path, ok, text):
            self.busy.discard(path)
            self.status[path] = (ok, text if ok else f"pull: {text}")
            self.draw()
            return False

        def finish():
            self.pulling_all = False
            self.queued = set()
            self.pull_all_button.set_label("Pull all")
            self.summary.set_text(pull_all_summary(results))
            self.summary.show()
            self.in_thread(repos.scan, self.scanned)
            return False

        def run():
            for i, path in enumerate(paths):
                GLib.idle_add(start, i, path)
                ok, text = repos.pull(path)
                results.append((ok, text))
                GLib.idle_add(one, path, ok, text)
            GLib.idle_add(finish)
        threading.Thread(target=run, daemon=True).start()

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
        self.order, self.cells, self.shown = [], {}, {}
        text = self.filter.get_text().strip()
        targets = pull_all_targets(self.repos, self.busy)
        self.pull_all_button.set_sensitive(bool(targets) and not self.fetching
                                           and not self.pulling_all)
        self.pull_all_button.set_tooltip_text(
            f"git pull --ff-only the {len(targets)} repo(s) behind their upstream, one at a time"
            if targets else "Nothing is behind, as of the last fetch (Rescan fetches)")
        if self.repos is None:
            self.body.attach(label("scanning...", "ctl-sub"), 0, 0, 4, 1)
            self.body.show_all()
            return
        # A repo with a result from this card stays listed even once clean.
        todo = [r for r in self.repos if repos.needs_attention(r) or r["path"] in self.status]
        everything = len(todo)
        if text:
            # Filtering looks through every repo, the clean ones included.
            shown = [r for r in self.repos if matches(r, text)]
            todo = [r for r in shown if repos.needs_attention(r)] + \
                   sorted((r for r in shown if not repos.needs_attention(r)), key=lambda r: r["name"].lower())
        # The change counter: files changed or new across every repo, plus
        # dotfiles drift, plus commits not pushed.
        changes = sum(r["changed"] + r["untracked"] + r.get("drift", 0) for r in self.repos)
        unpushed = sum(r["ahead"] for r in self.repos)
        counts = [f"{changes} changed"] if changes else []
        if unpushed:
            counts.append(f"{unpushed} unpushed")
        self.title.set_text("REPOS" + (f"  ·  {', '.join(counts)}" if counts else ""))
        # Unpushed first: those are the ones at risk (a filter keeps its own
        # order: the ones with work, then the clean ones it found).
        if not text:
            todo.sort(key=lambda r: (-(r["ahead"] > 0 or not r["upstream"]), r["name"].lower()))
        row = 0
        if not todo:
            self.body.attach(label(f"no repo matches “{text}”" if text else
                                   f"all {len(self.repos)} repos clean and pushed", "ctl-sub"),
                             0, row, 4, 1)
            row += 1
        for repo in todo:
            row = self.repo_rows(repo, row)
        clean = len(self.repos) - everything
        if todo and clean and not text:
            note = label(f"{clean} more clean and pushed", "ctl-sub")
            note.set_margin_top(6)
            self.body.attach(note, 0, row, 4, 1)
        # The highlight follows its repo across redraws; when the repo has
        # left the list it falls back to the top row -- and a filter with
        # text always lights the top match, so Enter acts on it.
        if self.hl not in self.cells:
            self.hl = self.order[0] if self.order and (text or self.hl) else None
        self.paint_highlight()
        self.body.show_all()
        if self.hl:
            GLib.idle_add(self.reveal_row)
        if not text:
            GLib.idle_add(self.fit_check)

    def fit_check(self):
        """The filter box when the full list does not fit the card, or when a
        key asked for it (filter_pinned). Read after the rows are laid out,
        and only from the unfiltered list -- a filtered one is short by
        design, and hiding the box under the pointer while you type would
        lose the text."""
        need = self.body.get_preferred_height()[1]
        room = self.scroll.get_allocated_height() + (self.filter.get_allocated_height()
                                                     if self.filter.get_visible() else 0)
        self.filter.set_visible(self.filter_pinned or (room > 1 and need > room))
        return False

    # -- the keyboard ----------------------------------------------------------------
    def paint_highlight(self):
        for path, (bar, name) in self.cells.items():
            on = path == self.hl
            for widget, cls in ((bar, "git-on"), (name, "git-hl")):
                ctx = widget.get_style_context()
                (ctx.add_class if on else ctx.remove_class)(cls)

    def reveal_row(self):
        """Scroll the highlighted row into view. After layout (an idle, like
        fit_check): the bar's place in the list is only known once it is
        allocated."""
        cell = self.cells.get(self.hl)
        if not cell:
            return False
        bar = cell[0]
        spot = bar.translate_coordinates(self.body, 0, 0)
        if not spot:
            return False
        top = spot[1]
        adj = self.scroll.get_vadjustment()
        adj.set_value(scroll_value(adj.get_value(), adj.get_page_size(),
                                   top, top + bar.get_allocated_height()))
        return False

    def move(self, how):
        if isinstance(self.get_focus(), Gtk.Button):
            # Back to the rows: a button left focused (Tab, a click that did
            # not rebuild its row) would take the Enter meant for the row.
            # The filter box keeps its focus: the arrows drive rows from it.
            self.set_focus(None)
        index = self.order.index(self.hl) if self.hl in self.order else None
        page = PAGE
        if self.order:
            # One repo is its bar's height (the bar spans both its lines)
            # plus the grid's 2 px row spacing.
            page = page_rows(self.scroll.get_allocated_height(),
                             self.cells[self.order[0]][0].get_allocated_height() + 2)
        new = step(index, len(self.order), how, page)
        if new is None:
            return
        self.hl = self.order[new]
        self.paint_highlight()
        self.reveal_row()

    def hint(self, repo, text):
        """A one-line answer in the row for a key that had nothing to do."""
        self.status[repo["path"]] = (True, text)
        self.draw()

    def act(self, action):
        repo = self.shown.get(self.hl)
        if repo is None:
            self.move("home")
            return
        if action == "main":
            action = main_action(repo)
        if action == "sync":
            self.sync_dotfiles()
        elif action == "pull":
            if self.can_pull(repo):
                self.pull(repo)
            elif not repo["upstream"]:
                self.hint(repo, "no upstream to pull from (Push sets one)")
            elif self.fetching:
                self.hint(repo, "fetching -- Pull once Rescan is done")
            # else: a pull of it is already running or queued; its row says so
        elif action == "commit":
            if has_work(repo):
                self.commit(repo)
            else:
                self.hint(repo, "nothing to commit or push")
        elif action == "preview":
            if repo.get("previewable"):
                self.preview(repo)
            else:
                self.hint(repo, "no static site to preview (no CNAME next to an index.html)")

    def open_filter(self, text=""):
        self.filter_pinned = True
        self.filter.show()
        self.filter.grab_focus_without_selecting()
        if text:
            # Into the text directly rather than replaying the key event: a
            # box shown a moment ago may not be realized to take one yet.
            pos = self.filter.get_position()
            self.filter.insert_text(text, pos)
            self.filter.set_position(pos + len(text))

    def filter_changed(self):
        # New text: the top match is lit (draw() puts the highlight there),
        # so Enter acts on it, as in a launcher. Text cleared: the highlight
        # stays where it was.
        if self.filter.get_text().strip():
            self.hl = None
        self.draw()

    def leave_filter(self):
        self.filter_pinned = False
        self.set_focus(None)
        GLib.idle_add(self.fit_check)

    def on_key(self, widget, event):
        name = Gdk.keyval_name(event.keyval) or ""
        # is_focus, not has_focus: the box is the card's focus widget, whether
        # or not the compositor counts the card's window as active just now.
        in_filter = self.filter.is_focus()
        if name == "Escape" and (self.filter.get_text() or in_filter):
            self.filter.set_text("")
            self.leave_filter()
            return True
        modified = bool(event.state & (Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.MOD1_MASK))
        on_button = isinstance(self.get_focus(), Gtk.Button)
        action = key_action(name, event.string or "", in_filter, modified, on_button)
        if action is None:
            return super().on_key(widget, event)
        if action == "filter":
            self.open_filter()
        elif action == "type":
            self.open_filter(event.string)
        elif action in MOVES:
            self.move(action)
        else:
            self.act(action)
        return True

    def repo_rows(self, repo, row):
        path = repo["path"]
        # The highlight bar: empty and 3 px wide, lit only on the highlighted
        # row (panel.css: git-mark / git-on); it spans the name and the detail.
        bar = label("", "git-mark")
        bar.set_size_request(3, -1)
        self.body.attach(bar, 0, row, 1, 2)
        name = label(repo["name"], "sn-value")
        name.set_hexpand(True)
        name.set_ellipsize(Pango.EllipsizeMode.END)
        # A minimum as well as a maximum: an ellipsizing label in a grid asks
        # for no width at all, and the name collapsed to "...".
        name.set_width_chars(16)
        name.set_max_width_chars(22)
        self.body.attach(name, 1, row, 1, 1)
        self.body.attach(label(repo["branch"], "sn-label", 1.0), 2, row, 1, 1)
        self.order.append(path)
        self.cells[path] = (bar, name)
        self.shown[path] = repo

        buttons = Gtk.Box(spacing=4)
        pulling = path in self.busy
        waiting = path in self.queued
        buttons.pack_start(pick("pulling..." if pulling else "queued" if waiting else "Pull",
                                lambda: self.pull(repo), sensitive=self.can_pull(repo)),
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
        self.body.attach(buttons, 3, row, 1, 2)

        # The row's own result, when it has one, in place of the counts
        # (each stored with its "pull: " / "preview: " prefix already).
        detail = repos.describe(repo) or "clean"
        failed = False
        if path in self.status:
            ok, detail = self.status[path]
            failed = not ok
        sub = label(detail, "sn-label")
        sub.set_ellipsize(Pango.EllipsizeMode.END)
        sub.set_max_width_chars(40)
        if to_push or failed:
            sub.set_markup(f"<span foreground='{MAGENTA}'>{GLib.markup_escape_text(detail)}</span>")
        self.body.attach(sub, 1, row + 1, 2, 1)
        return row + 2


if __name__ == "__main__":
    panelui.run(Repos)
