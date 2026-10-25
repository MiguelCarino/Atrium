"""repos_panel.py (the git card): its filter -- every word of what is typed
must be in the repo's name or branch, case aside. Pure: no window."""
import importlib.util
import os
import sys
import unittest

import helpers  # noqa: F401  (scratch HOME, paths)

WAYBAR_SCRIPTS = os.path.expanduser("~/.config/waybar/scripts")
sys.path.insert(0, WAYBAR_SCRIPTS)
_spec = importlib.util.spec_from_file_location("repos_panel", os.path.join(WAYBAR_SCRIPTS, "repos_panel.py"))
R = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(R)


class Filter(unittest.TestCase):
    def test_matches(self):
        repo = {"name": "Photo-Tools", "branch": "linux-port"}
        self.assertTrue(R.matches(repo, "photo"))
        self.assertTrue(R.matches(repo, "TOOLS port"))
        self.assertFalse(R.matches(repo, "photo main"))
        self.assertTrue(R.matches({"name": "Asobi", "branch": None}, "aso"))
        self.assertTrue(R.matches(repo, "   "))          # nothing typed: everything


if __name__ == "__main__":
    unittest.main()
