"""Files (Nautilus) for this desktop: right-click items and the Git column.

nautilus-python loads every .py in this folder into Nautilus when Nautilus
starts. This one is only the shell: which items a selection gets, what each
one runs, how git's answer is read and when it is asked again are all
decided in ~/.config/hypr/scripts/nautilus_actions.py (its docstring says
what each item does), which the tests import without a Nautilus. That
module is loaded here by its file path, not by putting the scripts folder on
sys.path: Nautilus's Python is shared with every other extension (KDE
Connect's, say), and the desktop's script names must not shadow theirs.

What lives here:
  - AtriumFiles.get_file_items / get_background_items: the menu (Nautilus 4
    API: no window argument), one Nautilus.MenuItem per rule the module
    returns, each starting its command with spawn() -- Gio.Subprocess, which
    reaps the child itself, so nothing waits and nothing is left a zombie
    (the Copy items' text goes to wl-copy's stdin, action_input()).
  - get_columns: the "Git" column of the list view (attribute ATTRIBUTE).
  - update_file_info_full: the column's text and the emblem. Nautilus asks
    for one file of a folder at a time; the first one of a folder starts one
    `git status` (Gio.Subprocess, asynchronous: the view is never held up)
    and returns IN_PROGRESS, the answer is kept per folder and every later
    file of that folder is answered at once from it. git gets
    GIT_TIMEOUT_MS; past that it is stopped and the folder shows no status
    (kept as an empty answer, so it is not asked again for every file).
    cancel_update drops a request Nautilus no longer wants (the folder was
    left) and the answer is still kept for the next visit.

Without the module (an install without the desktop's scripts), the extension
loads and adds nothing. NAUTILUS_PYTHON_DEBUG=misc nautilus shows the load.
"""
import importlib.util
import os
import shutil
import sys
import time

import gi

try:
    gi.require_version("Nautilus", "4.1")
except ValueError:
    gi.require_version("Nautilus", "4.0")
from gi.repository import Gio, GLib, GObject, Nautilus  # noqa: E402

CONFIG = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
HELPER = os.path.join(CONFIG, "hypr", "scripts", "nautilus_actions.py")
PREFIX = "AtriumFiles::"
CACHE_MAX = 256           # folders whose git answer is kept


def load_actions(path=HELPER):
    """nautilus_actions.py as a module of its own name, or None."""
    try:
        spec = importlib.util.spec_from_file_location("atrium_nautilus_actions", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    except (OSError, ImportError, SyntaxError) as exc:
        print(f"atrium_files: {path}: {exc}", file=sys.stderr)
        return None


actions = load_actions()


def spawn(argv, text=None):
    """Start argv and forget it (Gio.Subprocess reaps it when it ends).
    With text: that on its stdin, written asynchronously and then closed
    (the clipboard items: wl-copy reads it, however long). A name that is
    not UTF-8 goes back to its own bytes (surrogateescape), as an argument
    would have."""
    flags = Gio.SubprocessFlags.STDOUT_SILENCE | Gio.SubprocessFlags.STDERR_SILENCE
    if text is not None:
        flags |= Gio.SubprocessFlags.STDIN_PIPE
    try:
        proc = Gio.Subprocess.new(argv, flags)
    except GLib.Error as exc:
        print(f"atrium_files: cannot start {argv[0]}: {exc.message}", file=sys.stderr)
        return
    if text is not None:
        def written(source, result):
            try:
                source.communicate_finish(result)
            except GLib.Error as exc:
                print(f"atrium_files: {argv[0]}: {exc.message}", file=sys.stderr)
        proc.communicate_async(GLib.Bytes.new(text.encode("utf-8", "surrogateescape")), None, written)


def complete(closure, provider, handle):
    """Tell Nautilus an IN_PROGRESS file is done."""
    Nautilus.info_provider_update_complete_invoke(closure, provider, handle, Nautilus.OperationResult.COMPLETE)


def to_entry(info):
    """A Nautilus.FileInfo as the module's entry()."""
    location = info.get_location()
    path = location.get_path() if location is not None and info.get_uri_scheme() == "file" else None
    return actions.entry(info.get_uri() or "", path, info.is_directory(), info.get_mime_type() or "")


class AtriumFiles(GObject.GObject, Nautilus.MenuProvider, Nautilus.ColumnProvider, Nautilus.InfoProvider):
    def __init__(self):
        super().__init__()
        self.cache = {}         # folder -> (stamp, taken, {name: kind})
        self.waiting = {}       # folder -> [(provider, handle, closure, info, name)] while its git runs
        self.git = bool(actions) and shutil.which("git") is not None

    # -- the menu ----------------------------------------------------------------------------
    def menu(self, rules, items, where):
        out = []
        for key, label, tip in rules:
            item = Nautilus.MenuItem(name=f"{PREFIX}{where}-{key}", label=label, tip=tip)
            item.connect("activate", self.activate, key, items)
            out.append(item)
        return out

    def activate(self, _item, key, items):
        argv = actions.action_argv(key, items)
        if argv:
            spawn(argv, actions.action_input(key, items))

    def get_file_items(self, files):
        if actions is None or not files:
            return []
        items = [to_entry(f) for f in files]
        return self.menu(actions.file_items(items), items, "file")

    def get_background_items(self, folder):
        if actions is None or folder is None:
            return []
        item = to_entry(folder)
        return self.menu(actions.background_items(item), [item], "background")

    # -- the Git column ----------------------------------------------------------------------
    def get_columns(self):
        if actions is None:
            return []
        return [Nautilus.Column(name=f"{PREFIX}git", attribute=actions.ATTRIBUTE, label="Git",
                                description="The file's git status: modified, staged, untracked...")]

    def show(self, info, statuses, name):
        kind = actions.kind_for(statuses, name)
        info.add_string_attribute(actions.ATTRIBUTE, actions.column_text(kind))
        badge = actions.emblem(kind)
        if badge:
            info.add_emblem(badge)

    def update_file_info_full(self, provider, handle, closure, info):
        if actions is None:
            return Nautilus.OperationResult.COMPLETE
        location = info.get_location()
        path = location.get_path() if location is not None and info.get_uri_scheme() == "file" else None
        root = actions.find_repo(os.path.dirname(path)) if path and self.git else None
        if root is None:
            info.add_string_attribute(actions.ATTRIBUTE, "")
            return Nautilus.OperationResult.COMPLETE
        folder, name = os.path.split(path)
        stamp = actions.dir_stamp(folder, root)
        try:
            mtime = os.stat(path).st_mtime
        except OSError:
            mtime = None
        cached = self.cache.get(folder)
        if actions.cache_fresh(cached, stamp, mtime, time.time()):
            self.show(info, cached[2], name)
            return Nautilus.OperationResult.COMPLETE
        first = folder not in self.waiting
        self.waiting.setdefault(folder, []).append((provider, handle, closure, info, name))
        if first:
            self.ask_git(folder, root, stamp)
        return Nautilus.OperationResult.IN_PROGRESS

    def ask_git(self, folder, root, stamp):
        taken = time.time()
        try:
            proc = Gio.Subprocess.new(actions.status_argv(folder),
                                      Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_SILENCE)
        except GLib.Error:            # no git after all: answered from the main loop, after IN_PROGRESS
            GLib.idle_add(self.answer, folder, stamp, taken, {})
            return
        timer = {}
        timer["id"] = GLib.timeout_add(actions.GIT_TIMEOUT_MS, self.too_slow, proc, timer)

        def done(source, result):
            if timer["id"]:
                GLib.source_remove(timer["id"])
            statuses = {}
            try:
                _ok, out, _err = source.communicate_finish(result)
                if source.get_successful() and out is not None:
                    statuses = actions.dir_statuses(actions.parse_porcelain(out.get_data()), root, folder)
            except GLib.Error:
                pass
            self.answer(folder, stamp, taken, statuses)

        proc.communicate_async(None, None, done)

    @staticmethod
    def too_slow(proc, timer):
        timer["id"] = 0             # gone: done() must not remove it again
        proc.force_exit()
        return GLib.SOURCE_REMOVE

    def answer(self, folder, stamp, taken, statuses):
        self.cache[folder] = (stamp, taken, statuses)
        if len(self.cache) > CACHE_MAX:
            del self.cache[min(self.cache, key=lambda f: self.cache[f][1])]
        for provider, handle, closure, info, name in self.waiting.pop(folder, []):
            self.show(info, statuses, name)
            complete(closure, provider, handle)

    def cancel_update(self, _provider, handle):
        for folder in list(self.waiting):
            self.waiting[folder] = [w for w in self.waiting[folder] if w[1] != handle]
        # The git run goes on; answer() keeps its result for the next visit.
