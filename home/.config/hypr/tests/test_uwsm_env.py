"""~/.config/uwsm/env: the pointer theme chain in sh, the same one
lua/env.lua follows -- your own cursor_theme_user when installed, else the
desktop theme's cursor_theme= through inherit= (and cyberpunk), else
Adwaita -- plus the size and QT_QPA_PLATFORM's X11 fallback. Run with a
scratch HOME holding fake themes and cursor folders."""
import os
import shutil
import subprocess
import tempfile
import unittest

import helpers

ENV_FILE = os.path.join(os.path.dirname(os.path.dirname(helpers.SCRIPTS)), "uwsm", "env")


@unittest.skipUnless(os.path.exists(ENV_FILE), "no uwsm env file")
class UwsmEnv(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(dir=helpers.SCRATCH)
        self.addCleanup(shutil.rmtree, self.home, True)
        self.state = os.path.join(self.home, "state")
        os.makedirs(os.path.join(self.state, "hypr"))

    def theme(self, name, **keys):
        folder = os.path.join(self.home, ".config", "themes", name)
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, "theme.conf"), "w") as handle:
            for k, v in keys.items():
                handle.write(f"{k}={v}\n")

    def cursor(self, name):
        os.makedirs(os.path.join(self.home, ".icons", name, "cursors"), exist_ok=True)
        open(os.path.join(self.home, ".icons", name, "cursors", "default"), "w").close()

    def display(self, **keys):
        with open(os.path.join(self.state, "hypr", "display.conf"), "w") as handle:
            for k, v in keys.items():
                handle.write(f"{k}={v}\n")

    def env(self):
        out = subprocess.run(["sh", "-c", f'. "{ENV_FILE}"; echo "$XCURSOR_THEME|$XCURSOR_SIZE|$QT_QPA_PLATFORM"'],
                             capture_output=True, text=True, timeout=10,
                             env={"HOME": self.home, "XDG_STATE_HOME": self.state, "PATH": os.environ["PATH"]})
        self.assertEqual(out.returncode, 0, out.stderr)
        return out.stdout.strip().split("|")

    def test_theme_cursor_through_inherit(self):
        self.theme("cyberpunk", inherit="", cursor_theme="Base")
        self.theme("moe", inherit="pastel")
        self.theme("pastel", cursor_theme="Pink")
        self.cursor("Pink")
        self.cursor("Base")
        self.display(theme="moe", cursor_size="32")
        self.assertEqual(self.env(), ["Pink", "32", "wayland;xcb"])

    def test_falls_back_to_cyberpunk(self):
        self.theme("cyberpunk", inherit="", cursor_theme="Base")
        self.theme("plain")
        self.cursor("Base")
        self.display(theme="plain")
        self.assertEqual(self.env()[:2], ["Base", "24"])

    def test_own_cursor_wins_when_installed(self):
        self.theme("cyberpunk", cursor_theme="Base")
        self.cursor("Base")
        self.cursor("Mine")
        self.display(cursor_theme_user="Mine")
        self.assertEqual(self.env()[0], "Mine")

    def test_uninstalled_choice_is_skipped(self):
        self.theme("cyberpunk", cursor_theme="Base")
        self.cursor("Base")
        self.display(cursor_theme_user="Gone", cursor_size="huge")
        self.assertEqual(self.env()[:2], ["Base", "24"])

    def test_inherit_loop_ends(self):
        self.theme("a", inherit="b")
        self.theme("b", inherit="a")
        self.display(theme="a")
        theme = self.env()[0]
        self.assertIn(theme, ("", "Adwaita"))    # Adwaita only if this machine has it


if __name__ == "__main__":
    unittest.main()
