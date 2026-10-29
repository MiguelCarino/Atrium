"""make-icon-theme.py's Papirus lookup (papirus_dir): the user's copy in
~/.local/share/icons before the system's (/usr/share/icons, from Fedora's
papirus-icon-theme), the folder only counting when it is a theme (has an
index.theme), None when there is neither -- and theme.py's hints for the
sets a theme names but this machine lacks (missing_set_hint).

Hermetic: a scratch home and scratch data dirs; nothing built."""
import glob
import os
import shutil
import tempfile
import unittest
import unittest.mock

import helpers

mit = helpers.import_script("make-icon-theme.py", "make_icon_theme")
theme = helpers.import_script("theme.py", "theme")


def papirus(root):
    folder = os.path.join(root, "Papirus")
    os.makedirs(folder, exist_ok=True)
    open(os.path.join(folder, "index.theme"), "w").close()
    return folder


class PapirusLookup(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.home = os.path.join(self.tmp, "home")
        self.user = os.path.join(self.home, ".local", "share", "icons")
        self.local = os.path.join(self.tmp, "usr-local-share")
        self.system = os.path.join(self.tmp, "usr-share")
        self.dirs = [self.local, self.system]

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_user_copy_wins_over_the_system_one(self):
        mine = papirus(self.user)
        papirus(os.path.join(self.system, "icons"))
        self.assertEqual(mit.papirus_dir(self.home, self.dirs), mine)

    def test_system_copy_when_there_is_no_user_one(self):
        system = papirus(os.path.join(self.system, "icons"))
        self.assertEqual(mit.papirus_dir(self.home, self.dirs), system)

    def test_data_dirs_in_their_order(self):
        local = papirus(os.path.join(self.local, "icons"))
        papirus(os.path.join(self.system, "icons"))
        self.assertEqual(mit.papirus_dir(self.home, self.dirs), local)

    def test_a_folder_without_index_theme_is_not_papirus(self):
        os.makedirs(os.path.join(self.user, "Papirus"))
        system = papirus(os.path.join(self.system, "icons"))
        self.assertEqual(mit.papirus_dir(self.home, self.dirs), system)

    def test_none_when_there_is_neither(self):
        self.assertIsNone(mit.papirus_dir(self.home, self.dirs))

    def test_xdg_data_dirs_default_ends_in_usr_share(self):
        with unittest.mock.patch.dict(os.environ, {"XDG_DATA_DIRS": ""}):
            # No such folders in the scratch home: whatever it finds is a system one.
            found = mit.papirus_dir(self.home)
        self.assertTrue(found is None or found.startswith(("/usr/local/share/icons", "/usr/share/icons")))


class MissingSetHints(unittest.TestCase):
    def test_built_sets_point_at_the_builder(self):
        self.assertIn("make-icon-theme.py --all", theme.missing_set_hint("Neon"))

    def test_packaged_sets_point_at_dnf(self):
        self.assertIn("dnf install oxygen-icon-theme", theme.missing_set_hint("oxygen"))

    def test_unpackaged_sets_are_optional_with_their_upstream(self):
        for name in ("Chicago95", "candy-icons", "Sweet-Rainbow", "WhiteSur-light",
                     "WhiteSur-cursors", "catppuccin-mocha-pink-cursors"):
            hint = theme.missing_set_hint(name)
            self.assertIn("optional, not packaged", hint, name)
            self.assertIn("https://github.com/", hint, name)

    def test_every_set_a_theme_names_has_a_hint(self):
        names = set()
        for path in glob.glob(os.path.join(theme.THEMES_DIR, "**", "theme.conf"), recursive=True):
            for key, value in (theme.read_kv(path) or {}).items():
                if key in ("icon_theme", "cursor_theme") and value != "Adwaita":
                    names.add(value)
        names |= {b for bases in theme.BUILT_ON.values() for b in bases}
        for name in sorted(names):
            self.assertTrue(theme.missing_set_hint(name), name)


if __name__ == "__main__":
    unittest.main()
