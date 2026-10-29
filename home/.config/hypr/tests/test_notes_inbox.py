"""The notes inbox is one file for its three users: quick notes
(quicknote.py), voice memos (memo.py) and Settings > Notes, which lists
both. Each names it the same way, $MEMO_INBOX moving it for all three --
checked in their source, since quicknote.py and the page need GTK to import."""
import ast
import os
import unittest

import helpers

FILES = ("quicknote.py", "memo.py", os.path.join("settings_pages", "notes.py"))


def inbox_expr(path):
    """The source of the module-level `INBOX = ...` in `path`."""
    with open(path, encoding="utf-8") as handle:
        tree = ast.parse(handle.read())
    for node in tree.body:
        if isinstance(node, ast.Assign) and [getattr(t, "id", None) for t in node.targets] == ["INBOX"]:
            return ast.unparse(node.value)
    return None


class OneInbox(unittest.TestCase):
    def test_same_definition_everywhere(self):
        exprs = {f: inbox_expr(os.path.join(helpers.SCRIPTS, f)) for f in FILES}
        self.assertEqual(len(set(exprs.values())), 1, exprs)
        self.assertIn("MEMO_INBOX", exprs["quicknote.py"])
        self.assertIn("~/Documents/Notes/inbox.md", exprs["quicknote.py"])


if __name__ == "__main__":
    unittest.main()
