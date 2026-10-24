"""Settings page: project contexts (contexts.py).

The project you are in now, with Leave and "Save the open windows as its
layout"; a repo picker to make a new context (the repos in your projects folder
-- desktop_conf.py -- that have none yet, the name filled from the folder); the contexts, each with
Enter, Save layout, Edit and Delete (Delete asks by turning into "Delete?"
for a few seconds; the saved layout -- a workspace session of the same
name -- stays in Settings > Workspace sessions); and, for the one being
edited, what entering does (its session, a terminal, the editor, the
preview, the notification focus, a workspace) and what leaving does (save
the layout first, close the project's own windows).

Nothing is kept here: every control runs contexts.py (new, set NAME KEY
VALUE, enter, leave, save, delete), which writes ~/.config/hypr/contexts.json,
and the page redraws from `contexts.py status`. The projects folder row runs
desktop_conf.py set projects PATH (~/.config/hypr/desktop.conf; "Back to
the default" and who else reads it sit in a Details fold); the git
pill, the brief, the assistant and voice read it too (a service that is
already running picks it up when it next starts). Entering starts apps, so it
is spawned, never waited for.
"""
from gi.repository import GLib, Gtk  # noqa: F401

from .common import *  # noqa: F401,F403  (the shared helpers and paths)

import os  # noqa: E402
import time  # noqa: E402

PAGE = {"id": "contexts", "title": "Project contexts", "icon": "", "group": "Apps", "order": 17, "parent": "sessions", "tab": "Contexts",
        "keywords": ["project", "proyecto", "context", "contexto", "repo", "repository", "workspace", "focus",
                     "focus mode", "enter project", "switch project", "ctx", "preview", "layout",
                     "projects folder", "repos folder", "carpeta de proyectos"]}

CONTEXTS = os.path.join(HYPR, "contexts.py")  # noqa: F405
DESKTOP_CONF = os.path.join(HYPR, "desktop_conf.py")  # noqa: F405
SWITCHES = [("session", "", "Restore its windows",
             "its saved layout, skipping what is already open"),
            ("terminal", "", "Open a terminal in the repo", "unless one is open there already"),
            ("editor", "", "Open the editor on the repo", "the default editor, or the command below"),
            ("save_on_leave", "", "Save the layout when leaving",
             "what is open then is what entering brings back"),
            ("close_on_leave", "", "Close the project's windows when leaving",
             "idle terminals, editors and file managers on the repo")]
PREVIEW = [("off", "No preview"), ("start", "Start the preview"), ("open", "Start and open it")]
FOCUS = [("none", "Notifications as usual"), ("dnd", "Do Not Disturb"), ("project", "Only this project's")]
ENTRIES = [("workspace", "\uf009", "Go to workspace", "a number or name; empty: stay where you are"),
           ("editor_cmd", "\uf121", "Editor command", "empty: the default editor (Settings > Default apps)"),
           ("allow", "\uf0f3", "Also let through", "app names, comma-separated (Automations, Thunderbird)")]


# -- pure helpers (tests/test_contexts.py) ------------------------------------------------
def does_text(c):
    """"terminal, editor, its windows, preview · only its notifications"."""
    opens = [w for w, yes in (("its windows", c.get("session")), ("terminal", c.get("terminal")),
                              ("editor", c.get("editor")), ("preview", c.get("preview", "off") != "off"))
             if yes]
    focus = {"dnd": "Do Not Disturb", "project": "only its notifications"}.get(c.get("focus"), "")
    return "  ·  ".join(p for p in (", ".join(opens) or "opens nothing", focus) if p)


def context_sub(c, now=None):
    layout = c.get("layout")
    if layout:
        when = time.strftime("%a %d %b %H:%M", time.localtime(layout.get("saved", 0)))
        lay = f"layout: {layout.get('windows', 0)} windows, {when}"
    else:
        lay = "no layout saved yet"
    missing = "" if c.get("exists", True) else "  ·  the folder is gone"
    return f"{c.get('repo', '')}{missing}\n{does_text(c)}  ·  {lay}"


def name_for(repo):
    """The context name a repo folder suggests."""
    base = os.path.basename(repo.rstrip("/"))
    return "".join(ch if ch.isalnum() or ch in " ._-" else "-" for ch in base)[:40]


def centred(widget):
    widget.set_valign(Gtk.Align.CENTER)
    return widget


class Page:
    def __init__(self):
        self.widget = page_box()  # noqa: F405
        w = self.widget
        w.pack_start(heading("NOW"), False, False, 0)  # noqa: F405
        self.now_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        w.pack_start(self.now_box, False, False, 0)
        w.pack_start(sep(), False, False, 0)  # noqa: F405

        w.pack_start(heading("NEW PROJECT"), False, False, 0)  # noqa: F405
        self.folder = Gtk.FileChooserButton.new("Your projects folder", Gtk.FileChooserAction.SELECT_FOLDER)
        self.folder.set_width_chars(18)
        self.folder.connect("file-set", lambda c: c.get_filename() and self.set_folder(c.get_filename()))
        grid, self.folder_sub = row("\uf07c", "Your projects folder", "", self.folder)  # noqa: F405
        w.pack_start(grid, False, False, 0)
        box = Gtk.Box(spacing=8)
        self.repo = Gtk.ComboBoxText()
        self.repo.connect("changed", lambda _c: self.repo_changed())
        box.pack_start(self.repo, False, False, 0)
        self.name = Gtk.Entry()
        self.name.set_placeholder_text("its name")
        self.name.set_hexpand(True)
        self.name.connect("activate", lambda _e: self.add())
        box.pack_start(self.name, True, True, 0)
        box.pack_start(link("Add", self.add), False, False, 0)  # noqa: F405
        w.pack_start(box, False, False, 0)
        self.add_sub = dp.label("Starts with a terminal, the editor and only its notifications.", "ctl-sub")  # noqa: F405
        self.add_sub.set_line_wrap(True)
        w.pack_start(self.add_sub, False, False, 0)
        folder_note = dp.label("The git pill, the brief, the assistant and voice use the projects folder too "  # noqa: F405
                               "(a running service picks a change up when it next starts). A repo with a site "
                               "also starts its local preview.", "ctl-sub")
        folder_note.set_line_wrap(True)
        folder_note.set_max_width_chars(90)
        w.pack_start(details(folder_note, links_row(link("Back to the default folder",  # noqa: F405
                                                         lambda: self.set_folder("")))), False, False, 0)
        w.pack_start(sep(), False, False, 0)  # noqa: F405

        w.pack_start(heading("PROJECTS"), False, False, 0)  # noqa: F405
        self.rows = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        w.pack_start(self.rows, False, False, 0)
        note = dp.label("Also: \"project <name>\" in the launcher, the bar's project pill (click: switch, "  # noqa: F405
                        "right-click: leave), and automations (\"context NAME\", when a project is entered "
                        "or left).", "ctl-sub")
        note.set_line_wrap(True)
        w.pack_start(details(note, label="Other ways in"), False, False, 0)  # noqa: F405
        w.pack_start(sep(), False, False, 0)  # noqa: F405

        self.edit_heading = heading("EDIT")  # noqa: F405
        w.pack_start(self.edit_heading, False, False, 0)
        self.edit_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        w.pack_start(self.edit_box, False, False, 0)
        self.switches = {}
        for key, icon, title, sub in SWITCHES:
            sw = Gtk.Switch()
            sw.connect("state-set", lambda _s, state, k=key: self.set(k, "on" if state else "off"))
            grid, _ = row(icon, title, sub, sw)  # noqa: F405
            self.switches[key] = sw
            self.edit_box.pack_start(grid, False, False, 0)
        self.edit_box.pack_start(dp.label("Website preview (localhost)",  # noqa: F405
                                          "ctl-sub"), False, False, 0)
        self.preview = Chips(lambda key: self.set("preview", key))  # noqa: F405
        self.edit_box.pack_start(self.preview.widget, False, False, 0)
        self.edit_box.pack_start(dp.label("Notifications while in it (urgent ones always show)", "ctl-sub"),  # noqa: F405
                                 False, False, 0)
        self.focus = Chips(lambda key: self.set("focus", key))  # noqa: F405
        self.edit_box.pack_start(self.focus.widget, False, False, 0)
        self.entries = {}
        for key, icon, title, hint in ENTRIES:
            entry = Gtk.Entry()
            entry.set_placeholder_text(hint)
            entry.set_width_chars(34)
            entry.connect("activate", lambda e, k=key: self.set(k, e.get_text().strip()))
            entry.connect("focus-out-event", lambda e, _ev, k=key: (self.entry_done(k, e), False)[1])
            grid, _ = row(icon, title, "Enter keeps it", entry)  # noqa: F405
            self.entries[key] = entry
            self.edit_box.pack_start(grid, False, False, 0)
        self.edit_note = dp.label("", "ctl-sub")  # noqa: F405
        self.edit_note.set_line_wrap(True)
        self.edit_box.pack_start(self.edit_note, False, False, 0)
        self.selected = None
        self.data = {}
        self.updating = False
        self.armed = None

    # -- actions
    def set_folder(self, path):
        """Your projects folder ("" = the default: the first of ~/Github,
        ~/Projects, ~/src... that exists), then the repo list again."""
        if self.updating:
            return
        home = os.path.expanduser("~")
        if path.startswith(home + "/"):
            path = "~" + path[len(home):]
        background(lambda: run(DESKTOP_CONF, "set", "projects", path), lambda _o: self.refresh())  # noqa: F405

    def repo_changed(self):
        repo = self.repo.get_active_text() or ""
        self.name.set_text(name_for(repo) if repo else "")

    def add(self):
        repo, name = self.repo.get_active_text() or "", self.name.get_text().strip()
        if not repo or not name:
            self.add_sub.set_text("pick a repo and give it a name")
            return
        self.add_sub.set_text("adding…")

        def done(out):
            self.add_sub.set_text(out.strip() or "added")
            self.selected = name
            self.refresh()
        # 2>&1: the "there is one called that already" line is what to show
        background(lambda: run("sh", "-c", '"$0" new "$1" --repo "$2" 2>&1',  # noqa: F405
                               CONTEXTS, name, os.path.expanduser(repo), timeout=20), done)

    def set(self, key, value):
        if self.updating or not self.selected:
            return False
        name = self.selected

        def work():
            out = run("sh", "-c", 'out=$("$0" set "$1" "$2" "$3" 2>&1) || echo "$out"',  # noqa: F405
                      CONTEXTS, name, key, value)
            return out.strip()
        background(work, lambda err: (self.edit_note.set_text(err or f"{key}: saved"), self.refresh()))  # noqa: F405
        return False        # let a switch move

    def entry_done(self, key, entry):
        current = next((c for c in self.data.get("contexts", []) if c["name"] == self.selected), None)
        if not current or self.updating:
            return
        value = entry.get_text().strip()
        saved = ", ".join(current.get(key, [])) if key == "allow" else current.get(key, "")
        if value != saved:
            self.set(key, value)

    def enter(self, name):
        spawn(CONTEXTS, "enter", name)  # noqa: F405
        GLib.timeout_add(1500, lambda: (self.refresh(), False)[1])

    def leave(self):
        background(lambda: run(CONTEXTS, "leave", timeout=30), lambda _o: self.refresh())  # noqa: F405

    def save_layout(self, name, sub):
        sub.set_text("saving…")
        background(lambda: run(CONTEXTS, "save", name, timeout=20),  # noqa: F405
                   lambda out: (sub.set_text(out.strip() or "could not save: is Hyprland running?"),
                                GLib.timeout_add(2500, lambda: (self.refresh(), False)[1])))

    def edit(self, name):
        self.selected = name
        self.draw(self.data)

    def delete(self, name, button):
        if self.armed != name:
            self.armed = name
            button.set_label("Delete?")
            GLib.timeout_add(3000, lambda: (self.disarm(name, button), False)[1])
            return
        self.armed = None
        if self.selected == name:
            self.selected = None
        background(lambda: run(CONTEXTS, "delete", name), lambda _o: self.refresh())  # noqa: F405

    def disarm(self, name, button):
        if self.armed == name:
            self.armed = None
            button.set_label("Delete")

    # -- drawing
    def refresh(self):
        background(lambda: run_json(CONTEXTS, "status") or {}, self.draw)  # noqa: F405

    def draw(self, data):
        self.data = data or {}
        self.updating = True
        contexts = self.data.get("contexts") or []
        now = self.data.get("current") or {}
        clear(self.now_box)  # noqa: F405
        if now:
            mins = int((time.time() - now.get("since", time.time())) // 60)
            grid, sub = row("", f"In {now['name']}",  # noqa: F405
                            f"{now.get('repo', '')}  ·  for {mins // 60} h {mins % 60:02d} min")
            grid.attach(centred(links_row(link("Save the open windows as its layout",  # noqa: F405
                                               lambda n=now["name"], s=sub: self.save_layout(n, s)),
                                          link("Leave", self.leave))), 2, 0, 1, 2)  # noqa: F405
        else:
            grid, _ = row("", "Not in a project",  # noqa: F405
                          "Enter one below, from the launcher or the bar.")
        self.now_box.pack_start(grid, False, False, 0)

        folder = self.data.get("projects_full")
        if folder:
            if self.folder.get_filename() != folder and os.path.isdir(folder):
                self.folder.set_filename(folder)
            self.folder_sub.set_text(self.data.get("projects", folder)
                                     + ("" if os.path.isdir(folder) else "  ·  not there yet")
                                     + ("" if self.data.get("projects_set") else "  ·  the default"))
        repos = self.data.get("repos") or []
        if [r for r in repos] != [self.repo.get_model()[i][0] for i in range(len(self.repo.get_model()))]:
            keep = self.repo.get_active_text()
            self.repo.remove_all()
            for r in repos:
                self.repo.append_text(r)
            if repos:
                self.repo.set_active(repos.index(keep) if keep in repos else 0)

        clear(self.rows)  # noqa: F405
        for p in self.data.get("problems") or []:
            self.rows.pack_start(dp.label(f"contexts.json: {p}", "ctl-sub"), False, False, 0)  # noqa: F405
        for c in contexts:
            delete = Gtk.Button(label="Delete")
            delete.get_style_context().add_class("ctl-link")
            delete.connect("clicked", lambda b, n=c["name"]: self.delete(n, b))
            title = c["name"] + ("  ·  you are in it" if c.get("current") else "")
            grid, sub = row("", title, context_sub(c))  # noqa: F405
            grid.attach(centred(links_row(link("Enter", lambda n=c["name"]: self.enter(n)),  # noqa: F405
                                          link("Save layout", lambda n=c["name"], s=sub: self.save_layout(n, s)),  # noqa: F405
                                          link("Edit", lambda n=c["name"]: self.edit(n)), delete)),  # noqa: F405
                        2, 0, 1, 2)
            self.rows.pack_start(grid, False, False, 0)
        if not contexts:
            self.rows.pack_start(dp.label("No projects yet: pick a repo above.", "ctl-sub"), False, False, 0)  # noqa: F405

        if self.selected not in [c["name"] for c in contexts]:
            self.selected = contexts[0]["name"] if contexts else None
        chosen = next((c for c in contexts if c["name"] == self.selected), None)
        self.edit_heading.set_text(f"EDIT {chosen['name'].upper()}" if chosen else "EDIT")
        self.edit_box.set_sensitive(chosen is not None)
        if chosen:
            for key, sw in self.switches.items():
                sw.set_active(bool(chosen.get(key)))
            self.preview.set(PREVIEW, chosen.get("preview", "off"))
            self.focus.set(FOCUS, chosen.get("focus", "project"))
            for key, entry in self.entries.items():
                if not entry.has_focus():
                    value = chosen.get(key, "")
                    entry.set_text(", ".join(value) if key == "allow" else value)
        self.widget.show_all()
        self.updating = False
