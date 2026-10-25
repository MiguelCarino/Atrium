"""repos_panel.py (the git card): its filter -- every word of what is typed
must be in the repo's name or branch, case aside -- and the keyboard and
Pull all, through their pure parts: which action a key is, where the
highlight goes, how far the list scrolls, what Enter does on a row, and
which repos Pull all picks. Pure: no window."""
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


def repo(name="Tools", **over):
    """One scan row as repos.status() makes it: clean, pushed, up to date."""
    info = {"name": name, "path": f"/p/{name}", "branch": "main", "changed": 0,
            "untracked": 0, "ahead": 0, "behind": 0, "upstream": True, "error": "",
            "drift": 0, "website": "", "previewable": False}
    info.update(over)
    return info


class Filter(unittest.TestCase):
    def test_matches(self):
        repo = {"name": "Photo-Tools", "branch": "linux-port"}
        self.assertTrue(R.matches(repo, "photo"))
        self.assertTrue(R.matches(repo, "TOOLS port"))
        self.assertFalse(R.matches(repo, "photo main"))
        self.assertTrue(R.matches({"name": "Kite", "branch": None}, "kit"))
        self.assertTrue(R.matches(repo, "   "))          # nothing typed: everything


class Keys(unittest.TestCase):
    def test_rows_keys_work_everywhere(self):
        for in_filter in (False, True):
            self.assertEqual(R.key_action("Down", "", in_filter), "down")
            self.assertEqual(R.key_action("Up", "", in_filter), "up")
            self.assertEqual(R.key_action("Page_Down", "", in_filter), "pagedown")
            self.assertEqual(R.key_action("KP_Page_Up", "", in_filter), "pageup")
            self.assertEqual(R.key_action("Return", "\r", in_filter), "main")
            self.assertEqual(R.key_action("KP_Enter", "\r", in_filter), "main")

    def test_a_focused_button_keeps_enter_and_space(self):
        """Tab to Rescan or a row's Pull and press Enter: the button, not the
        highlighted row's main action (None: GTK activates the button)."""
        for name, text in (("Return", "\r"), ("KP_Enter", "\r"), ("ISO_Enter", "\r"), ("space", " ")):
            self.assertIsNone(R.key_action(name, text, False, on_button=True), name)
        self.assertEqual(R.key_action("Down", "", False, on_button=True), "down")   # still moves rows
        self.assertEqual(R.key_action("p", "p", False, on_button=True), "pull")
        self.assertEqual(R.key_action("Return", "\r", False, on_button=False), "main")

    def test_letters_are_commands_outside_the_filter(self):
        self.assertEqual(R.key_action("j", "j", False), "down")
        self.assertEqual(R.key_action("k", "k", False), "up")
        for name, action in (("p", "pull"), ("P", "pull"), ("c", "commit"), ("C", "commit"),
                             ("v", "preview"), ("V", "preview")):
            self.assertEqual(R.key_action(name, name, False), action)
        self.assertEqual(R.key_action("slash", "/", False), "filter")
        self.assertEqual(R.key_action("Home", "", False), "home")
        self.assertEqual(R.key_action("End", "", False), "end")

    def test_letters_are_text_inside_the_filter(self):
        # None: the key goes on to the Entry, which types it (or moves the caret).
        for name in ("j", "k", "p", "C", "v", "slash", "Home", "End", "a"):
            self.assertIsNone(R.key_action(name, name if len(name) == 1 else "", True), name)

    def test_any_other_printable_key_starts_the_filter(self):
        self.assertEqual(R.key_action("a", "a", False), "type")
        self.assertEqual(R.key_action("J", "J", False), "type")      # only lower-case j moves
        self.assertEqual(R.key_action("3", "3", False), "type")
        self.assertEqual(R.key_action("space", " ", False), "type")

    def test_not_ours(self):
        self.assertIsNone(R.key_action("Escape", "\x1b", False))     # the card's own Esc
        self.assertIsNone(R.key_action("Tab", "\t", False))
        self.assertIsNone(R.key_action("Shift_L", "", False))
        # Ctrl/Alt held: never a command and never filter text.
        self.assertIsNone(R.key_action("p", "p", False, modified=True))
        self.assertIsNone(R.key_action("Down", "", True, modified=True))


class Step(unittest.TestCase):
    def test_nothing_highlighted_yet(self):
        self.assertEqual(R.step(None, 6, "down"), 0)
        self.assertEqual(R.step(None, 6, "home"), 0)
        self.assertEqual(R.step(None, 6, "pagedown"), 0)
        self.assertEqual(R.step(None, 6, "up"), 5)
        self.assertEqual(R.step(None, 6, "end"), 5)

    def test_moves_clamp_without_wrapping(self):
        self.assertEqual(R.step(2, 6, "down"), 3)
        self.assertEqual(R.step(2, 6, "up"), 1)
        self.assertEqual(R.step(5, 6, "down"), 5)
        self.assertEqual(R.step(0, 6, "up"), 0)
        self.assertEqual(R.step(1, 20, "pagedown", page=6), 7)
        self.assertEqual(R.step(17, 20, "pagedown", page=6), 19)
        self.assertEqual(R.step(3, 20, "pageup", page=6), 0)
        self.assertEqual(R.step(9, 20, "home"), 0)
        self.assertEqual(R.step(9, 20, "end"), 19)

    def test_empty_and_shrunk_lists(self):
        self.assertIsNone(R.step(None, 0, "down"))
        self.assertIsNone(R.step(3, 0, "up"))
        # The list got shorter under the highlight (a filter, a rescan).
        self.assertEqual(R.step(9, 4, "down"), 3)
        self.assertEqual(R.step(9, 4, "up"), 2)

    def test_page_rows(self):
        self.assertEqual(R.page_rows(350, 44), 6)       # 7 fit, one kept as context
        self.assertEqual(R.page_rows(60, 44), 1)        # never less than one
        self.assertEqual(R.page_rows(0, 44), R.PAGE)    # not laid out yet
        self.assertEqual(R.page_rows(350, 0), R.PAGE)


class Scroll(unittest.TestCase):
    def test_in_view_stays(self):
        self.assertEqual(R.scroll_value(100, 300, 150, 190), 100)
        self.assertEqual(R.scroll_value(100, 300, 100, 400), 100)  # exactly the view

    def test_above_and_below(self):
        self.assertEqual(R.scroll_value(100, 300, 40, 80), 40)      # top to the top
        self.assertEqual(R.scroll_value(100, 300, 380, 420), 120)   # bottom to the bottom
        self.assertEqual(R.scroll_value(0, 300, 0, 40), 0)

    def test_taller_than_the_view(self):
        self.assertEqual(R.scroll_value(0, 30, 100, 140), 100)


class MainAction(unittest.TestCase):
    def test_commit_or_push_when_there_is_work(self):
        self.assertEqual(R.main_action(repo(changed=2)), "commit")
        self.assertEqual(R.main_action(repo(untracked=1)), "commit")
        self.assertEqual(R.main_action(repo(ahead=3)), "commit")            # the Push button
        self.assertEqual(R.main_action(repo(upstream=False)), "commit")     # Push sets one
        self.assertEqual(R.main_action(repo(changed=1, behind=2)), "commit")

    def test_pull_otherwise(self):
        self.assertEqual(R.main_action(repo()), "pull")
        self.assertEqual(R.main_action(repo(behind=4)), "pull")

    def test_dotfiles_drift_syncs(self):
        self.assertEqual(R.main_action(repo(drift=5)), "sync")
        self.assertEqual(R.main_action(repo(drift=5, changed=1)), "sync")


class PullAll(unittest.TestCase):
    def test_picks_only_the_ones_behind_an_upstream(self):
        rows = [repo("A", behind=2), repo("B"), repo("C", behind=1, upstream=False),
                repo("D", behind=3, error="not a git repository"),
                repo("E", behind=1, ahead=1), repo("F", behind=1, changed=4)]
        names = [r["name"] for r in R.pull_all_targets(rows)]
        # Diverged (E) and dirty (F) are tried: --ff-only refuses safely and
        # the row says why.
        self.assertEqual(names, ["A", "E", "F"])

    def test_skips_a_pull_already_running(self):
        rows = [repo("A", behind=2), repo("B", behind=1)]
        self.assertEqual([r["name"] for r in R.pull_all_targets(rows, busy={"/p/A"})], ["B"])

    def test_nothing_to_do(self):
        self.assertEqual(R.pull_all_targets(None), [])
        self.assertEqual(R.pull_all_targets([repo(), repo("B", ahead=2)]), [])
        # A cached scan from before "behind" was a key still works.
        old = repo("Old")
        del old["behind"]
        self.assertEqual(R.pull_all_targets([old]), [])

    def test_summary(self):
        self.assertEqual(R.pull_all_summary([]), "Pull all: nothing was behind")
        self.assertEqual(R.pull_all_summary([(True, "pulled"), (True, "pulled")]),
                         "Pull all: 2 of 2 pulled")
        self.assertEqual(R.pull_all_summary([(True, "pulled"), (False, "Not possible to fast-forward")]),
                         "Pull all: 1 of 2 pulled, 1 left to you (see the row)")


if __name__ == "__main__":
    unittest.main()
