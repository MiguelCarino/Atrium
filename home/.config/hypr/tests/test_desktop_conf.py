"""desktop_conf.py: ~/.config/hypr/desktop.conf -- your projects folder and
your dotfiles repo. Hermetic: every test gives its own file and its own
home folder (a scratch directory), never yours."""
import os
import tempfile
import unittest

import helpers

dc = helpers.import_script("desktop_conf.py")


class DesktopConf(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(dir=helpers.SCRATCH)
        self.conf = os.path.join(self.home, ".config", "hypr", "desktop.conf")

    def write(self, text):
        os.makedirs(os.path.dirname(self.conf), exist_ok=True)
        with open(self.conf, "w") as handle:
            handle.write(text)

    def test_parse_skips_comments_and_junk(self):
        self.assertEqual(dc.parse("# c\n\nprojects = ~/code \njunk\ndotfiles=\n"),
                         {"projects": "~/code", "dotfiles": ""})

    def test_missing_file_is_empty(self):
        self.assertEqual(dc.load(self.conf), {})

    def test_expand(self):
        self.assertEqual(dc.expand("~/a", "/h"), "/h/a")
        self.assertEqual(dc.expand("~", "/h"), "/h")
        self.assertEqual(dc.expand("rel/b", "/h"), "/h/rel/b")
        self.assertEqual(dc.expand("/abs/c/", "/h"), "/abs/c")
        self.assertEqual(dc.expand("", "/h"), "")

    def test_projects_set(self):
        self.write("projects=~/work\n")
        self.assertEqual(dc.projects_dir(self.conf, self.home), os.path.join(self.home, "work"))

    def test_projects_default_rule(self):
        # unset: the first candidate that exists, ~/Github before ~/Projects ...
        self.assertEqual(dc.projects_dir(self.conf, self.home), os.path.join(self.home, "Projects"))  # none
        os.makedirs(os.path.join(self.home, "src"))
        self.assertEqual(dc.projects_dir(self.conf, self.home), os.path.join(self.home, "src"))
        os.makedirs(os.path.join(self.home, "Projects"))
        self.assertEqual(dc.projects_dir(self.conf, self.home), os.path.join(self.home, "Projects"))
        os.makedirs(os.path.join(self.home, "Github"))
        self.assertEqual(dc.projects_dir(self.conf, self.home), os.path.join(self.home, "Github"))
        self.write("projects=\n")                                  # empty = unset
        self.assertEqual(dc.projects_dir(self.conf, self.home), os.path.join(self.home, "Github"))

    def test_dotfiles_needs_a_sync_sh(self):
        self.assertIsNone(dc.dotfiles_repo(self.conf, self.home))           # unset: hidden
        self.write("dotfiles=~/dots\n")
        self.assertIsNone(dc.dotfiles_repo(self.conf, self.home))           # no such repo
        os.makedirs(os.path.join(self.home, "dots"))
        self.assertIsNone(dc.dotfiles_repo(self.conf, self.home))           # no sync.sh
        open(os.path.join(self.home, "dots", "sync.sh"), "w").close()
        self.assertEqual(dc.dotfiles_repo(self.conf, self.home), os.path.join(self.home, "dots"))

    def test_set_key_keeps_the_rest(self):
        self.write("# mine\nprojects=~/a\nother=1\n")
        dc.set_key("projects", "~/b", self.conf)
        dc.set_key("dotfiles", "~/dots", self.conf)
        with open(self.conf) as handle:
            lines = handle.read().splitlines()
        self.assertEqual(lines, ["# mine", "projects=~/b", "other=1", "dotfiles=~/dots"])
        dc.set_key("projects", "", self.conf)                      # unset
        self.assertNotIn("projects", dc.load(self.conf))
        with self.assertRaises(ValueError):
            dc.set_key("nope", "x", self.conf)

    def test_set_key_makes_the_file(self):
        dc.set_key("projects", "~/code", self.conf)
        self.assertEqual(dc.load(self.conf), {"projects": "~/code"})

    def test_tilde(self):
        self.assertEqual(dc.tilde("/h/x", "/h"), "~/x")
        self.assertEqual(dc.tilde("/hx/y", "/h"), "/hx/y")

    def test_the_suite_uses_its_own_file(self):
        self.assertEqual(dc.CONF, os.environ["HYPR_DESKTOP_CONF"])
        self.assertEqual(os.path.basename(dc.projects_dir()), "Projects")


if __name__ == "__main__":
    unittest.main()
