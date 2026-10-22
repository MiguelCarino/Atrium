"""Settings page: Folder access -- which folders the AI features may read
files in (folder_access.py, which explains the rules; this page runs its
command line and redraws from what it reports).

    FOLDER ACCESS FOR AI   "Ask before AI reads a folder" on / off
    ALLOWED FOLDERS        each grant: the folder, for which feature, since
                           when, how it was given; Revoke. Then the folders
                           your background tasks work on (open to tasks by
                           the task itself; Deny one below to stop it)
    ADD A FOLDER           for which feature (all, or one), Allow a folder… /
                           Deny a folder… (a folder picker), and the search
                           index's folders as one-click suggestions
    DENIED FOLDERS         each denial; Remove
    NEVER READ             the secret and system folders no grant opens

Reached from Settings > Privacy and the Smart desktop hub's privacy strip.
"""
import datetime
import subprocess

from gi.repository import GLib, Gtk  # noqa: F401

from .common import *  # noqa: F401,F403  (the shared helpers and paths)

PAGE = {"id": "folders", "title": "Folder access", "icon": "", "group": "Safety", "order": 21,
        "keywords": ["folder access", "acceso a carpetas", "carpetas", "permissions", "permisos", "ai reads",
                     "files the ai reads", "allow folder", "deny folder", "revoke", "assistant files",
                     "local worker", "llm chat", "chat window", "read_file"]}

ACCESS = os.path.join(HYPR, "folder-access.py")
TASKS = os.path.join(HYPR, "tasks.py")
SETTINGS = os.path.join(HYPR, "settings.py")
HOME = os.path.expanduser("~")
WHO_CHOICES = [("all", "All AI features"), ("assistant", "Assistant"), ("chat", "LLM chat window"),
               ("worker", "Local worker (MCP)"),
               ("ask-desktop", "Ask your desktop"), ("tasks", "Background tasks"), ("phone", "Phone")]
BY_TEXT = {"prompt": "you said Always allow", "settings": "added here", "cli": "added from a terminal"}
SUGGESTED = ("Documents", "Downloads", "Desktop")      # the search index's folders (and the projects folder)


def tilde(path):
    return "~" + path[len(HOME):] if path == HOME or path.startswith(HOME + "/") else path


def day_text(epoch):
    if not epoch:
        return "?"
    then = datetime.datetime.fromtimestamp(epoch)
    return f"today {then:%H:%M}" if then.date() == datetime.date.today() else f"{then:%a %d %b %Y}"


def task_folders(data):
    """[(folder, task name)] from `tasks.py list --json`: the folders the
    tasks' model may read in by the task itself."""
    out = []
    for t in (data or {}).get("tasks") or []:
        p = t.get("params") or {}
        if t.get("type") == "summarise-folder" and p.get("folder"):
            out.append((os.path.expanduser(p["folder"]), t.get("name") or t.get("id")))
        elif t.get("type") == "watch-file" and p.get("path"):
            out.append((os.path.dirname(os.path.expanduser(p["path"])), t.get("name") or t.get("id")))
    return out


def covered(path, rows, who):
    return any((r["who"] in (who, "all")) and (path == r["path"] or path.startswith(r["path"].rstrip("/") + "/"))
               for r in rows)


class Page:
    def __init__(self):
        self.widget = page_box()
        w = self.widget
        self.updating = False
        self.data = None
        self.who = "all"

        w.pack_start(heading("FOLDER ACCESS FOR AI"), False, False, 0)
        self.ask_switch = Gtk.Switch()
        self.ask_switch.connect("state-set", self.ask_toggled)
        grid, self.ask_sub = row("", "Ask before AI reads a folder", "", self.ask_switch)
        w.pack_start(grid, False, False, 0)
        note = dp.label("Before an AI feature (the assistant, the LLM chat window's tools, the local worker, Ask your desktop, "
                        "background tasks, questions from the phone) hands a file's text to a model, its folder "
                        "must be open to that feature. If it is not, a prompt on the desktop says who asks, "
                        "which folder and the AI's reason: Deny (Esc), Allow once, or Always allow. A folder "
                        "covers everything inside it; a Deny on a folder inside an allowed one wins. Searches "
                        "still find files by name everywhere their Privacy switches allow, but show their text "
                        "only from open folders.", "ctl-sub")
        note.set_line_wrap(True)
        note.set_max_width_chars(90)
        w.pack_start(note, False, False, 0)
        w.pack_start(sep(), False, False, 0)

        w.pack_start(heading("ALLOWED FOLDERS"), False, False, 0)
        self.allowed = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        w.pack_start(self.allowed, False, False, 0)
        self.from_tasks = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        w.pack_start(self.from_tasks, False, False, 0)
        w.pack_start(sep(), False, False, 0)

        w.pack_start(heading("ADD A FOLDER"), False, False, 0)
        grid, self.who_sub = row("", "For", "")
        w.pack_start(grid, False, False, 0)
        self.who_chips = Chips(self.who_picked)
        self.who_chips.widget.set_min_children_per_line(3)
        self.who_chips.widget.set_halign(Gtk.Align.START)
        self.who_chips.widget.set_margin_start(52)
        w.pack_start(self.who_chips.widget, False, False, 0)
        w.pack_start(links_row(link("Allow a folder…", lambda: self.pick("allow")),
                               link("Deny a folder…", lambda: self.pick("deny"))), False, False, 0)
        self.suggest = Gtk.Box(spacing=6)
        self.suggest.set_halign(Gtk.Align.END)
        w.pack_start(self.suggest, False, False, 0)
        w.pack_start(sep(), False, False, 0)

        w.pack_start(heading("DENIED FOLDERS"), False, False, 0)
        self.denied = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        w.pack_start(self.denied, False, False, 0)
        w.pack_start(sep(), False, False, 0)

        w.pack_start(heading("NEVER READ"), False, False, 0)
        grid, self.never_sub = row("", "Secret and system folders",
                                   "Whatever is allowed here: ~/.ssh, ~/.gnupg, password stores, keyrings, browser "
                                   "and mail profiles, cloud keys (~/.aws, ~/.kube, ~/.docker), folders named "
                                   "secrets / credentials, files named like *secret*, *password*, *token*, *.env, "
                                   "id_rsa*, *.pem, *.key, and /proc, /sys, /dev, /run, /boot. Links are followed "
                                   "first: a link into another folder needs that folder.")
        w.pack_start(grid, False, False, 0)
        grid, _ = row("", "From a terminal",
                      "folder-access.py list · allow PATH --who assistant|worker|ask-desktop|tasks|phone|all · "
                      "deny PATH · revoke PATH · check PATH · ask on|off")
        w.pack_start(grid, False, False, 0)
        w.pack_start(links_row(link("Open Privacy", lambda: spawn(SETTINGS, "privacy")),
                               link("Open Background tasks", lambda: spawn(SETTINGS, "tasks"))), False, False, 0)
        self.msg = dp.label("", "ctl-sub")
        self.msg.set_line_wrap(True)
        w.pack_start(self.msg, False, False, 0)

    # -- doing things ----------------------------------------------------------------
    def act(self, *args):
        """folder-access.py <args> off the GTK thread, then redraw."""
        def work():
            try:
                res = subprocess.run([ACCESS, *args], capture_output=True, text=True, timeout=20)
                return "" if res.returncode == 0 else (res.stderr or res.stdout).strip()
            except (OSError, subprocess.SubprocessError) as exc:
                return str(exc)
        self.msg.set_text("")
        background(work, lambda err: (self.msg.set_text(err), self.refresh()))

    def ask_toggled(self, _switch, state):
        if not self.updating:
            self.act("ask", "on" if state else "off")
        return True         # the switch moves when refresh() says it did

    def who_picked(self, key):
        self.who = key
        self.show_who()
        self.show_suggestions()

    def pick(self, kind):
        """A folder picker; the folder chosen is allowed / denied for self.who."""
        dialog = Gtk.FileChooserDialog(title=f"{'Allow' if kind == 'allow' else 'Deny'} AI to read a folder",
                                       action=Gtk.FileChooserAction.SELECT_FOLDER)
        dialog.add_buttons("Cancel", Gtk.ResponseType.CANCEL,
                           "Allow" if kind == "allow" else "Deny", Gtk.ResponseType.OK)
        dialog.set_current_folder(HOME)
        top = self.widget.get_toplevel()
        if isinstance(top, Gtk.Window):
            dialog.set_transient_for(top)
        if dialog.run() == Gtk.ResponseType.OK and dialog.get_filename():
            self.act(kind, dialog.get_filename(), "--who", self.who)
        dialog.destroy()

    def refresh(self):
        background(lambda: (run_json(ACCESS, "list", "--json"), run_json(TASKS, "list", "--json", timeout=20),
                            run(os.path.join(HYPR, "desktop_conf.py"), "get", "projects").strip()), self.show)

    # -- drawing -------------------------------------------------------------------
    def rule_row(self, r, kind):
        who = dict(WHO_CHOICES).get(r["who"], r["who"])
        sub = f"{who}  ·  since {day_text(r.get('since'))}  ·  {BY_TEXT.get(r.get('by'), r.get('by') or '')}"
        caption = "Revoke" if kind == "allow" else "Remove"
        grid, _ = row("" if kind == "allow" else "", tilde(r["path"]), sub,
                      link(caption, lambda: self.act("revoke", r["path"], "--who", r["who"])))
        return grid

    def show(self, result):
        data, tasks, self.projects = result
        if not data:
            self.msg.set_text("folder-access.py did not answer (run it in a terminal to see why)")
            return
        self.data = data
        self.tasks = task_folders(tasks)
        self.updating = True
        try:
            self.ask_switch.set_active(data["ask"])
            self.ask_switch.set_state(data["ask"])
        finally:
            self.updating = False
        self.ask_sub.set_text(
            "on: a folder nobody opened yet asks first; no answer in a minute, or no screen to ask on, is a no"
            if data["ask"] else
            "off: AI features may read any folder that does not look secret, except the ones denied below")
        clear(self.allowed)
        for r in data["allow"]:
            self.allowed.pack_start(self.rule_row(r, "allow"), False, False, 0)
        if not data["allow"]:
            grid, _ = row("", "Nothing allowed yet",
                          "Each folder is asked about the first time an AI feature needs it, or add one below.")
            self.allowed.pack_start(grid, False, False, 0)
        clear(self.from_tasks)
        for folder, name in self.tasks:
            denied = covered(folder, data["deny"], "tasks")
            grid, _ = row("", tilde(folder),
                          f"Background tasks  ·  opened by your task “{name}” while it exists"
                          + ("  ·  DENIED below: the task works without the model" if denied else ""),
                          link("Deny", lambda f=folder: self.act("deny", f, "--who", "tasks")) if not denied else None)
            self.from_tasks.pack_start(grid, False, False, 0)
        clear(self.denied)
        for r in data["deny"]:
            self.denied.pack_start(self.rule_row(r, "deny"), False, False, 0)
        if not data["deny"]:
            grid, _ = row("", "Nothing denied", "A denied folder is never read by that feature and never "
                                                      "asked about: the request is refused at once.")
            self.denied.pack_start(grid, False, False, 0)
        self.show_who()
        self.show_suggestions()
        self.widget.show_all()

    def show_who(self):
        self.who_chips.set(WHO_CHOICES, self.who)
        self.who_sub.set_text("which feature the folder you add is for; All covers every one of them")

    def show_suggestions(self):
        clear(self.suggest)
        if not self.data:
            return
        projects = getattr(self, "projects", "")
        folders = [os.path.join(HOME, d) for d in SUGGESTED] + ([projects] if projects else [])
        todo = [f for f in folders if os.path.isdir(f) and not covered(os.path.realpath(f), self.data["allow"], self.who)]
        if todo:
            self.suggest.pack_start(dp.label("The search index's folders:", "ctl-sub"), False, False, 0)
            for f in todo:
                self.suggest.pack_start(link(f"Allow {tilde(f)}", lambda f=f: self.act("allow", f, "--who", self.who)),
                                        False, False, 0)
        self.suggest.show_all()
