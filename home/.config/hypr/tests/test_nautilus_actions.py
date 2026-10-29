"""nautilus_actions.py and the Files extension that uses it
(~/.local/share/nautilus-python/extensions/atrium_files.py): which
right-click items a selection gets, the commands they run (the terminal and
the editor through default-apps.py, in a scope), what Copy Path / Copy as
URI put on the clipboard, that sftp:// and trash:// files get no local-only
item, git's porcelain read into the Git column, when a folder's answer is
asked again (a file dated in the future included), inside an untracked
folder, Set as Wallpaper (and the monitors the moving wallpaper covers) and
Ask the Local Model with their commands stubbed, the Copy items' text on
wl-copy's stdin, never one over-long argument. Hermetic: no wl-copy, hyprctl, hyprpaper or model is reached; the
extension tests (only where nautilus-python's Nautilus 4 typelib is there)
use stand-in file infos and a scratch git repository."""
import importlib.util
import json
import os
import shutil
import subprocess
import tempfile
import unittest

import helpers

na = helpers.import_script("nautilus_actions.py")

HOME_OF = os.path.dirname(os.path.dirname(os.path.dirname(helpers.SCRIPTS)))
EXTENSION = os.path.join(HOME_OF, ".local", "share", "nautilus-python", "extensions", "atrium_files.py")


def f(path, mime="text/plain", is_dir=False):
    return na.entry("file://" + path.replace(" ", "%20"), path, is_dir, mime)


def keys(rules):
    return [k for k, _label, _tip in rules]


def no_uwsm(name):
    return None


def has_uwsm(name):
    return "/usr/bin/" + name


class Rp:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


class Entries(unittest.TestCase):
    def test_only_file_uris_keep_a_path(self):
        self.assertEqual(f("/a b")["path"], "/a b")
        gvfs = na.entry("sftp://host/home/x.txt", "/run/user/1000/gvfs/sftp:host=host/home/x.txt", False, "text/plain")
        self.assertIsNone(gvfs["path"])
        self.assertIsNone(na.entry("trash:///x.txt", "/home/u/.local/share/Trash/files/x.txt")["path"])

    def test_textish(self):
        for mime in ("text/plain", "text/x-python", "application/json", "application/x-shellscript",
                     "application/octet-stream", "application/x-zerosize", "application/ld+json", ""):
            self.assertTrue(na.textish(mime), mime)
        for mime in ("image/png", "video/mp4", "audio/flac", "application/pdf", "application/zip",
                     "application/x-compressed-tar", "application/x-7z-compressed", "application/x-executable",
                     "application/vnd.oasis.opendocument.text", "application/x-iso9660-image",
                     "application/vnd.sqlite3", "font/ttf", "inode/directory", "application/epub+zip"):
            self.assertFalse(na.textish(mime), mime)


class Menus(unittest.TestCase):
    def test_nothing_selected(self):
        self.assertEqual(na.file_items([]), [])
        self.assertEqual(na.background_items(None), [])

    def test_one_folder(self):
        self.assertEqual(keys(na.file_items([f("/home/u/pro jects", "inode/directory", True)])),
                         ["terminal", "copy-path", "copy-uri"])

    def test_one_text_file(self):
        self.assertEqual(keys(na.file_items([f("/home/u/notes.md", "text/markdown")])),
                         ["editor", "ask", "copy-path", "copy-uri"])

    def test_one_picture(self):
        self.assertEqual(keys(na.file_items([f("/home/u/sky.png", "image/png")])),
                         ["wallpaper", "ask", "copy-path", "copy-uri"])
        # a GIF: not hyprpaper's, not the card's
        self.assertEqual(keys(na.file_items([f("/home/u/cat.gif", "image/gif")])), ["copy-path", "copy-uri"])
        # a line break in the name: show cannot pass it on
        self.assertNotIn("wallpaper", keys(na.file_items([f("/home/u/a\nb.png", "image/png")])))

    def test_several(self):
        rules = na.file_items([f("/a.txt"), f("/b.py", "text/x-python")])
        self.assertEqual(keys(rules), ["editor", "copy-path", "copy-uri"])
        self.assertEqual(rules[1][1], "Copy Paths")
        mixed = [f("/a.txt"), f("/d", "inode/directory", True)]
        self.assertEqual(keys(na.file_items(mixed)), ["copy-path", "copy-uri"])
        many = [f(f"/{n}.txt") for n in range(na.EDITOR_MAX + 1)]
        self.assertNotIn("editor", keys(na.file_items(many)))

    def test_not_local_gets_only_the_uri(self):
        for uri in ("sftp://host/srv/notes.txt", "trash:///notes.txt", "smb://nas/share/a.png"):
            mime = "image/png" if uri.endswith(".png") else "text/plain"
            self.assertEqual(keys(na.file_items([na.entry(uri, "/run/user/1000/gvfs/x", False, mime)])),
                             ["copy-uri"], uri)
        folder = na.entry("sftp://host/srv", "/run/user/1000/gvfs/x", True, "inode/directory")
        self.assertEqual(keys(na.file_items([folder])), ["copy-uri"])
        self.assertEqual(keys(na.background_items(folder)), ["copy-uri"])
        # one remote file in a local selection: no local items for any of them
        self.assertEqual(keys(na.file_items([f("/a.txt"), na.entry("sftp://h/b.txt")])), ["copy-uri"])

    def test_background(self):
        self.assertEqual(keys(na.background_items(f("/home/u", "inode/directory", True))),
                         ["terminal", "copy-path", "copy-uri"])


class Commands(unittest.TestCase):
    def test_terminal_goes_through_default_apps_in_a_scope(self):
        folder = [f("/home/u/my ñ dir", "inode/directory", True)]
        self.assertEqual(na.action_argv("terminal", folder, has_uwsm),
                         ["uwsm", "app", "--", na.DEFAULT_APPS, "run", "terminal", "--dir", "/home/u/my ñ dir"])
        self.assertEqual(na.action_argv("terminal", folder, lambda n: "/usr/bin/systemd-run"
                                        if n == "systemd-run" else None)[:5],
                         ["systemd-run", "--user", "--scope", "--quiet", "--"])
        self.assertEqual(na.action_argv("terminal", folder, no_uwsm)[0], na.DEFAULT_APPS)

    def test_editor_wallpaper_ask(self):
        files = [f("/home/u/a b.txt"), f("/home/u/c.txt")]
        self.assertEqual(na.action_argv("editor", files, no_uwsm),
                         [na.DEFAULT_APPS, "run", "editor", "/home/u/a b.txt", "/home/u/c.txt"])
        pic = [f("/home/u/sky.png", "image/png")]
        self.assertEqual(na.action_argv("wallpaper", pic, no_uwsm), [na.SELF, "wallpaper", "/home/u/sky.png"])
        self.assertEqual(na.action_argv("ask", pic, no_uwsm), [na.SELF, "ask", "/home/u/sky.png"])
        self.assertIsNone(na.action_argv("nope", pic, no_uwsm))

    def test_copy_path(self):
        one = [f("/home/u/a b ñ.txt")]
        # wl-copy reads the text on stdin, not in its argv: not in a scope either
        self.assertEqual(na.action_argv("copy-path", one, has_uwsm), ["wl-copy", "--type", "text/plain"])
        self.assertEqual(na.action_input("copy-path", one), "/home/u/a b ñ.txt")
        self.assertEqual(na.path_text(["/a b", "/c"]), "/a b\n/c")
        self.assertEqual(na.path_text(["/a\nb", "/c d"]), "'/a\nb' '/c d'")
        self.assertEqual(na.path_text(["/-x"]), "/-x")
        self.assertEqual(na.action_input("copy-path", [f("/-n")]), "/-n")
        self.assertIsNone(na.action_input("terminal", [f("/d", "inode/directory", True)]))

    def test_copy_uri(self):
        items = [f("/home/u/a b.txt"), na.entry("trash:///x.txt")]
        self.assertEqual(na.action_argv("copy-uri", items), na.clipboard_argv())
        self.assertEqual(na.action_input("copy-uri", items), "file:///home/u/a%20b.txt\ntrash:///x.txt")

    def test_a_huge_selection_is_never_one_argument(self):
        # 2 000 paths of ~70 characters: past Linux's 128 KiB per argument
        many = [f("/home/u/" + "d" * 50 + f"/file-{n:05}.txt") for n in range(2000)]
        argv = na.action_argv("copy-path", many)
        self.assertLess(max(len(a.encode()) for a in argv), 4096)
        self.assertGreater(len(na.action_input("copy-path", many).encode()), 128 * 1024)


class Porcelain(unittest.TestCase):
    DATA = (b" M a.txt\0?? new file.txt\0R  moved.txt\0old.txt\0UU both.txt\0M  staged.txt\0"
            b"MM sub/deep/f.txt\0?? fresh/\0A  sub/added.txt\0 D gone.txt\0?? caf\xc3\xa9\nline.txt\0"
            b"?? bad\xff.txt\0")

    def test_parse(self):
        got = na.parse_porcelain(self.DATA)
        self.assertIn(("R ", "moved.txt"), got)
        self.assertNotIn("old.txt", [p for _xy, p in got])
        self.assertIn(("??", "café\nline.txt"), got)
        self.assertIn(("??", os.fsdecode(b"bad\xff.txt")), got)
        self.assertEqual(na.parse_porcelain(b""), [])

    def test_classify(self):
        self.assertEqual([na.classify(x) for x in (" M", "MM", "M ", "A ", "R ", "UU", "??", " D", "!!")],
                         ["modified", "modified", "staged", "added", "renamed", "conflict", "untracked",
                          "deleted", None])

    def test_root_folder(self):
        st = na.dir_statuses(na.parse_porcelain(self.DATA), "/r", "/r")
        self.assertEqual(st["a.txt"], "modified")
        self.assertEqual(st["new file.txt"], "untracked")
        self.assertEqual(st["moved.txt"], "renamed")
        self.assertEqual(st["both.txt"], "conflict")
        self.assertEqual(st["fresh"], "untracked")
        self.assertEqual(st["sub"], "modified")           # a change under it
        self.assertEqual(st["café\nline.txt"], "untracked")
        self.assertNotIn("old.txt", st)

    def test_sub_folder(self):
        st = na.dir_statuses(na.parse_porcelain(self.DATA), "/r", "/r/sub")
        self.assertEqual(st, {"deep": "modified", "added.txt": "added"})
        self.assertEqual(na.dir_statuses(na.parse_porcelain(b"?? new/a\0?? new/b\0"), "/r", "/r"),
                         {"new": "untracked"})

    def test_inside_an_untracked_folder(self):
        # git, asked in new/ or new/inner/, says only the folder itself
        data = b"?? new/\0"
        for where in ("/r/new", "/r/new/inner"):
            st = na.dir_statuses(na.parse_porcelain(data), "/r", where)
            self.assertEqual(st, {na.EVERYTHING: "untracked"}, where)
            self.assertEqual(na.kind_for(st, "q.txt"), "untracked")
        # a sibling whose name starts the same is not inside it
        self.assertEqual(na.dir_statuses(na.parse_porcelain(data), "/r", "/r/newer"), {})
        # the work tree's root: the folder by its name, as before
        st = na.dir_statuses(na.parse_porcelain(data), "/r", "/r")
        self.assertEqual(st, {"new": "untracked"})
        self.assertEqual(na.kind_for(st, "other"), None)

    def test_labels_and_emblems(self):
        self.assertEqual(na.column_text("untracked"), "Untracked")
        self.assertEqual(na.column_text(None), "")
        self.assertEqual(na.emblem("modified"), "emblem-important")
        self.assertEqual(na.emblem("untracked"), "emblem-new")
        self.assertIsNone(na.emblem(None))

    def test_find_repo(self):
        have = {"/home/u/proj/.git"}
        exists = have.__contains__
        self.assertEqual(na.find_repo("/home/u/proj/src/x", exists), "/home/u/proj")
        self.assertEqual(na.find_repo("/home/u/proj", exists), "/home/u/proj")
        self.assertIsNone(na.find_repo("/home/u/other", exists))
        self.assertIsNone(na.find_repo("/home/u/proj/.git/refs", exists))

    def test_status_argv(self):
        argv = na.status_argv("/r/a b")
        self.assertEqual(argv[:4], ["git", "--no-optional-locks", "-C", "/r/a b"])
        self.assertIn("-z", argv)
        self.assertEqual(argv[-2:], ["--", "."])

    def test_cache_fresh(self):
        cached = ((1, 2), 100.0, {})
        self.assertTrue(na.cache_fresh(cached, (1, 2), 99.0, 110.0))
        self.assertTrue(na.cache_fresh(cached, (1, 2), None, 110.0))
        self.assertFalse(na.cache_fresh(cached, (1, 3), 99.0, 110.0))          # git add / commit
        self.assertFalse(na.cache_fresh(cached, (1, 2), 105.0, 110.0))         # edited in place since
        self.assertFalse(na.cache_fresh(cached, (1, 2), 99.0, 100.0 + na.CACHE_TTL + 1))
        self.assertFalse(na.cache_fresh(None, (1, 2), 1.0, 1.0))
        # dated in the future (a camera's clock ahead): kept, the stamp and ttl decide
        self.assertTrue(na.cache_fresh(cached, (1, 2), 5000.0, 110.0))
        self.assertFalse(na.cache_fresh(cached, (1, 3), 5000.0, 110.0))
        self.assertFalse(na.cache_fresh(cached, (1, 2), 5000.0, 100.0 + na.CACHE_TTL + 1))


class Wallpaper(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(dir=helpers.SCRATCH)
        self.pic = os.path.join(self.dir, "sky blue.png")
        with open(self.pic, "wb") as fh:
            fh.write(b"\x89PNG")
        self.calls, self.said = [], []

    def run_stub(self, settings, fail=(), motion='{"video": "", "on": true}'):
        def run(argv, **_kw):
            self.calls.append(argv)
            if argv[1] == "settings":
                return Rp(stdout=settings)
            if argv[1] == "motion":
                self.assertEqual(argv, [na.SLIDESHOW, "motion"])     # asked, never switched
                return Rp(stdout=motion)
            return Rp(returncode=1 if argv[2] in fail else 0, stderr="hyprpaper said no")
        return run

    def say(self, title, body="", icon=""):
        self.said.append((title, body))

    def test_every_connected_monitor(self):
        settings = '{"auto": true, "outputs": {"DP-1": {"connected": true}, "DP-2": {"connected": false},' \
                   ' "HDMI-A-1": {"connected": true}}}'
        self.assertEqual(na.set_wallpaper(self.pic, self.run_stub(settings), self.say), 0)
        self.assertEqual(self.calls[1:3], [[na.SLIDESHOW, "show", "DP-1", self.pic],
                                           [na.SLIDESHOW, "show", "HDMI-A-1", self.pic]])
        self.assertEqual(self.said[0][0], "Wallpaper set")
        self.assertIn("next change", self.said[0][1])
        self.assertNotIn("Not visible", self.said[0][1])

    def test_monitors_under_the_moving_wallpaper_are_named(self):
        walls = tempfile.mkdtemp(dir=helpers.SCRATCH)
        for output in ("DP-1", "DP-2", "DP-3"):
            os.mkdir(os.path.join(walls, output))
        for output in ("DP-1", "DP-2"):
            open(os.path.join(walls, output, "sakura.mp4"), "w").close()
        outs = {o: {"connected": True, "folder": os.path.join(walls, o)} for o in ("DP-1", "DP-2", "DP-3")}
        settings = json.dumps({"auto": True, "outputs": outs})
        on = '{"video": "sakura.mp4", "on": true}'
        self.assertEqual(na.set_wallpaper(self.pic, self.run_stub(settings, motion=on), self.say), 0)
        # set on all three (it shows once the video is off), but said
        self.assertEqual([c[2] for c in self.calls if c[1] == "show"], ["DP-1", "DP-2", "DP-3"])
        self.assertIn("Not visible on DP-1, DP-2: the moving wallpaper", self.said[0][1])
        # the switch off: nothing hidden
        self.said.clear()
        na.set_wallpaper(self.pic, self.run_stub(settings, motion='{"video": "sakura.mp4", "on": false}'), self.say)
        self.assertNotIn("Not visible", self.said[0][1])
        # a monitor whose show failed is said once, as failed
        self.said.clear()
        na.set_wallpaper(self.pic, self.run_stub(settings, fail={"DP-1"}, motion=on), self.say)
        self.assertIn("Not on DP-1:", self.said[0][1])
        self.assertIn("Not visible on DP-2:", self.said[0][1])

    def test_under_video(self):
        folders = {"A": "/w/A", "B": "/w/B", "C": ""}
        has = {"/w/A/v.mp4"}.__contains__
        self.assertEqual(na.under_video(["A", "B", "C"], folders, "v.mp4", True, has), ["A"])
        self.assertEqual(na.under_video(["A"], folders, "v.mp4", False, has), [])
        self.assertEqual(na.under_video(["A"], folders, "", True, has), [])

    def test_failures_are_said(self):
        settings = '{"auto": false, "outputs": {"DP-1": {"connected": true}}}'
        self.assertEqual(na.set_wallpaper(self.pic, self.run_stub(settings, fail={"DP-1"}), self.say), 1)
        self.assertEqual(self.said[0][0], "Not set as wallpaper")
        self.assertEqual(na.set_wallpaper(self.pic, self.run_stub('{"outputs": {}}'), self.say), 1)
        self.assertEqual(na.set_wallpaper(self.dir + "/none.png", self.run_stub("{}"), self.say), 1)


class Ask(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(dir=helpers.SCRATCH)
        self.runs, self.execs, self.said = [], [], []

    def write(self, name, data):
        path = os.path.join(self.dir, name)
        with open(path, "wb") as fh:
            fh.write(data)
        return path

    def ask(self, path, mime="text/plain"):
        def run(argv, **kw):
            self.runs.append((argv, kw.get("input")))
            return Rp()
        return na.ask_about(path, run, lambda exe, argv: self.execs.append(argv),
                            lambda title, body="", icon="": self.said.append(title), mime)

    def test_text_goes_to_the_card(self):
        path = self.write("notes ñ.txt", b"hello\nworld\n" + b"x" * (na.TEXT_BYTES * 2))
        self.assertEqual(self.ask(path), 0)
        argv, text = self.runs[0]
        self.assertEqual(argv, [na.SCREEN_ASK, "text"])
        text = text.decode("utf-8")
        self.assertTrue(text.startswith("File: notes ñ.txt\n\nhello\nworld\n"))
        self.assertLess(len(text), na.TEXT_BYTES + 100)

    def test_a_name_that_is_not_utf8(self):
        path = self.write(os.fsdecode(b"bad\xff.txt"), b"hello\n")
        self.assertEqual(self.ask(path), 0)
        _argv, data = self.runs[0]
        self.assertIsInstance(data, bytes)             # sent as bytes: no encode left to fail
        self.assertTrue(data.decode("utf-8").startswith("File: bad\ufffd.txt\n\nhello"))

    def test_picture_goes_as_it_is_never_deleted(self):
        path = self.write("sky.png", b"\x89PNG")
        self.ask(path, "image/png")
        self.assertEqual(self.execs, [[na.SCREEN_ASK, "image", path]])

    def test_binary_and_secret_are_refused(self):
        self.assertEqual(self.ask(self.write("blob", b"ab\0cd"), "application/octet-stream"), 1)
        self.assertEqual(self.ask(self.write("api-token.txt", b"s3cret")), 1)
        self.assertEqual(self.ask(self.dir), 1)
        self.assertEqual(self.runs, [])
        self.assertEqual(self.said, ["Not asked"] * 3)


@unittest.skipUnless(os.path.isfile(EXTENSION), "the Files extension is not installed")
class Extension(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import gi
            try:
                gi.require_version("Nautilus", "4.1")
            except ValueError:
                gi.require_version("Nautilus", "4.0")
            from gi.repository import Nautilus  # noqa: F401
        except (ImportError, ValueError):
            raise unittest.SkipTest("no nautilus-python (Nautilus 4 typelib)")
        spec = importlib.util.spec_from_file_location("atrium_files_under_test", EXTENSION)
        cls.ext = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.ext)
        cls.ext.actions = na                   # this checkout's module, whatever is installed

    def load_fresh(self):
        spec = importlib.util.spec_from_file_location("atrium_files_fresh", EXTENSION)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def setUp(self):
        self.spawned, self.completed = [], []
        self.ext.spawn = lambda argv, text=None: self.spawned.append((argv, text))
        self.ext.complete = lambda closure, provider, handle: self.completed.append(handle)
        self.provider = self.ext.AtriumFiles()

    def test_menu_items_run_their_commands(self):
        items = self.provider.get_file_items([Info("/home/u/a b", "inode/directory", True)])
        self.assertEqual([i.props.label for i in items], ["Open in Terminal", "Copy Path", "Copy as URI"])
        items[0].activate()
        self.assertEqual(self.spawned[0][0][-4:], ["run", "terminal", "--dir", "/home/u/a b"])
        self.assertIsNone(self.spawned[0][1])
        items[2].activate()
        self.assertEqual(self.spawned[1], (["wl-copy", "--type", "text/plain"], "file:///home/u/a%20b"))

    def test_spawn_writes_long_text_on_stdin(self):
        from gi.repository import GLib
        spawn = self.load_fresh().spawn                 # the real one, not setUp's stand-in
        out = os.path.join(tempfile.mkdtemp(dir=helpers.SCRATCH), "got")
        text = "/home/u/" + "x" * 200_000 + os.fsdecode(b"\xff")     # past 128 KiB, a non-UTF-8 byte
        spawn(["sh", "-c", 'cat > "$0"', out], text)
        want = text.encode("utf-8", "surrogateescape")
        loop = GLib.MainLoop()

        def check():
            if os.path.exists(out) and os.path.getsize(out) == len(want):
                loop.quit()
                return False
            return True
        GLib.timeout_add(20, check)
        GLib.timeout_add(5000, loop.quit)
        loop.run()
        with open(out, "rb") as fh:
            self.assertEqual(fh.read(), want)

    def test_remote_and_background(self):
        remote = Info("/srv/x.txt", "text/plain", uri="sftp://host/srv/x.txt")
        self.assertEqual([i.props.label for i in self.provider.get_file_items([remote])], ["Copy as URI"])
        self.assertEqual([i.props.label for i in self.provider.get_background_items(Info("/home/u", "", True))],
                         ["Open in Terminal", "Copy Path", "Copy as URI"])
        self.assertEqual(self.provider.get_file_items([]), [])

    def test_column(self):
        (column,) = self.provider.get_columns()
        self.assertEqual(column.props.attribute, na.ATTRIBUTE)

    def test_outside_a_repo(self):
        info = Info(os.path.join(helpers.SCRATCH, "plain.txt"))
        self.assertEqual(self.provider.update_file_info_full(None, "h", None, info),
                         self.ext.Nautilus.OperationResult.COMPLETE)
        self.assertEqual(info.attrs, {na.ATTRIBUTE: ""})

    @unittest.skipUnless(shutil.which("git"), "no git")
    def test_git_column_asks_once_per_folder(self):
        from gi.repository import GLib
        repo = tempfile.mkdtemp(dir=helpers.SCRATCH)
        env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
        git = lambda *a: subprocess.run(["git", "-C", repo, *a], env=env, capture_output=True, check=True)  # noqa: E731
        git("init", "-q")
        for name in ("a.txt", "b c.txt"):
            with open(os.path.join(repo, name), "w") as fh:
                fh.write("1\n")
        git("add", ".")
        git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init")
        with open(os.path.join(repo, "a.txt"), "a") as fh:
            fh.write("2\n")
        with open(os.path.join(repo, "new ñ.txt"), "w") as fh:
            fh.write("n\n")
        os.utime(os.path.join(repo, "a.txt"), (1, 1))            # older than the answer
        os.utime(os.path.join(repo, "new ñ.txt"), (1, 1))
        first, second = Info(os.path.join(repo, "a.txt")), Info(os.path.join(repo, "new ñ.txt"))
        clean = Info(os.path.join(repo, "b c.txt"))
        os.utime(os.path.join(repo, "b c.txt"), (1, 1))
        done = self.ext.Nautilus.OperationResult
        self.assertEqual(self.provider.update_file_info_full(None, "h1", None, first), done.IN_PROGRESS)
        loop = GLib.MainLoop()
        GLib.timeout_add(50, lambda: (loop.quit() if self.completed else True))
        GLib.timeout_add(5000, loop.quit)
        loop.run()
        self.assertEqual(self.completed, ["h1"])
        self.assertEqual(first.attrs[na.ATTRIBUTE], "Modified")
        self.assertEqual(first.emblems, ["emblem-important"])
        # the same folder: from the kept answer, at once
        self.assertEqual(self.provider.update_file_info_full(None, "h2", None, second), done.COMPLETE)
        self.assertEqual((second.attrs[na.ATTRIBUTE], second.emblems), ("Untracked", ["emblem-new"]))
        self.assertEqual(self.provider.update_file_info_full(None, "h3", None, clean), done.COMPLETE)
        self.assertEqual((clean.attrs[na.ATTRIBUTE], clean.emblems), ("", []))

    @unittest.skipUnless(shutil.which("git"), "no git")
    def test_inside_an_untracked_folder(self):
        from gi.repository import GLib
        repo = tempfile.mkdtemp(dir=helpers.SCRATCH)
        env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
        subprocess.run(["git", "-C", repo, "init", "-q"], env=env, capture_output=True, check=True)
        inner = os.path.join(repo, "newdir", "inner")
        os.makedirs(inner)
        with open(os.path.join(inner, "q"), "w") as fh:
            fh.write("q\n")
        os.utime(os.path.join(inner, "q"), (1, 1))
        for folder, name in ((os.path.join(repo, "newdir"), "inner"), (inner, "q")):
            info = Info(os.path.join(folder, name), is_dir=name == "inner")
            self.completed.clear()
            self.provider.update_file_info_full(None, name, None, info)
            loop = GLib.MainLoop()
            GLib.timeout_add(20, lambda: (loop.quit() if self.completed else True))
            GLib.timeout_add(5000, loop.quit)
            loop.run()
            self.assertEqual((info.attrs[na.ATTRIBUTE], info.emblems), ("Untracked", ["emblem-new"]), folder)

    def test_slow_git_is_stopped(self):
        from gi.repository import GLib
        repo = tempfile.mkdtemp(dir=helpers.SCRATCH)
        os.mkdir(os.path.join(repo, ".git"))
        old = na.status_argv, na.GIT_TIMEOUT_MS
        na.status_argv, na.GIT_TIMEOUT_MS = (lambda directory: ["sleep", "30"]), 100
        try:
            info = Info(os.path.join(repo, "a.txt"))
            self.provider.update_file_info_full(None, "h", None, info)
            loop = GLib.MainLoop()
            GLib.timeout_add(20, lambda: (loop.quit() if self.completed else True))
            GLib.timeout_add(5000, loop.quit)
            loop.run()
        finally:
            na.status_argv, na.GIT_TIMEOUT_MS = old
        self.assertEqual(self.completed, ["h"])
        self.assertEqual(info.attrs, {na.ATTRIBUTE: ""})
        self.assertEqual(self.provider.cache[repo][2], {})        # kept: not asked again per file

    def test_cancel_drops_the_request(self):
        self.provider.waiting["/r"] = [(None, "h1", None, Info("/r/a"), "a"), (None, "h2", None, Info("/r/b"), "b")]
        self.provider.cancel_update(None, "h1")
        self.provider.answer("/r", (0, 0), 0.0, {"b": "modified"})
        self.assertEqual(self.completed, ["h2"])
        self.assertIn("/r", self.provider.cache)


class Info:
    """A stand-in Nautilus.FileInfo: the calls the extension makes."""

    def __init__(self, path, mime="text/plain", is_dir=False, uri=None):
        self.path, self.mime, self.dir = path, mime, is_dir
        self.uri = uri or "file://" + path.replace(" ", "%20").replace("ñ", "%C3%B1")
        self.attrs, self.emblems = {}, []

    def get_uri(self):
        return self.uri

    def get_uri_scheme(self):
        return self.uri.split(":", 1)[0]

    def get_location(self):
        return Location(self.path)

    def is_directory(self):
        return self.dir

    def get_mime_type(self):
        return self.mime

    def add_string_attribute(self, key, value):
        self.attrs[key] = value

    def add_emblem(self, name):
        self.emblems.append(name)


class Location:
    def __init__(self, path):
        self.path = path

    def get_path(self):
        return self.path


if __name__ == "__main__":
    unittest.main()
