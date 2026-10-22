"""default-apps.py (the Settings "Default apps" page's backend) and the
page's pure helpers.

Hermetic: the end-to-end tests run the script as a child with
XDG_CONFIG_HOME, XDG_DATA_HOME and XDG_DATA_DIRS on scratch folders holding
a few fake desktop entries, so GLib sees only those apps and the
mimeapps.list written is a scratch one; XDG_STATE_HOME is helpers.py's
scratch. `run` is only ever called with --dry-run."""
import json
import os
import subprocess
import tempfile
import textwrap
import unittest

import helpers

da = helpers.import_script("default-apps.py")
SCRIPT = os.path.join(helpers.SCRIPTS, "default-apps.py")

APPS = {
    "fakebrowser.desktop": ("Fake Browser", "fakebrowser %u", "Network;WebBrowser;",
                            "x-scheme-handler/http;x-scheme-handler/https;text/html;application/xhtml+xml;"
                            "application/x-extension-htm;text/xml;"),
    "otherbrowser.desktop": ("Other Browser", "/usr/bin/flatpak run org.Other @@u %U @@", "Network;WebBrowser;",
                             "x-scheme-handler/https;text/html;"),
    "fakeview.desktop": ("Fake Viewer", "fakeview %F", "Graphics;Viewer;", "image/png;image/jpeg;image/webp;"),
    "fakeedit.desktop": ("Fake Edit", "fakeedit --new %F", "Utility;TextEditor;",
                         "text/plain;text/x-python;text/html;inode/directory;"),
    "fakefiles.desktop": ("Fake Files", "fakefiles --new-window %U", "System;FileManager;", "inode/directory;"),
    "faketerm.desktop": ("Fake Term", "kitty", "System;TerminalEmulator;", ""),
    "fakevim.desktop": ("Fake Vim", "vim %F", "Utility;TextEditor;", "text/plain;", "true"),
    "fakemag.desktop": ("Fake Torrent", "fakemag %U", "Network;", "x-scheme-handler/magnet;"),
}


def desktop_entry(name, exec_line, cats, mimes, terminal="false"):
    return textwrap.dedent(f"""\
        [Desktop Entry]
        Type=Application
        Name={name}
        Exec={exec_line}
        Icon=application-x-executable
        Terminal={terminal}
        Categories={cats}
        MimeType={mimes}
        """)


class Scratch(unittest.TestCase):
    """A scratch config/data tree with the fake apps."""

    def setUp(self):
        self.root = tempfile.mkdtemp(dir=helpers.SCRATCH)
        self.config = os.path.join(self.root, "config")
        self.data = os.path.join(self.root, "data")
        self.state = os.path.join(self.root, "state")
        apps = os.path.join(self.data, "applications")
        os.makedirs(apps)
        os.makedirs(self.config)
        for app_id, fields in APPS.items():
            with open(os.path.join(apps, app_id), "w") as handle:
                handle.write(desktop_entry(*fields))
        # GLib hides an entry whose Exec program is not on PATH: stubs
        # (never run -- `run` is only called with --dry-run).
        bin_dir = os.path.join(self.root, "bin")
        os.makedirs(bin_dir)
        for exe in ("fakebrowser", "fakeview", "fakeedit", "fakefiles", "fakemag", "vim", "kitty"):
            stub = os.path.join(bin_dir, exe)
            with open(stub, "w") as handle:
                handle.write("#!/bin/sh\nexit 0\n")
            os.chmod(stub, 0o755)
        self.env = dict(os.environ, PATH=bin_dir + os.pathsep + os.environ.get("PATH", ""),
                        XDG_CONFIG_HOME=self.config, XDG_DATA_HOME=self.data,
                        XDG_DATA_DIRS=os.path.join(self.root, "nothing"), XDG_STATE_HOME=self.state,
                        XDG_CURRENT_DESKTOP="Hyprland")

    def da(self, *args, ok=True):
        out = subprocess.run([SCRIPT, *args], capture_output=True, text=True, env=self.env, timeout=30)
        if ok:
            self.assertEqual(out.returncode, 0, out.stderr)
        return out.stdout

    def mimeapps(self):
        return da.MimeApps(os.path.join(self.config, "mimeapps.list"))


class Owners(unittest.TestCase):
    def test_exact_entries_beat_families(self):
        self.assertEqual(da.owner("text/html").id, "browser")
        self.assertEqual(da.owner("text/calendar").id, "calendar")
        self.assertEqual(da.owner("text/csv").id, "spreadsheets")
        self.assertEqual(da.owner("text/x-python").id, "editor")
        self.assertEqual(da.owner("image/webp").id, "image")
        self.assertIsNone(da.owner("x-scheme-handler/magnet"))

    def test_role_types_take_only_own_claimed_types(self):
        types = da.role_types(da.BY_ID["editor"], ["text/plain", "text/x-python", "text/html", "inode/directory"])
        self.assertEqual(types, ["text/plain", "text/x-python"])
        types = da.role_types(da.BY_ID["browser"], ["text/html", "text/xml", "application/x-extension-htm"])
        self.assertIn("x-scheme-handler/https", types)          # core always
        self.assertIn("application/x-extension-htm", types)
        self.assertNotIn("text/xml", types)                      # XML is the editor's


class MimeAppsFile(unittest.TestCase):
    def test_edit_keeps_everything_else(self):
        path = os.path.join(tempfile.mkdtemp(dir=helpers.SCRATCH), "mimeapps.list")
        with open(path, "w") as handle:
            handle.write("# mine\n[Default Applications]\nvideo/mp4=mpv.desktop\n\n[Added Associations]\n"
                         "image/png=a.desktop;b.desktop;\n\n[Removed Associations]\nimage/png=new.desktop;\n")
        m = da.MimeApps(path)
        da.assign(m, ["image/png"], "new.desktop")
        m.save()
        text = open(path).read()
        self.assertTrue(text.startswith("# mine\n"))
        self.assertIn("video/mp4=mpv.desktop", text)
        m = da.MimeApps(path)
        self.assertEqual(m.get(da.DEFAULTS, "image/png"), ["new.desktop"])
        self.assertEqual(m.get(da.ADDED, "image/png"), ["new.desktop", "a.desktop", "b.desktop"])
        self.assertEqual(m.get(da.REMOVED, "image/png"), [])
        self.assertTrue(da.unassign(m, ["image/png", "video/mp4"]))
        self.assertEqual(m.keys(da.DEFAULTS), [])
        self.assertEqual(m.get(da.ADDED, "image/png")[0], "new.desktop")   # associations stay


    def test_put_first_reorders_without_dropping(self):
        path = os.path.join(tempfile.mkdtemp(dir=helpers.SCRATCH), "mimeapps.list")
        with open(path, "w") as handle:
            handle.write("[Added Associations]\nimage/png=new.desktop;sys.desktop;mine.desktop;\n")
        m = da.MimeApps(path)
        self.assertTrue(da.put_first(m, {"image/png": "sys.desktop", "image/gif": "sys.desktop",
                                         "image/jpeg": None}))
        self.assertEqual(m.get(da.ADDED, "image/png"), ["sys.desktop", "new.desktop", "mine.desktop"])
        self.assertEqual(m.get(da.ADDED, "image/gif"), [])            # no list: nothing to reorder
        self.assertFalse(da.put_first(m, {"image/png": "sys.desktop"}))


class ExpandExec(unittest.TestCase):
    def test_field_codes(self):
        self.assertEqual(da.expand_exec("app --new-window %U", []), ["app", "--new-window"])
        self.assertEqual(da.expand_exec("app %u", ["https://x.org"]), ["app", "https://x.org"])
        self.assertEqual(da.expand_exec("app %F", ["/tmp/a b", "file:///tmp/c%20d"]), ["app", "/tmp/a b", "/tmp/c d"])
        self.assertEqual(da.expand_exec("app %i %c", [], name="App", icon="ic"), ["app", "--icon", "ic", "App"])
        self.assertEqual(da.expand_exec("app", ["https://x.org"]), ["app", "https://x.org"])   # no code: appended
        self.assertEqual(da.expand_exec('sh -c "echo 100%%"', []), ["sh", "-c", "echo 100%"])

    def test_flatpak_markers_survive(self):
        self.assertEqual(da.expand_exec("flatpak run x @@u %U @@", ["https://a"]),
                         ["flatpak", "run", "x", "@@u", "https://a", "@@"])


class EndToEnd(Scratch):
    def test_list_sees_the_fake_apps(self):
        rows = {r["id"]: r for r in json.loads(self.da("list", "--json"))}
        ids = [c["id"] for c in rows["browser"]["candidates"]]
        self.assertEqual(sorted(ids), ["fakebrowser.desktop", "otherbrowser.desktop"])
        files = [c["id"] for c in rows["files"]["candidates"]]
        self.assertEqual(files, ["fakefiles.desktop"])         # strict: the editor claims folders but is no FM
        self.assertEqual([c["id"] for c in rows["terminal"]["candidates"]], ["faketerm.desktop"])
        self.assertFalse(rows["browser"]["user_set"])

    def test_set_and_reset_a_role(self):
        self.da("set", "browser", "otherbrowser")
        m = self.mimeapps()
        for mime in da.BY_ID["browser"].core:
            self.assertEqual(m.get(da.DEFAULTS, mime), ["otherbrowser.desktop"])
        self.assertEqual(self.da("get", "browser").strip(), "otherbrowser.desktop")
        rows = {r["id"]: r for r in json.loads(self.da("list", "--json"))}
        self.assertTrue(rows["browser"]["user_set"])
        self.da("set", "browser", "fakebrowser.desktop")
        m = self.mimeapps()
        self.assertEqual(m.get(da.DEFAULTS, "application/x-extension-htm"), ["fakebrowser.desktop"])
        self.assertEqual(m.get(da.DEFAULTS, "text/xml"), [])
        self.da("reset", "browser")
        m = self.mimeapps()
        self.assertEqual([k for k in m.keys(da.DEFAULTS) if da.owns(da.BY_ID["browser"], k)], [])

    def test_reset_really_gives_the_system_default_back(self):
        # `set` puts the app first in [Added Associations] too; with only the
        # default line deleted, GLib would keep opening the old choice.
        # GLib's implicit (no mimeapps.list) defaults come from mimeinfo.cache,
        # which update-desktop-database writes; here by hand.
        with open(os.path.join(self.data, "applications", "mimeinfo.cache"), "w") as handle:
            handle.write("[MIME Cache]\n" + "".join(f"{t}=otherbrowser.desktop;fakebrowser.desktop;\n"
                                                     for t in da.BY_ID["browser"].core))
        system, other = "otherbrowser.desktop", "fakebrowser.desktop"
        self.assertEqual(json.loads(self.da("list", "--json"))[0]["system"]["id"], system)
        self.da("set", "browser", other)
        self.assertEqual(self.da("get", "browser").strip(), other)
        self.da("reset", "browser")
        self.assertEqual(self.da("get", "browser").strip(), system)
        rows = {r["id"]: r for r in json.loads(self.da("list", "--json"))}
        self.assertFalse(rows["browser"]["user_set"])
        self.assertIn(other, self.mimeapps().get(da.ADDED, "x-scheme-handler/https"))   # still in "Open with"

    def test_desktop_specific_list_gives_way(self):
        path = os.path.join(self.config, "hyprland-mimeapps.list")
        with open(path, "w") as handle:
            handle.write("[Default Applications]\nimage/png=fakebrowser.desktop\nvideo/mp4=x.desktop\n")
        self.da("set", "image", "fakeview")
        other = da.MimeApps(path)
        self.assertEqual(other.get(da.DEFAULTS, "image/png"), [])
        self.assertEqual(other.get(da.DEFAULTS, "video/mp4"), ["x.desktop"])
        self.assertEqual(self.da("get", "image").strip(), "fakeview.desktop")

    def test_raw_mime_type_and_unknown_app(self):
        self.da("set", "x-scheme-handler/magnet", "fakemag")
        self.assertEqual(self.da("get", "x-scheme-handler/magnet").strip(), "fakemag.desktop")
        out = subprocess.run([SCRIPT, "set", "image", "nope"], capture_output=True, text=True, env=self.env)
        self.assertNotEqual(out.returncode, 0)

    def test_terminal_preference(self):
        self.da("set", "terminal", "faketerm")
        with open(os.path.join(self.state, "hypr", "default-apps.conf")) as handle:
            self.assertIn("terminal=faketerm.desktop", handle.read())
        with open(os.path.join(self.config, "xdg-terminals.list")) as handle:
            self.assertIn("faketerm.desktop", handle.read())
        run = json.loads(self.da("run", "terminal", "--dir", "/tmp", "--dry-run", "--", "htop", "--dry-run"))
        self.assertEqual(run["argv"], ["kitty", "--directory", "/tmp", "htop", "--dry-run"])
        self.da("reset", "terminal")
        self.assertFalse(os.path.exists(os.path.join(self.config, "xdg-terminals.list")))

    def test_hand_written_terminals_list_is_left_alone(self):
        path = os.path.join(self.config, "xdg-terminals.list")
        with open(path, "w") as handle:
            handle.write("foot.desktop\n")
        self.da("set", "terminal", "faketerm")
        self.da("reset", "terminal")
        self.assertEqual(open(path).read(), "foot.desktop\n")

    def test_run_files_and_terminal_apps(self):
        self.da("set", "files", "fakefiles")
        run = json.loads(self.da("run", "files", "--dry-run"))
        self.assertEqual(run["argv"], ["fakefiles", "--new-window"])
        self.da("set", "terminal", "faketerm")
        self.da("set", "editor", "fakevim")
        run = json.loads(self.da("run", "editor", "/tmp/x.txt", "--dry-run"))
        self.assertEqual(run["argv"], ["kitty", "vim", "/tmp/x.txt"])     # Terminal=true: inside the terminal

    def test_run_falls_back_when_nothing_is_there(self):
        env = dict(self.env, XDG_DATA_HOME=os.path.join(self.root, "empty"))
        out = subprocess.run([SCRIPT, "run", "terminal", "--dry-run"], capture_output=True, text=True,
                             env=env, timeout=30)
        self.assertEqual(json.loads(out.stdout)["argv"], da.FALLBACK["terminal"])
        out = subprocess.run([SCRIPT, "run", "files", "--dry-run"], capture_output=True, text=True,
                             env=env, timeout=30)
        self.assertEqual(json.loads(out.stdout)["argv"], da.FALLBACK["files"])


class PageHelpers(unittest.TestCase):
    """settings_pages/apps.py's pure helpers (GTK imported, nothing shown)."""

    @classmethod
    def setUpClass(cls):
        import sys
        sys.path.insert(0, helpers.SCRIPTS)
        try:
            import gi
            gi.require_version("Gtk", "3.0")           # settings.py does this before any page loads
            gi.require_version("Gdk", "3.0")
            from settings_pages import apps
        except Exception as exc:  # noqa: BLE001 -- no GTK in this environment
            raise unittest.SkipTest(f"settings_pages.apps not importable: {exc}")
        cls.apps = apps

    def test_keys_text(self):
        binds = [{"modmask": 8, "key": "Q", "arg": "~/.config/hypr/scripts/default-apps.py run terminal"},
                 {"modmask": 72, "key": "w", "arg": "x/default-apps.py run files"},
                 {"modmask": 8, "key": "E", "arg": "launcher.py"}]
        self.assertEqual(self.apps.keys_text(binds), "ALT+Q terminal  ·  SUPER+ALT+W files")
        self.assertEqual(self.apps.keys_text(None), "")

    def test_keys_text_lua_binds(self):
        # Lua binds report a function id as arg; the description names them.
        binds = [{"modmask": 8, "key": "Q", "arg": "6", "description": "Apps: Terminal"},
                 {"modmask": 8, "key": "W", "arg": "19", "description": "Apps: File manager"},
                 {"modmask": 8, "key": "E", "arg": "7", "description": "Apps: Launcher"}]
        self.assertEqual(self.apps.keys_text(binds), "ALT+Q terminal  ·  ALT+W files")

    def test_role_sub(self):
        app = {"id": "a.desktop", "name": "A"}
        sub = self.apps.role_sub({"current": app, "system": {"id": "b.desktop", "name": "B"}, "user_set": True,
                                  "candidates": [app], "mixed": []})
        self.assertIn("would use B", sub)
        sub = self.apps.role_sub({"current": None, "system": None, "candidates": [], "mixed": []})
        self.assertIn("nothing installed", sub)

    def test_flatpak_names_only_when_ambiguous(self):
        a = {"id": "x.desktop", "name": "Chrome", "flatpak": True}
        b = {"id": "y.desktop", "name": "Chrome", "flatpak": False}
        self.assertEqual(self.apps.app_name(a, [a, b]), "Chrome (Flatpak)")
        self.assertEqual(self.apps.app_name(a, [a]), "Chrome")


if __name__ == "__main__":
    unittest.main()
